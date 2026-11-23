from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from vpn_platform.db.models import Subscription
from vpn_platform.services.device_accounts import device_rows


async def policy_ready(path: str) -> bool:
    try:
        ack = json.loads(await asyncio.to_thread(Path(path).read_text))
        return isinstance(ack.get("providers"), dict) and 0 <= time.time() - ack["sent_at"] <= 15
    except (OSError, ValueError, KeyError, TypeError):
        return False


async def policy_usage(
    path: str, subscription: Subscription, *, device_db: AsyncSession | None = None
) -> int | None:
    if not path or not subscription.access_policy:
        return None
    try:
        ack = json.loads(await asyncio.to_thread(Path(path).read_text))
        group = f"{subscription.id}:{subscription.access_policy.get('epoch', 'initial')}"
        value = ack.get("usage", {}).get(group)
        sent_at = ack["sent_at"]
        if not 0 <= time.time() - sent_at <= 15 or type(value) is not int or value < 0:
            return None
        if device_db is not None:
            providers = ack["providers"]
            if not isinstance(providers, dict):
                return None
            # The publisher accepts a node sample up to five seconds before sent_at.
            earliest_sample = sent_at - 5
            for device in await device_rows(device_db, subscription):
                changed = device.revoked_at or device.created_at
                if changed.timestamp() > earliest_sample or device.status == "revoking":
                    return None
                if device.status == "active" and providers.get(device.provider_user_id) != group:
                    return None
        return value
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
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
