#!/usr/bin/env python3
"""Run disposable Xray clients against every link in the E2E subscription."""

from __future__ import annotations

import base64
import json
import os
import re
import signal
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


IMAGE = "remnawave/node:2.7.0"
TEST_URL = os.environ.get(
    "E2E_TEST_URL", "https://www.cloudflare.com/cdn-cgi/trace"
)
XRAY_BINARY = os.environ.get("E2E_XRAY_BIN", "")
E2E_USER_FILE = os.environ.get(
    "E2E_USER_FILE", "/opt/remnanode/e2e-user.json"
)
TARGET_ADDRESS = os.environ.get("E2E_TARGET_ADDRESS", "127.0.0.1")
WORK_DIRECTORY = os.environ.get("E2E_WORK_DIRECTORY", "/opt/remnanode")
MAX_LINKS = int(os.environ.get("E2E_MAX_LINKS", "0"))
LABEL_FILTER = os.environ.get("E2E_LABEL_CONTAINS", "")
OUTBOUND_INTERFACE = os.environ.get("E2E_OUTBOUND_INTERFACE", "")
FINGERPRINT_OVERRIDE = os.environ.get("E2E_FINGERPRINT_OVERRIDE", "")
XHTTP_MODE_OVERRIDE = os.environ.get("E2E_XHTTP_MODE_OVERRIDE", "")
TEST_TIMEOUT = int(os.environ.get("E2E_TIMEOUT", "20"))
IDLE_SECONDS = int(os.environ.get("E2E_IDLE_SECONDS", "0"))
SOCKS_BASE_PORT = int(os.environ.get("E2E_SOCKS_BASE_PORT", "10880"))
OUTAGE_SECONDS = int(os.environ.get("E2E_OUTAGE_SECONDS", "0"))
HAPP_JSON = os.environ.get("E2E_HAPP_JSON", "0") == "1"


def fetch_happ_configs() -> list[tuple[str, dict[str, Any]]]:
    url = json.loads(Path(E2E_USER_FILE).read_text())["subscriptionUrl"]
    request = urllib.request.Request(url, headers={"User-Agent": "Happ/5.5.0/ios"})
    with urllib.request.urlopen(request, timeout=30) as response:
        configs = json.load(response)
    if not isinstance(configs, list):
        raise RuntimeError("expected Happ JSON config list")
    results = []
    for config in configs:
        proxies = [o for o in config.get("outbounds", [])
                   if o.get("protocol") in {"vless", "hysteria"}
                   and o.get("tag") == "proxy"]
        if len(proxies) != 1:
            raise RuntimeError("expected one VPN outbound per Happ profile")
        network = proxies[0].get("streamSettings", {}).get("network", "unknown")
        # Retain the generated VPN outbound (including sockopts/finalmask).
        # The probe must always traverse it, regardless of split-routing rules.
        results.append((network, {"log": {"loglevel": "warning"},
                                  "outbounds": proxies}))
    return results


def sanitize(message: str) -> str:
    message = re.sub(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b", "<uuid>", message
    )
    return re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "<secret>", message)


