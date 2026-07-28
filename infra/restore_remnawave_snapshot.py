#!/usr/bin/env python3
"""Restore the managed Rovyn Remnawave profile from a private snapshot."""

from __future__ import annotations

import glob
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PANEL_URL = "https://panel.vpn.example"
PROFILE_NAME = "Rovyn-Production"
NODE_UUID = "02d38534-9370-4a0e-9aca-50f115292b33"
SQUAD_UUID = "8e319819-2110-44ab-b6f5-e76138233ed5"
APP_ENV = Path("/opt/vpn-platform/.env.production")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def api(
    token: str, method: str, path: str, payload: dict[str, Any] | None = None
) -> Any:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        PANEL_URL + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            document = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{method} {path} failed with HTTP {error.code}") from error
    return document.get("response", document)


def as_list(value: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, list):
                return candidate
    return []


def managed_host_payload(
    host: dict[str, Any], profile_uuid: str, inbound_uuid: str
) -> dict[str, Any]:
    fields = (
        "remark",
        "address",
        "port",
        "path",
        "sni",
        "host",
        "alpn",
        "fingerprint",
        "isDisabled",
        "securityLayer",
        "serverDescription",
        "tags",
        "isHidden",
        "overrideSniFromAddress",
        "keepSniBlank",
        "shuffleHost",
        "mihomoX25519",
        "nodes",
        "excludedInternalSquads",
        "excludeFromSubscriptionTypes",
    )
    payload = {key: host.get(key) for key in fields}
    payload["uuid"] = host["uuid"]
    payload["inbound"] = {
        "configProfileUuid": profile_uuid,
        "configProfileInboundUuid": inbound_uuid,
    }
    return payload


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    paths = [argument for argument in sys.argv[1:] if not argument.startswith("--")]
    snapshot_path = (
        Path(paths[0])
        if paths
        else Path(sorted(glob.glob("/opt/remnawave/backups/rovyn-production-*.json"))[-1])
    )
    snapshot = json.loads(snapshot_path.read_text())

    saved_profiles = snapshot["configProfiles"]["response"]["configProfiles"]
    saved_profile = next(item for item in saved_profiles if item["name"] == PROFILE_NAME)
    saved_hosts = snapshot["hosts"]["response"]
    managed_hosts = [
        host
        for host in saved_hosts
        if any(str(tag).startswith("ROVYN_") for tag in host.get("tags", []))
    ]
    if not saved_profile.get("config") or not saved_profile.get("inbounds"):
        raise RuntimeError("snapshot profile is incomplete")
    if not managed_hosts:
        raise RuntimeError("snapshot contains no managed Rovyn hosts")
    if check_only:
        print(
            f"snapshot_check=pass profile={PROFILE_NAME} "
            f"hosts={len(managed_hosts)} inbounds={len(saved_profile['inbounds'])}"
        )
        return 0

    token = read_env(APP_ENV)["REMNAWAVE_API_TOKEN"]
    profile_uuid = saved_profile["uuid"]
    api(
        token,
        "PATCH",
        "/api/config-profiles/",
        {
            "uuid": profile_uuid,
            "name": saved_profile["name"],
            "config": saved_profile["config"],
        },
    )

    current_inbounds = as_list(
        api(token, "GET", f"/api/config-profiles/{profile_uuid}/inbounds"),
        "inbounds",
        "items",
    )
    current_by_tag = {item["tag"]: item for item in current_inbounds}
    saved_uuid_to_tag = {
        item["uuid"]: item["tag"] for item in saved_profile.get("inbounds", [])
    }

    restored_tags: list[str] = []
    for host in managed_hosts:
        saved_inbound_uuid = host["inbound"]["configProfileInboundUuid"]
        tag = saved_uuid_to_tag[saved_inbound_uuid]
        api(
            token,
            "PATCH",
            "/api/hosts/",
            managed_host_payload(host, profile_uuid, current_by_tag[tag]["uuid"]),
        )
        restored_tags.append(tag)

    ordered_inbound_uuids = [
        current_by_tag[tag]["uuid"]
        for tag in restored_tags
        if tag in current_by_tag
    ]
    api(
        token,
        "PATCH",
        "/api/nodes/",
        {
            "uuid": NODE_UUID,
            "configProfile": {
                "activeConfigProfileUuid": profile_uuid,
                "activeInbounds": ordered_inbound_uuids,
            },
        },
    )
    api(
        token,
        "PATCH",
        "/api/internal-squads/",
        {"uuid": SQUAD_UUID, "inbounds": ordered_inbound_uuids},
    )
    print(
        f"snapshot_restored=true profile={PROFILE_NAME} "
        f"hosts={len(managed_hosts)} inbounds={len(ordered_inbound_uuids)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"snapshot restore failed: {error}", file=sys.stderr)
        raise SystemExit(1)
