from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TelegramAuthRequest(BaseModel):
    init_data: str = Field(default="", max_length=16_384)


class UserResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    locale: str | None


class AuthResponse(BaseModel):
    user: UserResponse
    csrf_token: str
    expires_at: datetime


class PlanResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    duration_days: int
    traffic_limit_bytes: int
    device_limit: int
    price_minor: int
    currency: str
    server_groups: list[str]


class SubscriptionResponse(BaseModel):
    status: str
    plan_name: str
    expires_at: datetime
    traffic_limit_bytes: int
    device_limit: int
    used_bytes: int | None = None


class MeResponse(BaseModel):
    user: UserResponse
    wallet_balance_minor: int
    wallet_currency: str
    referral_code: str
    subscription: SubscriptionResponse | None
