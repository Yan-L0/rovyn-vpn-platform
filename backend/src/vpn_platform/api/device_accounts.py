from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from vpn_platform.api.dependencies import AuthenticatedUser, DatabaseSession, require_csrf
from vpn_platform.db.models import Subscription, SubscriptionStatus, VpnAccount, VpnDevice
from vpn_platform.domain.vpn_provider import ProviderError, ProvisionUser, VPNProvider
from vpn_platform.services.device_accounts import device_rows, sync_device_access

router = APIRouter(prefix="/api/v2/device-accounts", tags=["device-accounts"])
MutatingUser = Annotated[AuthenticatedUser, Depends(require_csrf)]


class CreateDeviceRequest(BaseModel):
    request_id: uuid.UUID
    name: str = Field(min_length=1, max_length=128)


def provider_for(request: Request) -> VPNProvider:
    if not request.app.state.settings.REMNAWAVE_DEVICE_SESSION_REVOCATION_ENABLED:
        raise HTTPException(503, "Personal device revocation is not configured")
    if request.app.state.vpn_provider is None:
        raise HTTPException(503, "VPN service unavailable")
    return cast(VPNProvider, request.app.state.vpn_provider)


async def locked_subscription(db: DatabaseSession, user_id: uuid.UUID) -> Subscription:
    subscription = await db.scalar(
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.SUSPENDED]),
        )
        .order_by(Subscription.expires_at.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if subscription is None:
        raise HTTPException(404, "Subscription not found")
    if subscription.status != SubscriptionStatus.ACTIVE or subscription.expires_at <= datetime.now(
        UTC
    ):
        raise HTTPException(409, "Subscription is not active")
    if subscription.traffic_limit_bytes != 0:
        raise HTTPException(409, "Personal devices currently require an unlimited plan")
    return subscription


@router.post("/migrate", status_code=204)
async def migrate(request: Request, db: DatabaseSession, auth: MutatingUser) -> Response:
    provider = provider_for(request)
    if not request.app.state.settings.REMNAWAVE_DEVICE_EXTERNAL_SQUAD_UUID:
        raise HTTPException(503, "Personal device policy is not configured")
    subscription = await locked_subscription(db, auth.user.id)
    parent = await db.scalar(
        select(VpnAccount).where(VpnAccount.subscription_id == subscription.id)
    )
    if parent is None:
        raise HTTPException(409, "Subscription is not provisioned")
    # Commit the terminal legacy-access decision before the remote operation;
    # retries and the reconciler can safely finish a failed remote disable.
    subscription.isolated_devices = True
    await db.commit()
    subscription = await locked_subscription(db, auth.user.id)
    try:
        await sync_device_access(db, provider, subscription)
    except ProviderError as error:
        raise HTTPException(
            502, "Transition pending; retry to finish disabling the old link"
        ) from error
    await db.commit()
    return Response(status_code=204)


@router.post("")
async def create_device(
    payload: CreateDeviceRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
    auth: MutatingUser,
) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    provider = provider_for(request)
    subscription = await locked_subscription(db, auth.user.id)
    if not subscription.isolated_devices:
        raise HTTPException(409, "Switch to personal device links first")
    external_squad = request.app.state.settings.REMNAWAVE_DEVICE_EXTERNAL_SQUAD_UUID
    if not external_squad:
        raise HTTPException(503, "Personal device policy is not configured")
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Device name cannot be blank")
    existing = await db.get(VpnDevice, payload.request_id)
    if existing is not None and existing.subscription_id != subscription.id:
        raise HTTPException(409, "Request identifier unavailable")
    if existing is not None and existing.status in {"revoking", "revoked"}:
        raise HTTPException(410, "This device has been revoked; add a new device explicitly")
    if existing is None:
        rows = await device_rows(db, subscription)
        if sum(d.status != "revoked" for d in rows) >= subscription.device_limit:
            raise HTTPException(409, "Device limit reached")
        existing = VpnDevice(
            id=payload.request_id, subscription_id=subscription.id, name=name, status="pending"
        )
        db.add(existing)
        # Durable reservation prevents retries from leaking extra remote accounts.
        await db.commit()
        subscription = await locked_subscription(db, auth.user.id)
        await db.refresh(existing)
        if existing.status in {"revoking", "revoked"}:
            raise HTTPException(410, "Device revoked")
    try:
        parent = await db.scalar(
            select(VpnAccount).where(VpnAccount.subscription_id == subscription.id)
        )
        if parent:
            await provider.disable_user(parent.provider_user_id)
            await provider.drop_connections(parent.provider_user_id)
        if existing.provider_user_id:
            remote = await provider.get_subscription_info(existing.provider_user_id)
        else:
            remote = await provider.create_user(
                ProvisionUser(
                    external_key=f"device:{existing.id}",
                    username=f"dev_{existing.id.hex}",
                    expire_at=subscription.expires_at,
                    traffic_limit_bytes=0,
                    device_limit=1,
                    external_squad_id=external_squad,
                    server_group_ids=request.app.state.settings.default_squad_uuids
                    or subscription.server_groups,
                ),
                idempotency_key=f"device:{existing.id}",
            )
            existing.provider_user_id = remote.provider_id
        existing.status = "active"
        await db.commit()
    except ProviderError as error:
        raise HTTPException(502, "Device provisioning pending; retry the same request") from error
    if not remote.subscription_url:
        raise HTTPException(502, "Device link unavailable")
    return {
        "id": str(existing.id),
        "name": existing.name,
        "subscription_url": remote.subscription_url,
    }


@router.post("/{device_id}/link")
async def device_link(
    device_id: uuid.UUID,
    request: Request,
    response: Response,
    db: DatabaseSession,
    auth: MutatingUser,
) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    subscription = await locked_subscription(db, auth.user.id)
    device = await db.get(VpnDevice, device_id)
    if device is None or device.subscription_id != subscription.id:
        raise HTTPException(404, "Device not found")
    if device.status != "active" or not device.provider_user_id:
        raise HTTPException(410, "Device is not active")
    remote = await provider_for(request).get_subscription_info(device.provider_user_id)
    if not remote.subscription_url:
        raise HTTPException(502, "Device link unavailable")
    return {"subscription_url": remote.subscription_url}


@router.delete("/{device_id}", status_code=204)
async def revoke(
    device_id: uuid.UUID, request: Request, db: DatabaseSession, auth: MutatingUser
) -> Response:
    provider = provider_for(request)
    subscription = await locked_subscription(db, auth.user.id)
    device = await db.get(VpnDevice, device_id)
    if device is None or device.subscription_id != subscription.id:
        raise HTTPException(404, "Device not found")
    device.status = "revoking"
    device.revoked_at = datetime.now(UTC)
    await db.commit()
    await locked_subscription(db, auth.user.id)
    try:
        if not device.provider_user_id:
            # Resolve a possibly completed remote creation after a lost response.
            remote = await provider.create_user(
                ProvisionUser(
                    external_key=f"device:{device.id}",
                    username=f"dev_{device.id.hex}",
                    expire_at=subscription.expires_at,
                    traffic_limit_bytes=0,
                    device_limit=1,
                    external_squad_id=request.app.state.settings.REMNAWAVE_DEVICE_EXTERNAL_SQUAD_UUID,
                    server_group_ids=request.app.state.settings.default_squad_uuids
                    or subscription.server_groups,
                ),
                idempotency_key=f"device:{device.id}",
            )
            device.provider_user_id = remote.provider_id
            await db.commit()
            await locked_subscription(db, auth.user.id)
        await provider.disable_user(device.provider_user_id)
        await provider.drop_connections(device.provider_user_id)
        device.status = "revoked"
        await db.commit()
    except ProviderError as error:
        raise HTTPException(
            502, "Revocation pending; access will not be reissued, retry to finish"
        ) from error
    return Response(status_code=204)
