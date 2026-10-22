#!/usr/bin/env python3
"""Prepare the restricted publisher and durable policy directory on the node.

Usage: prepare_tariff_node.py publisher.pub receive_tariff_policy.py
This step does not restart the node or activate the limiter.
"""
import os
from pathlib import Path
import shutil
import sys


def prepare(public_key: str, receiver: str) -> None:
    key = Path(public_key).read_text().strip()
    if not key.startswith("ssh-ed25519 ") or len(key.split()) != 3:
        raise ValueError("invalid publisher key")
    destination = Path("/opt/remnanode/tariffs")
    destination.mkdir(mode=0o700, exist_ok=True)
    state = destination / "policy.json.state"
    if not state.exists():
        compose = Path("/opt/remnanode/docker-compose.yml")
        if (destination / "policy.json").exists() or (compose.exists() and "XRAY_ROVYN_TARIFF_POLICY" in compose.read_text()):
            raise RuntimeError("Existing tariff state is missing; restore its backup instead of resetting quotas")
        with state.open("x") as stream:
            stream.write("{}")
        state.chmod(0o600)
    receiver_path = Path("/usr/local/sbin/rovyn-receive-tariff-policy")
    shutil.copyfile(receiver, receiver_path)
    receiver_path.chmod(0o700)
    authorized = Path("/root/.ssh/authorized_keys")
    line = ("from=\"31.76.24.171\",restrict,command=\"/usr/bin/python3 "
            "/usr/local/sbin/rovyn-receive-tariff-policy\" " + key)
    current = authorized.read_text()
    if key.split()[1] not in current:
        with authorized.open("a") as stream:
            stream.write("\n" + line + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    authorized.chmod(0o600)
    print("Restricted policy receiver prepared")


if __name__ == "__main__":
    prepare(*sys.argv[1:])
