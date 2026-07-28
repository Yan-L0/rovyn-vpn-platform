#!/usr/bin/env python3
"""Create a private Remnawave configuration snapshot without logging secrets."""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PANEL_URL = "https://panel.vpn.example"
APP_ENV = Path("/opt/vpn-platform/.env.production")
BACKUP_DIRECTORY = Path("/opt/remnawave/backups")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def api(token: str, path: str) -> Any:
    request = urllib.request.Request(
        PANEL_URL + path,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    token = read_env(APP_ENV)["REMNAWAVE_API_TOKEN"]
    snapshot = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "configProfiles": api(token, "/api/config-profiles/"),
        "hosts": api(token, "/api/hosts/"),
        "nodes": api(token, "/api/nodes/"),
        "internalSquads": api(token, "/api/internal-squads/"),
    }
    BACKUP_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = BACKUP_DIRECTORY / f"rovyn-production-{timestamp}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    os.chmod(path, 0o600)
    print(f"backup_created={path}")


if __name__ == "__main__":
    main()
