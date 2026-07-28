from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from vpn_platform.domain.payment_provider import (
    CreatePayment,
    PaymentProviderError,
    PaymentResponseError,
    PaymentState,
    ProviderPayment,
)


class YooKassaProvider:
    """Minimal YooKassa adapter for one-stage SBP payments."""

    def __init__(
        self,
        shop_id: str,
        secret_key: str,
        timeout_seconds: float = 10,
        base_url: str = "https://api.yookassa.ru",
    ):
        if not shop_id or not secret_key:
            raise ValueError("YooKassa shop ID and secret key are required")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            auth=httpx.BasicAuth(shop_id, secret_key),
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def create_payment(
        self,
        payment: CreatePayment,
        idempotency_key: str,
    ) -> ProviderPayment:
        self._validate_idempotency_key(idempotency_key)
        if payment.currency.upper() != "RUB":
            raise ValueError("YooKassa SBP payments must use RUB")
        self._validate_return_url(payment.return_url)

        payload: dict[str, Any] = {
            "amount": {
                "value": self._format_amount(payment.amount_minor),
                "currency": "RUB",
            },
            "payment_method_data": {"type": "sbp"},
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": payment.return_url,
            },
            "description": payment.description,
        }
        if payment.metadata:
            payload["metadata"] = dict(payment.metadata)

        body = await self._request(
            "POST",
            "/v3/payments",
            headers={"Idempotence-Key": idempotency_key},
            json=payload,
        )
        result = self.parse_payment(body)
        if result.confirmation_url is None and result.status is PaymentState.PENDING:
            raise PaymentResponseError(
                "YooKassa pending payment has no redirect confirmation URL"
            )
        return result

    async def get_payment(self, provider_payment_id: str) -> ProviderPayment:
        if not provider_payment_id or not provider_payment_id.strip():
            raise ValueError("provider_payment_id is required")
        body = await self._request(
            "GET",
            f"/v3/payments/{quote(provider_payment_id, safe='')}",
        )
        return self.parse_payment(body)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        try:
            response = await self._client.request(
                method,
                path,
                headers=headers,
                json=json,
            )
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise PaymentProviderError(
                f"YooKassa request timed out: {method} {path}"
            ) from error
        except httpx.HTTPStatusError as error:
            raise PaymentProviderError(
                f"YooKassa rejected {method} {path} with HTTP "
                f"{error.response.status_code}"
            ) from error
        except httpx.HTTPError as error:
            raise PaymentProviderError(
                f"YooKassa request failed: {method} {path}"
            ) from error

        try:
            body = response.json()
        except ValueError as error:
            raise PaymentResponseError("YooKassa returned non-JSON data") from error
        if not isinstance(body, dict):
            raise PaymentResponseError("YooKassa returned an invalid payment document")
        return body

    @classmethod
    def parse_payment(cls, value: Mapping[str, Any]) -> ProviderPayment:
        provider_id = value.get("id")
        raw_status = value.get("status")
        paid = value.get("paid")
        amount = value.get("amount")

        if not isinstance(provider_id, str) or not provider_id:
            raise PaymentResponseError("YooKassa payment has no ID")
        if not isinstance(raw_status, str):
            raise PaymentResponseError("YooKassa payment has an unknown status")
        try:
            status = PaymentState(raw_status)
        except ValueError as error:
            raise PaymentResponseError("YooKassa payment has an unknown status") from error
        if not isinstance(paid, bool):
            raise PaymentResponseError("YooKassa payment has an invalid paid flag")
        if not isinstance(amount, dict):
            raise PaymentResponseError("YooKassa payment has no amount")

        amount_minor = cls._parse_amount(amount.get("value"))
        currency = amount.get("currency")
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
            raise PaymentResponseError("YooKassa payment has an invalid currency")

        confirmation_url = cls._parse_confirmation(value.get("confirmation"))
        created_at = cls._parse_created_at(value.get("created_at"))
        metadata = cls._parse_metadata(value.get("metadata"))

        return ProviderPayment(
            provider_id=provider_id,
            status=status,
            paid=paid,
            amount_minor=amount_minor,
            currency=currency.upper(),
            confirmation_url=confirmation_url,
            created_at=created_at,
            metadata=metadata,
            raw=value,
        )

    @staticmethod
    def _parse_amount(value: Any) -> int:
        if not isinstance(value, str):
            raise PaymentResponseError("YooKassa payment has an invalid amount")
        try:
            decimal = Decimal(value)
        except InvalidOperation as error:
            raise PaymentResponseError("YooKassa payment has an invalid amount") from error
        minor = decimal * 100
        if not decimal.is_finite() or decimal < 0 or minor != minor.to_integral_value():
            raise PaymentResponseError("YooKassa payment has an invalid amount")
        return int(minor)

    @staticmethod
    def _parse_confirmation(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, dict) or value.get("type") != "redirect":
            raise PaymentResponseError("YooKassa payment has an invalid confirmation")
        url = value.get("confirmation_url")
        if not isinstance(url, str) or not url:
            raise PaymentResponseError(
                "YooKassa redirect confirmation has no confirmation URL"
            )
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise PaymentResponseError(
                "YooKassa redirect confirmation URL is invalid"
            )
        return url

    @staticmethod
    def _parse_created_at(value: Any) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise PaymentResponseError("YooKassa payment has an invalid creation time")
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PaymentResponseError(
                "YooKassa payment has an invalid creation time"
            ) from error

    @staticmethod
    def _parse_metadata(value: Any) -> Mapping[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict) or any(
            not isinstance(key, str) or not isinstance(item, str)
            for key, item in value.items()
        ):
            raise PaymentResponseError("YooKassa payment has invalid metadata")
        return value

    @staticmethod
    def _format_amount(amount_minor: int) -> str:
        return f"{amount_minor // 100}.{amount_minor % 100:02d}"

    @staticmethod
    def _validate_idempotency_key(value: str) -> None:
        if not value or not value.strip() or len(value) > 64:
            raise ValueError("YooKassa idempotency key must contain 1 to 64 characters")

    @staticmethod
    def _validate_return_url(value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("return_url must be an absolute HTTP(S) URL")
