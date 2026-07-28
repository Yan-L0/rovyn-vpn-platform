from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from vpn_platform.db.models import User, WebSession
from vpn_platform.services.identity import IdentityService


@dataclass(frozen=True)
class AuthenticatedUser:
    session: WebSession
    user: User


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as db:
        yield db


DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
SessionCookie = Annotated[str, Cookie(alias="vpn_session")]


async def get_current_user(
    db: DatabaseSession,
    vpn_session: SessionCookie = "",
) -> AuthenticatedUser:
    authenticated = await IdentityService().authenticate_session(db, vpn_session)
    if authenticated is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    session, user = authenticated
    await db.commit()
    return AuthenticatedUser(session=session, user=user)
