#!/usr/bin/env python3
"""Create or remove the disposable user used by native client acceptance tests."""

from __future__ import annotations

import json
import os
import secrets
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PANEL_URL = "https://panel.vpn.example"
SQUAD_UUID = "8e319819-2110-44ab-b6f5-e76138233ed5"
APP_ENV = Path("/opt/vpn-platform/.env.production")
USER_FILE = Path("/opt/remnawave/native-acceptance-user.json")
STATE_FILE = Path("/opt/remnawave/native-acceptance-state.json")


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


def create(token: str) -> None:
    if STATE_FILE.exists() or USER_FILE.exists():
        raise RuntimeError("temporary acceptance state already exists")
    created = api(
        token,
        "POST",
        "/api/users",
        {
            "username": "native_" + secrets.token_hex(6),
            "expireAt": (
                datetime.now(timezone.utc) + timedelta(hours=2)
            ).isoformat(),
            "trafficLimitBytes": 5 * 1024**3,
            "trafficLimitStrategy": "NO_RESET",
            "hwidDeviceLimit": 2,
            "activeInternalSquads": [SQUAD_UUID],
            "description": "temporary native client acceptance user",
        },
    )
    try:
        USER_FILE.write_text(
            json.dumps({"subscriptionUrl": created["subscriptionUrl"]})
        )
        STATE_FILE.write_text(json.dumps({"uuid": created["uuid"]}))
        os.chmod(USER_FILE, 0o600)
        os.chmod(STATE_FILE, 0o600)
    except Exception:
        api(token, "DELETE", f"/api/users/{created['uuid']}")
        USER_FILE.unlink(missing_ok=True)
        STATE_FILE.unlink(missing_ok=True)
        raise
    print("temporary_user_created=true")


def delete(token: str) -> None:
    if not STATE_FILE.exists():
        USER_FILE.unlink(missing_ok=True)
        print("temporary_user_deleted=already_absent")
        return
    state = json.loads(STATE_FILE.read_text())
    api(token, "DELETE", f"/api/users/{state['uuid']}")
    USER_FILE.unlink(missing_ok=True)
    STATE_FILE.unlink(missing_ok=True)
    print("temporary_user_deleted=true")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"create", "delete"}:
        print("usage: manage_transport_test_user.py create|delete", file=sys.stderr)
        return 2
    token = read_env(APP_ENV)["REMNAWAVE_API_TOKEN"]
    if sys.argv[1] == "create":
        create(token)
    else:
        delete(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
