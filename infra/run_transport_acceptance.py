#!/usr/bin/env python3
"""Create a disposable user, test every transport, and always remove the user."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PANEL_URL = "https://panel.vpn.example"
SQUAD_UUID = "8e319819-2110-44ab-b6f5-e76138233ed5"
APP_ENV = Path("/opt/vpn-platform/.env.production")
WORK_DIRECTORY = Path("/opt/remnawave")
USER_FILE = WORK_DIRECTORY / "transport-acceptance-user.json"
TRANSPORT_TEST = WORK_DIRECTORY / "test_node_transports.py"


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
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        if response.status == 204 or not body:
            return {}
        document = json.loads(body)
    return document.get("response", document)


def main() -> int:
    token = read_env(APP_ENV)["REMNAWAVE_API_TOKEN"]
    created: dict[str, Any] | None = None
    try:
        created = api(
            token,
            "POST",
            "/api/users",
            {
                "username": "accept_" + secrets.token_hex(6),
                "expireAt": (
                    datetime.now(timezone.utc) + timedelta(hours=2)
                ).isoformat(),
                "trafficLimitBytes": 5 * 1024**3,
                "trafficLimitStrategy": "NO_RESET",
                "hwidDeviceLimit": 2,
                "activeInternalSquads": [SQUAD_UUID],
                "description": "temporary transport acceptance user",
            },
        )
        USER_FILE.write_text(
            json.dumps({"subscriptionUrl": created["subscriptionUrl"]})
        )
        os.chmod(USER_FILE, 0o600)
        environment = os.environ.copy()
        environment.update(
            {
                "E2E_USER_FILE": str(USER_FILE),
                "E2E_TARGET_ADDRESS": "node.vpn.example",
                "E2E_WORK_DIRECTORY": str(WORK_DIRECTORY),
            }
        )
        result = subprocess.run(
            [sys.executable, str(TRANSPORT_TEST)],
            env=environment,
            check=False,
        )
        print(f"transport_acceptance={'pass' if result.returncode == 0 else 'fail'}")
        return result.returncode
    finally:
        USER_FILE.unlink(missing_ok=True)
        if created is not None:
            api(token, "DELETE", f"/api/users/{created['uuid']}")
            print("temporary_user_deleted=true")


if __name__ == "__main__":
    raise SystemExit(main())
