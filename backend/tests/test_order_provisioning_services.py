import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from vpn_platform.db.models import (
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    ServiceEvent,
    Subscription,
    SubscriptionStatus,
    VpnAccount,
)
from vpn_platform.domain.payment_provider import (
    PaymentState,
    ProviderPayment,
    VerifiedPayment,
)
from vpn_platform.domain.vpn_provider import AccountStatus, ProviderUser
from vpn_platform.services.orders import OrderConflict, OrderService
from vpn_platform.services.provisioning import ProvisioningService


class FakeSession:
    def __init__(self, *, objects: dict[type[Any], Any], scalars: list[Any]):
        self.objects = objects
        self.scalars = scalars
        self.added: list[Any] = []
        self.flushes = 0

    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def scalar(self, _statement: Any) -> Any:
        return self.scalars.pop(0)

    async def get(self, model: type[Any], _key: Any, **_kwargs: Any) -> Any:
        return self.objects.get(model)

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushes += 1


def make_order(*, status: OrderStatus = OrderStatus.PAID) -> Order:
    return Order(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        plan_id=uuid.uuid4(),
        status=status,
        amount_minor=10_000,
        currency="RUB",
        plan_snapshot={
            "duration_days": 30,
            "traffic_limit_bytes": 1000,
            "device_limit": 2,
            "server_groups": ["group-1"],
        },
        idempotency_key="order-key",
    )


def make_subscription(order: Order) -> Subscription:
    now = datetime(2026, 7, 28, tzinfo=UTC)
    return Subscription(
        id=uuid.uuid4(),
        user_id=order.user_id,
        plan_id=order.plan_id,
        status=SubscriptionStatus.PENDING,
        starts_at=now,
        expires_at=now + timedelta(days=30),
        traffic_limit_bytes=1000,
        device_limit=2,
        server_groups=["group-1"],
        public_token_digest=b"x" * 32,
    )


@pytest.mark.asyncio
async def test_create_order_replay_reuses_order_and_rejects_changed_plan() -> None:
    order = make_order(status=OrderStatus.PENDING)
    db = FakeSession(objects={}, scalars=[order])
    service = OrderService()

    replay = await service.create_order(  # type: ignore[arg-type]
        db,
        user_id=order.user_id,
        plan_id=order.plan_id,
        idempotency_key=order.idempotency_key,
    )
    assert replay is order
    assert db.added == []

    db.scalars = [order]
    with pytest.raises(OrderConflict, match="another plan"):
        await service.create_order(  # type: ignore[arg-type]
            db,
            user_id=order.user_id,
            plan_id=uuid.uuid4(),
            idempotency_key=order.idempotency_key,
        )


@pytest.mark.asyncio
async def test_verified_payment_replay_reuses_entitlement() -> None:
    order = make_order()
    subscription = make_subscription(order)
    payment = Payment(
        id=uuid.uuid4(),
        order_id=order.id,
        provider="yookassa",
        provider_payment_id="payment-1",
        status=PaymentStatus.SUCCEEDED,
        amount_minor=order.amount_minor,
        currency=order.currency,
        raw_status={},
    )
    event = ServiceEvent(
        aggregate_type="order",
        aggregate_id=order.id,
        event_type="vpn.subscription.provision",
        payload={"subscription_id": str(subscription.id), "order_id": str(order.id)},
        idempotency_key=f"provision-order:{order.id}",
        available_at=datetime(2026, 7, 28, tzinfo=UTC),
    )
    db = FakeSession(
        objects={Order: order, Subscription: subscription},
        scalars=[payment, event],
    )
    verified = VerifiedPayment(
        provider="yookassa",
        provider_payment_id="payment-1",
        order_id=order.id,
        amount_minor=order.amount_minor,
        currency=order.currency,
        raw={"status": "succeeded"},
    )

    result = await OrderService().apply_verified_payment(  # type: ignore[arg-type]
        db,
        verified,
        now=datetime(2026, 7, 28, tzinfo=UTC),
    )

    assert result.subscription is subscription
    assert result.provisioning_event is event
    assert not any(isinstance(item, Subscription) for item in db.added)


class FakeProvider:
    def __init__(self) -> None:
        self.created = 0
        self.server_group_ids: tuple[str, ...] = ()

    async def create_user(self, user: Any, idempotency_key: str) -> ProviderUser:
        self.created += 1
        self.server_group_ids = tuple(user.server_group_ids)
        assert user.external_key
        assert idempotency_key.startswith("provision-order:")
        return ProviderUser(
            provider_id="remote-user",
            username=user.username,
            status=AccountStatus.ACTIVE,
            expire_at=user.expire_at,
            subscription_url="https://subscription.example/opaque",
            raw={"uuid": "remote-user"},
        )

    def __getattr__(self, _name: str) -> Any:
        raise AssertionError("unexpected provider method")


@pytest.mark.asyncio
async def test_provisioning_activates_subscription_only_after_provider_success() -> None:
    order = make_order()
    subscription = make_subscription(order)
    event = ServiceEvent(
        aggregate_type="order",
        aggregate_id=order.id,
        event_type="vpn.subscription.provision",
        payload={"subscription_id": str(subscription.id), "order_id": str(order.id)},
        idempotency_key=f"provision-order:{order.id}",
        available_at=datetime(2026, 7, 28, tzinfo=UTC),
        attempts=0,
    )
    db = FakeSession(
        objects={Order: order, Subscription: subscription},
        scalars=[event, None, 42],
    )
    provider = FakeProvider()

    result = await ProvisioningService(provider).provision_order(  # type: ignore[arg-type]
        db,  # type: ignore[arg-type]
        order_id=order.id,
        now=datetime(2026, 7, 28, tzinfo=UTC),
    )

    assert result.fulfilled is True
    assert provider.created == 1
    assert order.status is OrderStatus.FULFILLED
    assert subscription.status is SubscriptionStatus.ACTIVE
    assert event.processed_at is not None
    assert isinstance(result.vpn_account, VpnAccount)


@pytest.mark.asyncio
async def test_provisioning_uses_configured_remnawave_squads() -> None:
    order = make_order()
    subscription = make_subscription(order)
    event = ServiceEvent(
        aggregate_type="order",
        aggregate_id=order.id,
        event_type="vpn.subscription.provision",
        payload={"subscription_id": str(subscription.id), "order_id": str(order.id)},
        idempotency_key=f"provision-order:{order.id}",
        available_at=datetime(2026, 7, 28, tzinfo=UTC),
        attempts=0,
    )
    db = FakeSession(
        objects={Order: order, Subscription: subscription},
        scalars=[event, None, 42],
    )
    provider = FakeProvider()
    squad_id = "8e319819-2110-44ab-b6f5-e76138233ed5"

    await ProvisioningService(
        provider,  # type: ignore[arg-type]
        default_server_group_ids=(squad_id,),
    ).provision_order(
        db,  # type: ignore[arg-type]
        order_id=order.id,
        now=datetime(2026, 7, 28, tzinfo=UTC),
    )

    assert provider.server_group_ids == (squad_id,)


def test_verified_payment_requires_a_paid_provider_document() -> None:
    payment = ProviderPayment(
        provider_id="payment-1",
        status=PaymentState.PENDING,
        paid=False,
        amount_minor=100,
        currency="RUB",
        confirmation_url="https://example.test/pay",
        created_at=None,
        metadata={},
        raw={},
    )
    with pytest.raises(ValueError, match="has not succeeded"):
        VerifiedPayment.from_provider_payment(
            payment,
            provider="yookassa",
            order_id=uuid.uuid4(),
        )
