from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, text

from vpn_platform.api.dependencies import (
    AuthenticatedUser,
    DatabaseSession,
    get_current_user,
    require_csrf,
)
from vpn_platform.db.models import (
    AuditLog,
    Plan,
    Subscription,
    SubscriptionStatus,
    TelegramAccount,
    User,
    VpnAccount,
    Wallet,
)
from vpn_platform.domain.vpn_provider import AccountStatus, ProviderError, ProvisionUser

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class AdminAccessResponse(BaseModel):
    is_owner: bool


class AdminSubscriptionSummary(BaseModel):
    plan_name: str
    status: str
    expires_at: datetime


class AdminUserResponse(BaseModel):
    found: bool
    telegram_id: int
    display_name: str | None = None
    username: str | None = None
    remnawave_linked: bool = False
    subscription: AdminSubscriptionSummary | None = None


class AdminGrantRequest(BaseModel):
    telegram_id: int = Field(gt=0)
    plan_id: uuid.UUID
    device_limit: int | None = Field(default=None, ge=1, le=50)
    starts_on: date | None = None
    comment: str = Field(default="Ручная выдача", max_length=240)


class AdminGrantResponse(BaseModel):
    telegram_id: int
    display_name: str
    status: str
    expires_at: datetime
    subscription_url: str | None


async def _owner_telegram_id(db: DatabaseSession, auth: AuthenticatedUser) -> int | None:
    return await db.scalar(
        select(TelegramAccount.telegram_id)
        .where(TelegramAccount.user_id == auth.user.id)
        .limit(1)
    )


async def _is_owner(request: Request, db: DatabaseSession, auth: AuthenticatedUser) -> bool:
    telegram_id = await _owner_telegram_id(db, auth)
    return (
        telegram_id is not None
        and telegram_id in request.app.state.settings.bot_owner_telegram_ids
    )


