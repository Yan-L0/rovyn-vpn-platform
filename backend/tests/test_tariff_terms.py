import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text

from vpn_platform.api.device_accounts import locked_subscription
from vpn_platform.db.models import Order, Plan, Subscription, SubscriptionStatus
from vpn_platform.services.orders import OrderService


def test_catalog_migration_does_not_treat_json_colons_as_bind_parameters(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0007_tariffs_20261022.py"
    spec = importlib.util.spec_from_file_location("tariff_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.upgrade()
    assert len(statements) == 3
    for statement in statements:
        assert not text(statement).compile().params


def test_checkout_snapshots_policy_without_retroactive_catalog_changes():
    plan = Plan(
        id=uuid4(),
        code="MONTH",
        name="Month",
        duration_days=30,
        traffic_limit_bytes=25 * 1024**3,
        device_limit=5,
        price_minor=11100,
        currency="RUB",
        server_groups=[],
        access_policy={"mbps": 70},
    )
    snapshot = OrderService._snapshot(plan)
    plan.access_policy["mbps"] = 200
    plan.traffic_limit_bytes = 0
    service = OrderService(personal_devices=True)
    sub = service._new_subscription(
        Order(user_id=uuid4(), plan_id=plan.id, plan_snapshot=snapshot), datetime.now(UTC)
    )
    assert sub.access_policy == {"mbps": 70}
    assert sub.traffic_limit_bytes == 25 * 1024**3
    assert sub.isolated_devices
    assert sub.expires_at - sub.starts_at == timedelta(days=30)


@pytest.mark.asyncio
async def test_finite_quota_subscription_can_manage_individual_devices():
    sub = Subscription(
        id=uuid4(),
        status=SubscriptionStatus.ACTIVE,
        expires_at=datetime.now(UTC) + timedelta(days=30),
        traffic_limit_bytes=25 * 1024**3,
        access_policy={"mbps": 70},
        isolated_devices=True,
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=sub))
    assert await locked_subscription(db, uuid4()) is sub
