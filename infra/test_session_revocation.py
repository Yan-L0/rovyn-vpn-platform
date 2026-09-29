#!/usr/bin/env python3
"""Loopback-only acceptance: two credentials, live TCP/UDP, cached reconnects.

Usage: python3 test_session_revocation.py /absolute/path/to/patched/xray
No production users, config, ports or credentials are touched.
"""
import json
import hashlib
import ssl
import secrets
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        while data := self.request.recv(4096):
            self.request.sendall(data)


class UDPEcho(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        sock.sendto(data, self.client_address)


def read(sock, n):
    result = b""
    while len(result) < n:
        chunk = sock.recv(n - len(result))
        if not chunk:
            raise OSError("connection closed")
        result += chunk
    return result


def socks(port, target, udp=False):
    sock = socket.create_connection(("127.0.0.1", port), timeout=2)
    try:
        sock.sendall(b"\x05\x01\x00")
        assert read(sock, 2) == b"\x05\x00"
        sock.sendall(bytes([5, 3 if udp else 1, 0, 1]) + socket.inet_aton("127.0.0.1") + struct.pack("!H", target))
        head = read(sock, 4)
        assert head[:3] == b"\x05\x00\x00"
        size = 4 if head[3] == 1 else 16 if head[3] == 4 else read(sock, 1)[0]
        addr = read(sock, size)
        remote_port = struct.unpack("!H", read(sock, 2))[0]
        return sock, ("127.0.0.1", remote_port)
    except BaseException:
        sock.close()
        raise


def tcp_passes(sock):
    payload = secrets.token_bytes(32)
    try:
        sock.sendall(payload)
        return read(sock, len(payload)) == payload
    except OSError:
        return False


def udp_passes(sock, relay, target):
    payload = secrets.token_bytes(32)
    header = b"\x00\x00\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack("!H", target)
    try:
        sock.sendto(header + payload, relay)
        response = sock.recv(4096)
        return response.endswith(payload)
    except OSError:
        return False


def main(binary):
    processes, live, udps, controls = [], [], [], []
    tcp = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo)
    tcp.daemon_threads = True
    udp = socketserver.ThreadingUDPServer(("127.0.0.1", 0), UDPEcho)
    udp.daemon_threads = True
    for server in (tcp, udp):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    tcp_target, udp_target = tcp.server_address[1], udp.server_address[1]
    names = ("raw", "xhttp", "hysteria")
    try:
        with tempfile.TemporaryDirectory(prefix="rovyn-session-") as directory:
            root = Path(directory)
            cert, key = root / "cert.pem", root / "key.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(cert)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ids = [str(uuid.uuid4()), str(uuid.uuid4())]
            cert_pin = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
            inbounds = [{"tag": "api", "listen": "127.0.0.1", "port": 19850, "protocol": "dokodemo-door", "settings": {"address": "127.0.0.1"}}]
            for index, network in enumerate(names):
                stream = {"network": network, "security": "none"}
                settings = {"decryption": "none", "clients": [{"id": value, "email": f"device-{i}"} for i, value in enumerate(ids)]}
                if network != "raw":
                    stream.update(security="tls", tlsSettings={"certificates": [{"certificateFile": str(cert), "keyFile": str(key)}], "alpn": ["h3" if network == "hysteria" else "h2"]})
                if network == "xhttp":
                    stream["xhttpSettings"] = {"path": "/session-test", "mode": "stream-up"}
                if network == "hysteria":
                    settings = {"version": 2, "clients": [{"auth": value, "email": f"device-{i}"} for i, value in enumerate(ids)]}
                    stream["hysteriaSettings"] = {"version": 2}
                inbounds.append({"tag": network, "listen": "127.0.0.1", "port": 19851 + index, "protocol": "hysteria" if network == "hysteria" else "vless", "settings": settings, "streamSettings": stream})
            server_config = {"log": {"loglevel": "warning"}, "api": {"tag": "api-out", "services": ["HandlerService"]}, "inbounds": inbounds, "outbounds": [{"protocol": "freedom"}], "routing": {"rules": [{"type": "field", "inboundTag": ["api"], "outboundTag": "api-out"}]}}

            def start(name, config):
                path = root / (name + ".json")
                path.write_text(json.dumps(config))
                path.chmod(0o600)
                log = (root / (name + ".log")).open("w")
                process = subprocess.Popen([binary, "run", "-c", str(path)], stdout=log, stderr=log)
                log.close()
                processes.append(process)
                process.test_log = root / (name + ".log")

            start("server", server_config)
            for owner in range(2):
                for index, network in enumerate(names):
                    stream = {"network": network, "security": "none"}
                    settings = {"vnext": [{"address": "127.0.0.1", "port": 19851 + index, "users": [{"id": ids[owner], "encryption": "none"}]}]}
                    if network != "raw":
                        stream.update(security="tls", tlsSettings={"serverName": "localhost", "pinnedPeerCertSha256": cert_pin, "alpn": ["h3" if network == "hysteria" else "h2"]})
                    if network == "xhttp":
                        stream["xhttpSettings"] = {"path": "/session-test", "mode": "stream-up"}
                    if network == "hysteria":
                        settings = {"version": 2, "address": "127.0.0.1", "port": 19851 + index}
                        stream["hysteriaSettings"] = {"version": 2, "auth": ids[owner]}
                    start(f"client-{owner}-{network}", {"log": {"loglevel": "warning"}, "inbounds": [{"listen": "127.0.0.1", "port": 19860 + owner * 3 + index, "protocol": "socks", "settings": {"udp": True}}], "outbounds": [{"protocol": "hysteria" if network == "hysteria" else "vless", "settings": settings, "streamSettings": stream}]})
            time.sleep(2)
            for process in processes:
                assert process.poll() is None, f"core startup failed: {process.test_log.read_text()}"
            for port in range(19860, 19866):
                conn, _ = socks(port, tcp_target)
                live.append(conn)
                assert tcp_passes(conn), f"TCP baseline failed for {port}"
                control, relay = socks(port, 0, udp=True)
                controls.append(control)
                datagram = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                datagram.settimeout(2)
                udps.append((datagram, relay))
                assert udp_passes(datagram, relay, udp_target), f"UDP baseline failed for {port}"
            print("baseline: six TCP and six UDP paths PASS", flush=True)
            for tag in names:
                subprocess.run([binary, "api", "rmu", "--server=127.0.0.1:19850", f"-tag={tag}", "device-0"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            time.sleep(1)
            checks = []
            for index in range(6):
                retained = index >= 3
                tcp_ok = tcp_passes(live[index])
                udp_ok = udp_passes(*udps[index], udp_target)
                try:
                    conn, _ = socks(19860 + index, tcp_target)
                    with conn:
                        fresh_ok = tcp_passes(conn)
                except (OSError, AssertionError):
                    fresh_ok = False
                print(f"device={index // 3} transport={names[index % 3]} live_TCP={tcp_ok} live_UDP={udp_ok} cached_reconnect={fresh_ok} expected={retained}", flush=True)
                checks.extend([tcp_ok == retained, udp_ok == retained, fresh_ok == retained])
            assert all(checks), "session isolation gate failed"
            print("session revocation + same-IP isolation PASS", flush=True)
    finally:
        for conn in live + controls:
            conn.close()
        for conn, _ in udps:
            conn.close()
        for process in processes:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        tcp.shutdown()
        udp.shutdown()
        tcp.server_close()
        udp.server_close()


if __name__ == "__main__":
    main(str(Path(sys.argv[1]).resolve()))
