#!/usr/bin/env python3
"""Provision the first production Remnawave profile without logging secrets."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PANEL_URL = "https://panel.vpn.example"
PROFILE_NAME = "Rovyn-Production"
NODE_UUID = "02d38534-9370-4a0e-9aca-50f115292b33"
SQUAD_UUID = "8e319819-2110-44ab-b6f5-e76138233ed5"
NODE_ADDRESS = "node.vpn.example"
REALITY_TARGET = "127.0.0.1:9443"
REALITY_SNI = NODE_ADDRESS
CERTIFICATE_FILE = "/var/lib/remnawave/configs/xray/ssl/fullchain.pem"
PRIVATE_KEY_FILE = "/var/lib/remnawave/configs/xray/ssl/privkey.pem"
BACKUP_DIRECTORY = Path("/opt/remnawave/backups")


def read_env(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def api(token: str, method: str, path: str, payload: Any | None = None) -> Any:
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
            body = json.load(response)
    except urllib.error.HTTPError as error:
        # Never echo the response body: validation errors may contain the profile.
        raise RuntimeError(f"{method} {path} failed with HTTP {error.code}") from error
    return body.get("response", body)


def profile_config(secrets: dict[str, str]) -> dict[str, Any]:
    reality = []
    for index in range(1, 4):
        reality.append(
            {
                "private": secrets[f"REALITY_{index}_PRIVATE"],
                "short": secrets[f"REALITY_{index}_SHORT"],
            }
        )

    sniffing = {
        "enabled": True,
        "destOverride": ["http", "tls", "quic"],
        "routeOnly": True,
    }

    def reality_settings(index: int) -> dict[str, Any]:
        return {
            "show": False,
            "target": REALITY_TARGET,
            "xver": 0,
            "serverNames": [REALITY_SNI],
            "privateKey": reality[index]["private"],
            "shortIds": [reality[index]["short"]],
        }

    def tls_settings(alpn: list[str]) -> dict[str, Any]:
        return {
            "serverName": NODE_ADDRESS,
            "alpn": alpn,
            "minVersion": "1.3",
            "certificates": [
                {
                    "usage": "encipherment",
                    "certificateFile": CERTIFICATE_FILE,
                    "keyFile": PRIVATE_KEY_FILE,
                }
            ],
        }

    def stable_tcp_sockopt() -> dict[str, Any]:
        return {
            "tcpKeepAliveIdle": 45,
            "tcpKeepAliveInterval": 15,
            "tcpUserTimeout": 30000,
        }

    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "VLESS-REALITY-RAW",
                "listen": "0.0.0.0",
                "port": 443,
                "protocol": "vless",
                "settings": {
                    "clients": [],
                    "decryption": "none",
                    "flow": "xtls-rprx-vision",
                },
                "streamSettings": {
                    "network": "raw",
                    "security": "reality",
                    "realitySettings": reality_settings(0),
                    "sockopt": stable_tcp_sockopt(),
                },
                "sniffing": sniffing,
            },
            {
                "tag": "VLESS-REALITY-GRPC",
                "listen": "0.0.0.0",
                "port": 8443,
                "protocol": "vless",
                "settings": {"clients": [], "decryption": "none", "flow": ""},
                "streamSettings": {
                    "network": "grpc",
                    "security": "tls",
                    "tlsSettings": tls_settings(["h2"]),
                    "grpcSettings": {
                        "serviceName": secrets["GRPC_SERVICE"],
                        "multiMode": False,
                    },
                    "sockopt": stable_tcp_sockopt(),
                },
                "sniffing": sniffing,
            },
            {
                "tag": "VLESS-REALITY-XHTTP",
                "listen": "0.0.0.0",
                "port": 2096,
                "protocol": "vless",
                "settings": {"clients": [], "decryption": "none", "flow": ""},
                "streamSettings": {
                    "network": "xhttp",
                    "security": "tls",
                    "tlsSettings": tls_settings(["h2"]),
                    "xhttpSettings": {
                        "path": secrets["XHTTP_PATH"],
                        "mode": "stream-up",
                    },
                    "sockopt": stable_tcp_sockopt(),
                },
                "sniffing": sniffing,
            },
            {
                "tag": "HYSTERIA2-TLS",
                "listen": "0.0.0.0",
                "port": 443,
                "protocol": "hysteria",
                "settings": {
                    "version": 2,
                    "clients": [],
                },
                "streamSettings": {
                    "network": "hysteria",
                    "security": "tls",
                    "tlsSettings": tls_settings(["h3"]),
                    "hysteriaSettings": {
                        "version": 2,
                        "auth": secrets["HYSTERIA_AUTH"],
                        "udpIdleTimeout": 30,
                    },
                    "finalmask": {
                        "quicParams": {
                            "congestion": "bbr",
                            "bbrProfile": "standard",
                            "debug": False,
                            "initStreamReceiveWindow": 8388608,
                            "maxStreamReceiveWindow": 8388608,
                            "initConnectionReceiveWindow": 20971520,
                            "maxConnectionReceiveWindow": 20971520,
                            # Detect a dead mobile/NAT path quickly and use the
                            # conservative QUIC packet size after network changes.
                            "maxIdleTimeout": 30,
                            "keepAlivePeriod": 10,
                            "disablePathMTUDiscovery": True,
                            "maxIncomingStreams": 1024,
                        }
                    },
                },
            },
        ],
        "outbounds": [
            {"tag": "DIRECT", "protocol": "freedom"},
            {"tag": "BLOCK", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "ip": ["geoip:private"],
                    "outboundTag": "BLOCK",
                }
            ],
        },
    }


def as_list(value: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, list):
                return candidate
    return []


def main() -> int:
    app_env = read_env("/opt/vpn-platform/.env.production")
    transport_secrets = read_env("/opt/remnawave/reality.env")
    token = app_env["REMNAWAVE_API_TOKEN"]
    config = profile_config(transport_secrets)

    profiles = as_list(api(token, "GET", "/api/config-profiles/"), "configProfiles", "items")
    profile = next((item for item in profiles if item.get("name") == PROFILE_NAME), None)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if profile:
        BACKUP_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
        backup_path = BACKUP_DIRECTORY / f"config-profile-{timestamp}.json"
        backup_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2))
        os.chmod(backup_path, 0o600)
        profile = api(
            token,
            "PATCH",
            "/api/config-profiles/",
            {"uuid": profile["uuid"], "name": PROFILE_NAME, "config": config},
        )
        action = "updated"
    else:
        profile = api(
            token,
            "POST",
            "/api/config-profiles/",
            {"name": PROFILE_NAME, "config": config},
        )
        action = "created"

    profile_uuid = profile["uuid"]
    inbound_response = api(
        token, "GET", f"/api/config-profiles/{profile_uuid}/inbounds"
    )
    inbounds = as_list(inbound_response, "inbounds", "items")
    by_tag = {item["tag"]: item for item in inbounds}
    expected_tags = [
        "VLESS-REALITY-RAW",
        "VLESS-REALITY-GRPC",
        "VLESS-REALITY-XHTTP",
        "HYSTERIA2-TLS",
    ]
    missing = [tag for tag in expected_tags if tag not in by_tag]
    if missing:
        raise RuntimeError(f"Remnawave did not create expected inbound tags: {missing}")
    inbound_uuids = [by_tag[tag]["uuid"] for tag in expected_tags]

    api(
        token,
        "PATCH",
        "/api/nodes/",
        {
            "uuid": NODE_UUID,
            "configProfile": {
                "activeConfigProfileUuid": profile_uuid,
                "activeInbounds": inbound_uuids,
            },
        },
    )
    api(
        token,
        "PATCH",
        "/api/internal-squads/",
        {"uuid": SQUAD_UUID, "inbounds": inbound_uuids},
    )

    host_specs = [
        {
            "tag": "VLESS-REALITY-RAW",
            "remark": "🌐 Основной REALITY",
            "port": 443,
            "sni": REALITY_SNI,
            "alpn": "http/1.1",
            "fingerprint": "firefox",
            "xhttpExtraParams": None,
            "sockoptParams": {
                "tcpKeepAliveIdle": 45,
                "tcpKeepAliveInterval": 15,
                "tcpUserTimeout": 30000,
            },
            "serverDescription": None,
        },
        {
            "tag": "VLESS-REALITY-GRPC",
            "remark": "⚡ Резервный gRPC TLS",
            "port": 8443,
            "sni": NODE_ADDRESS,
            "alpn": "h2",
            "fingerprint": "firefox",
            "xhttpExtraParams": None,
            "sockoptParams": {
                "tcpKeepAliveIdle": 45,
                "tcpKeepAliveInterval": 15,
                "tcpUserTimeout": 30000,
            },
            "serverDescription": None,
        },
        {
            "tag": "VLESS-REALITY-XHTTP",
            "remark": "🛡️ Надёжный XHTTP TLS",
            "port": 2096,
            "sni": NODE_ADDRESS,
            "alpn": "h2",
            "fingerprint": "firefox",
            "xhttpExtraParams": None,
            "sockoptParams": {
                "tcpKeepAliveIdle": 45,
                "tcpKeepAliveInterval": 15,
                "tcpUserTimeout": 30000,
            },
            "serverDescription": None,
        },
        {
            "tag": "HYSTERIA2-TLS",
            "remark": "🚀 Быстрый Hysteria2 BBR",
            "port": 443,
            "sni": NODE_ADDRESS,
            "alpn": "h3",
            "fingerprint": None,
            "xhttpExtraParams": None,
            "sockoptParams": None,
            "serverDescription": None,
        },
    ]

    existing_hosts = as_list(api(token, "GET", "/api/hosts/"), "hosts", "items")
    BACKUP_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing_by_tag: dict[str, dict[str, Any]] = {}
    for host in existing_hosts:
        for tag in host.get("tags", []):
            if tag.startswith("ROVYN_"):
                existing_by_tag[tag] = host

    hosts_backup_path = BACKUP_DIRECTORY / f"managed-hosts-{timestamp}.json"
    hosts_backup_path.write_text(
        json.dumps(list(existing_by_tag.values()), ensure_ascii=False, indent=2)
    )
    os.chmod(hosts_backup_path, 0o600)

    for spec in host_specs:
        managed_tag = "ROVYN_" + spec["tag"].replace("-", "_")
        payload = {
            "inbound": {
                "configProfileUuid": profile_uuid,
                "configProfileInboundUuid": by_tag[spec["tag"]]["uuid"],
            },
            "remark": spec["remark"],
            "address": NODE_ADDRESS,
            "port": spec["port"],
            "path": None,
            "sni": spec["sni"],
            "host": None,
            "alpn": spec["alpn"],
            "fingerprint": spec["fingerprint"],
            "xhttpExtraParams": spec["xhttpExtraParams"],
            "sockoptParams": spec["sockoptParams"],
            "isDisabled": False,
            "securityLayer": "DEFAULT",
            "serverDescription": spec["serverDescription"],
            "tags": ["PROD", "PRIMARY", managed_tag],
            "isHidden": False,
            "overrideSniFromAddress": False,
            "keepSniBlank": False,
            "shuffleHost": False,
            "mihomoX25519": False,
            "nodes": [NODE_UUID],
            "excludedInternalSquads": [],
            "excludeFromSubscriptionTypes": [],
        }
        existing = existing_by_tag.get(managed_tag)
        if existing:
            api(token, "PATCH", "/api/hosts/", {"uuid": existing["uuid"], **payload})
        else:
            api(token, "POST", "/api/hosts/", payload)

    print(f"profile={PROFILE_NAME} uuid={profile_uuid} action={action}")
    for tag in expected_tags:
        item = by_tag[tag]
        print(
            f"inbound={tag} uuid={item['uuid']} "
            f"network={item.get('network')} security={item.get('security')} "
            f"port={item.get('port')}"
        )
    print(f"node={NODE_UUID} squad={SQUAD_UUID} hosts={len(host_specs)}")
    if action == "updated":
        print(f"backup_created={backup_path}")
    print(f"hosts_backup_created={hosts_backup_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"provisioning failed: {error}", file=sys.stderr)
        raise SystemExit(1)
