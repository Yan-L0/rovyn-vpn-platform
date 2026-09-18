#!/usr/bin/env python3
"""Probe actual subscription UDP paths with a disposable account; no secrets logged."""
import json
import os
import secrets
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from manage_transport_test_user import APP_ENV, SQUAD_UUID, api, read_env


def receive(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise OSError("SOCKS connection closed")
        data += chunk
    return data


def stun(port, host, destination_port):
    """An RFC 5389 Binding response proves bidirectional UDP through the proxy."""
    with socket.create_connection(("127.0.0.1", port), timeout=8) as control:
        control.sendall(b"\x05\x01\x00")
        if receive(control, 2) != b"\x05\x00":
            raise OSError("SOCKS greeting rejected")
        control.sendall(b"\x05\x03\x00\x01" + b"\x00" * 6)
        reply = receive(control, 4)
        if reply != b"\x05\x00\x00\x01":
            raise OSError("SOCKS UDP association rejected")
        address = socket.inet_ntoa(receive(control, 4))
        relay_port = struct.unpack("!H", receive(control, 2))[0]
        if address == "0.0.0.0":
            address = "127.0.0.1"
        transaction = secrets.token_bytes(12)
        request = struct.pack("!HHI", 1, 0, 0x2112A442) + transaction
        target = host.encode()
        packet = b"\x00\x00\x00\x03" + bytes([len(target)]) + target
        packet += struct.pack("!H", destination_port) + request
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.settimeout(5)
            for _ in range(2):
                udp.sendto(packet, (address, relay_port))
                try:
                    response = udp.recv(4096)
                except socket.timeout:
                    continue
                if response[3] == 1:
                    payload = response[10:]
                elif response[3] == 4:
                    payload = response[22:]
                elif response[3] == 3:
                    payload = response[7 + response[4]:]
                else:
                    continue
                if len(payload) >= 20 and payload[:2] == b"\x01\x01" and payload[8:20] == transaction:
                    return True
        return False


def main():
    token = read_env(APP_ENV)["REMNAWAVE_API_TOKEN"]
    user = api(token, "POST", "/api/users", {
        "username": "udpcheck_" + secrets.token_hex(6),
        "expireAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "trafficLimitBytes": 1024**3, "trafficLimitStrategy": "NO_RESET",
        "hwidDeviceLimit": 2, "activeInternalSquads": [SQUAD_UUID],
        "description": "temporary bidirectional UDP acceptance test",
    })
    try:
        req = urllib.request.Request(user["subscriptionUrl"], headers={"User-Agent": "Happ/5.8.0/ios"})
        with urllib.request.urlopen(req, timeout=30) as response:
            configs = json.load(response)
        results = []
        with tempfile.TemporaryDirectory(prefix="rovyn-udp-") as directory:
            for index, config in enumerate(configs):
                proxy = next(o for o in config["outbounds"] if o.get("tag") == "proxy")
                network = proxy["streamSettings"]["network"]
                flow = proxy.get("settings", {}).get("vnext", [{}])[0].get("users", [{}])[0].get("flow", "")
                print(json.dumps({"network": network, "flow": flow,
                    "routing_rules": len(config.get("routing", {}).get("rules", [])),
                    "outbound_tags": [o.get("tag") for o in config["outbounds"]]}), flush=True)
                force_down = os.environ.get("E2E_FORCE_PRIMARY_DOWN") == "1"
                if force_down:
                    # Fault injection affects only this temporary client's outbound.
                    settings = proxy["settings"]
                    if "vnext" in settings:
                        settings["vnext"][0].update(address="127.0.0.1", port=9)
                    else:
                        settings.update(address="127.0.0.1", port=9)
                port = 11980 + index
                # Preserve production routing and outbounds; replace only local entrypoint.
                config["inbounds"] = [{"listen": "127.0.0.1", "port": port, "protocol": "socks", "settings": {"udp": True}}]
                config["log"] = {"loglevel": "warning"}
                path = Path(directory) / f"{index}.json"
                path.write_text(json.dumps(config))
                path.chmod(0o600)
                name = "rovyn-udp-" + secrets.token_hex(5)
                try:
                    subprocess.run(["docker", "run", "-d", "--name", name, "--network", "host", "--entrypoint", "/usr/local/bin/xray", "-v", f"{path}:/tmp/test.json:ro", "remnawave/node:2.7.0", "run", "-c", "/tmp/test.json"], check=True, capture_output=True, timeout=30)
                    time.sleep(2)
                    started = time.monotonic()
                    while True:
                        http = subprocess.run(["curl", "--silent", "--output", "/dev/null",
                            "--write-out", "%{http_code}", "--max-time", "8",
                            "--socks5-hostname", f"127.0.0.1:{port}",
                            "https://www.gstatic.com/generate_204"], capture_output=True, text=True, timeout=12)
                        ok = http.returncode == 0 and http.stdout == "204"
                        if ok or not force_down or time.monotonic() - started >= 50:
                            break
                        time.sleep(2)
                    results.append(ok)
                    print(f"{network} HTTPS={'PASS' if ok else 'FAIL'} primary_disabled={force_down} elapsed={time.monotonic()-started:.1f}s", flush=True)
                    for host, target in [("stun.cloudflare.com", 3478), ("stun.l.google.com", 19302)]:
                        ok = stun(port, host, target)
                        results.append(ok)
                        print(f"{network} STUN {host}:{target}={'PASS' if ok else 'FAIL'}", flush=True)
                finally:
                    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)
        print(f"udp_checks={sum(results)}/{len(results)}")
        return 0 if results and all(results) else 1
    finally:
        api(token, "DELETE", "/api/users/" + user["uuid"])
        print("temporary_user_deleted=true")


if __name__ == "__main__":
    raise SystemExit(main())
