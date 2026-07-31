from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Protocol


class ProviderError(RuntimeError):
    pass


class ProviderCapabilityUnavailable(ProviderError):
    pass


class AccountStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ProvisionUser:
    external_key: str
    username: str
    expire_at: datetime
    traffic_limit_bytes: int
    device_limit: int
    server_group_ids: Sequence[str]
    telegram_id: int | None = None


@dataclass(frozen=True)
class ProviderUser:
    provider_id: str
    username: str
    status: AccountStatus
    expire_at: datetime
    subscription_url: str | None
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class Usage:
    used_bytes: int
    traffic_limit_bytes: int
    upload_bytes: int | None = None
    download_bytes: int | None = None


@dataclass(frozen=True)
class UsagePoint:
    usage_date: date
    used_bytes: int


@dataclass(frozen=True)
class Device:
    hardware_id: str
    platform: str | None
    model: str | None
    last_seen_at: datetime | None
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class ProviderHealth:
    healthy: bool
    latency_ms: float | None
    detail: str


class VPNProvider(Protocol):
    async def create_user(self, user: ProvisionUser, idempotency_key: str) -> ProviderUser: ...
    async def update_user(self, provider_id: str, user: ProvisionUser) -> ProviderUser: ...
    async def delete_user(self, provider_id: str) -> None: ...
    async def enable_user(self, provider_id: str) -> None: ...
    async def disable_user(self, provider_id: str) -> None: ...
    async def set_expiry(self, provider_id: str, expire_at: datetime) -> None: ...
    async def set_traffic_limit(self, provider_id: str, limit_bytes: int) -> None: ...
    async def reset_traffic(self, provider_id: str) -> None: ...
    async def set_device_limit(self, provider_id: str, device_limit: int) -> None: ...
    async def assign_server_groups(self, provider_id: str, group_ids: Sequence[str]) -> None: ...
    async def remove_server_groups(self, provider_id: str, group_ids: Sequence[str]) -> None: ...
    async def get_usage(self, provider_id: str) -> Usage: ...
    async def get_usage_history(
        self,
        provider_id: str,
        start: date,
        end: date,
    ) -> Sequence[UsagePoint]: ...
    async def get_online_connections(self, provider_id: str) -> int: ...
    async def get_devices(self, provider_id: str) -> Sequence[Device]: ...
    async def revoke_device(self, provider_id: str, hardware_id: str) -> None: ...
    async def get_subscription_info(self, provider_id: str) -> ProviderUser: ...
    async def rotate_credentials(self, provider_id: str) -> ProviderUser: ...
    async def suspend(self, provider_id: str) -> None: ...
    async def restore(self, provider_id: str) -> None: ...
    async def health(self) -> ProviderHealth: ...
