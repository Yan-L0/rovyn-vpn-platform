from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from vpn_platform.api import admin
from vpn_platform.db.models import Plan, Subscription, SubscriptionStatus, User, VpnAccount
from vpn_platform.domain.vpn_provider import AccountStatus, ProviderError, ProviderUser


@pytest.mark.asyncio
async def test_grant_reports_sync_failure_and_rolls_back(monkeypatch):
    user = User(id=uuid4(), display_name="Test")
    plan = Plan(
        id=uuid4(), duration_days=30, traffic_limit_bytes=0, device_limit=5, server_groups=[]
    )
    sub = Subscription(
        id=uuid4(),
        user_id=user.id,
        isolated_devices=True,
        starts_at=datetime.now(UTC) - timedelta(days=1),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        status=SubscriptionStatus.ACTIVE,
    )
    account = VpnAccount(provider_user_id="current", provider_username="test")
    db = SimpleNamespace(
        execute=AsyncMock(),
        scalar=AsyncMock(side_effect=[plan, SimpleNamespace(user_id=user.id), sub, account]),
        get=AsyncMock(return_value=user),
        flush=AsyncMock(),
        rollback=AsyncMock(),
        commit=AsyncMock(),
        add=Mock(),
    )
    remote = ProviderUser("current", "test", AccountStatus.ACTIVE, sub.expires_at, None, {})
    provider = SimpleNamespace(update_user=AsyncMock(return_value=remote))
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                vpn_provider=provider, settings=SimpleNamespace(default_squad_uuids=())
            )
        )
    )
    monkeypatch.setattr(
        admin, "sync_device_access", AsyncMock(side_effect=ProviderError("offline"))
    )
    with pytest.raises(HTTPException) as result:
        await admin.grant_access(
            admin.AdminGrantRequest(telegram_id=123, plan_id=plan.id),
            request,
            db,
            SimpleNamespace(user=user),
        )
    assert result.value.status_code == 502
    db.rollback.assert_awaited_once()
    db.commit.assert_not_called()
