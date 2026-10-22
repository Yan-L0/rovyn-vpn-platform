#!/usr/bin/env python3
"""Restricted SSH command: accepts only a bounded valid policy document."""
import json
import os
import sys
import tempfile
import hashlib
import time
from pathlib import Path

DIRECTORY = "/opt/remnanode/tariffs"
TARGET = DIRECTORY + "/policy.json"


def receive() -> None:
    data = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("policy too large")
    doc = json.loads(data)
    if doc.get("version") != 1 or not isinstance(doc.get("groups"), list):
        raise ValueError("invalid policy")
    seen = set()
    ids = set()
    for group in doc["groups"]:
        if not isinstance(group["id"], str) or not group["id"] or group["id"] in ids:
            raise ValueError("invalid group")
        ids.add(group["id"])
        for key in ("mbps", "quota"):
            if type(group[key]) is not int or group[key] < 0:
                raise ValueError("invalid limit")
        if type(group["fup"]) is not bool:
            raise ValueError("invalid fair use policy")
        for email in group["emails"]:
            if not isinstance(email, str) or not email.isdecimal() or email in seen:
                raise ValueError("invalid credential identity")
            seen.add(email)
    with tempfile.NamedTemporaryFile(dir=DIRECTORY, prefix=".policy-", delete=False) as stream:
        path = stream.name
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(path, TARGET)
        finally:
            if os.path.exists(path):
                os.unlink(path)
    digest = hashlib.sha256(data).hexdigest()
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        try:
            ack = json.loads(Path(TARGET + ".applied").read_text())
            if ack["digest"] == digest and ack["healthy"] is True and 0 <= time.time() - ack["checked_at"] <= 5:
                print(json.dumps({"digest": digest, "checked_at": ack["checked_at"], "usage":ack.get("usage",{})}))
                return
        except (OSError, ValueError, KeyError, TypeError):
            pass
        time.sleep(0.1)
    raise RuntimeError("core has not applied the policy")


if __name__ == "__main__":
    try:
        receive()
    except Exception:
        sys.exit("Invalid tariff policy")
