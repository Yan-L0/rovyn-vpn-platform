#!/usr/bin/env python3
"""Remove endpoint DNS dependency while retaining explicit TLS/REALITY names."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from manage_transport_test_user import APP_ENV, api, read_env

MANAGED_TAGS = {
    "ROVYN_VLESS_REALITY_RAW",
    "ROVYN_VLESS_REALITY_XHTTP",
    "ROVYN_HYSTERIA2_TLS",
}


def plan_updates(hosts: list[dict], domain: str, address: str) -> list[dict]:
    if not ipaddress.ip_address(address).is_global:
        raise ValueError("node address must be a public IP")
    selected: dict[str, dict] = {}
    for host in hosts:
        tags = MANAGED_TAGS.intersection(host.get("tags", []))
        if not tags:
            continue
        if len(tags) != 1:
            raise ValueError("ambiguous managed host")
        tag = next(iter(tags))
        if tag in selected:
            raise ValueError("duplicate managed host")
        if host.get("address") not in (domain, address):
            raise ValueError("unexpected current node address")
        if (not host.get("sni") or host.get("overrideSniFromAddress")
                or host.get("keepSniBlank")):
            raise ValueError("explicit TLS/REALITY name must be preserved")
        selected[tag] = host
    if set(selected) != MANAGED_TAGS:
        raise ValueError("expected exactly three managed hosts")
    return [{"uuid": selected[tag]["uuid"],
             "address": selected[tag]["address"],
             "sni": selected[tag]["sni"]} for tag in sorted(selected)]


def apply_updates(token: str, originals: list[dict], address: str) -> None:
    # Record each attempted request: a lost HTTP response can still mean applied.
    attempted = []
    try:
        for host in originals:
            attempted.append(host)
            api(token, "PATCH", "/api/hosts", {"uuid": host["uuid"], "address": address})
    except Exception:
        rollback_failed = False
        for host in reversed(attempted):
            try:
                api(token, "PATCH", "/api/hosts", {"uuid": host["uuid"], "address": host["address"]})
            except Exception:
                rollback_failed = True
        if rollback_failed:
            raise RuntimeError("rollback incomplete; use saved snapshot") from None
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain")
    parser.add_argument("--address")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args()
    token = read_env(APP_ENV)["REMNAWAVE_API_TOKEN"]
    hosts = api(token, "GET", "/api/hosts")
    if args.restore:
        snapshot = json.loads(args.restore.read_text())
        current = {h["uuid"]: h for h in hosts}
        # Validate all hosts before changing any; do not overwrite later edits.
        for old in snapshot["hosts"]:
            host = current[old["uuid"]]
            if host["address"] != snapshot["address"] or host["sni"] != old["sni"]:
                raise ValueError("host changed since bootstrap update")
        for old in snapshot["hosts"]:
            api(token, "PATCH", "/api/hosts", {"uuid": old["uuid"], "address": old["address"]})
        print("node_bootstrap_restored=true")
        return
    if not args.domain or not args.address:
        parser.error("--domain and --address required")
    originals = plan_updates(hosts, args.domain, args.address)
    print(f"node_bootstrap_plan=3 address={args.address} tls_names=preserved")
    if not args.apply:
        return
    directory = Path("/opt/remnawave/backups")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / ("node-bootstrap-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        json.dump({"address": args.address, "hosts": originals}, output)
    print(f"rollback_snapshot={path}", flush=True)
    apply_updates(token, originals, args.address)
    print("node_bootstrap_applied=true")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # API errors can include credentials in their response bodies.
        print(f"node_bootstrap_error={type(error).__name__}")
        raise SystemExit(1)
