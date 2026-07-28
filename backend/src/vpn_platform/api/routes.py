from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select

from vpn_platform.api.dependencies import AuthenticatedUser, DatabaseSession, get_current_user
from vpn_platform.api.schemas import (
    AuthResponse,
    MeResponse,
    PlanResponse,
    SubscriptionResponse,
    TelegramAuthRequest,
    UserResponse,
)
from vpn_platform.db.models import LedgerEntry, Plan, Subscription, SubscriptionStatus, Wallet
from vpn_platform.security.telegram import (
    TelegramAuthError,
    TelegramIdentity,
    TelegramInitDataVerifier,
)
from vpn_platform.services.identity import IdentityService

router = APIRouter(prefix="/api/v1")
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


@router.post("/auth/telegram", response_model=AuthResponse)
async def authenticate_telegram(
    payload: TelegramAuthRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
) -> AuthResponse:
    settings = request.app.state.settings
    if payload.init_data:
        try:
            identity = TelegramInitDataVerifier(
                settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
                max_age_seconds=settings.TELEGRAM_AUTH_MAX_AGE_SECONDS,
            ).verify(payload.init_data)
        except (TelegramAuthError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid Telegram authorization",
            ) from error
    elif settings.TELEGRAM_AUTH_DEV_BYPASS:
        identity = TelegramIdentity(
            telegram_id=9_000_000_001,
            first_name="Local",
            last_name="Developer",
            username="local_developer",
            language_code="ru",
            photo_url=None,
            auth_date=int(datetime.now(UTC).timestamp()),
            query_id=None,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram initData required",
        )

    client_ip = request.client.host if request.client else None
    request_id = request.headers.get("x-request-id")
    identity_service = IdentityService()
    async with db.begin():
        user = await identity_service.get_or_create_telegram_user(
            db,
            identity,
            request_id=request_id,
            ip_address=client_ip,
        )
        issued = await identity_service.issue_session(
            db,
            user.id,
            user_agent=request.headers.get("user-agent"),
            ip_address=client_ip,
        )

    response.set_cookie(
        "vpn_session",
        issued.token,
        expires=issued.expires_at,
        secure=settings.is_production_like,
        httponly=True,
        # Telegram Web renders the Mini App in a cross-site iframe. Production
        # cookies therefore need SameSite=None (which also requires Secure) or
        # the following authenticated API requests lose the new session.
        samesite="none" if settings.is_production_like else "lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(
        user=UserResponse(id=user.id, display_name=user.display_name, locale=user.locale),
        csrf_token=issued.csrf_token,
        expires_at=issued.expires_at,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    auth: CurrentUser,
    db: DatabaseSession,
) -> MeResponse:
    wallet = await db.scalar(
        select(Wallet).where(Wallet.user_id == auth.user.id, Wallet.currency == "RUB")
    )
    balance = 0
    if wallet is not None:
        balance = int(
            await db.scalar(
                select(func.coalesce(func.sum(LedgerEntry.amount_minor), 0)).where(
                    LedgerEntry.wallet_id == wallet.id
                )
            )
            or 0
        )

    subscription_row = (
        await db.execute(
            select(Subscription, Plan)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(
                Subscription.user_id == auth.user.id,
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.SUSPENDED]),
            )
            .order_by(Subscription.expires_at.desc())
            .limit(1)
        )
    ).first()
    subscription = None
    if subscription_row:
        item, plan = subscription_row
        subscription = SubscriptionResponse(
            status=item.status.value,
            plan_name=plan.name,
            expires_at=item.expires_at,
            traffic_limit_bytes=item.traffic_limit_bytes,
            device_limit=item.device_limit,
            used_bytes=None,
        )

    return MeResponse(
        user=UserResponse(
            id=auth.user.id,
            display_name=auth.user.display_name,
            locale=auth.user.locale,
        ),
        wallet_balance_minor=balance,
        wallet_currency="RUB",
        referral_code=auth.user.referral_code,
        subscription=subscription,
    )


@router.get("/catalog/plans", response_model=list[PlanResponse])
async def plans(db: DatabaseSession) -> list[PlanResponse]:
    items = (
        await db.scalars(
            select(Plan).where(Plan.active.is_(True)).order_by(Plan.sort_order, Plan.price_minor)
        )
    ).all()
    return [
        PlanResponse(
            id=item.id,
            code=item.code,
            name=item.name,
            description=item.description,
            duration_days=item.duration_days,
            traffic_limit_bytes=item.traffic_limit_bytes,
            device_limit=item.device_limit,
            price_minor=item.price_minor,
            currency=item.currency,
            server_groups=item.server_groups,
        )
        for item in items
    ]
