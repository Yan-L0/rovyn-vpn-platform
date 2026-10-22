#!/usr/bin/env python3
"""Panel-side policy publisher. No client secrets leave either database.

Run as root with a dedicated SSH key whose authorized command on the node is
receive_tariff_policy.py. Last valid node policy survives publisher outages.
"""
import json
import subprocess
import time
import os
import tempfile
import hashlib


def query(container: str, user: str, database: str, sql: str) -> list:
    result = subprocess.run(
        ["docker", "exec", container, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", user,
         "-d", database, "-Atc", sql], capture_output=True, timeout=20, check=True,
    )
    return json.loads(result.stdout)


def document(subscriptions: list, remote_users: list) -> dict:
    index = {str(row["uuid"]): str(row["t_id"]) for row in remote_users}
    assigned = set()
    groups = []
    owned = {value for sub in subscriptions for value in sub["providers"]}
    for sub in subscriptions:
        policy = sub["policy"] or {}
        if not policy:
            continue  # Previously purchased terms are grandfathered.
        emails = [index[value] for value in sub["providers"] if value in index]
        if assigned.intersection(emails):
            raise ValueError("credential belongs to multiple policies")
        assigned.update(emails)
        groups.append({"id": sub["id"] + ":" + policy.get("epoch", "initial"),
                       "emails": emails, "mbps": int(policy.get("mbps", 0)),
                       "quota": int(sub["quota"]), "fup": bool(policy.get("fup", False))})
    for row in remote_users:
        if row["username"].startswith(("dev_", "vpn_")) and str(row["uuid"]) not in owned:
            continue  # Remote create succeeded but the application transaction is pending.
        email = index[str(row["uuid"])]
        if email not in assigned:
            groups.append({"id": "legacy:" + email, "emails": [email], "mbps": 0,
                           "quota": 0, "fup": False})
    return {"version": 1, "groups": groups}


def publish() -> None:
    subs = query("vpn-platform-postgres-1", "vpn", "vpn", """
      SELECT COALESCE(json_agg(x), '[]'::json) FROM (
        SELECT s.id::text, s.access_policy AS policy, s.traffic_limit_bytes AS quota,
          ARRAY(SELECT provider_user_id FROM vpn_accounts WHERE subscription_id=s.id
            UNION SELECT provider_user_id FROM vpn_devices
              WHERE subscription_id=s.id AND provider_user_id IS NOT NULL) AS providers
        FROM subscriptions s) x
    """)
    users = query("remnawave-db", "postgres", "postgres", """
      SELECT COALESCE(json_agg(x), '[]'::json) FROM (SELECT uuid, t_id, username FROM users) x
    """)
    doc = document(subs, users)
    payload = json.dumps(doc, separators=(",", ":")).encode()
    result = subprocess.run([
        "ssh", "-T", "-i", "/opt/rovyn-tariffs/publisher_key", "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=yes", "-o",
        "UserKnownHostsFile=/opt/rovyn-tariffs/node_known_hosts", "root@89.34.219.170",
    ], input=payload, capture_output=True, timeout=15, check=True)
    applied = json.loads(result.stdout)
    if applied.get("digest") != hashlib.sha256(payload).hexdigest() or not 0 <= time.time() - applied["checked_at"] <= 5:
        raise RuntimeError("core policy acknowledgement is invalid")
    mapping = {email: group["id"] for group in doc["groups"] for email in group["emails"]}
    ack = {"sent_at": time.time(), "usage":applied.get("usage",{}), "providers": {
        str(row["uuid"]): mapping[str(row["t_id"])] for row in users if str(row["t_id"]) in mapping
    }}
    with tempfile.NamedTemporaryFile(dir="/opt/rovyn-tariffs/ack", mode="w", delete=False) as stream:
        json.dump(ack, stream)
        os.fchmod(stream.fileno(), 0o644)
        temporary = stream.name
    os.replace(temporary, "/opt/rovyn-tariffs/ack/policy.json")


if __name__ == "__main__":
    while True:
        try:
            publish()
        except Exception as error:
            # Do not print SQL result, user identifiers, or SSH credentials.
            print(f"Tariff policy synchronization failed: {type(error).__name__}", flush=True)
        time.sleep(5)
