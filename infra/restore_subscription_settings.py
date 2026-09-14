#!/usr/bin/env python3
"""Restore Remnawave subscription delivery settings through the configured API."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any


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


def api(base_url: str, token: str, payload: dict[str, Any]) -> None:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/subscription-settings",
        data=json.dumps(payload).encode(),
        method="PATCH",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in {200, 204}:
            raise RuntimeError(f"unexpected API status: {response.status}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    backup = json.loads(args.backup.read_text())
    environment = read_env(APP_ENV)
    api(
        environment["REMNAWAVE_BASE_URL"],
        environment["REMNAWAVE_API_TOKEN"],
        {
            "uuid": backup["uuid"],
            "profileUpdateInterval": 1,
            "happRouting": backup.get("happRouting"),
            "customResponseHeaders": backup.get("customResponseHeaders") or {},
        },
    )
    print("subscription_settings_restored=true")
    print("profile_update_interval_hours=1")


if __name__ == "__main__":
    main()
