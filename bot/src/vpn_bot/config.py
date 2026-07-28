from enum import Enum

from pydantic import AnyHttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    APP_ENV: Environment = Environment.DEVELOPMENT
    APP_NAME: str = "VPN Platform"
    TELEGRAM_BOT_TOKEN: SecretStr = SecretStr("")
    MINIAPP_PUBLIC_URL: AnyHttpUrl = "http://localhost:5173"

    @model_validator(mode="after")
    def validate_token(self) -> "Settings":
        if not self.TELEGRAM_BOT_TOKEN.get_secret_value():
            raise ValueError("TELEGRAM_BOT_TOKEN is required to start the bot")
        if self.APP_ENV in {Environment.STAGING, Environment.PRODUCTION} and not str(
            self.MINIAPP_PUBLIC_URL
        ).startswith("https://"):
            raise ValueError("MINIAPP_PUBLIC_URL must use HTTPS")
        return self
