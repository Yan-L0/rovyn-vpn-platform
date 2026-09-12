from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select

from vpn_platform.api.dependencies import (
    AuthenticatedUser,
    DatabaseSession,
    get_current_user,
    require_csrf,
)
from vpn_platform.api.schemas import (
    AuthResponse,
    EmailCodeRequest,
    EmailCodeRequestResponse,
    EmailCodeVerifyRequest,
    MeResponse,
    PlanResponse,
    SubscriptionResponse,
    TelegramAuthRequest,
    TelegramLinkResponse,
    UserResponse,
)
from vpn_platform.db.models import (
    EmailAccount,
    LedgerEntry,
    Plan,
    Subscription,
    SubscriptionStatus,
    TelegramAccount,
    Wallet,
)
from vpn_platform.security.telegram import (
    TelegramAuthError,
    TelegramIdentity,
    TelegramInitDataVerifier,
)
from vpn_platform.services.email_auth import EmailAuthService, normalize_email
from vpn_platform.services.identity import IdentityService

router = APIRouter(prefix="/api/v1")
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


def set_session_cookie(
    response: Response, token: str, expires_at: datetime, *, production: bool
) -> None:
    response.set_cookie(
        "vpn_session",
        token,
        expires=expires_at,
        secure=production,
        httponly=True,
        samesite="none" if production else "lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


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
    link_user_id = None
    if identity.start_param and identity.start_param.startswith("link_"):
        ticket = identity.start_param.removeprefix("link_")
        raw_user_id = await request.app.state.redis.getdel(f"telegram-link:{ticket}")
        if raw_user_id is None:
            raise HTTPException(status_code=400, detail="Ссылка привязки устарела")
        link_user_id = uuid.UUID(
            raw_user_id.decode() if isinstance(raw_user_id, bytes) else raw_user_id
        )
    async with db.begin():
        try:
            user = await identity_service.get_or_create_telegram_user(
                db,
                identity,
                request_id=request_id,
                ip_address=client_ip,
                link_user_id=link_user_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        issued = await identity_service.issue_session(
            db,
            user.id,
            user_agent=request.headers.get("user-agent"),
            ip_address=client_ip,
        )

    set_session_cookie(
        response, issued.token, issued.expires_at, production=settings.is_production_like
    )
    return AuthResponse(
        user=UserResponse(
            id=user.id,
            telegram_id=identity.telegram_id,
            display_name=user.display_name,
            locale=user.locale,
        ),
        csrf_token=issued.csrf_token,
        expires_at=issued.expires_at,
    )


@router.post("/auth/telegram/link", response_model=TelegramLinkResponse)
async def create_telegram_link(
    request: Request,
    auth: Annotated[AuthenticatedUser, Depends(require_csrf)],
) -> TelegramLinkResponse:
    ticket = secrets.token_urlsafe(24)
    expires_in = 600
    await request.app.state.redis.setex(f"telegram-link:{ticket}", expires_in, str(auth.user.id))
    return TelegramLinkResponse(start_param=f"link_{ticket}", expires_in=expires_in)


@router.post("/auth/email/request", response_model=EmailCodeRequestResponse)
async def request_email_code(
    payload: EmailCodeRequest, request: Request, db: DatabaseSession
) -> EmailCodeRequestResponse:
    settings = request.app.state.settings
    email = normalize_email(payload.email)
    current_user_id = None
    token = request.cookies.get("vpn_session", "")
    if token:
        authenticated = await IdentityService().authenticate_session(db, token)
        if authenticated is not None:
            _, current_user = authenticated
            current_user_id = current_user.id
            await db.commit()
    service = EmailAuthService(
        request.app.state.redis,
        secret=settings.SESSION_SECRET.get_secret_value(),
        api_key=settings.RESEND_API_KEY.get_secret_value(),
        sender=settings.EMAIL_FROM,
        ttl=settings.EMAIL_AUTH_CODE_TTL_SECONDS,
    )
    challenge_id = await service.request_code(
        email,
        ip=request.client.host if request.client else "unknown",
        pending_user_id=current_user_id,
    )
    return EmailCodeRequestResponse(
        challenge_id=challenge_id, expires_in=settings.EMAIL_AUTH_CODE_TTL_SECONDS
    )


@router.post("/auth/email/verify", response_model=AuthResponse)
async def verify_email_code(
    payload: EmailCodeVerifyRequest, request: Request, response: Response, db: DatabaseSession
) -> AuthResponse:
    settings = request.app.state.settings
    service = EmailAuthService(
        request.app.state.redis,
        secret=settings.SESSION_SECRET.get_secret_value(),
        api_key=settings.RESEND_API_KEY.get_secret_value(),
        sender=settings.EMAIL_FROM,
        ttl=settings.EMAIL_AUTH_CODE_TTL_SECONDS,
    )
    email, pending_user_id = await service.consume(payload.challenge_id, payload.code)
    client_ip = request.client.host if request.client else None
    identity_service = IdentityService()
    async with db.begin():
        user = await service.get_or_create_user(
            db,
            email,
            pending_user_id,
            ip=client_ip or "unknown",
            request_id=request.headers.get("x-request-id"),
        )
        issued = await identity_service.issue_session(
            db, user.id, user_agent=request.headers.get("user-agent"), ip_address=client_ip
        )
    telegram_id = await db.scalar(
        select(TelegramAccount.telegram_id).where(TelegramAccount.user_id == user.id)
    )
    set_session_cookie(
        response, issued.token, issued.expires_at, production=settings.is_production_like
    )
    return AuthResponse(
        user=UserResponse(
            id=user.id, telegram_id=telegram_id, display_name=user.display_name, locale=user.locale
        ),
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
    telegram_id = await db.scalar(
        select(TelegramAccount.telegram_id).where(TelegramAccount.user_id == auth.user.id)
    )
    email = await db.scalar(select(EmailAccount.email).where(EmailAccount.user_id == auth.user.id))
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
            telegram_id=telegram_id,
            display_name=auth.user.display_name,
            locale=auth.user.locale,
            email=email,
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
