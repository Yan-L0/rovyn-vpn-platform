from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl


class TelegramAuthError(ValueError):
    """Telegram initData is missing, invalid or outside the freshness window."""


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_id: int
    first_name: str
    last_name: str | None
    username: str | None
    language_code: str | None
    photo_url: str | None
    auth_date: int
    query_id: str | None


class TelegramInitDataVerifier:
    def __init__(self, bot_token: str, max_age_seconds: int = 300, future_skew_seconds: int = 30):
        if not bot_token:
            raise ValueError("bot token is required")
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self._bot_token = bot_token
        self._max_age_seconds = max_age_seconds
        self._future_skew_seconds = future_skew_seconds

    def verify(self, init_data: str, now: int | None = None) -> TelegramIdentity:
        if not init_data:
            raise TelegramAuthError("initData is required")

        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise TelegramAuthError("duplicate initData fields are not allowed")

        data = dict(pairs)
        supplied_hash = data.pop("hash", None)
        if not supplied_hash or len(supplied_hash) != 64:
            raise TelegramAuthError("initData hash is missing or malformed")

        # Telegram's bot-token HMAC covers every received field except `hash`.
        # Newer clients also send an Ed25519 `signature` field, so it must stay
        # in the data-check-string even though we do not validate it separately.
        check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
        secret_key = hmac.new(b"WebAppData", self._bot_token.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, supplied_hash.lower()):
            raise TelegramAuthError("initData signature is invalid")

        try:
            auth_date = int(data["auth_date"])
        except (KeyError, TypeError, ValueError) as error:
            raise TelegramAuthError("auth_date is missing or invalid") from error

        current_time = int(time.time()) if now is None else now
        age = current_time - auth_date
        if age > self._max_age_seconds:
            raise TelegramAuthError("initData has expired")
        if age < -self._future_skew_seconds:
            raise TelegramAuthError("auth_date is too far in the future")

        user = self._decode_user(data.get("user"))
        telegram_id = user.get("id")
        if isinstance(telegram_id, bool) or not isinstance(telegram_id, int) or telegram_id <= 0:
            raise TelegramAuthError("Telegram user id is invalid")

        first_name = user.get("first_name")
        if not isinstance(first_name, str) or not first_name.strip():
            raise TelegramAuthError("Telegram first_name is invalid")

        return TelegramIdentity(
            telegram_id=telegram_id,
            first_name=first_name.strip(),
            last_name=self._optional_string(user, "last_name"),
            username=self._optional_string(user, "username"),
            language_code=self._optional_string(user, "language_code"),
            photo_url=self._optional_string(user, "photo_url"),
            auth_date=auth_date,
            query_id=data.get("query_id"),
        )

    @staticmethod
    def _decode_user(raw_user: str | None) -> Mapping[str, Any]:
        if raw_user is None:
            raise TelegramAuthError("user is missing")
        try:
            value = json.loads(raw_user)
        except (TypeError, json.JSONDecodeError) as error:
            raise TelegramAuthError("user JSON is invalid") from error
        if not isinstance(value, dict):
            raise TelegramAuthError("user must be an object")
        return value

    @staticmethod
    def _optional_string(value: Mapping[str, Any], key: str) -> str | None:
        item = value.get(key)
        if item is None:
            return None
        if not isinstance(item, str):
            raise TelegramAuthError(f"Telegram {key} is invalid")
        return item
