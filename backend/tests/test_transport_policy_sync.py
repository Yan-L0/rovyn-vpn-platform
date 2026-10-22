import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from vpn_platform.api import account_v2
from vpn_platform.db.models import SubscriptionStatus
from vpn_platform.services import transport_policy


@pytest.mark.asyncio
async def test_link_waits_for_correct_subscription_epoch(tmp_path, monkeypatch):
    sub = SimpleNamespace(id=uuid4(), access_policy={"mbps": 70, "epoch": "new"})
    path = tmp_path / "ack.json"
    path.write_text(
        json.dumps({"sent_at": time.time() - 5, "providers": {"device": f"{sub.id}:new"}})
    )
    await transport_policy.wait_for_policy(str(path), sub, "device")
    path.write_text(
        json.dumps({"sent_at": time.time() - 5, "providers": {"device": f"{sub.id}:old"}})
    )
    clock = iter([0, 0, 16])
    monkeypatch.setattr(
        transport_policy, "time", SimpleNamespace(monotonic=lambda: next(clock), time=time.time)
    )
    monkeypatch.setattr(transport_policy.asyncio, "sleep", AsyncMock())
    with pytest.raises(HTTPException) as error:
        await transport_policy.wait_for_policy(str(path), sub, "device")
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_quota_usage_must_be_fresh_and_owned(tmp_path):
    sub = SimpleNamespace(id=uuid4(), access_policy={"mbps": 70})
    path = tmp_path / "ack.json"
    path.write_text(json.dumps({"sent_at": time.time(), "usage": {f"{sub.id}:initial": 123}}))
    assert await transport_policy.policy_usage(str(path), sub) == 123
    path.write_text(json.dumps({"sent_at": time.time() - 30, "usage": {f"{sub.id}:initial": 123}}))
    assert await transport_policy.policy_usage(str(path), sub) is None
    path.write_text(json.dumps({"sent_at": time.time(), "usage": {"other:initial": 0}}))
    assert await transport_policy.policy_usage(str(path), sub) is None


@pytest.mark.asyncio
async def test_cabinet_shows_authoritative_exhaustion_without_zero_fallback(monkeypatch):
    now = datetime.now(UTC)
    sub = SimpleNamespace(
        id=uuid4(),
        isolated_devices=True,
        access_policy={"mbps": 70},
        status=SubscriptionStatus.ACTIVE,
        starts_at=now,
        expires_at=now + timedelta(days=30),
        device_limit=5,
        traffic_limit_bytes=25 * 1024**3,
    )
    provider = SimpleNamespace(get_usage=AsyncMock(side_effect=RuntimeError("not sampled")))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(vpn_provider=provider)))
    row = (sub, SimpleNamespace(name="Month"), SimpleNamespace(provider_user_id="owned"))
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(first=lambda: row)))
    monkeypatch.setattr(account_v2, "policy_usage", AsyncMock(return_value=sub.traffic_limit_bytes))
    result = await account_v2.subscription_access(
        request, Response(), db, SimpleNamespace(user=SimpleNamespace(id=uuid4()))
    )
    assert result.usage.used_bytes == result.usage.traffic_limit_bytes
    provider.get_usage.assert_not_called()
