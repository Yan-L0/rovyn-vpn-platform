from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import httpx

from vpn_platform.domain.vpn_provider import (
    AccountStatus,
    Device,
    ProviderCapabilityUnavailable,
    ProviderError,
    ProviderHealth,
    ProviderUser,
    ProvisionUser,
    Usage,
    UsagePoint,
)


class RemnawaveConflict(ProviderError):
    pass


class RemnawaveNotFound(ProviderError):
    """The local account no longer exists in Remnawave."""

    pass


class RemnawaveProvider:
    """Remnawave v2 API adapter based on the inspected v2.8.1 contracts."""

    def __init__(self, base_url: str, api_token: str, timeout_seconds: float = 10):
        if not base_url or not api_token:
            raise ValueError("Remnawave base URL and API token are required")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def create_user(self, user: ProvisionUser, idempotency_key: str) -> ProviderUser:
        payload = self._payload(user)
        payload["description"] = f"business-key:{user.external_key};request:{idempotency_key}"
        try:
            response = await self._request("POST", "/api/users", json=payload)
        except RemnawaveConflict:
            # Username is deterministic and unique in Remnawave. A conflict can
            # therefore be a safe retry only when the business key also matches.
            response = await self._request(
                "GET",
                f"/api/users/by-username/{quote(user.username, safe='')}",
            )
            description = response.get("description") if isinstance(response, dict) else None
            if (
                not isinstance(description, str)
                or f"business-key:{user.external_key}" not in description
            ):
                raise ProviderError(
                    "Remnawave username conflict belongs to another account"
                ) from None
        return self._map_user(response)

    async def update_user(self, provider_id: str, user: ProvisionUser) -> ProviderUser:
        payload = self._payload(user)
        payload["uuid"] = provider_id
        response = await self._request("PATCH", "/api/users", json=payload)
        return self._map_user(response)

    async def delete_user(self, provider_id: str) -> None:
        await self._request("DELETE", f"/api/users/{provider_id}")

    async def enable_user(self, provider_id: str) -> None:
        await self._request("POST", f"/api/users/{provider_id}/actions/enable")

    async def disable_user(self, provider_id: str) -> None:
        await self._request("POST", f"/api/users/{provider_id}/actions/disable")

    async def set_expiry(self, provider_id: str, expire_at: datetime) -> None:
        await self._patch(provider_id, {"expireAt": expire_at.isoformat()})

    async def set_traffic_limit(self, provider_id: str, limit_bytes: int) -> None:
        if limit_bytes < 0:
            raise ValueError("limit_bytes cannot be negative")
        await self._patch(provider_id, {"trafficLimitBytes": limit_bytes})

    async def reset_traffic(self, provider_id: str) -> None:
        await self._request("POST", f"/api/users/{provider_id}/actions/reset-traffic")

    async def set_device_limit(self, provider_id: str, device_limit: int) -> None:
        if device_limit < 0:
            raise ValueError("device_limit cannot be negative")
        await self._patch(provider_id, {"hwidDeviceLimit": device_limit})

    async def assign_server_groups(self, provider_id: str, group_ids: Sequence[str]) -> None:
        await self._patch(provider_id, {"activeInternalSquads": list(dict.fromkeys(group_ids))})

    async def remove_server_groups(self, provider_id: str, group_ids: Sequence[str]) -> None:
        user = await self._get_user(provider_id)
        current = user.get("activeInternalSquads", [])
        removed = set(group_ids)
        current_ids = [self._extract_uuid(item) for item in current]
        kept = [item for item in current_ids if item not in removed]
        await self.assign_server_groups(provider_id, kept)

    async def get_usage(self, provider_id: str) -> Usage:
        user = await self._get_user(provider_id)
        return Usage(
            used_bytes=self._integer(user.get("usedTrafficBytes")),
            traffic_limit_bytes=self._integer(user.get("trafficLimitBytes")),
        )

    async def get_usage_history(
        self,
        provider_id: str,
        start: date,
        end: date,
    ) -> Sequence[UsagePoint]:
        if end < start:
            raise ValueError("usage history end cannot be before start")
        response = await self._request(
            "GET",
            (
                f"/api/bandwidth-stats/users/{quote(provider_id, safe='')}"
                f"?start={start.isoformat()}&end={end.isoformat()}&topNodesLimit=1"
            ),
        )
        if not isinstance(response, dict):
            raise ProviderError("Remnawave returned an invalid usage history document")
        categories = response.get("categories")
        values = response.get("sparklineData")
        if not isinstance(categories, list) or not isinstance(values, list):
            raise ProviderError("Remnawave usage history is missing required series")
        if len(categories) != len(values):
            raise ProviderError("Remnawave usage history series lengths do not match")

        points: list[UsagePoint] = []
        for raw_date, raw_value in zip(categories, values, strict=True):
            if not isinstance(raw_date, str):
                raise ProviderError("Remnawave usage history contains an invalid date")
            try:
                usage_date = date.fromisoformat(raw_date)
            except ValueError as error:
                raise ProviderError("Remnawave usage history contains an invalid date") from error
            points.append(UsagePoint(usage_date=usage_date, used_bytes=self._integer(raw_value)))
        return points

    async def get_online_connections(self, provider_id: str) -> int:
        raise ProviderCapabilityUnavailable(
            "Remnawave v2.8.1 does not expose a stable per-user online connection count contract"
        )

    async def get_devices(self, provider_id: str) -> Sequence[Device]:
        response = await self._request("GET", f"/api/hwid/devices/{provider_id}")
        rows = response.get("devices", []) if isinstance(response, dict) else []
        return [self._map_device(row) for row in rows if isinstance(row, dict)]

    async def revoke_device(self, provider_id: str, hardware_id: str) -> None:
        await self._request(
            "POST",
            "/api/hwid/devices/delete",
            json={"userUuid": provider_id, "hwid": hardware_id},
        )

    async def get_subscription_info(self, provider_id: str) -> ProviderUser:
        return self._map_user(await self._get_user(provider_id))

    async def rotate_credentials(self, provider_id: str) -> ProviderUser:
        await self._request("POST", f"/api/users/{provider_id}/actions/revoke")
        return self._map_user(await self._get_user(provider_id))

    async def suspend(self, provider_id: str) -> None:
        await self.disable_user(provider_id)

    async def restore(self, provider_id: str) -> None:
        await self.enable_user(provider_id)

    async def health(self) -> ProviderHealth:
        started = time.perf_counter()
        try:
            # Remnawave serves the frontend document at /health on the public
            # panel origin. Use a small authenticated API request so readiness
            # also verifies that the configured token can reach the provider.
            await self._request("GET", "/api/users?start=0&size=1", unwrap=False)
        except ProviderError as error:
            return ProviderHealth(False, None, str(error))
        latency = (time.perf_counter() - started) * 1000
        return ProviderHealth(True, round(latency, 2), "ok")

    async def _patch(self, provider_id: str, fields: Mapping[str, Any]) -> None:
        payload = {"uuid": provider_id, **fields}
        await self._request("PATCH", "/api/users", json=payload)

    async def _get_user(self, provider_id: str) -> Mapping[str, Any]:
        response = await self._request("GET", f"/api/users/{provider_id}")
        if not isinstance(response, dict):
            raise ProviderError("Remnawave returned an invalid user document")
        return response

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        unwrap: bool = True,
    ) -> Any:
        try:
            response = await self._client.request(method, path, json=json)
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ProviderError(f"Remnawave request timed out: {method} {path}") from error
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                raise RemnawaveNotFound(
                    f"Remnawave resource was not found: {method} {path}"
                ) from error
            if error.response.status_code == 409:
                raise RemnawaveConflict(f"Remnawave conflict for {method} {path}") from error
            raise ProviderError(
                f"Remnawave rejected {method} {path} with HTTP {error.response.status_code}"
            ) from error
        except httpx.HTTPError as error:
            raise ProviderError(f"Remnawave request failed: {method} {path}") from error

        if response.status_code == 204 or not response.content:
            return {}
        try:
            body = response.json()
        except ValueError as error:
            raise ProviderError("Remnawave returned non-JSON data") from error
        if unwrap and isinstance(body, dict) and "response" in body:
            return body["response"]
        return body

    @staticmethod
    def _payload(user: ProvisionUser) -> dict[str, Any]:
        if user.traffic_limit_bytes < 0 or user.device_limit < 0:
            raise ValueError("traffic and device limits cannot be negative")
        payload: dict[str, Any] = {
            "username": user.username,
            "expireAt": user.expire_at.isoformat(),
            "trafficLimitBytes": user.traffic_limit_bytes,
            "trafficLimitStrategy": "NO_RESET",
            "hwidDeviceLimit": user.device_limit,
            "activeInternalSquads": list(user.server_group_ids),
        }
        if user.telegram_id is not None:
            payload["telegramId"] = user.telegram_id
        return payload

    @staticmethod
    def _map_user(value: Any) -> ProviderUser:
        if not isinstance(value, dict):
            raise ProviderError("Remnawave returned an invalid user document")
        provider_id = value.get("uuid")
        username = value.get("username")
        expire_at = value.get("expireAt")
        if not isinstance(provider_id, str) or not provider_id:
            raise ProviderError("Remnawave user document has no UUID")
        if not isinstance(username, str) or not username:
            raise ProviderError("Remnawave user document has no username")
        if not isinstance(expire_at, str) or not expire_at:
            raise ProviderError("Remnawave user document is missing required fields")
        try:
            parsed_expiry = datetime.fromisoformat(expire_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ProviderError("Remnawave returned an invalid expiry") from error
        status = AccountStatus.ACTIVE if value.get("status") == "ACTIVE" else AccountStatus.DISABLED
        subscription_url = value.get("subscriptionUrl")
        return ProviderUser(
            provider_id=provider_id,
            username=username,
            status=status,
            expire_at=parsed_expiry,
            subscription_url=subscription_url if isinstance(subscription_url, str) else None,
            raw=value,
        )

    @staticmethod
    def _map_device(value: Mapping[str, Any]) -> Device:
        raw_last_seen = value.get("updatedAt") or value.get("createdAt")
        last_seen = None
        if isinstance(raw_last_seen, str):
            try:
                last_seen = datetime.fromisoformat(raw_last_seen.replace("Z", "+00:00"))
            except ValueError:
                last_seen = None
        hardware_id = value.get("hwid")
        if not isinstance(hardware_id, str) or not hardware_id:
            raise ProviderError("Remnawave device has no HWID")
        return Device(
            hardware_id=hardware_id,
            platform=value.get("platform") if isinstance(value.get("platform"), str) else None,
            model=value.get("deviceModel") if isinstance(value.get("deviceModel"), str) else None,
            last_seen_at=last_seen,
            raw=value,
        )

    @staticmethod
    def _extract_uuid(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            squad_uuid = value.get("uuid")
            if isinstance(squad_uuid, str):
                return squad_uuid
        raise ProviderError("Remnawave squad entry has no UUID")

    @staticmethod
    def _integer(value: Any) -> int:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return max(0, value)
        return 0
