from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vpn_platform.db.models import (
    Order,
    OrderStatus,
    ServiceEvent,
    Subscription,
    SubscriptionStatus,
    TelegramAccount,
    VpnAccount,
)
from vpn_platform.domain.vpn_provider import (
    AccountStatus,
    ProviderError,
    ProvisionUser,
    VPNProvider,
)


@dataclass(frozen=True)
class ProvisioningResult:
    fulfilled: bool
    order: Order
    subscription: Subscription
    vpn_account: VpnAccount | None
    error: str | None = None


class ProvisioningService:
    """Processes durable provisioning events through the provider boundary."""

    def __init__(
        self,
        provider: VPNProvider,
        *,
        provider_name: str = "remnawave",
        default_server_group_ids: tuple[str, ...] = (),
    ):
        self._provider = provider
        self._provider_name = provider_name
        self._default_server_group_ids = default_server_group_ids

    async def provision_order(
        self,
        db: AsyncSession,
        *,
        order_id: uuid.UUID,
        now: datetime | None = None,
    ) -> ProvisioningResult:
        current_time = now or datetime.now(UTC)
        order = await db.get(Order, order_id, with_for_update=True)
        if order is None:
            raise ValueError("order does not exist")
        if order.status not in {OrderStatus.PAID, OrderStatus.FULFILLED}:
            raise ValueError(f"order {order.id} is not paid")

        event = await db.scalar(
            select(ServiceEvent)
            .where(ServiceEvent.idempotency_key == f"provision-order:{order.id}")
            .with_for_update()
        )
        if event is None:
            raise RuntimeError("paid order has no provisioning event")
        subscription_id = uuid.UUID(str(event.payload["subscription_id"]))
        subscription = await db.get(Subscription, subscription_id, with_for_update=True)
        if subscription is None:
            raise RuntimeError("provisioning event points to a missing subscription")

        account = await db.scalar(
            select(VpnAccount)
            .where(
                VpnAccount.subscription_id == subscription.id,
                VpnAccount.provider == self._provider_name,
            )
            .with_for_update()
        )
        if (
            order.status == OrderStatus.FULFILLED
            and subscription.status == SubscriptionStatus.ACTIVE
            and account is not None
        ):
            return ProvisioningResult(True, order, subscription, account)

        telegram_id = await db.scalar(
            select(TelegramAccount.telegram_id)
            .where(TelegramAccount.user_id == order.user_id)
            .limit(1)
        )
        desired = ProvisionUser(
            external_key=str(order.id),
            username=f"vpn_{subscription.id.hex}",
            expire_at=subscription.expires_at,
            traffic_limit_bytes=subscription.traffic_limit_bytes,
            device_limit=subscription.device_limit,
            server_group_ids=self._default_server_group_ids or subscription.server_groups,
            telegram_id=telegram_id,
        )
        try:
            if account is None:
                remote = await self._provider.create_user(
                    desired,
                    idempotency_key=event.idempotency_key,
                )
            else:
                remote = await self._provider.update_user(account.provider_user_id, desired)
            if remote.status is not AccountStatus.ACTIVE:
                await self._provider.enable_user(remote.provider_id)
        except ProviderError as error:
            event.attempts += 1
            event.last_error = str(error)[:2000]
            event.available_at = current_time + self._retry_delay(event.attempts)
            await db.flush()
            return ProvisioningResult(
                False,
                order,
                subscription,
                account,
                error=str(error),
            )

        desired_state: dict[str, Any] = {
            "order_id": str(order.id),
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
        if account is None:
            account = VpnAccount(
                subscription_id=subscription.id,
                provider=self._provider_name,
                provider_user_id=remote.provider_id,
                provider_username=remote.username,
                desired_state=desired_state,
                observed_state=observed_state,
                reconciled_at=current_time,
            )
            db.add(account)
        else:
            account.provider_user_id = remote.provider_id
            account.provider_username = remote.username
            account.desired_state = desired_state
            account.observed_state = observed_state
            account.reconciled_at = current_time

        subscription.status = SubscriptionStatus.ACTIVE
        order.status = OrderStatus.FULFILLED
        event.processed_at = current_time
        event.last_error = None
        await db.flush()
        return ProvisioningResult(True, order, subscription, account)

    @staticmethod
    def _retry_delay(attempt: int) -> timedelta:
        seconds = min(15 * (2 ** max(0, attempt - 1)), 3600)
        return timedelta(seconds=seconds)