def fetch_links() -> list[str]:
    subscription_url = json.loads(
        Path(E2E_USER_FILE).read_text()
    )["subscriptionUrl"]
    request = urllib.request.Request(
        subscription_url,
        headers={"User-Agent": "v2rayTun/4.0", "Accept": "*/*"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        encoded = b"".join(response.read().split())
    decoded = base64.b64decode(encoded + b"=" * ((4 - len(encoded) % 4) % 4))
    return [line for line in decoded.decode().splitlines() if line.strip()]


def single(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def decode_share_json(value: str) -> dict[str, Any] | None:
    if not value:
        return None
    raw = urllib.parse.unquote(value)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = None
    if isinstance(result, dict):
        return result
    try:
        padding = "=" * ((4 - len(raw) % 4) % 4)
        decoded = base64.urlsafe_b64decode(raw + padding)
        result = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    return result if isinstance(result, dict) else None


def vless_outbound(parsed: urllib.parse.ParseResult) -> dict[str, Any]:
    query = urllib.parse.parse_qs(parsed.query)
    network = single(query, "type", "tcp")
    if network == "tcp":
        network = "raw"
    user: dict[str, Any] = {
        "id": urllib.parse.unquote(parsed.username or ""),
        "encryption": single(query, "encryption", "none"),
    }
    flow = single(query, "flow")
    if flow:
        user["flow"] = flow

    stream: dict[str, Any] = {
        "network": network,
        "security": single(query, "security", "none"),
    }
    if stream["security"] == "reality":
        stream["realitySettings"] = {
            "serverName": single(query, "sni"),
            "fingerprint": single(query, "fp", "chrome"),
            "publicKey": single(query, "pbk"),
            "shortId": single(query, "sid"),
            "spiderX": single(query, "spx"),
        }
    elif stream["security"] == "tls":
        tls_settings: dict[str, Any] = {
            "serverName": single(query, "sni"),
            "fingerprint": single(query, "fp", "chrome"),
            "allowInsecure": single(query, "allowInsecure").lower() == "true",
        }
        alpn = single(query, "alpn")
        if alpn:
            tls_settings["alpn"] = alpn.split(",")
        stream["tlsSettings"] = tls_settings
    if network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": single(query, "serviceName"),
            "multiMode": single(query, "mode") == "multi",
        }
    elif network == "xhttp":
        stream["xhttpSettings"] = {
            "path": single(query, "path"),
            "mode": single(query, "mode", "auto"),
        }
    finalmask = decode_share_json(single(query, "fm"))
    if finalmask:
        stream["finalmask"] = finalmask

    return {
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": TARGET_ADDRESS,
                    "port": parsed.port,
                    "users": [user],
                }
            ]
        },
        "streamSettings": stream,
    }


def hysteria_outbound(parsed: urllib.parse.ParseResult) -> dict[str, Any]:
    query = urllib.parse.parse_qs(parsed.query)
    stream: dict[str, Any] = {
        "network": "hysteria",
        "security": "tls",
        "tlsSettings": {
            "serverName": single(query, "sni"),
            "alpn": ["h3"],
            "allowInsecure": False,
        },
        "hysteriaSettings": {
            "version": 2,
            "auth": urllib.parse.unquote(parsed.username or ""),
        },
    }
    finalmask = decode_share_json(single(query, "fm"))
    if finalmask:
        stream["finalmask"] = finalmask
    return {
        "protocol": "hysteria",
        "settings": {
            "version": 2,
            "address": TARGET_ADDRESS,
            "port": parsed.port,
        },
        "streamSettings": stream,
    }


def make_config(link: str, socks_port: int) -> tuple[str, dict[str, Any]]:
    parsed = urllib.parse.urlparse(link)
    if parsed.scheme == "vless":
        outbound = vless_outbound(parsed)
        label = urllib.parse.unquote(parsed.fragment)
    elif parsed.scheme == "hysteria2":
        outbound = hysteria_outbound(parsed)
        label = urllib.parse.unquote(parsed.fragment)
    else:
        raise RuntimeError(f"unsupported subscription scheme: {parsed.scheme}")
    if OUTBOUND_INTERFACE:
        outbound["streamSettings"].setdefault("sockopt", {})[
            "interface"
        ] = OUTBOUND_INTERFACE
    stream = outbound["streamSettings"]
    if FINGERPRINT_OVERRIDE:
        if "realitySettings" in stream:
            stream["realitySettings"]["fingerprint"] = FINGERPRINT_OVERRIDE
        if "tlsSettings" in stream:
            stream["tlsSettings"]["fingerprint"] = FINGERPRINT_OVERRIDE
    if XHTTP_MODE_OVERRIDE and "xhttpSettings" in stream:
        stream["xhttpSettings"]["mode"] = XHTTP_MODE_OVERRIDE
    config = {
        "log": {"loglevel": "debug"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"udp": True},
            }
        ],
        "outbounds": [outbound],
    }
    return label, config


