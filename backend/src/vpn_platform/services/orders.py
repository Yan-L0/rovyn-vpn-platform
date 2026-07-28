from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vpn_platform.db.models import (
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Plan,
    ServiceEvent,
    Subscription,
    SubscriptionStatus,
)
from vpn_platform.domain.payment_provider import (
    CreatePayment,
    PaymentProvider,
    ProviderPayment,
    VerifiedPayment,
)


class OrderConflict(ValueError):
    pass


class PaymentConflict(ValueError):
    pass


@dataclass(frozen=True)
class PaymentApplication:
    payment: Payment
    order: Order
    subscription: Subscription
    provisioning_event: ServiceEvent


class OrderService:
    """Owns order/payment state transitions; transaction ownership stays with the caller."""

    async def create_order(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        plan_id: uuid.UUID,
        idempotency_key: str,
    ) -> Order:
        key = idempotency_key.strip()
        if not key or len(key) > 128:
            raise ValueError("idempotency_key must contain 1..128 characters")

        # The schema already has a unique constraint. The transaction advisory
        # lock additionally makes the common concurrent-retry path deterministic
        # without putting the SQLAlchemy transaction into a failed state.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"order:{user_id}:{key}"},
        )
        existing = await db.scalar(
            select(Order).where(
                Order.user_id == user_id,
                Order.idempotency_key == key,
            )
        )
        if existing is not None:
            if existing.plan_id != plan_id:
                raise OrderConflict("idempotency key was already used for another plan")
            return existing

        plan = await db.get(Plan, plan_id)
        if plan is None or not plan.active:
            raise ValueError("plan is unavailable")
        order = Order(
            user_id=user_id,
            plan_id=plan.id,
            status=OrderStatus.PENDING,
            amount_minor=plan.price_minor,
            currency=plan.currency,
            plan_snapshot=self._snapshot(plan),
            idempotency_key=key,
        )
        db.add(order)
        await db.flush()
        return order

    async def initiate_payment(
        self,
        db: AsyncSession,
        *,
        order_id: uuid.UUID,
        provider: PaymentProvider,
        provider_name: str,
        return_url: str,
    ) -> tuple[Payment, ProviderPayment]:
        order = await db.get(Order, order_id, with_for_update=True)
        if order is None:
            raise ValueError("order does not exist")
        if order.status not in {OrderStatus.PENDING, OrderStatus.AWAITING_PAYMENT}:
            raise OrderConflict(f"cannot initiate payment for {order.status.value} order")

        previous = await db.scalar(
            select(Payment)
            .where(
                Payment.order_id == order.id,
                Payment.provider == provider_name,
                Payment.status.in_([PaymentStatus.CREATED, PaymentStatus.PENDING]),
            )
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        if previous is not None:
            url = previous.raw_status.get("confirmation_url")
            if isinstance(url, str) and url:
                restored = await provider.get_payment(previous.provider_payment_id)
                return previous, restored

        intent = await provider.create_payment(
            CreatePayment(
                amount_minor=order.amount_minor,
                currency=order.currency,
                description=f"VPN subscription order {order.id}",
                return_url=return_url,
                metadata={"order_id": str(order.id)},
            ),
            f"order-{order.id}",
        )
        if intent.confirmation_url is None:
            raise RuntimeError("payment provider returned no confirmation URL")
        raw = dict(intent.raw)
        raw["confirmation_url"] = intent.confirmation_url
        payment = Payment(
            order_id=order.id,
            provider=provider_name,
            provider_payment_id=intent.provider_id,
            status=PaymentStatus.PENDING,
            amount_minor=order.amount_minor,
            currency=order.currency,
            raw_status=raw,
        )
        db.add(payment)
        order.status = OrderStatus.AWAITING_PAYMENT
        await db.flush()
        return payment, intent

    async def apply_verified_payment(
        self,
        db: AsyncSession,
        verified: VerifiedPayment,
        *,
        now: datetime | None = None,
    ) -> PaymentApplication:
        current_time = now or datetime.now(UTC)
        order = await db.get(Order, verified.order_id, with_for_update=True)
        if order is None:
            raise PaymentConflict("payment points to an unknown order")
        if order.status in {
            OrderStatus.CANCELLED,
            OrderStatus.REFUNDED,
        }:
            raise PaymentConflict(f"payment cannot advance a {order.status.value} order")
        if (
            verified.amount_minor != order.amount_minor
            or verified.currency.upper() != order.currency
        ):
            raise PaymentConflict("verified amount or currency does not match the order")

        payment = await db.scalar(
            select(Payment)
            .where(
                Payment.provider == verified.provider,
                Payment.provider_payment_id == verified.provider_payment_id,
            )
            .with_for_update()
        )
        if payment is None:
            payment = Payment(
                order_id=order.id,
                provider=verified.provider,
                provider_payment_id=verified.provider_payment_id,
                status=PaymentStatus.SUCCEEDED,
                amount_minor=verified.amount_minor,
                currency=verified.currency.upper(),
                raw_status=dict(verified.raw),
                confirmed_at=current_time,
            )
            db.add(payment)
        else:
            self._assert_same_payment(payment, verified)
            if payment.status in {PaymentStatus.CANCELLED, PaymentStatus.REFUNDED}:
                raise PaymentConflict(f"cannot advance a {payment.status.value} payment")
            payment.status = PaymentStatus.SUCCEEDED
            payment.raw_status = dict(verified.raw)
            payment.confirmed_at = payment.confirmed_at or current_time

        order.status = (
            OrderStatus.FULFILLED
            if order.status == OrderStatus.FULFILLED
            else OrderStatus.PAID
        )
        order.paid_at = order.paid_at or current_time

        event_key = f"provision-order:{order.id}"
        event = await db.scalar(
            select(ServiceEvent).where(ServiceEvent.idempotency_key == event_key)
        )
        if event is not None:
            subscription_id = uuid.UUID(str(event.payload["subscription_id"]))
            subscription = await db.get(Subscription, subscription_id)
            if subscription is None:
                raise RuntimeError("provisioning event points to a missing subscription")
        else:
            subscription = self._new_subscription(order, current_time)
            db.add(subscription)
            await db.flush()
            event = ServiceEvent(
                aggregate_type="order",
                aggregate_id=order.id,
                event_type="vpn.subscription.provision",
                payload={
                    "order_id": str(order.id),
                    "subscription_id": str(subscription.id),
                },
                idempotency_key=event_key,
                available_at=current_time,
            )
            db.add(event)

        await db.flush()
        return PaymentApplication(payment, order, subscription, event)

    @staticmethod
    def _snapshot(plan: Plan) -> dict[str, Any]:
        return {
            "code": plan.code,
            "name": plan.name,
            "duration_days": plan.duration_days,
            "traffic_limit_bytes": plan.traffic_limit_bytes,
            "device_limit": plan.device_limit,
            "server_groups": list(plan.server_groups),
            "price_minor": plan.price_minor,
            "currency": plan.currency,
        }

    @staticmethod
    def _new_subscription(order: Order, now: datetime) -> Subscription:
        snapshot = order.plan_snapshot
        try:
            duration_days = int(snapshot["duration_days"])
            traffic_limit = int(snapshot["traffic_limit_bytes"])
            device_limit = int(snapshot["device_limit"])
            groups = list(snapshot["server_groups"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("order contains an invalid plan snapshot") from error
        if duration_days <= 0 or traffic_limit < 0 or device_limit < 0:
            raise RuntimeError("order contains an invalid plan snapshot")
        token = secrets.token_urlsafe(48)
        return Subscription(
            user_id=order.user_id,
            plan_id=order.plan_id,
            status=SubscriptionStatus.PENDING,
            starts_at=now,
            expires_at=now + timedelta(days=duration_days),
            traffic_limit_bytes=traffic_limit,
            device_limit=device_limit,
            server_groups=groups,
            public_token_digest=hashlib.sha256(token.encode()).digest(),
        )

    @staticmethod
    def _assert_same_payment(payment: Payment, verified: VerifiedPayment) -> None:
        if (
            payment.order_id != verified.order_id
            or payment.amount_minor != verified.amount_minor
            or payment.currency != verified.currency.upper()
        ):
            raise PaymentConflict("provider payment id was already bound to different facts")
