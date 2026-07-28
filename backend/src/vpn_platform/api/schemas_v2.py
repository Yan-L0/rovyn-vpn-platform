from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SubscriptionUsageResponse(BaseModel):
    used_bytes: int = Field(ge=0)
    traffic_limit_bytes: int = Field(ge=0)
    upload_bytes: int | None = Field(default=None, ge=0)
    download_bytes: int | None = Field(default=None, ge=0)


class SubscriptionAccessResponse(BaseModel):
    subscription_id: uuid.UUID
    status: str
    provider_status: str
    plan_name: str
    subscription_url: str
    starts_at: datetime
    expires_at: datetime
    device_limit: int = Field(ge=0)
    usage: SubscriptionUsageResponse


class DeviceResponse(BaseModel):
    hardware_id: str
    platform: str | None
    model: str | None
    last_seen_at: datetime | None


class ReferralSummaryResponse(BaseModel):
    referral_code: str
    referral_url: str
    total_referrals: int = Field(ge=0)
    total_earned_minor: int = Field(ge=0)
    currency: str


class CreateSupportTicketRequest(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1, max_length=5_000)

    @field_validator("subject", "body")
    @classmethod
    def strip_and_reject_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class SupportTicketResponse(BaseModel):
    id: uuid.UUID
    status: str
    subject: str
    body: str
    created_at: datetime
