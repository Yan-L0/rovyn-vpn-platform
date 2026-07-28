from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class PaymentProviderError(RuntimeError):
    """A sanitized failure reported by a payment adapter."""


class PaymentResponseError(PaymentProviderError):
    """The provider returned a document that violates its contract."""


class PaymentState(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CANCELED = "canceled"


@dataclass(frozen=True)
class CreatePayment:
    amount_minor: int
    currency: str
    description: str
    return_url: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.amount_minor, bool) or self.amount_minor <= 0:
            raise ValueError("amount_minor must be a positive integer")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.metadata.items()
        ):
            raise ValueError("payment metadata keys and values must be strings")


@dataclass(frozen=True)
class ProviderPayment:
    provider_id: str
    status: PaymentState
    paid: bool
    amount_minor: int
    currency: str
    confirmation_url: str | None
    created_at: datetime | None
    metadata: Mapping[str, str]
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class VerifiedPayment:
    """Provider data after the adapter has authenticated/re-fetched the payment."""

    provider: str
    provider_payment_id: str
    order_id: uuid.UUID
    amount_minor: int
    currency: str
    raw: Mapping[str, Any]

    @classmethod
    def from_provider_payment(
        cls,
        payment: ProviderPayment,
        *,
        provider: str,
        order_id: uuid.UUID,
    ) -> VerifiedPayment:
        if payment.status is not PaymentState.SUCCEEDED or not payment.paid:
            raise ValueError("provider payment has not succeeded")
        return cls(
            provider=provider,
            provider_payment_id=payment.provider_id,
            order_id=order_id,
            amount_minor=payment.amount_minor,
            currency=payment.currency,
            raw=payment.raw,
        )


class PaymentProvider(Protocol):
    """Small boundary implemented by the YooKassa/SBP adapter."""

    async def create_payment(
        self,
        payment: CreatePayment,
        idempotency_key: str,
    ) -> ProviderPayment: ...

    async def get_payment(self, provider_payment_id: str) -> ProviderPayment: ...
