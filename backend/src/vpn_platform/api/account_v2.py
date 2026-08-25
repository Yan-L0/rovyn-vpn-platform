from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from sqlalchemy import delete, func, select

from vpn_platform.api.dependencies import (
    AuthenticatedUser,
    DatabaseSession,
    get_current_user,
    require_csrf,
)
from vpn_platform.api.schemas_v2 import (
    CreateSupportTicketRequest,
    DeviceResponse,
    MonthlyUsageResponse,
    ReferralSummaryResponse,
    SubscriptionAccessResponse,
    SubscriptionUsageResponse,
    SupportTicketResponse,
    YearlyUsageResponse,
)
from vpn_platform.db.models import (
    Plan,
    Referral,
    ReferralReward,
    Subscription,
    SubscriptionStatus,
    SupportTicket,
    VpnAccount,
    VpnUsageDaily,
)
from vpn_platform.domain.vpn_provider import ProviderError, VPNProvider
from vpn_platform.providers.remnawave import RemnawaveNotFound
from vpn_platform.services.usage_sync import store_usage_points

router = APIRouter(prefix="/api/v2", tags=["account-v2"])
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
MutatingUser = Annotated[AuthenticatedUser, Depends(require_csrf)]
HardwareId = Annotated[str, Path(min_length=1, max_length=512)]


def _provider(request: Request) -> VPNProvider:
    provider = request.app.state.vpn_provider
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VPN service is temporarily unavailable",
        )
    return cast(VPNProvider, provider)


async def _vpn_account(
    db: DatabaseSession,
    user_id: uuid.UUID,
) -> tuple[Subscription, VpnAccount] | None:
    row = (
        await db.execute(
            select(Subscription, VpnAccount)
            .join(VpnAccount, VpnAccount.subscription_id == Subscription.id)
            .where(
                Subscription.user_id == user_id,
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.SUSPENDED]),
            )
            .order_by(Subscription.expires_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return row[0], row[1]


async def _expire_local_subscription(db: DatabaseSession, subscription: Subscription) -> None:
    """Keep the cabinet truthful when an account was removed in Remnawave."""
    subscription.status = SubscriptionStatus.EXPIRED
    await db.execute(delete(VpnUsageDaily).where(VpnUsageDaily.user_id == subscription.user_id))
    await db.commit()


@router.get("/subscription/access", response_model=SubscriptionAccessResponse)
async def subscription_access(
    request: Request,
    response: Response,
    db: DatabaseSession,
    auth: CurrentUser,
) -> SubscriptionAccessResponse:
    row = (
        await db.execute(
            select(Subscription, Plan, VpnAccount)
            .join(Plan, Plan.id == Subscription.plan_id)
            .join(VpnAccount, VpnAccount.subscription_id == Subscription.id)
            .where(
                Subscription.user_id == auth.user.id,
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.SUSPENDED]),
            )
            .order_by(Subscription.expires_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VPN subscription not found",
        )

    subscription, plan, account = row
    provider = _provider(request)
    try:
        provider_user = await provider.get_subscription_info(account.provider_user_id)
        usage = await provider.get_usage(account.provider_user_id)
    except RemnawaveNotFound as error:
        await _expire_local_subscription(db, subscription)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VPN subscription not found",
        ) from error
    except ProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="VPN service did not return subscription data",
        ) from error
    if not provider_user.subscription_url:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VPN subscription is not provisioned yet",
        )

    response.headers["Cache-Control"] = "no-store"
    return SubscriptionAccessResponse(
        subscription_id=subscription.id,
        status=subscription.status.value,
        provider_status=provider_user.status.value,
        plan_name=plan.name,
        subscription_url=provider_user.subscription_url,
        starts_at=subscription.starts_at,
        expires_at=provider_user.expire_at,
        device_limit=subscription.device_limit,
        usage=SubscriptionUsageResponse(
            used_bytes=usage.used_bytes,
            traffic_limit_bytes=usage.traffic_limit_bytes,
            upload_bytes=usage.upload_bytes,
            download_bytes=usage.download_bytes,
        ),
    )


@router.get("/devices", response_model=list[DeviceResponse])
async def devices(
    request: Request,
    response: Response,
    db: DatabaseSession,
    auth: CurrentUser,
) -> list[DeviceResponse]:
    response.headers["Cache-Control"] = "no-store"
    row = await _vpn_account(db, auth.user.id)
    if row is None:
        return []
    _, account = row
    try:
        items = await _provider(request).get_devices(account.provider_user_id)
    except RemnawaveNotFound as error:
        await _expire_local_subscription(db, row[0])
        return []
    except ProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="VPN service did not return device data",
        ) from error
    return [
        DeviceResponse(
            hardware_id=item.hardware_id,
            platform=item.platform,
            model=item.model,
            last_seen_at=item.last_seen_at,
        )
        for item in items
    ]


