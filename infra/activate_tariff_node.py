#!/usr/bin/env python3
"""Install a verified core with rollback; retain the revocation bind mount."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def activate(binary: str, expected_digest: str) -> None:
    root = Path("/opt/remnanode")
    compose = root / "docker-compose.yml"
    active = root / "bin/xray-device-revoke"
    policy = root / "tariffs/policy.json"
    if hashlib.sha256(Path(binary).read_bytes()).hexdigest() != expected_digest:
        raise ValueError("core checksum mismatch")
    if not json.loads(policy.read_text())["groups"]:
        raise ValueError("published policy is missing")
    original = compose.read_text()
    environment = '      NODE_PORT: "2222"\n'
    volume = "      - /var/log/remnanode:/var/log/remnanode\n"
    if original.count(environment) != 1 or original.count(volume) != 1:
        raise ValueError("unexpected node compose layout")
    if "XRAY_ROVYN_TARIFF_POLICY" in original:
        if 'XRAY_ROVYN_TARIFF_POLICY: /etc/rovyn-tariffs/policy.json' not in original or '/opt/remnanode/tariffs:/etc/rovyn-tariffs' not in original:
            raise ValueError("unexpected existing tariff mounts")
        replacement = original
    else:
        replacement = original.replace(environment, environment +
            '      XRAY_ROVYN_TARIFF_POLICY: /etc/rovyn-tariffs/policy.json\n').replace(
            volume, volume + '      - /opt/remnanode/tariffs:/etc/rovyn-tariffs\n')
    backup = Path(tempfile.mkdtemp(prefix="tariffs-20261022-", dir=root / "backups"))
    shutil.copy2(active, backup / "xray")
    shutil.copy2(compose, backup / "docker-compose.yml")
    command = ["docker", "compose", "-f", str(compose), "up", "-d", "--no-deps", "--force-recreate", "remnanode"]
    print(f"Rollback assets: {backup}", flush=True)
    try:
        stage = active.with_suffix(".tariff-next")
        shutil.copyfile(binary, stage)
        stage.chmod(0o755)
        os.replace(stage, active)
        compose.write_text(replacement)
        subprocess.run(["docker", "compose", "-f", str(compose), "config", "--quiet"], check=True, timeout=20)
        subprocess.run(command, check=True, timeout=120)
        deadline = time.monotonic() + 60
        while True:
            running = subprocess.run(["docker", "exec", "remnanode", "sh", "-c", "pidof xray >/dev/null"], timeout=10)
            if running.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("node did not start its core")
            time.sleep(2)
        actual = subprocess.check_output(["docker", "exec", "remnanode", "sha256sum", "/usr/local/bin/xray"], text=True)
        if actual.split()[0] != expected_digest:
            raise ValueError("container is not using the verified core")
        capabilities = subprocess.check_output(["docker", "inspect", "remnanode", "--format", "{{json .HostConfig.CapAdd}}"], text=True)
        if "NET_ADMIN" in capabilities:
            raise ValueError("credential revocation capability invariant violated")
    except BaseException:
        shutil.copyfile(backup / "docker-compose.yml", compose)
        stage = active.with_suffix(".rollback-next")
        shutil.copyfile(backup / "xray", stage)
        stage.chmod(0o755)
        os.replace(stage, active)
        subprocess.run(command, check=True, timeout=120)
        raise
    print("Tariff core started; external traffic acceptance is still required", flush=True)


if __name__ == "__main__":
    activate(*sys.argv[1:])
