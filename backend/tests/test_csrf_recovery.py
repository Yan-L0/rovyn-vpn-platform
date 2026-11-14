from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request, Response

from vpn_platform.api.routes import recover_csrf
from vpn_platform.services.identity import IdentityService


def context(origin="https://bot.yanlo.biz", header="refresh", cookie="test-session"):
    app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(
        MINIAPP_PUBLIC_URL="https://bot.yanlo.biz/",
    )))
    request = Request({
        "type": "http", "app": app,
        "headers": [(b"origin", origin.encode()), (b"x-csrf-token", header.encode()),
                    (b"cookie", f"vpn_session={cookie}".encode())],
    })
    return request


@pytest.mark.asyncio
async def test_recovery_is_stable_and_bound_to_session():
    auth = SimpleNamespace(session=SimpleNamespace(csrf_digest=b"old"))
    db = SimpleNamespace(commit=AsyncMock())
    response = Response()
    first = await recover_csrf(context(), response, auth, db)
    second = await recover_csrf(context(), response, auth, db)
    assert first == second
    assert IdentityService.verify_csrf(auth.session, first["csrf_token"])
    assert response.headers["Cache-Control"] == "no-store"
    other = await recover_csrf(context(cookie="other-session"), response, auth, db)
    assert first != other
    assert not IdentityService.verify_csrf(auth.session, first["csrf_token"])


@pytest.mark.asyncio
@pytest.mark.parametrize("origin,header", [
    ("https://attacker.example", "refresh"),
    ("", "refresh"),
    ("https://bot.yanlo.biz", ""),
])
async def test_recovery_rejects_foreign_origins_and_simple_requests(origin, header):
    db = SimpleNamespace(commit=AsyncMock())
    auth = SimpleNamespace(session=SimpleNamespace(csrf_digest=b"unchanged"))
    with pytest.raises(HTTPException) as error:
        await recover_csrf(context(origin, header), Response(), auth, db)
    assert error.value.status_code == 403
    assert auth.session.csrf_digest == b"unchanged"
    db.commit.assert_not_awaited()
