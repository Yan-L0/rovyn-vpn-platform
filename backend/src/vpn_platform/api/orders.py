from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select

from vpn_platform.api.dependencies import (
    AuthenticatedUser,
    DatabaseSession,
    get_current_user,
    require_csrf,
)
from vpn_platform.api.schemas import (
    CreateOrderRequest,
    OrderPaymentResponse,
    YooKassaWebhookEnvelope,
)
from vpn_platform.db.models import (
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    PaymentWebhook,
)
from vpn_platform.domain.payment_provider import (
    PaymentProviderError,
    PaymentState,
    VerifiedPayment,
)
from vpn_platform.services.orders import OrderConflict, OrderService, PaymentConflict
from vpn_platform.services.provisioning import ProvisioningService

router = APIRouter(prefix="/api/v1")
MutatingUser = Annotated[AuthenticatedUser, Depends(require_csrf)]


def _payment_response(order: Order, payment: Payment) -> OrderPaymentResponse:
    confirmation_url = payment.raw_status.get("confirmation_url")
    return OrderPaymentResponse(
        order_id=order.id,
        status=order.status.value,
        amount_minor=order.amount_minor,
        currency=order.currency,
        payment_id=payment.id,
        payment_status=payment.status.value,
        confirmation_url=confirmation_url if isinstance(confirmation_url, str) else None,
    )


async def _latest_payment(db: DatabaseSession, order_id: uuid.UUID) -> Payment | None:
    return cast(
        Payment | None,
        await db.scalar(
            select(Payment)
            .where(Payment.order_id == order_id, Payment.provider == "yookassa")
            .order_by(Payment.created_at.desc())
            .limit(1)
        ),
    )


@router.post("/orders", response_model=OrderPaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: CreateOrderRequest,
    request: Request,
    db: DatabaseSession,
    auth: MutatingUser,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
) -> OrderPaymentResponse:
    provider = request.app.state.payment_provider
    settings = request.app.state.settings
    if provider is None or not settings.YOOKASSA_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SBP payments are temporarily unavailable",
        )
    try:
        async with db.begin():
            order = await OrderService().create_order(
                db,
                user_id=auth.user.id,
                plan_id=payload.plan_id,
                idempotency_key=idempotency_key,
            )
            existing = await _latest_payment(db, order.id)
            if existing is not None and order.status not in {
                OrderStatus.PENDING,
                OrderStatus.AWAITING_PAYMENT,
            }:
                return _payment_response(order, existing)
            payment, intent = await OrderService().initiate_payment(
                db,
                order_id=order.id,
                provider=provider,
                provider_name="yookassa",
                return_url=str(settings.YOOKASSA_RETURN_URL),
            )
            if intent.confirmation_url:
                payment.raw_status = {
                    **dict(payment.raw_status),
                    "confirmation_url": intent.confirmation_url,
                }
            return _payment_response(order, payment)
    except (ValueError, OrderConflict) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PaymentProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="payment provider is unavailable",
        ) from error


@router.get("/orders/{order_id}", response_model=OrderPaymentResponse)
async def get_order(
    order_id: uuid.UUID,
    db: DatabaseSession,
    auth: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> OrderPaymentResponse:
    order = await db.get(Order, order_id)
    if order is None or order.user_id != auth.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    payment = await _latest_payment(db, order.id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="payment not initialized")
    return _payment_response(order, payment)


@router.post("/payments/yookassa/webhook", include_in_schema=False)
async def yookassa_webhook(
    payload: YooKassaWebhookEnvelope,
    request: Request,
    db: DatabaseSession,
) -> dict[str, str]:
    provider = request.app.state.payment_provider
    vpn_provider = request.app.state.vpn_provider
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="payment provider is not configured",
        )
    provider_payment_id = payload.object.get("id")
    if not isinstance(provider_payment_id, str) or not provider_payment_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="payment id is missing")

    # YooKassa callbacks are not signed. Never trust the callback object: fetch
    # the payment over the authenticated API and make decisions from that copy.
    try:
        remote = await provider.get_payment(provider_payment_id)
    except PaymentProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="could not verify payment",
        ) from error

    raw_order_id = remote.metadata.get("order_id")
    try:
        order_id = uuid.UUID(raw_order_id or "")
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="verified payment has invalid order metadata",
        ) from error

    event_id = f"{payload.event}:{provider_payment_id}"
    digest = hashlib.sha256(
        json.dumps(payload.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    ).digest()
    now = datetime.now(UTC)

    try:
        async with db.begin():
            webhook = await db.scalar(
                select(PaymentWebhook)
                .where(
                    PaymentWebhook.provider == "yookassa",
                    PaymentWebhook.provider_event_id == event_id,
                )
                .with_for_update()
            )
            if webhook is None:
                webhook = PaymentWebhook(
                    provider="yookassa",
                    provider_event_id=event_id,
                    payload_digest=digest,
                    signature_valid=True,
                    status="verified",
                )
                db.add(webhook)
            elif webhook.payload_digest != digest:
                raise PaymentConflict("webhook event id was reused with different content")

            if remote.status is PaymentState.SUCCEEDED and remote.paid:
                verified = VerifiedPayment.from_provider_payment(
                    remote,
                    provider="yookassa",
                    order_id=order_id,
                )
                await OrderService().apply_verified_payment(db, verified, now=now)
                webhook.status = "payment_applied"
            elif remote.status is PaymentState.CANCELED:
                payment = await db.scalar(
                    select(Payment)
                    .where(
                        Payment.provider == "yookassa",
                        Payment.provider_payment_id == provider_payment_id,
                    )
                    .with_for_update()
                )
                if payment is not None and payment.status is not PaymentStatus.SUCCEEDED:
                    payment.status = PaymentStatus.CANCELLED
                    payment.raw_status = dict(remote.raw)
                    order = await db.get(Order, payment.order_id, with_for_update=True)
                    if order is not None and order.status in {
                        OrderStatus.PENDING,
                        OrderStatus.AWAITING_PAYMENT,
                    }:
                        order.status = OrderStatus.CANCELLED
                webhook.status = "cancellation_applied"
            else:
                webhook.status = "ignored_non_terminal"
            webhook.processed_at = now
    except PaymentConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    if remote.status is PaymentState.SUCCEEDED and remote.paid:
        if vpn_provider is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="VPN provider is not configured",
            )
        async with db.begin():
            result = await ProvisioningService(vpn_provider).provision_order(
                db,
                order_id=order_id,
                now=now,
            )
        if not result.fulfilled:
            # A non-2xx response asks YooKassa to retry the notification. The
            # paid order and durable provisioning event remain safe to replay.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="subscription provisioning will be retried",
            )

    return {"status": "accepted"}
