from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class ProviderName(StrEnum):
    REMNAWAVE = "remnawave"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_ENV: Environment = Environment.DEVELOPMENT
    APP_NAME: str = "VPN Platform"
    API_PUBLIC_URL: AnyHttpUrl = AnyHttpUrl("http://localhost:8080")
    MINIAPP_PUBLIC_URL: AnyHttpUrl = AnyHttpUrl("http://localhost:5173")

    DATABASE_URL: str = "postgresql+asyncpg://vpn:vpn@localhost:5432/vpn"
    REDIS_URL: str = "redis://localhost:6379/0"
    SESSION_SECRET: SecretStr = SecretStr("development-only-secret-change-me")

    TELEGRAM_BOT_TOKEN: SecretStr = SecretStr("")
    TELEGRAM_AUTH_MAX_AGE_SECONDS: Annotated[int, Field(ge=30, le=3600)] = 300
    TELEGRAM_AUTH_DEV_BYPASS: bool = False

    VPN_PROVIDER: ProviderName = ProviderName.REMNAWAVE
    REMNAWAVE_BASE_URL: str = ""
    REMNAWAVE_API_TOKEN: SecretStr = SecretStr("")
    REMNAWAVE_DEFAULT_SQUAD_UUIDS: str = ""

    # V2 intentionally supports one payment rail only. YooKassa is configured
    # server-side and every checkout explicitly requests payment_method_data=sbp.
    YOOKASSA_ENABLED: bool = False
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: SecretStr = SecretStr("")
    YOOKASSA_RETURN_URL: AnyHttpUrl | None = None
    YOOKASSA_WEBHOOK_PATH: str = "/api/v1/payments/yookassa/webhook"
    YOOKASSA_DESCRIPTION_PREFIX: str = "VPN Platform"

    HTTP_TIMEOUT_SECONDS: Annotated[float, Field(gt=0, le=60)] = 10
    LOG_LEVEL: str = "INFO"

    @property
    def is_production_like(self) -> bool:
        return self.APP_ENV in {Environment.STAGING, Environment.PRODUCTION}

    @property
    def default_squad_uuids(self) -> tuple[str, ...]:
        return tuple(
            item.strip() for item in self.REMNAWAVE_DEFAULT_SQUAD_UUIDS.split(",") if item.strip()
        )

    @model_validator(mode="after")
    def enforce_fail_closed_configuration(self) -> Settings:
        if self.TELEGRAM_AUTH_DEV_BYPASS and self.APP_ENV not in {
            Environment.DEVELOPMENT,
            Environment.TEST,
        }:
            raise ValueError("TELEGRAM_AUTH_DEV_BYPASS is forbidden outside development/test")

        if self.is_production_like:
            if len(self.SESSION_SECRET.get_secret_value()) < 32:
                raise ValueError("SESSION_SECRET must contain at least 32 characters")
            if not self.TELEGRAM_BOT_TOKEN.get_secret_value():
                raise ValueError("TELEGRAM_BOT_TOKEN is required")
            if self.VPN_PROVIDER is ProviderName.REMNAWAVE:
                if not self.REMNAWAVE_BASE_URL.startswith("https://"):
                    raise ValueError("REMNAWAVE_BASE_URL must use HTTPS")
                if not self.REMNAWAVE_API_TOKEN.get_secret_value():
                    raise ValueError("REMNAWAVE_API_TOKEN is required")
            if self.YOOKASSA_ENABLED:
                if not self.YOOKASSA_SHOP_ID:
                    raise ValueError("YOOKASSA_SHOP_ID is required when YooKassa is enabled")
                if not self.YOOKASSA_SECRET_KEY.get_secret_value():
                    raise ValueError("YOOKASSA_SECRET_KEY is required when YooKassa is enabled")
                if self.YOOKASSA_RETURN_URL is None:
                    raise ValueError("YOOKASSA_RETURN_URL is required when YooKassa is enabled")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
