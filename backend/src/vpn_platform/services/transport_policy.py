from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import HTTPException

from vpn_platform.db.models import Subscription


async def policy_ready(path: str) -> bool:
    try:
        ack = json.loads(await asyncio.to_thread(Path(path).read_text))
        return isinstance(ack.get("providers"), dict) and 0 <= time.time() - ack["sent_at"] <= 15
    except (OSError, ValueError, KeyError, TypeError):
        return False


async def policy_usage(path: str, subscription: Subscription) -> int | None:
    if not path or not subscription.access_policy:
        return None
    try:
        ack = json.loads(await asyncio.to_thread(Path(path).read_text))
        group = f"{subscription.id}:{subscription.access_policy.get('epoch', 'initial')}"
        value = ack.get("usage", {}).get(group)
        if 0 <= time.time() - ack["sent_at"] <= 15 and type(value) is int and value >= 0:
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


async def wait_for_policy(path: str, subscription: Subscription, provider_id: str) -> None:
    """Do not hand out a newly created link before the node has its terms."""
    if not path:
        return
    policy = subscription.access_policy or {}
    group = f"{subscription.id}:{policy.get('epoch', 'initial')}" if policy else None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            ack = json.loads(await asyncio.to_thread(Path(path).read_text))
            actual = ack["providers"].get(provider_id)
            if (actual == group if group else actual is not None) and 0 <= time.time() - ack[
                "sent_at"
            ] <= 15:
                return
        except (OSError, ValueError, KeyError, TypeError):
            pass
        await asyncio.sleep(0.25)
    raise HTTPException(503, "Device policy is being synchronized. Retry the same device.")
