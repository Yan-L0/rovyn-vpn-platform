from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vpn_platform.db.models import Subscription, SubscriptionStatus, VpnAccount, VpnUsageDaily
from vpn_platform.domain.vpn_provider import ProviderError, UsagePoint, VPNProvider

logger = logging.getLogger(__name__)


async def store_usage_points(
    db: AsyncSession,
    user_id: uuid.UUID,
    points: Sequence[UsagePoint],
) -> None:
    if not points:
        return
    statement = insert(VpnUsageDaily).values(
        [
            {
                "user_id": user_id,
                "usage_date": point.usage_date,
                "used_bytes": point.used_bytes,
            }
            for point in points
        ]
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[VpnUsageDaily.user_id, VpnUsageDaily.usage_date],
            set_={"used_bytes": statement.excluded.used_bytes, "sampled_at": func.now()},
        )
    )


async def sync_all_usage(
    session_factory: async_sessionmaker[AsyncSession],
    provider: VPNProvider,
    *,
    today: date | None = None,
) -> None:
    current_date = today or datetime.now(UTC).date()
    start = current_date - timedelta(days=13)
    async with session_factory() as db:
        accounts = (
            await db.execute(
                select(Subscription.user_id, VpnAccount.provider_user_id)
                .join(VpnAccount, VpnAccount.subscription_id == Subscription.id)
                .where(Subscription.status == SubscriptionStatus.ACTIVE)
            )
        ).all()
        for user_id, provider_user_id in accounts:
            try:
                points = await provider.get_usage_history(provider_user_id, start, current_date)
            except ProviderError:
                logger.warning(
                    "Remnawave usage sync failed for provider user",
                    extra={"provider_user_id": provider_user_id},
                    exc_info=True,
                )
                continue
            await store_usage_points(db, user_id, points)
        await db.commit()


async def usage_sync_loop(
    session_factory: async_sessionmaker[AsyncSession],
    provider: VPNProvider,
    interval_seconds: int,
) -> None:
    while True:
        try:
            await sync_all_usage(session_factory, provider)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected VPN usage synchronization failure")
        await asyncio.sleep(interval_seconds)
