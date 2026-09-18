#!/usr/bin/env python3
"""Install per-host JSON routing and observed transport fallback (Remnawave 2.8+).

Defaults to a read-only plan. --apply creates a private rollback snapshot first.
Credentials are always injected by Remnawave for the requesting user.
"""
import argparse
import base64
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from manage_transport_test_user import APP_ENV, api, read_env


def make_template(base, routing, backup_uuid, reality):
    document = copy.deepcopy(base)
    document["remnawave"] = {
        "addVirtualHostAsOutbound": True,
        "injectHosts": [{"selector": {"type": "uuids", "values": [backup_uuid]},
                         "selectFrom": "ALL", "tagPrefix": "backup"}],
    }
    rules = copy.deepcopy(routing["rules"])
    # Subscription bootstrap remains direct, even if the VPN has stopped working.
    local = next(r for r in rules if r.get("__name__") == "Локальные сервисы напрямую")
    calls = {"type": "field", "domain": ["domain:telegram.org", "domain:t.me",
             "domain:telegram.me", "domain:telegram-cdn.org", "domain:telesco.pe",
             "domain:discord.com", "domain:discord.gg", "domain:discord.media",
             "domain:discordapp.com", "domain:discordapp.net"], "balancerTag": "resilient"}
    # Protect LAN access, then carry public UDP through the VPN before geoip:ru.
    rules = [local, {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
             {"type": "field", "network": "udp", **({"outboundTag": "backup"} if reality else {"balancerTag": "resilient"})},
             calls] + [r for r in rules if r is not local]
    for rule in rules:
        rule.pop("id", None)
        rule.pop("__name__", None)
        if rule.get("outboundTag") == "proxy":
            del rule["outboundTag"]
            rule["balancerTag"] = "resilient"
    document["routing"] = {"domainStrategy": "IPIfNonMatch", "rules": rules,
        "balancers": [{"tag": "resilient", "selector": ["proxy"],
                       "fallbackTag": "backup", "strategy": {"type": "random"}}]}
    document["observatory"] = {"subjectSelector": ["proxy"],
        "probeUrl": "https://www.gstatic.com/generate_204", "probeInterval": "30s",
        "enableConcurrency": True}
    for inbound in document.get("inbounds", []):
        if "sniffing" in inbound:
            inbound["sniffing"]["routeOnly"] = True
    return document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args()
    token = read_env(APP_ENV)["REMNAWAVE_API_TOKEN"]
    if args.restore:
        snapshot = json.loads(args.restore.read_text())
        for host in snapshot["hosts"]:
            api(token, "PATCH", "/api/hosts", {"uuid": host["uuid"], "xrayJsonTemplateUuid": host.get("xrayJsonTemplateUuid")})
        for template in snapshot.get("templates", []):
            api(token, "PATCH", "/api/subscription-templates", {
                "uuid": template["uuid"], "templateJson": template["templateJson"]})
        print("host_templates_restored=true")
        return
    hosts = api(token, "GET", "/api/hosts")
    profiles = api(token, "GET", "/api/config-profiles")["configProfiles"]
    profile = next(p for p in profiles if p["name"] == "Rovyn-Production")
    # Select only this production profile's known transports.
    inbounds = api(token, "GET", f"/api/config-profiles/{profile['uuid']}/inbounds")
    if isinstance(inbounds, dict):
        inbounds = inbounds["inbounds"]
    tags = {i["uuid"]: i["tag"] for i in inbounds}
    selected = {tags.get(h["inbound"]["configProfileInboundUuid"]): h for h in hosts
                if h["inbound"]["configProfileUuid"] == profile["uuid"] and not h["isDisabled"]}
    expected = ["VLESS-REALITY-RAW", "VLESS-REALITY-XHTTP", "HYSTERIA2-TLS"]
    if not all(tag in selected for tag in expected):
        raise RuntimeError("expected production transports absent")
    templates = api(token, "GET", "/api/subscription-templates")["templates"]
    default = next(t for t in templates if t["name"] == "Default" and t["templateType"] == "XRAY_JSON")
    base = api(token, "GET", f"/api/subscription-templates/{default['uuid']}")["templateJson"]
    settings = api(token, "GET", "/api/subscription-settings")
    routing = json.loads(base64.b64decode(settings["happRouting"]))
    if settings["profileUpdateInterval"] != 1:
        raise RuntimeError("hourly subscription refresh must already be enabled")
    plan = []
    for tag in expected:
        backup = "HYSTERIA2-TLS" if tag == "VLESS-REALITY-XHTTP" else "VLESS-REALITY-XHTTP"
        name = "Rovyn Recovery " + tag
        existing = next((t for t in templates if t["name"] == name), None)
        current_template = selected[tag].get("xrayJsonTemplateUuid")
        if current_template not in (None, default["uuid"], existing["uuid"] if existing else None):
            raise RuntimeError("host has an unrelated custom template")
        config = make_template(base, routing, selected[backup]["uuid"], tag == "VLESS-REALITY-RAW")
        plan.append((tag, name, existing, config))
        print(f"plan={tag} fallback={backup} observed_every=30s public_udp=VPN")
    if not args.apply:
        return
    directory = Path("/opt/remnawave/backups")
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / ("call-recovery-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    old_templates = [api(token, "GET", f"/api/subscription-templates/{existing['uuid']}")
                     for _, _, existing, _ in plan if existing]
    snapshot = {"hosts": list(selected.values()), "default": base,
                "settings": settings, "templates": old_templates}
    with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        json.dump(snapshot, output)
    print(f"rollback_snapshot={path}")
    try:
        assignments = []
        for tag, name, existing, config in plan:
            template = existing or api(token, "POST", "/api/subscription-templates", {"name": name, "templateType": "XRAY_JSON"})
            api(token, "PATCH", "/api/subscription-templates", {"uuid": template["uuid"], "templateJson": config})
            assignments.append({"uuid": selected[tag]["uuid"], "xrayJsonTemplateUuid": template["uuid"]})
        for assignment in assignments:
            api(token, "PATCH", "/api/hosts", assignment)
    except Exception:
        for host in snapshot["hosts"]:
            api(token, "PATCH", "/api/hosts", {"uuid": host["uuid"], "xrayJsonTemplateUuid": host.get("xrayJsonTemplateUuid")})
        for template in old_templates:
            api(token, "PATCH", "/api/subscription-templates", {
                "uuid": template["uuid"], "templateJson": template["templateJson"]})
        raise
    print("call_recovery_templates_applied=true")


if __name__ == "__main__":
    main()