async def _require_owner(
    request: Request,
    db: DatabaseSession,
    auth: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    if not await _is_owner(request, db, auth):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner access required")
    return auth


async def _require_owner_csrf(
    request: Request,
    db: DatabaseSession,
    auth: Annotated[AuthenticatedUser, Depends(require_csrf)],
) -> AuthenticatedUser:
    if not await _is_owner(request, db, auth):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner access required")
    return auth


@router.get("/access", response_model=AdminAccessResponse)
async def admin_access(
    request: Request,
    db: DatabaseSession,
    auth: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AdminAccessResponse:
    return AdminAccessResponse(is_owner=await _is_owner(request, db, auth))


@router.get("/users/{telegram_id}", response_model=AdminUserResponse)
async def find_user(
    telegram_id: int,
    db: DatabaseSession,
    _auth: Annotated[AuthenticatedUser, Depends(_require_owner)],
) -> AdminUserResponse:
    account = await db.scalar(
        select(TelegramAccount).where(TelegramAccount.telegram_id == telegram_id).limit(1)
    )
    if account is None:
        return AdminUserResponse(found=False, telegram_id=telegram_id)
    user = await db.get(User, account.user_id)
    row = (
        await db.execute(
            select(Subscription, Plan, VpnAccount)
            .join(Plan, Plan.id == Subscription.plan_id)
            .outerjoin(VpnAccount, VpnAccount.subscription_id == Subscription.id)
            .where(Subscription.user_id == account.user_id)
            .order_by(desc(Subscription.expires_at))
            .limit(1)
        )
    ).first()
    subscription = None
    linked = False
    if row is not None:
        current, plan, vpn_account = row
        subscription = AdminSubscriptionSummary(
            plan_name=plan.name,
            status=current.status.value,
            expires_at=current.expires_at,
        )
        linked = vpn_account is not None
    return AdminUserResponse(
        found=True,
        telegram_id=telegram_id,
        display_name=user.display_name if user else account.first_name,
        username=account.username,
        remnawave_linked=linked,
        subscription=subscription,
    )


@router.post("/grants", response_model=AdminGrantResponse)
async def grant_access(
    payload: AdminGrantRequest,
    request: Request,
    db: DatabaseSession,
    auth: Annotated[AuthenticatedUser, Depends(_require_owner_csrf)],
    request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> AdminGrantResponse:
    provider = request.app.state.vpn_provider
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VPN provider unavailable",
        )

    now = datetime.now(UTC)
    starts_at = datetime.combine(payload.starts_on or now.date(), time.min, tzinfo=UTC)
    if starts_at.date() > now.date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="future start is not supported",
        )
    starts_at = now

    # Serializes grants for one Telegram account without adding a schema-only lock table.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": payload.telegram_id})
    plan = await db.scalar(select(Plan).where(Plan.id == payload.plan_id, Plan.active.is_(True)))
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plan not found")

    account = await db.scalar(
        select(TelegramAccount).where(TelegramAccount.telegram_id == payload.telegram_id).limit(1)
    )
    if account is None:
        user = User(
            display_name=f"Пользователь {payload.telegram_id}",
            locale="ru",
            referral_code=secrets.token_urlsafe(9)[:12],
        )
        db.add(user)
        await db.flush()
        account = TelegramAccount(
            user_id=user.id,
            telegram_id=payload.telegram_id,
            first_name="Пользователь",
        )
        db.add_all([account, Wallet(user_id=user.id, currency="RUB")])
        await db.flush()
    else:
        user = await db.get(User, account.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="linked user is missing",
            )

    row = (
        await db.execute(
            select(Subscription, VpnAccount)
            .outerjoin(VpnAccount, VpnAccount.subscription_id == Subscription.id)
            .where(
                Subscription.user_id == user.id,
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.SUSPENDED]),
            )
            .order_by(desc(Subscription.expires_at))
            .limit(1)
            .with_for_update()
        )
    ).first()
    vpn_account: VpnAccount | None = None
    if row is None:
        subscription = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status=SubscriptionStatus.PENDING,
            starts_at=starts_at,
            expires_at=starts_at + timedelta(days=plan.duration_days),
            traffic_limit_bytes=plan.traffic_limit_bytes,
            device_limit=payload.device_limit or plan.device_limit,
            server_groups=list(plan.server_groups),
            public_token_digest=hashlib.sha256(secrets.token_bytes(32)).digest(),
        )
        db.add(subscription)
        await db.flush()
    else:
        subscription, vpn_account = row
        subscription.plan_id = plan.id
        subscription.starts_at = min(subscription.starts_at, starts_at)
        subscription.expires_at = max(subscription.expires_at, starts_at) + timedelta(
            days=plan.duration_days
        )
        subscription.traffic_limit_bytes = plan.traffic_limit_bytes
        subscription.device_limit = payload.device_limit or plan.device_limit
        subscription.server_groups = list(plan.server_groups)

    desired = ProvisionUser(
        external_key=f"admin:{subscription.id}",
        username=f"vpn_{subscription.id.hex}",
        expire_at=subscription.expires_at,
        traffic_limit_bytes=subscription.traffic_limit_bytes,
        device_limit=subscription.device_limit,
        server_group_ids=(
            request.app.state.settings.default_squad_uuids or subscription.server_groups
        ),
        telegram_id=payload.telegram_id,
    )
    try:
        if vpn_account is None:
            remote = await provider.create_user(
                desired,
                idempotency_key=f"admin-grant:{subscription.id}",
            )
        else:
            remote = await provider.update_user(vpn_account.provider_user_id, desired)
        if remote.status is not AccountStatus.ACTIVE:
            await provider.enable_user(remote.provider_id)
    except ProviderError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Remnawave rejected the grant",
        ) from error

    desired_state: dict[str, Any] = {
        "source": "owner_admin",
        "expires_at": subscription.expires_at.isoformat(),
        "traffic_limit_bytes": subscription.traffic_limit_bytes,
        "device_limit": subscription.device_limit,
        "server_groups": list(subscription.server_groups),
    }
    observed_state = {
        "status": AccountStatus.ACTIVE.value,
        "subscription_url": remote.subscription_url,
        "provider": dict(remote.raw),
    }
    if vpn_account is None:
        vpn_account = VpnAccount(
            subscription_id=subscription.id,
            provider="remnawave",
            provider_user_id=remote.provider_id,
            provider_username=remote.username,
            desired_state=desired_state,
            observed_state=observed_state,
            reconciled_at=now,
        )
        db.add(vpn_account)
    else:
        vpn_account.provider_user_id = remote.provider_id
        vpn_account.provider_username = remote.username
        vpn_account.desired_state = desired_state
        vpn_account.observed_state = observed_state
        vpn_account.reconciled_at = now
    subscription.status = SubscriptionStatus.ACTIVE
    db.add(
        AuditLog(
            actor_type="owner",
            actor_id=auth.user.id,
            action="admin.subscription.granted",
            resource_type="subscription",
            resource_id=subscription.id,
            outcome="success",
            request_id=request_id,
            before=None,
            after={
                "telegram_id": payload.telegram_id,
                "plan_id": str(plan.id),
                "expires_at": subscription.expires_at.isoformat(),
                "comment": payload.comment,
            },
        )
    )
    await db.commit()
    return AdminGrantResponse(
        telegram_id=payload.telegram_id,
        display_name=user.display_name,
        status=subscription.status.value,
        expires_at=subscription.expires_at,
        subscription_url=remote.subscription_url,
    )
