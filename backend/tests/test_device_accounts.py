from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from vpn_platform.api import device_accounts as api
from vpn_platform.db.models import Subscription, SubscriptionStatus, VpnDevice
from vpn_platform.domain.vpn_provider import ProviderError
from vpn_platform.providers.remnawave import RemnawaveProvider


def fixture(monkeypatch):
    sub = Subscription(
        id=uuid4(),
        user_id=uuid4(),
        isolated_devices=True,
        status=SubscriptionStatus.ACTIVE,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        traffic_limit_bytes=0,
        device_limit=2,
        server_groups=[],
    )
    monkeypatch.setattr(api, "locked_subscription", AsyncMock(return_value=sub))
    provider = SimpleNamespace(
        disable_user=AsyncMock(),
        drop_connections=AsyncMock(),
        create_user=AsyncMock(),
        get_subscription_info=AsyncMock(),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                vpn_provider=provider,
                settings=SimpleNamespace(
                    REMNAWAVE_DEVICE_SESSION_REVOCATION_ENABLED=True,
                    REMNAWAVE_DEVICE_EXTERNAL_SQUAD_UUID="policy",
                    default_squad_uuids=(),
                ),
            )
        )
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=None),
        scalar=AsyncMock(return_value=None),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    auth = SimpleNamespace(user=SimpleNamespace(id=sub.user_id))
    return sub, provider, request, db, auth


@pytest.mark.asyncio
async def test_revoked_key_cannot_be_recreated(monkeypatch):
    sub, provider, request, db, auth = fixture(monkeypatch)
    device = VpnDevice(id=uuid4(), subscription_id=sub.id, name="Phone", status="revoked")
    db.get.return_value = device
    with pytest.raises(HTTPException) as result:
        await api.create_device(
            api.CreateDeviceRequest(request_id=device.id, name="Phone"),
            request,
            Response(),
            db,
            auth,
        )
    assert result.value.status_code == 410
    provider.create_user.assert_not_called()


@pytest.mark.asyncio
async def test_foreign_device_cannot_be_removed(monkeypatch):
    _, provider, request, db, auth = fixture(monkeypatch)
    device = VpnDevice(id=uuid4(), subscription_id=uuid4(), name="Other", status="active")
    db.get.return_value = device
    with pytest.raises(HTTPException) as result:
        await api.revoke(device.id, request, db, auth)
    assert result.value.status_code == 404
    provider.disable_user.assert_not_called()


@pytest.mark.asyncio
async def test_pending_reservations_count_towards_limit(monkeypatch):
    _, provider, request, db, auth = fixture(monkeypatch)
    monkeypatch.setattr(
        api,
        "device_rows",
        AsyncMock(return_value=[VpnDevice(status="pending"), VpnDevice(status="revoking")]),
    )
    with pytest.raises(HTTPException) as result:
        await api.create_device(
            api.CreateDeviceRequest(request_id=uuid4(), name="Extra"), request, Response(), db, auth
        )
    assert result.value.status_code == 409
    provider.create_user.assert_not_called()


@pytest.mark.asyncio
async def test_failed_revoke_preserves_terminal_intent(monkeypatch):
    sub, provider, request, db, auth = fixture(monkeypatch)
    device = VpnDevice(
        id=uuid4(), subscription_id=sub.id, name="Phone", status="active", provider_user_id="owned"
    )
    db.get.return_value = device
    provider.disable_user.side_effect = ProviderError("unreachable")
    with pytest.raises(HTTPException) as result:
        await api.revoke(device.id, request, db, auth)
    assert result.value.status_code == 502
    assert device.status == "revoking"
    db.commit.assert_awaited_once()
    provider.disable_user.assert_awaited_once_with("owned")


@pytest.mark.asyncio
async def test_disabled_gate_prevents_migration(monkeypatch):
    sub, _, request, db, auth = fixture(monkeypatch)
    sub.isolated_devices = False
    request.app.state.settings.REMNAWAVE_DEVICE_SESSION_REVOCATION_ENABLED = False
    with pytest.raises(HTTPException) as result:
        await api.migrate(request, db, auth)
    assert result.value.status_code == 503
    assert not sub.isolated_devices
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_revocation_never_calls_ip_drop(monkeypatch):
    provider = RemnawaveProvider("http://localhost", "test-token")
    read_user = AsyncMock(return_value={"status": "DISABLED"})
    mutation = AsyncMock()
    monkeypatch.setattr(provider, "_get_user", read_user)
    monkeypatch.setattr(provider, "_request", mutation)
    try:
        await provider.drop_connections("device")
        mutation.assert_not_called()
        read_user.return_value = {"status": "ACTIVE"}
        with pytest.raises(ProviderError):
            await provider.drop_connections("device")
    finally:
        await provider.close()
