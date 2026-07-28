# ruff: noqa: S106 -- explicit non-secret values exercise secret validation

import pytest
from pydantic import ValidationError

from vpn_platform.core.config import Settings


def test_development_allows_explicit_telegram_bypass() -> None:
    settings = Settings(APP_ENV="development", TELEGRAM_AUTH_DEV_BYPASS=True)
    assert settings.TELEGRAM_AUTH_DEV_BYPASS is True


def test_production_rejects_telegram_bypass() -> None:
    with pytest.raises(ValidationError, match="DEV_BYPASS"):
        Settings(
            APP_ENV="production",
            TELEGRAM_AUTH_DEV_BYPASS=True,
            TELEGRAM_BOT_TOKEN="token",
            SESSION_SECRET="x" * 32,
            REMNAWAVE_BASE_URL="https://panel.example",
            REMNAWAVE_API_TOKEN="api-token",
        )


def test_production_rejects_non_https_provider() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            APP_ENV="production",
            TELEGRAM_BOT_TOKEN="token",
            SESSION_SECRET="x" * 32,
            REMNAWAVE_BASE_URL="http://panel.example",
            REMNAWAVE_API_TOKEN="api-token",
        )


def test_production_yookassa_requires_complete_configuration() -> None:
    with pytest.raises(ValidationError, match="YOOKASSA_SHOP_ID"):
        Settings(
            APP_ENV="production",
            SESSION_SECRET="x" * 32,
            TELEGRAM_BOT_TOKEN="token",
            REMNAWAVE_BASE_URL="https://panel.example",
            REMNAWAVE_API_TOKEN="api-token",
            YOOKASSA_ENABLED=True,
        )


def test_production_accepts_sbp_only_yookassa_configuration() -> None:
    settings = Settings(
        APP_ENV="production",
        SESSION_SECRET="x" * 32,
        TELEGRAM_BOT_TOKEN="token",
        REMNAWAVE_BASE_URL="https://panel.example",
        REMNAWAVE_API_TOKEN="api-token",
        YOOKASSA_ENABLED=True,
        YOOKASSA_SHOP_ID="shop-id",
        YOOKASSA_SECRET_KEY="secret",
        YOOKASSA_RETURN_URL="https://app.example/cabinet",
    )
    assert settings.YOOKASSA_ENABLED is True
