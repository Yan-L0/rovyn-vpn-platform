import json

import httpx
import pytest

from vpn_platform.domain.payment_provider import (
    CreatePayment,
    PaymentProviderError,
    PaymentResponseError,
    PaymentState,
)
from vpn_platform.providers.yookassa import YooKassaProvider


def create_request() -> CreatePayment:
    return CreatePayment(
        amount_minor=12_345,
        currency="RUB",
        description="Заказ 42",
        return_url="https://app.example/payments/return",
        metadata={"order_id": "42"},
    )


def payment_response(
    *,
    status: str = "pending",
    paid: bool = False,
    confirmation: object = ...,
) -> dict:
    result = {
        "id": "2f80bd65-000f-5000-9000-1b310f39a31d",
        "status": status,
        "paid": paid,
        "amount": {"value": "123.45", "currency": "RUB"},
        "created_at": "2026-07-28T10:20:30.123Z",
        "metadata": {"order_id": "42"},
    }
    if confirmation is ...:
        result["confirmation"] = {
            "type": "redirect",
            "confirmation_url": "https://yoomoney.ru/checkout/opaque",
        }
    elif confirmation is not None:
        result["confirmation"] = confirmation
    return result


async def provider_with(handler: httpx.AsyncBaseTransport) -> YooKassaProvider:
    provider = YooKassaProvider("shop-id", "secret-key")
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="https://api.yookassa.test",
        auth=httpx.BasicAuth("shop-id", "secret-key"),
        transport=handler,
    )
    return provider


@pytest.mark.asyncio
async def test_create_sbp_payment_uses_redirect_and_idempotence_header() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v3/payments"
        assert request.headers["idempotence-key"] == "order-42-attempt-1"
        assert request.headers["authorization"].startswith("Basic ")
        payload = json.loads(request.content)
        assert payload == {
            "amount": {"value": "123.45", "currency": "RUB"},
            "payment_method_data": {"type": "sbp"},
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": "https://app.example/payments/return",
            },
            "description": "Заказ 42",
            "metadata": {"order_id": "42"},
        }
        return httpx.Response(200, json=payment_response(), request=request)

    provider = await provider_with(httpx.MockTransport(handler))
    try:
        result = await provider.create_payment(
            create_request(),
            "order-42-attempt-1",
        )
    finally:
        await provider.close()

    assert result.status is PaymentState.PENDING
    assert result.amount_minor == 12_345
    assert result.confirmation_url == "https://yoomoney.ru/checkout/opaque"


@pytest.mark.asyncio
async def test_fetch_payment_encodes_id_and_accepts_final_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.raw_path == b"/v3/payments/id%2Fwith%20spaces"
        return httpx.Response(
            200,
            json=payment_response(
                status="succeeded",
                paid=True,
                confirmation=None,
            ),
            request=request,
        )

    provider = await provider_with(httpx.MockTransport(handler))
    try:
        result = await provider.get_payment("id/with spaces")
    finally:
        await provider.close()

    assert result.status is PaymentState.SUCCEEDED
    assert result.paid is True
    assert result.confirmation_url is None


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"id": ""}, "no ID"),
        ({"status": "refunded"}, "unknown status"),
        ({"paid": "true"}, "paid flag"),
        ({"amount": {"value": "1.001", "currency": "RUB"}}, "amount"),
        ({"amount": {"value": "1.00", "currency": "R"}}, "currency"),
        ({"confirmation": {"type": "external"}}, "confirmation"),
        ({"created_at": "not-a-date"}, "creation time"),
        ({"metadata": {"order_id": 42}}, "metadata"),
    ],
)
def test_payment_parser_rejects_malformed_documents(
    patch: dict,
    message: str,
) -> None:
    value = payment_response()
    value.update(patch)

    with pytest.raises(PaymentResponseError, match=message):
        YooKassaProvider.parse_payment(value)


@pytest.mark.asyncio
async def test_create_rejects_pending_payment_without_redirect() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=payment_response(confirmation=None),
            request=request,
        )

    provider = await provider_with(httpx.MockTransport(handler))
    try:
        with pytest.raises(PaymentResponseError, match="redirect confirmation"):
            await provider.create_payment(create_request(), "idempotent-key")
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_http_errors_are_sanitized() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"description": "secret provider response"},
            request=request,
        )

    provider = await provider_with(httpx.MockTransport(handler))
    try:
        with pytest.raises(PaymentProviderError) as raised:
            await provider.get_payment("payment-id")
    finally:
        await provider.close()

    assert "HTTP 401" in str(raised.value)
    assert "secret provider response" not in str(raised.value)


@pytest.mark.parametrize("key", ["", " ", "x" * 65])
@pytest.mark.asyncio
async def test_create_validates_idempotency_key_before_network(key: str) -> None:
    provider = YooKassaProvider("shop-id", "secret-key")
    try:
        with pytest.raises(ValueError, match="idempotency key"):
            await provider.create_payment(create_request(), key)
    finally:
        await provider.close()


def test_create_request_validates_amount_and_metadata() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        CreatePayment(0, "RUB", "Order", "https://example.com")
    with pytest.raises(ValueError, match="metadata"):
        CreatePayment(
            100,
            "RUB",
            "Order",
            "https://example.com",
            {"order_id": 42},  # type: ignore[dict-item]
        )
