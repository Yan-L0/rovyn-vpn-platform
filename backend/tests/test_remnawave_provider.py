from datetime import UTC, date, datetime

import httpx
import pytest

from vpn_platform.domain.vpn_provider import (
    AccountStatus,
    ProviderCapabilityUnavailable,
    ProvisionUser,
)
from vpn_platform.providers.remnawave import RemnawaveProvider


def provision_user() -> ProvisionUser:
    return ProvisionUser(
        external_key="subscription-001",
        username="user_001",
        expire_at=datetime(2027, 1, 1, tzinfo=UTC),
        traffic_limit_bytes=100 * 1024**3,
        device_limit=5,
        server_group_ids=["11111111-1111-4111-8111-111111111111"],
        telegram_id=42,
    )


def user_response(description: str = "business-key:subscription-001;request:req-1") -> dict:
    return {
        "response": {
            "uuid": "22222222-2222-4222-8222-222222222222",
            "username": "user_001",
            "status": "ACTIVE",
            "expireAt": "2027-01-01T00:00:00.000Z",
            "subscriptionUrl": "https://subscription.example/s/opaque",
            "description": description,
        }
    }


@pytest.mark.asyncio
async def test_create_user_maps_contract_and_authorizes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/users"
        assert request.headers["authorization"] == "Bearer api-token"
        payload = __import__("json").loads(request.content)
        assert payload["trafficLimitBytes"] == 100 * 1024**3
        assert payload["hwidDeviceLimit"] == 5
        assert payload["description"] == "business-key:subscription-001;request:req-1"
        return httpx.Response(201, json=user_response(), request=request)

    provider = RemnawaveProvider("https://panel.example", "api-token")
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="https://panel.example",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer api-token"},
    )
    try:
        result = await provider.create_user(provision_user(), "req-1")
    finally:
        await provider.close()

    assert result.status is AccountStatus.ACTIVE
    assert result.provider_id == "22222222-2222-4222-8222-222222222222"
    assert result.subscription_url == "https://subscription.example/s/opaque"


@pytest.mark.asyncio
async def test_create_user_resolves_matching_conflict_idempotently() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return httpx.Response(409, json={"message": "duplicate"}, request=request)
        return httpx.Response(200, json=user_response(), request=request)

    provider = RemnawaveProvider("https://panel.example", "api-token")
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="https://panel.example",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await provider.create_user(provision_user(), "req-1")
    finally:
        await provider.close()

    assert result.username == "user_001"
    assert calls == ["POST /api/users", "GET /api/users/by-username/user_001"]


@pytest.mark.asyncio
async def test_online_connections_fails_explicitly() -> None:
    provider = RemnawaveProvider("https://panel.example", "api-token")
    try:
        with pytest.raises(ProviderCapabilityUnavailable):
            await provider.get_online_connections("user-id")
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_health_checks_authenticated_api_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/users"
        assert dict(request.url.params) == {"start": "0", "size": "1"}
        assert request.headers["authorization"] == "Bearer api-token"
        return httpx.Response(
            200,
            json={"response": {"total": 0, "users": []}},
            request=request,
        )

    provider = RemnawaveProvider("https://panel.example", "api-token")
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="https://panel.example",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer api-token"},
    )
    try:
        result = await provider.health()
    finally:
        await provider.close()

    assert result.healthy is True
    assert result.detail == "ok"


@pytest.mark.asyncio
async def test_usage_history_maps_daily_remnawave_series() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == (
            "/api/bandwidth-stats/users/22222222-2222-4222-8222-222222222222"
        )
        assert dict(request.url.params) == {
            "start": "2026-07-29",
            "end": "2026-07-31",
            "topNodesLimit": "1",
        }
        return httpx.Response(
            200,
            json={
                "response": {
                    "categories": ["2026-07-29", "2026-07-30", "2026-07-31"],
                    "sparklineData": [1024, 2048, 4096],
                    "series": [],
                    "topNodes": [],
                }
            },
            request=request,
        )

    provider = RemnawaveProvider("https://panel.example", "api-token")
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="https://panel.example",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await provider.get_usage_history(
            "22222222-2222-4222-8222-222222222222",
            date(2026, 7, 29),
            date(2026, 7, 31),
        )
    finally:
        await provider.close()

    assert [(point.usage_date, point.used_bytes) for point in result] == [
        (date(2026, 7, 29), 1024),
        (date(2026, 7, 30), 2048),
        (date(2026, 7, 31), 4096),
    ]
