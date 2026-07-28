#!/usr/bin/env python3
"""Apply or roll back the DPI-tested Remnawave Host client parameters."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from manage_transport_test_user import APP_ENV, api, read_env


BACKUP_DIRECTORY = Path("/opt/remnawave/backups")
TARGETS: dict[str, dict[str, Any]] = {
    "ROVYN_VLESS_REALITY_RAW": {
        "fingerprint": "firefox",
        "xhttpExtraParams": None,
    },
    "ROVYN_VLESS_REALITY_GRPC": {
        "fingerprint": "firefox",
        "xhttpExtraParams": None,
    },
}


def hosts(token: str) -> list[dict[str, Any]]:
    response = api(token, "GET", "/api/hosts/")
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for key in ("hosts", "items", "response"):
            value = response.get(key)
            if isinstance(value, list):
                return value
    raise RuntimeError("unexpected hosts response")


def managed_hosts(token: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for host in hosts(token):
        for tag in host.get("tags", []):
            if tag in TARGETS:
                result[tag] = host
    missing = sorted(set(TARGETS) - set(result))
    if missing:
        raise RuntimeError("managed hosts are missing: " + ", ".join(missing))
    return result


def restore(token: str, backup: dict[str, Any]) -> None:
    for item in backup["hosts"]:
        api(
            token,
            "PATCH",
            "/api/hosts/",
            {
                "uuid": item["uuid"],
                "fingerprint": item["fingerprint"],
                "xhttpExtraParams": item["xhttpExtraParams"],
            },
        )


def apply(token: str) -> Path:
    current = managed_hosts(token)
    backup = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "hosts": [
            {
                "tag": tag,
                "uuid": host["uuid"],
                "fingerprint": host.get("fingerprint"),
                "xhttpExtraParams": host.get("xhttpExtraParams"),
            }
            for tag, host in sorted(current.items())
        ],
    }
    BACKUP_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = BACKUP_DIRECTORY / f"dpi-host-settings-{timestamp}.json"
    backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2))
    os.chmod(backup_path, 0o600)

    try:
        for tag, target in TARGETS.items():
            api(
                token,
                "PATCH",
                "/api/hosts/",
                {"uuid": current[tag]["uuid"], **target},
            )
        updated = managed_hosts(token)
        for tag, target in TARGETS.items():
            for field, expected in target.items():
                if updated[tag].get(field) != expected:
                    raise RuntimeError(f"{tag} did not retain {field}")
    except Exception:
        restore(token, backup)
        print("dpi_host_fixes=rolled_back", file=sys.stderr)
        raise

    print("dpi_host_fixes=applied")
    print(f"backup_created={backup_path}")
    return backup_path


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"apply", "rollback"}:
        print(
            "usage: apply_dpi_host_fixes.py apply|rollback [backup.json]",
            file=sys.stderr,
        )
        return 2
    token = read_env(APP_ENV)["REMNAWAVE_API_TOKEN"]
    if sys.argv[1] == "apply":
        apply(token)
        return 0
    if len(sys.argv) != 3:
        print("rollback requires a backup path", file=sys.stderr)
        return 2
    backup_path = Path(sys.argv[2])
    restore(token, json.loads(backup_path.read_text()))
    print("dpi_host_fixes=rolled_back")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
