import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import JSON, DateTime, MetaData, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite import DATETIME
from sqlalchemy.orm import Session

from vpn_platform.api import account_v2, device_accounts
from vpn_platform.api.dependencies import get_current_user, get_db, require_csrf
from vpn_platform.db.base import Base
from vpn_platform.db.models import Plan, Subscription, SubscriptionStatus, VpnAccount, VpnDevice
from vpn_platform.domain.vpn_provider import ProviderError, Usage
from vpn_platform.services import transport_policy


class UTCDateTime(DATETIME):
    """SQLite returns naive values for the UTC timestamptz columns used by these routes."""

    def result_processor(self, dialect, coltype):
        return lambda value: datetime.fromisoformat(value).replace(tzinfo=UTC) if value else None


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    engine.dialect.colspecs = {**engine.dialect.colspecs, DateTime: UTCDateTime}
    schema = MetaData()
    for table in Base.metadata.tables.values():
        copy = table.to_metadata(schema)
        for column in copy.c:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    models = [Plan, Subscription, VpnAccount, VpnDevice]
    schema.create_all(engine, tables=[schema.tables[m.__tablename__] for m in models])
    with Session(engine, expire_on_commit=False) as db:
        yield db
    engine.dispose()


@pytest.mark.asyncio
async def test_two_device_cycle_through_access_and_public_meter(session, tmp_path, monkeypatch):
    now = datetime.now(UTC)
    gib = 2**30
    plan = Plan(
        id=uuid4(),
        code="MONTH",
        name="Month",
        duration_days=30,
        traffic_limit_bytes=10 * gib,
        device_limit=2,
        price_minor=100,
    )
    sub = Subscription(
        id=uuid4(),
        user_id=uuid4(),
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE,
        starts_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
        traffic_limit_bytes=plan.traffic_limit_bytes,
        device_limit=2,
        isolated_devices=True,
        access_policy={"epoch": "current", "usage_baseline": {"parent": 8 * gib, "phone": gib}},
        public_token_digest=b"x" * 32,
    )
    parent = VpnAccount(
        subscription_id=sub.id,
        provider="test",
        provider_user_id="parent",
        provider_username="legacy",
    )
    first = VpnDevice(
        id=uuid4(),
        subscription_id=sub.id,
        name="Phone",
        status="active",
        provider_user_id="phone",
        created_at=now - timedelta(hours=1),
    )
    second_id = uuid4()
    session.add_all([plan, sub, parent, first])
    session.commit()
    path = tmp_path / "ack.json"
    clock = now.timestamp()
    monkeypatch.setattr(
        transport_policy,
        "time",
        SimpleNamespace(
            time=lambda: clock,
            monotonic=time.monotonic,
        ),
    )

    def publish(used, members, *, sent_at=None):
        group = f"{sub.id}:current"
        path.write_text(
            json.dumps(
                {
                    "sent_at": clock if sent_at is None else sent_at,
                    "usage": {group: used},
                    "providers": dict.fromkeys(["parent", *members], group),
                }
            )
        )

    # Prior-period baselines are per credential. Disabled devices retain their counters.
    counters = {"parent": 9 * gib, "phone": 3 * gib, "tablet": 0}
    base_url = "https://profile.example"
    urls = {name: f"{base_url}/{name}-key" for name in ("phone", "tablet")}
    provider = SimpleNamespace(
        get_usage=AsyncMock(side_effect=lambda key: Usage(counters[key], 0)),
        get_subscription_info=AsyncMock(
            side_effect=lambda key: SimpleNamespace(
                provider_id=key,
                subscription_url=urls[key],
            )
        ),
        create_user=AsyncMock(
            return_value=SimpleNamespace(
                provider_id="tablet",
                subscription_url=urls["tablet"],
            )
        ),
        disable_user=AsyncMock(),
        drop_connections=AsyncMock(),
    )
    database = SimpleNamespace(
        add=session.add,
        **{
            name: AsyncMock(side_effect=getattr(session, name))
            for name in ("execute", "scalar", "scalars", "get", "commit", "refresh")
        },
    )
    app = FastAPI()
    app.include_router(account_v2.router)
    app.include_router(device_accounts.router)
    app.state.vpn_provider = provider
    app.state.settings = SimpleNamespace(
        TARIFF_POLICY_ACK_PATH=str(path),
        REMNAWAVE_DEVICE_SESSION_REVOCATION_ENABLED=True,
        REMNAWAVE_DEVICE_EXTERNAL_SQUAD_UUID="test",
        default_squad_uuids=(),
    )
    auth = SimpleNamespace(user=SimpleNamespace(id=sub.user_id))
    app.dependency_overrides[get_db] = lambda: database
    app.dependency_overrides[get_current_user] = app.dependency_overrides[require_csrf] = lambda: (
        auth
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.example/api/v2/"
    ) as client:

        async def meter(device_id, key):
            return await client.post(
                "subscription/device-usage",
                json={
                    "device_id": device_id.hex,
                    "link_key": key,
                },
            )

        async def check(used, links):
            access = await client.get("subscription/access")
            assert access.status_code == 200 and access.json()["status"] == "active"
            usage = {"used_bytes": used, "traffic_limit_bytes": 10 * gib}
            assert {k: access.json()["usage"][k] for k in usage} == usage
            for device_id, key in links:
                response = await meter(device_id, key)
                assert response.status_code == 200 and response.json() == usage
                assert response.headers["access-control-allow-origin"] == base_url
                assert "no-store" in response.headers["cache-control"]

        phone = (first.id, "phone-key")
        tablet = (second_id, "tablet-key")
        publish(3 * gib, ["phone"])
        await check(3 * gib, [phone])
        provider.get_usage.assert_not_awaited()

        # Current policy is available when the device creation route releases the new link.
        publish(3 * gib, ["phone", "tablet"])
        created = await client.post(
            "device-accounts", json={"name": "Tablet", "request_id": str(second_id)}
        )
        assert created.status_code == 200 and created.json()["subscription_url"] == urls["tablet"]
        assert provider.create_user.await_args.args[0].traffic_limit_bytes == 0
        await check(3 * gib, [phone, tablet])
        counters["tablet"] = 2 * gib
        clock += 7
        # Both ACKs are inside the TTL. One predates creation, one omits the new provider.
        publish(3 * gib, ["phone", "tablet"], sent_at=now.timestamp() - 1)
        await check(5 * gib, [phone, tablet])
        publish(3 * gib, ["phone"])
        await check(5 * gib, [phone, tablet])
        assert (await meter(second_id, "phone-key")).status_code == 404

        publish(5 * gib + 10, ["phone", "tablet"])
        provider.get_usage.reset_mock()
        await check(5 * gib + 10, [phone, tablet])
        provider.get_usage.assert_not_awaited()
        before_revoke = time.time()
        assert (await client.delete(f"device-accounts/{first.id}")).status_code == 204
        provider.disable_user.assert_awaited_with("phone")
        provider.drop_connections.assert_awaited_with("phone")
        assert (await meter(*phone)).status_code == 404
        assert (await client.post(f"device-accounts/{first.id}/link")).status_code == 410
        retained = await client.post(f"device-accounts/{second_id}/link")
        assert retained.status_code == 200 and retained.json()["subscription_url"] == urls["tablet"]

        counters["tablet"] += gib
        publish(5 * gib, ["phone", "tablet"], sent_at=before_revoke)
        await check(6 * gib, [tablet])
        publish(6 * gib + 10, ["phone", "tablet"])
        provider.get_usage.reset_mock()
        await check(6 * gib + 10, [tablet])
        provider.get_usage.assert_not_awaited()

        # A broken snapshot and a missing counter must never report a partial sum or zero.
        path.write_text("[]")
        provider.get_usage.side_effect = ProviderError("unsampled")
        await check(None, [tablet])
        publish(6 * gib, ["phone", "tablet"])
        await check(6 * gib, [tablet])
