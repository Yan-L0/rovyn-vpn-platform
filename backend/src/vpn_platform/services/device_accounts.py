from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vpn_platform.db.models import Subscription, SubscriptionStatus, VpnAccount, VpnDevice
from vpn_platform.domain.vpn_provider import ProviderError, UsagePoint, VPNProvider


async def device_rows(db: AsyncSession, subscription: Subscription) -> list[VpnDevice]:
    return list(
        (
            await db.scalars(
                select(VpnDevice)
                .where(VpnDevice.subscription_id == subscription.id)
                .order_by(VpnDevice.created_at)
            )
        ).all()
    )


async def sync_device_access(
    db: AsyncSession, provider: VPNProvider, subscription: Subscription
) -> None:
    """Retry terminal revocation and propagate business expiry to every device."""
    if not subscription.isolated_devices:
        return
    parents = (
        await db.scalars(
            select(VpnAccount)
            .join(Subscription, VpnAccount.subscription_id == Subscription.id)
            .where(Subscription.user_id == subscription.user_id)
        )
    ).all()
    for parent in parents:
        # Legacy credentials must never revive after renewal or an admin grant.
        await provider.disable_user(parent.provider_user_id)
        await provider.drop_connections(parent.provider_user_id)
    occupied = 0
    for device in await device_rows(db, subscription):
        if device.status == "revoked":
            continue
        if device.status in {"active", "pending", "limited"}:
            occupied += 1
        if not device.provider_user_id:
            continue
        allowed = (
            device.status in {"active", "limited"}
            and occupied <= subscription.device_limit
            and subscription.status == SubscriptionStatus.ACTIVE
            and subscription.expires_at > datetime.now(UTC)
            and subscription.traffic_limit_bytes == 0
        )
        if not allowed:
            await provider.disable_user(device.provider_user_id)
            await provider.drop_connections(device.provider_user_id)
            if device.status == "revoking":
                device.status = "revoked"
            elif device.status in {"active", "limited"}:
                device.status = "limited"
            continue
        remote = await provider.get_subscription_info(device.provider_user_id)
        if int(remote.expire_at.timestamp()) != int(subscription.expires_at.timestamp()):
            await provider.set_expiry(device.provider_user_id, subscription.expires_at)
        await provider.enable_user(device.provider_user_id)
        device.status = "active"


async def subscription_history(
    db: AsyncSession,
    provider: VPNProvider,
    subscription: Subscription,
    parent: VpnAccount,
    start: date,
    end: date,
) -> list[UsagePoint]:
    ids = [parent.provider_user_id]
    if subscription.isolated_devices:
        # Include prior subscription periods after a renewal, without overwriting
        # the user's daily totals with one device's samples.
        ids = list(
            (
                await db.scalars(
                    select(VpnAccount.provider_user_id)
                    .join(Subscription, VpnAccount.subscription_id == Subscription.id)
                    .where(Subscription.user_id == subscription.user_id)
                )
            ).all()
        )
        device_ids = list(
            (
                await db.scalars(
                    select(VpnDevice.provider_user_id)
                    .join(Subscription, VpnDevice.subscription_id == Subscription.id)
                    .where(
                        Subscription.user_id == subscription.user_id,
                        VpnDevice.provider_user_id.is_not(None),
                    )
                )
            ).all()
        )
        ids += [value for value in device_ids if value is not None]
    totals: dict[date, int] = defaultdict(int)
    for provider_id in set(ids):
        for point in await provider.get_usage_history(provider_id, start, end):
            totals[point.usage_date] += point.used_bytes
    return [UsagePoint(usage_date=day, used_bytes=value) for day, value in sorted(totals.items())]


async def device_reconcile_loop(
    factory: async_sessionmaker[AsyncSession], provider: VPNProvider
) -> None:
    while True:
        try:
            async with factory() as db:
                ids = list(
                    (
                        await db.scalars(
                            select(Subscription.id).where(Subscription.isolated_devices.is_(True))
                        )
                    ).all()
                )
            for subscription_id in ids:
                async with factory() as db:
                    subscription = await db.get(Subscription, subscription_id, with_for_update=True)
                    if subscription is None:
                        continue
                    try:
                        await sync_device_access(db, provider, subscription)
                        await db.commit()
                    except ProviderError:
                        await db.rollback()
                        logging.getLogger(__name__).warning("Device access reconciliation pending")
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger(__name__).exception("Device reconciliation failed")
        await asyncio.sleep(60)
