#!/usr/bin/env python3
"""Configure resilient Happ/v2RayTun subscriptions with a private backup."""

from __future__ import annotations

import base64
import json
import os
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def api(
    base_url: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        document = json.load(response)
    return document.get("response", document)


def rule_id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"rovyn-routing:{name}")).upper()


def routing_document() -> dict[str, Any]:
    return {
        "id": rule_id("document"),
        "name": "Rovyn Smart Routing",
        "domainStrategy": "IPIfNonMatch",
        "domainMatcher": "hybrid",
        "balancers": [],
        "rules": [
            {
                "id": rule_id("bittorrent"),
                "__name__": "BitTorrent напрямую",
                "type": "field",
                "protocol": ["bittorrent"],
                "outboundTag": "direct",
            },
            {
                "id": rule_id("local-services"),
                "__name__": "Локальные сервисы напрямую",
                "type": "field",
                "domain": [
                    # Subscription refresh must not depend on the health of
                    # the currently selected VPN tunnel.
                    "domain:subscription.vpn.example",
                    "domain:panel.vpn.example",
                    "domain:bot.vpn.example",
                    "domain:mtalk.google.com",
                    "domain:push.apple.com",
                    "domain:api.push.apple.com",
                    "domain:push-apple.com.akadns.net",
                    "domain:courier.push.apple.com",
                    "domain:yandex.com",
                    "domain:yandex.net",
                    "domain:mail.ru",
                    "domain:vk.com",
                    "domain:vkusvill.ru",
                    "domain:ozon.ru",
                    "domain:wildberries.ru",
                    "domain:sberbank.ru",
                    "domain:tbank.ru",
                    "domain:tinkoff.ru",
                    "domain:gosuslugi.ru",
                    "domain:nalog.gov.ru",
                    "domain:mos.ru",
                    "domain:2gis.com",
                    "domain:2gis.ru",
                ],
                "outboundTag": "direct",
            },
            {
                "id": rule_id("apple-network"),
                "__name__": "Apple Push напрямую",
                "type": "field",
                "ip": ["17.0.0.0/8"],
                "outboundTag": "direct",
            },
            {
                "id": rule_id("private-and-ru-domains"),
                "__name__": "Частные и российские домены напрямую",
                "type": "field",
                "domain": ["geosite:private", "geosite:category-ru"],
                "outboundTag": "direct",
            },
            {
                "id": rule_id("private-and-ru-networks"),
                "__name__": "Частные и российские сети напрямую",
                "type": "field",
                "ip": ["geoip:private", "geoip:ru"],
                "outboundTag": "direct",
            },
            {
                "id": rule_id("vpn-default"),
                "__name__": "Остальной трафик через VPN",
                "type": "field",
                "network": "tcp,udp",
                "outboundTag": "proxy",
            },
        ],
    }


def main() -> None:
    environment = read_env(APP_ENV)
    base_url = environment["REMNAWAVE_BASE_URL"]
    token = environment["REMNAWAVE_API_TOKEN"]
    settings = api(base_url, token, "GET", "/api/subscription-settings")

    BACKUP_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = BACKUP_DIRECTORY / f"subscription-settings-{timestamp}.json"
    backup_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2))
    os.chmod(backup_path, 0o600)

    routing_json = json.dumps(
        routing_document(), ensure_ascii=False, separators=(",", ":")
    ).encode()
    routing_header = base64.b64encode(routing_json).decode()
    headers = dict(settings.get("customResponseHeaders") or {})
    headers["routing"] = routing_header

    api(
        base_url,
        token,
        "PATCH",
        "/api/subscription-settings",
        {
            "uuid": settings["uuid"],
            # Happ honors this response header on iOS, Android/TV and desktop.
            # One hour is the shortest supported interval and missed updates are
            # retried by Happ the next time the application starts.
            "profileUpdateInterval": 1,
            "happRouting": routing_header,
            "customResponseHeaders": headers,
        },
    )
    print("profile_update_interval_hours=1")
    print(f"routing_configured=true header_bytes={len(routing_header)}")
    print(f"backup_created={backup_path}")


if __name__ == "__main__":
    main()
