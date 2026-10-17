import json
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from vpn_platform.services.email_auth import EmailAuthService, normalize_email


def test_email_normalization_and_validation():
    assert normalize_email(" User@Example.com ") == "user@example.com"
    with pytest.raises(HTTPException):
        normalize_email("invalid")


@pytest.mark.asyncio
async def test_email_challenge_checks_code_and_returns_linked_identity():
    redis = SimpleNamespace(
        get=AsyncMock(), delete=AsyncMock(), ttl=AsyncMock(return_value=300), setex=AsyncMock()
    )
    service = EmailAuthService(
        redis, secret=secrets.token_hex(16), api_key="", sender="test", ttl=600
    )
    user_id = uuid4()
    payload = {
        "email": "user@example.com",
        "digest": service._digest("user@example.com", "123456"),
        "attempts": 0,
        "user_id": str(user_id),
    }
    redis.get.return_value = json.dumps(payload)
    with pytest.raises(HTTPException):
        await service.consume("test-challenge", "000000")
    assert json.loads(redis.setex.call_args.args[2])["attempts"] == 1
    redis.delete.assert_not_called()
    assert await service.consume("test-challenge", "123456") == ("user@example.com", user_id)
    redis.delete.assert_awaited_once_with("email-auth:challenge:test-challenge")


@pytest.mark.asyncio
async def test_expired_email_code_cannot_authenticate():
    redis = SimpleNamespace(get=AsyncMock(return_value=None))
    service = EmailAuthService(
        redis, secret=secrets.token_hex(16), api_key="", sender="test", ttl=600
    )
    with pytest.raises(HTTPException) as error:
        await service.consume("expired-challenge", "123456")
    assert error.value.status_code == 400
