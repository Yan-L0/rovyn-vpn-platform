from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vpn_platform.db.models import AuditLog, TelegramAccount, User, Wallet, WebSession
from vpn_platform.security.telegram import TelegramIdentity


@dataclass(frozen=True)
class IssuedSession:
    token: str
    csrf_token: str
    expires_at: datetime


class IdentityService:
    async def get_or_create_telegram_user(
        self,
        db: AsyncSession,
        identity: TelegramIdentity,
        *,
        request_id: str | None,
        ip_address: str | None,
    ) -> User:
        # The transaction-scoped advisory lock prevents duplicate account creation
        # when Telegram launches the Mini App twice in parallel.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:telegram_id)"),
            {"telegram_id": identity.telegram_id},
        )
        account = await db.scalar(
            select(TelegramAccount).where(TelegramAccount.telegram_id == identity.telegram_id)
        )
        display_name = " ".join(
            item for item in (identity.first_name, identity.last_name) if item
        ).strip()
        now = datetime.now(UTC)
        user: User

        if account is None:
            user = User(
                display_name=display_name,
                locale=identity.language_code,
                referral_code=secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12],
            )
            db.add(user)
            await db.flush()
            account = TelegramAccount(
                user_id=user.id,
                telegram_id=identity.telegram_id,
                username=identity.username,
                first_name=identity.first_name,
                last_name=identity.last_name,
                photo_url=identity.photo_url,
                last_authenticated_at=now,
            )
            db.add_all([account, Wallet(user_id=user.id, currency="RUB")])
            action = "identity.telegram.created"
        else:
            existing_user = await db.get(User, account.user_id, with_for_update=True)
            if existing_user is None:
                raise RuntimeError("Telegram account points to a missing user")
            user = existing_user
            user.display_name = display_name
            user.locale = identity.language_code
            account.username = identity.username
            account.first_name = identity.first_name
            account.last_name = identity.last_name
            account.photo_url = identity.photo_url
            account.last_authenticated_at = now
            action = "identity.telegram.authenticated"

        db.add(
            AuditLog(
                actor_type="user",
                actor_id=user.id,
                action=action,
                resource_type="user",
                resource_id=user.id,
                outcome="success",
                ip_address=ip_address,
                request_id=request_id,
            )
        )
        return user

    async def issue_session(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        user_agent: str | None,
        ip_address: str | None,
        ttl: timedelta = timedelta(days=30),
    ) -> IssuedSession:
        token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + ttl
        user_agent_hash = self._digest(user_agent) if user_agent else None
        db.add(
            WebSession(
                user_id=user_id,
                token_digest=self._digest(token),
                csrf_digest=self._digest(csrf_token),
                user_agent_hash=user_agent_hash,
                ip_address=ip_address,
                expires_at=expires_at,
            )
        )
        return IssuedSession(token=token, csrf_token=csrf_token, expires_at=expires_at)

    async def authenticate_session(
        self,
        db: AsyncSession,
        token: str,
    ) -> tuple[WebSession, User] | None:
        if not token:
            return None
        now = datetime.now(UTC)
        session = await db.scalar(
            select(WebSession)
            .where(
                WebSession.token_digest == self._digest(token),
                WebSession.revoked_at.is_(None),
                WebSession.expires_at > now,
            )
            .with_for_update()
        )
        if session is None:
            return None
        user = await db.get(User, session.user_id)
        if user is None or user.status.value != "active":
            return None
        session.last_seen_at = now
        return session, user

    @staticmethod
    def verify_csrf(session: WebSession, csrf_token: str) -> bool:
        return secrets.compare_digest(session.csrf_digest, IdentityService._digest(csrf_token))

    @staticmethod
    def _digest(value: str) -> bytes:
        return hashlib.sha256(value.encode()).digest()