def run_test(config_path: Path, socks_port: int) -> tuple[bool, str]:
    name = "rovyn-e2e-" + uuid.uuid4().hex[:10]
    network_name = name + "-network"
    network_created = False
    if OUTAGE_SECONDS and (XRAY_BINARY or not 1 <= OUTAGE_SECONDS <= 60):
        raise RuntimeError("outage test requires Docker and 1..60 seconds")
    mount = f"{config_path}:/tmp/client.json:ro"
    if XRAY_BINARY:
        validation_command = [
            XRAY_BINARY,
            "run",
            "-test",
            "-config",
            str(config_path),
        ]
    else:
        validation_command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "host",
            "--entrypoint",
            "/usr/local/bin/xray",
            "--volume",
            mount,
            IMAGE,
            "run",
            "-test",
            "-config",
            "/tmp/client.json",
        ]
    validation = subprocess.run(
        validation_command,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if validation.returncode != 0:
        message = (validation.stderr or validation.stdout).strip().splitlines()[-1]
        return False, f"config-error: {sanitize(message)[:180]}"
    native_process: subprocess.Popen[str] | None = None
    native_log: tempfile.NamedTemporaryFile[str] | None = None
    try:
        if XRAY_BINARY:
            native_log = tempfile.NamedTemporaryFile(
                mode="w+", prefix="rovyn-xray-", suffix=".log"
            )
            native_process = subprocess.Popen(
                [
                    XRAY_BINARY,
                    "run",
                    "-config",
                    str(config_path),
                ],
                text=True,
                stdout=native_log,
                stderr=subprocess.STDOUT,
            )
        else:
            network_args = ["--network", "host"]
            if OUTAGE_SECONDS:
                subprocess.run(["docker", "network", "create", network_name],
                               check=True, capture_output=True, timeout=20)
                network_created = True
                network_args = ["--network", network_name, "--publish",
                                f"127.0.0.1:{socks_port}:{socks_port}"]
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    name,
                    *network_args,
                    "--entrypoint",
                    "/usr/local/bin/xray",
                    "--volume",
                    mount,
                    IMAGE,
                    "run",
                    "-config",
                    "/tmp/client.json",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        time.sleep(2)
        def probe() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    "curl",
                    "--silent",
                    "--show-error",
                    "--output",
                    "/dev/null",
                    "--write-out",
                    "%{http_code} %{speed_download}",
                    "--max-time",
                    str(TEST_TIMEOUT),
                    "--socks5-hostname",
                    f"127.0.0.1:{socks_port}",
                    TEST_URL,
                ],
                text=True,
                capture_output=True,
                timeout=TEST_TIMEOUT + 5,
            )

        result = probe()
        recovery = ""
        if result.returncode == 0 and result.stdout.split()[:1] == ["200"] and OUTAGE_SECONDS:
            # Disconnect only this disposable client. Production node and
            # application networking are never changed by fault injection.
            subprocess.run(["docker", "network", "disconnect", network_name, name],
                           check=True, capture_output=True, timeout=20)
            blocked = probe()
            if blocked.returncode == 0:
                return False, "fault injection did not interrupt client traffic"
            time.sleep(OUTAGE_SECONDS)
            subprocess.run(["docker", "network", "connect", network_name, name],
                           check=True, capture_output=True, timeout=20)
            started = time.monotonic()
            deadline = started + 60
            while True:
                result = probe()
                if result.returncode == 0 and result.stdout.split()[:1] == ["200"]:
                    recovery = f"; recovered_after_network_loss={time.monotonic()-started:.1f}s"
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(2)
        if result.returncode == 0 and result.stdout.split()[:1] == ["200"] and IDLE_SECONDS:
            time.sleep(IDLE_SECONDS)
            result = probe()
        fields = result.stdout.split()
        if result.returncode == 0 and fields and fields[0] == "200":
            speed = float(fields[1]) * 8 / 1_000_000 if len(fields) > 1 else 0
            return True, f"200; {speed:.1f} Mbit/s{recovery}"
        if XRAY_BINARY and native_log is not None:
            native_log.flush()
            native_log.seek(0)
            raw_logs = native_log.read()
        else:
            logs = subprocess.run(
                ["docker", "logs", "--tail", "20", name],
                text=True,
                capture_output=True,
                timeout=10,
            )
            raw_logs = logs.stderr or logs.stdout
        message = (raw_logs or result.stderr).strip().splitlines()
        diagnostic = [
            line
            for line in message
            if any(
                marker in line.lower()
                for marker in ("error", "failed", "timeout", "reality", "handshake")
            )
        ]
        selected = diagnostic[-5:] if diagnostic else message[-5:]
        detail = sanitize(" | ".join(selected))[:900] if selected else "no client log"
        status = fields[0] if fields else "000"
        return False, f"{status}; {detail}"
    finally:
        if XRAY_BINARY:
            if native_process is not None:
                native_process.terminate()
                try:
                    native_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    native_process.kill()
                    native_process.wait(timeout=5)
            if native_log is not None:
                native_log.close()
        else:
            subprocess.run(
                ["docker", "rm", "--force", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
            )
            if network_created:
                subprocess.run(["docker", "network", "rm", network_name],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=20)


def main() -> int:
    if HAPP_JSON:
        profiles = fetch_happ_configs()
    else:
        return run_link_tests()
    results = []
    with tempfile.TemporaryDirectory(prefix="e2e-", dir=WORK_DIRECTORY) as directory:
        for index, (label, config) in enumerate(profiles):
            port = SOCKS_BASE_PORT + index
            config["inbounds"] = [{"listen": "0.0.0.0" if OUTAGE_SECONDS else "127.0.0.1",
                                   "port": port, "protocol": "socks",
                                   "settings": {"udp": True}}]
            path = Path(directory) / f"client-{index}.json"
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            print(f"{label}: checking", flush=True)
            try:
                ok, status = run_test(path, port)
            except subprocess.TimeoutExpired as error:
                operation = " ".join(str(part) for part in error.cmd[:2])
                ok, status = False, f"probe infrastructure timeout: {operation} ({error.timeout}s)"
            except Exception as error:
                ok, status = False, f"probe error: {type(error).__name__}"
            results.append(ok)
            print(f"{label}: {'PASS' if ok else 'FAIL'} ({status})", flush=True)
    print(f"transport_tests={sum(results)}/{len(results)}")
    return 0 if len(results) == 3 and all(results) else 1


def run_link_tests() -> int:
    links = fetch_links()
    if LABEL_FILTER:
        links = [
            link
            for link in links
            if LABEL_FILTER.casefold()
            in urllib.parse.unquote(urllib.parse.urlparse(link).fragment).casefold()
        ]
    if MAX_LINKS > 0:
        links = links[:MAX_LINKS]
    results: list[bool] = []
    with tempfile.TemporaryDirectory(prefix="e2e-", dir=WORK_DIRECTORY) as directory:
        os.chmod(directory, 0o700)
        for index, link in enumerate(links):
            socks_port = SOCKS_BASE_PORT + index
            label, config = make_config(link, socks_port)
            if OUTAGE_SECONDS:
                config["inbounds"][0]["listen"] = "0.0.0.0"
            path = Path(directory) / f"client-{index}.json"
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            ok, status = run_test(path, socks_port)
            results.append(ok)
            print(f"{label}: {'PASS' if ok else 'FAIL'} ({status})")
    print(f"transport_tests={sum(results)}/{len(results)}")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    def interrupted(signum: int, frame: Any) -> None:
        raise InterruptedError("transport check interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"transport_tests=error type={type(error).__name__}", flush=True)
        raise SystemExit(1)
