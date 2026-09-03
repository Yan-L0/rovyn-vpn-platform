#!/usr/bin/env python3
"""Verify production subscription links and client routing without printing secrets."""

from __future__ import annotations

import base64
import json
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from manage_transport_test_user import APP_ENV, PANEL_URL, SQUAD_UUID, api, read_env


def decode_b64(value: bytes | str) -> bytes:
    raw = value.encode() if isinstance(value, str) else value
    raw = b"".join(raw.split())
    return base64.b64decode(raw + b"=" * ((4 - len(raw) % 4) % 4))


def fetch(url: str, user_agent: str) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "*/*"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read(), dict(response.headers.items())


def single(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    return values[0] if values else ""


def main() -> int:
    token = read_env(APP_ENV)["REMNAWAVE_API_TOKEN"]
    created: dict[str, Any] | None = None
    try:
        created = api(
            token,
            "POST",
            "/api/users",
            {
                "username": "verify_" + secrets.token_hex(6),
                "expireAt": (
                    datetime.now(timezone.utc) + timedelta(hours=2)
                ).isoformat(),
                "trafficLimitBytes": 1024**3,
                "trafficLimitStrategy": "NO_RESET",
                "hwidDeviceLimit": 2,
                "activeInternalSquads": [SQUAD_UUID],
                "description": "temporary subscription output verifier",
            },
        )
        body, headers = fetch(created["subscriptionUrl"], "v2rayTun/4.0")
        links = [
            line
            for line in decode_b64(body).decode().splitlines()
            if line.strip()
        ]
        if len(links) != 4:
            raise RuntimeError(f"expected 4 links, got {len(links)}")

        transports: dict[str, tuple[str, str, dict[str, list[str]]]] = {}
        for link in links:
            parsed = urllib.parse.urlparse(link)
            label = urllib.parse.unquote(parsed.fragment)
            query = urllib.parse.parse_qs(parsed.query)
            network = (
                "hysteria2"
                if parsed.scheme == "hysteria2"
                else single(query, "type")
            )
            transports[network] = (parsed.scheme, label, query)

        raw_key = "tcp" if "tcp" in transports else "raw"
        raw = transports[raw_key]
        grpc = transports["grpc"]
        xhttp = transports["xhttp"]
        hysteria = transports["hysteria2"]
        if raw[0] != "vless" or single(raw[2], "security") != "reality":
            raise RuntimeError("RAW is not VLESS REALITY")
        if single(raw[2], "sni") != "node.vpn.example":
            raise RuntimeError("RAW REALITY SNI is incorrect")
        if single(raw[2], "fp") != "firefox":
            raise RuntimeError("RAW REALITY fingerprint is not firefox")
        if grpc[0] != "vless" or single(grpc[2], "security") != "tls":
            raise RuntimeError("gRPC is not VLESS TLS")
        if single(grpc[2], "fp") != "firefox":
            raise RuntimeError("gRPC fingerprint is not firefox")
        if xhttp[0] != "vless" or single(xhttp[2], "security") != "tls":
            raise RuntimeError("XHTTP is not VLESS TLS")
        if single(xhttp[2], "fp") != "firefox":
            raise RuntimeError("XHTTP fingerprint is not firefox")
        if single(xhttp[2], "mode") != "stream-up":
            raise RuntimeError("XHTTP mode is not stream-up")
        if not single(grpc[2], "serviceName"):
            raise RuntimeError("gRPC serviceName is missing")
        if not single(xhttp[2], "path") or not single(xhttp[2], "mode"):
            raise RuntimeError("XHTTP path or mode is missing")

        finalmask = json.loads(urllib.parse.unquote(single(hysteria[2], "fm")))
        quic = finalmask.get("quicParams", {})
        if quic.get("congestion") != "bbr":
            raise RuntimeError("Hysteria2 FinalMask BBR is missing")
        if quic.get("maxIdleTimeout") != 30:
            raise RuntimeError("Hysteria2 stale-path timeout is incorrect")
        if quic.get("keepAlivePeriod") != 10:
            raise RuntimeError("Hysteria2 keepalive period is incorrect")
        if quic.get("disablePathMTUDiscovery") is not True:
            raise RuntimeError("Hysteria2 safe mobile MTU mode is missing")

        routing_header = next(
            (value for key, value in headers.items() if key.lower() == "routing"),
            "",
        )
        routing = json.loads(decode_b64(routing_header))
        if len(routing.get("rules", [])) != 6:
            raise RuntimeError("routing header does not contain 6 rules")

        happ_body, happ_headers = fetch(
            created["subscriptionUrl"], "Happ/5.5.0/ios"
        )
        happ_configs = json.loads(happ_body)
        if not isinstance(happ_configs, list):
            raise RuntimeError("Happ subscription is not a JSON config list")
        recovered_networks: set[str] = set()
        for config in happ_configs:
            for outbound in config.get("outbounds", []):
                stream = outbound.get("streamSettings", {})
                network = stream.get("network")
                if network not in {"raw", "tcp", "grpc", "xhttp"}:
                    continue
                sockopt = stream.get("sockopt", {})
                if sockopt.get("tcpKeepAliveIdle") != 45:
                    raise RuntimeError(f"{network} TCP keepalive idle is incorrect")
                if sockopt.get("tcpKeepAliveInterval") != 15:
                    raise RuntimeError(
                        f"{network} TCP keepalive interval is incorrect"
                    )
                if sockopt.get("tcpUserTimeout") != 30000:
                    raise RuntimeError(f"{network} TCP user timeout is incorrect")
                recovered_networks.add("raw" if network == "tcp" else network)
        missing_networks = {"raw", "grpc", "xhttp"} - recovered_networks
        if missing_networks:
            raise RuntimeError(
                "Happ TCP recovery settings are missing for: "
                + ", ".join(sorted(missing_networks))
            )
        happ_routing = next(
            (
                value
                for key, value in happ_headers.items()
                if key.lower() == "routing"
            ),
            "",
        )
        if happ_routing != routing_header:
            raise RuntimeError("Happ routing header differs from v2RayTun")

        print("subscription_links=4/4")
        print("raw_reality=valid")
        print("grpc_tls=valid")
        print("xhttp_tls=valid")
        print("tcp_recovery_happ=3/3")
        print("hysteria2_bbr_and_recovery=valid")
        print("routing_v2raytun=6_rules")
        print("routing_happ=6_rules")
        return 0
    finally:
        if created is not None:
            api(token, "DELETE", f"/api/users/{created['uuid']}")
            print("temporary_user_deleted=true")


if __name__ == "__main__":
    raise SystemExit(main())
