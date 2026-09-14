#!/usr/bin/env python3
"""Remove only the managed deprecated gRPC transport from Remnawave."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from manage_transport_test_user import APP_ENV, api, read_env


PROFILE_NAME = "Rovyn-Production"
NODE_UUID = "02d38534-9370-4a0e-9aca-50f115292b33"
SQUAD_UUID = "8e319819-2110-44ab-b6f5-e76138233ed5"
GRPC_TAG = "VLESS-REALITY-GRPC"
GRPC_HOST_TAG = "ROVYN_VLESS_REALITY_GRPC"
EXPECTED_TAGS = ("VLESS-REALITY-RAW", "VLESS-REALITY-XHTTP", "HYSTERIA2-TLS")
BACKUP_DIRECTORY = Path("/opt/remnawave/backups")


def as_list(value: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in keys:
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
    return []


def main() -> None:
    token = read_env(APP_ENV)["REMNAWAVE_API_TOKEN"]
    profiles = as_list(api(token, "GET", "/api/config-profiles/"), "configProfiles", "items")
    profile = next((item for item in profiles if item.get("name") == PROFILE_NAME), None)
    if not profile or not isinstance(profile.get("config"), dict):
        raise RuntimeError("production config profile was not found")

    config = profile["config"]
    inbounds = config.get("inbounds")
    if not isinstance(inbounds, list):
        raise RuntimeError("production profile has no inbound list")
    grpc_inbounds = [item for item in inbounds if item.get("tag") == GRPC_TAG]
    if len(grpc_inbounds) > 1:
        raise RuntimeError("multiple managed gRPC inbounds found")

    hosts = as_list(api(token, "GET", "/api/hosts/"), "hosts", "items")
    grpc_hosts = [host for host in hosts if GRPC_HOST_TAG in host.get("tags", [])]
    if len(grpc_hosts) > 1:
        raise RuntimeError("multiple managed gRPC hosts found")

    BACKUP_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = BACKUP_DIRECTORY / f"remove-grpc-{timestamp}.json"
    backup_path.write_text(json.dumps({"profile": profile, "hosts": grpc_hosts}, ensure_ascii=False, indent=2))
    os.chmod(backup_path, 0o600)

    if grpc_inbounds:
        updated_config = {
            **config,
            "inbounds": [item for item in inbounds if item.get("tag") != GRPC_TAG],
        }
        api(token, "PATCH", "/api/config-profiles/", {
            "uuid": profile["uuid"],
            "name": PROFILE_NAME,
            "config": updated_config,
        })

    inbound_response = api(token, "GET", f"/api/config-profiles/{profile['uuid']}/inbounds")
    active_inbounds = as_list(inbound_response, "inbounds", "items")
    by_tag = {item.get("tag"): item for item in active_inbounds}
    missing = [tag for tag in EXPECTED_TAGS if tag not in by_tag]
    if missing:
        raise RuntimeError("required inbounds disappeared: " + ", ".join(missing))
    inbound_uuids = [by_tag[tag]["uuid"] for tag in EXPECTED_TAGS]

    api(token, "PATCH", "/api/nodes/", {
        "uuid": NODE_UUID,
        "configProfile": {
            "activeConfigProfileUuid": profile["uuid"],
            "activeInbounds": inbound_uuids,
        },
    })
    api(token, "PATCH", "/api/internal-squads/", {
        "uuid": SQUAD_UUID,
        "inbounds": inbound_uuids,
    })
    for host in grpc_hosts:
        api(token, "DELETE", f"/api/hosts/{host['uuid']}")

    print("grpc_removed=true")
    print("active_transports=3")
    print(f"backup_created={backup_path}")


if __name__ == "__main__":
    main()