@router.get("/traffic/year", response_model=YearlyUsageResponse)
async def yearly_traffic(
    request: Request,
    response: Response,
    db: DatabaseSession,
    auth: CurrentUser,
    year: Annotated[int | None, Query(ge=2020, le=2200)] = None,
) -> YearlyUsageResponse:
    now = datetime.now(UTC)
    selected_year = year or now.year
    row = await _vpn_account(db, auth.user.id)
    if row is None:
        response.headers["Cache-Control"] = "no-store"
        return YearlyUsageResponse(
            year=selected_year,
            current_month=now.month if selected_year == now.year else 12,
            current_month_used_bytes=0,
            updated_at=None,
            source_status="stored",
            months=[
                MonthlyUsageResponse(month=index + 1, used_bytes=0, has_data=False)
                for index in range(12)
            ],
        )
    subscription, account = row

    source_status = "stored"
    if selected_year == now.year:
        try:
            points = await _provider(request).get_usage_history(
                account.provider_user_id,
                now.date() - timedelta(days=13),
                now.date(),
            )
            await store_usage_points(db, auth.user.id, points)
            await db.commit()
            source_status = "fresh"
        except RemnawaveNotFound:
            await _expire_local_subscription(db, subscription)
            response.headers["Cache-Control"] = "no-store"
            return YearlyUsageResponse(
                year=selected_year,
                current_month=now.month,
                current_month_used_bytes=0,
                updated_at=None,
                source_status="stored",
                months=[
                    MonthlyUsageResponse(month=index + 1, used_bytes=0, has_data=False)
                    for index in range(12)
                ],
            )
        except ProviderError:
            source_status = "stale"

    start = date(selected_year, 1, 1)
    end = date(selected_year, 12, 31)
    rows = (
        await db.scalars(
            select(VpnUsageDaily).where(
                VpnUsageDaily.user_id == auth.user.id,
                VpnUsageDaily.usage_date >= start,
                VpnUsageDaily.usage_date <= end,
            )
        )
    ).all()
    totals = [0] * 12
    has_data = [False] * 12
    updated_at = None
    for item in rows:
        index = item.usage_date.month - 1
        totals[index] += item.used_bytes
        has_data[index] = True
        if updated_at is None or item.sampled_at > updated_at:
            updated_at = item.sampled_at

    current_month = now.month if selected_year == now.year else 12
    response.headers["Cache-Control"] = "no-store"
    return YearlyUsageResponse(
        year=selected_year,
        current_month=current_month,
        current_month_used_bytes=totals[current_month - 1],
        updated_at=updated_at,
        source_status=source_status,
        months=[
            MonthlyUsageResponse(month=index + 1, used_bytes=value, has_data=has_data[index])
            for index, value in enumerate(totals)
        ],
    )


@router.delete("/devices/{hardware_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    hardware_id: HardwareId,
    request: Request,
    db: DatabaseSession,
    auth: MutatingUser,
) -> Response:
    row = await _vpn_account(db, auth.user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="device not found")
    _, account = row
    try:
        await _provider(request).revoke_device(account.provider_user_id, hardware_id)
    except ProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="VPN service did not revoke the device",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/referrals/summary", response_model=ReferralSummaryResponse)
async def referral_summary(
    request: Request,
    db: DatabaseSession,
    auth: CurrentUser,
) -> ReferralSummaryResponse:
    total_referrals = int(
        await db.scalar(
            select(func.count(Referral.id)).where(Referral.referrer_user_id == auth.user.id)
        )
        or 0
    )
    total_earned = int(
        await db.scalar(
            select(func.coalesce(func.sum(ReferralReward.amount_minor), 0))
            .join(Referral, Referral.id == ReferralReward.referral_id)
            .where(Referral.referrer_user_id == auth.user.id)
        )
        or 0
    )
    base_url = str(request.app.state.settings.MINIAPP_PUBLIC_URL).rstrip("/")
    referral_url = f"{base_url}/?invite={quote(auth.user.referral_code, safe='')}"
    return ReferralSummaryResponse(
        referral_code=auth.user.referral_code,
        referral_url=referral_url,
        total_referrals=total_referrals,
        total_earned_minor=total_earned,
        currency="RUB",
    )


def _ticket_response(ticket: SupportTicket) -> SupportTicketResponse:
    return SupportTicketResponse(
        id=ticket.id,
        status=ticket.status,
        subject=ticket.subject,
        body=ticket.body,
        created_at=ticket.created_at,
    )


@router.get("/support/tickets", response_model=list[SupportTicketResponse])
async def support_tickets(
    db: DatabaseSession,
    auth: CurrentUser,
) -> list[SupportTicketResponse]:
    items = (
        await db.scalars(
            select(SupportTicket)
            .where(SupportTicket.user_id == auth.user.id)
            .order_by(SupportTicket.created_at.desc())
            .limit(100)
        )
    ).all()
    return [_ticket_response(item) for item in items]


@router.post(
    "/support/tickets",
    response_model=SupportTicketResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_support_ticket(
    payload: CreateSupportTicketRequest,
    db: DatabaseSession,
    auth: MutatingUser,
) -> SupportTicketResponse:
    ticket = SupportTicket(
        user_id=auth.user.id,
        status="open",
        subject=payload.subject,
        body=payload.body,
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return _ticket_response(ticket)
