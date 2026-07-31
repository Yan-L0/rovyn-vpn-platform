from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import Request, Response

from vpn_platform.api.account_v2 import (
    create_support_ticket,
    delete_device,
    referral_summary,
    router,
    subscription_access,
    yearly_traffic,
)
from vpn_platform.api.dependencies import AuthenticatedUser, require_csrf
from vpn_platform.api.schemas_v2 import CreateSupportTicketRequest
from vpn_platform.db.models import (
    Plan,
    Subscription,
    SubscriptionStatus,
    User,
    VpnAccount,
    VpnUsageDaily,
)
from vpn_platform.domain.vpn_provider import AccountStatus, ProviderUser, Usage, UsagePoint


class Result:
    def __init__(self, row: object | None):
        self.row = row

    def first(self) -> object | None:
        return self.row


class ScalarRows:
    def __init__(self, rows: list[object]):
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class FakeDatabase:
    def __init__(
        self,
        *,
        rows: list[object | None] | None = None,
        scalar_values: list[int] | None = None,
        scalar_rows: list[object] | None = None,
    ):
        self.rows = list(rows or [])
        self.scalar_values = list(scalar_values or [])
        self.scalar_rows = list(scalar_rows or [])
        self.added: list[object] = []

    async def execute(self, _statement: object) -> Result:
        return Result(self.rows.pop(0))

    async def scalar(self, _statement: object) -> int:
        return self.scalar_values.pop(0)

    async def scalars(self, _statement: object) -> ScalarRows:
        return ScalarRows(self.scalar_rows)

    def add(self, item: object) -> None:
        self.added.append(item)

    async def commit(self) -> None:
        return None

    async def refresh(self, item: object) -> None:
        item.id = uuid.uuid4()
        item.created_at = datetime(2026, 7, 28, tzinfo=UTC)


class FakeProvider:
    def __init__(self) -> None:
        self.revoked: tuple[str, str] | None = None

    async def get_subscription_info(self, provider_id: str) -> ProviderUser:
        return ProviderUser(
            provider_id=provider_id,
            username="vpn_user",
            status=AccountStatus.ACTIVE,
            expire_at=datetime(2026, 9, 1, tzinfo=UTC),
            subscription_url="https://subscription.example/s/opaque",
            raw={},
        )

    async def get_usage(self, _provider_id: str) -> Usage:
        return Usage(used_bytes=10, traffic_limit_bytes=100)

    async def get_usage_history(
        self,
        _provider_id: str,
        start: object,
        end: object,
    ) -> list[UsagePoint]:
        return [UsagePoint(usage_date=end, used_bytes=20)]

    async def revoke_device(self, provider_id: str, hardware_id: str) -> None:
        self.revoked = (provider_id, hardware_id)


def authenticated_user() -> AuthenticatedUser:
    user = User(
        id=uuid.uuid4(),
        display_name="Test",
        referral_code="REFCODE",
    )
    return AuthenticatedUser(session=SimpleNamespace(), user=user)


def request_with(provider: object | None = None) -> Request:
    app = SimpleNamespace(
        state=SimpleNamespace(
            vpn_provider=provider,
            settings=SimpleNamespace(MINIAPP_PUBLIC_URL="https://vpn.example/app"),
        )
    )
    return Request({"type": "http", "app": app})


def subscription_row(user_id: uuid.UUID) -> tuple[Subscription, Plan, VpnAccount]:
    plan_id = uuid.uuid4()
    subscription = Subscription(
        id=uuid.uuid4(),
        user_id=user_id,
        plan_id=plan_id,
        status=SubscriptionStatus.ACTIVE,
        starts_at=datetime(2026, 7, 1, tzinfo=UTC),
        expires_at=datetime(2026, 8, 1, tzinfo=UTC),
        traffic_limit_bytes=100,
        device_limit=3,
        server_groups=[],
        public_token_digest=b"x" * 32,
    )
    plan = Plan(
        id=plan_id,
        code="TEST",
        name="Test plan",
        description="",
        duration_days=30,
        traffic_limit_bytes=100,
        device_limit=3,
        price_minor=100,
        currency="RUB",
        server_groups=[],
        active=True,
        sort_order=1,
    )
    account = VpnAccount(
        id=uuid.uuid4(),
        subscription_id=subscription.id,
        provider="remnawave",
        provider_user_id="provider-user-id",
        provider_username="vpn_user",
        desired_state={},
        observed_state={},
    )
    return subscription, plan, account


@pytest.mark.asyncio
async def test_subscription_access_uses_remnawave_as_source_of_url_and_usage() -> None:
    auth = authenticated_user()
    provider = FakeProvider()
    db = FakeDatabase(rows=[subscription_row(auth.user.id)])
    response = Response()

    result = await subscription_access(request_with(provider), response, db, auth)

    assert result.subscription_url == "https://subscription.example/s/opaque"
    assert result.provider_status == "active"
    assert result.usage.used_bytes == 10
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_yearly_traffic_returns_twelve_real_month_buckets() -> None:
    auth = authenticated_user()
    subscription, _, account = subscription_row(auth.user.id)
    now = datetime.now(UTC)
    daily = VpnUsageDaily(
        user_id=auth.user.id,
        usage_date=now.date(),
        used_bytes=20,
        sampled_at=now,
    )
    db = FakeDatabase(rows=[(subscription, account), None], scalar_rows=[daily])
    response = Response()

    result = await yearly_traffic(
        request_with(FakeProvider()),
        response,
        db,
        auth,
        year=now.year,
    )

    assert len(result.months) == 12
    assert result.months[now.month - 1].used_bytes == 20
    assert result.months[now.month - 1].has_data is True
    assert result.current_month_used_bytes == 20
    assert result.source_status == "fresh"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_delete_device_calls_provider_for_owned_vpn_account() -> None:
    auth = authenticated_user()
    subscription, _, account = subscription_row(auth.user.id)
    provider = FakeProvider()
    db = FakeDatabase(rows=[(subscription, account)])

    response = await delete_device("device-hwid", request_with(provider), db, auth)

    assert response.status_code == 204
    assert provider.revoked == ("provider-user-id", "device-hwid")


def test_delete_device_route_requires_csrf_dependency() -> None:
    route = next(item for item in router.routes if item.path == "/api/v2/devices/{hardware_id}")
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
    assert require_csrf in dependency_calls


@pytest.mark.asyncio
async def test_referral_summary_uses_owned_referrals_and_rewards() -> None:
    auth = authenticated_user()
    db = FakeDatabase(scalar_values=[4, 12_500])

    result = await referral_summary(request_with(), db, auth)

    assert result.total_referrals == 4
    assert result.total_earned_minor == 12_500
    assert result.referral_url == "https://vpn.example/app/?invite=REFCODE"


@pytest.mark.asyncio
async def test_create_support_ticket_strips_input_and_owns_ticket() -> None:
    auth = authenticated_user()
    db = FakeDatabase()
    payload = CreateSupportTicketRequest(subject="  Connection issue  ", body="  Details  ")

    result = await create_support_ticket(payload, db, auth)

    assert result.status == "open"
    assert result.subject == "Connection issue"
    assert result.body == "Details"
    assert db.added[0].user_id == auth.user.id
