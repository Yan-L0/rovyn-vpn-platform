from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from vpn_platform.db.models import AuditLog, EmailAccount, User, Wallet

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Введите корректный email"
        )
    return email


class EmailAuthService:
    def __init__(self, redis: Redis, *, secret: str, api_key: str, sender: str, ttl: int) -> None:
        self.redis = redis
        self.secret = secret.encode()
        self.api_key = api_key
        self.sender = sender
        self.ttl = ttl

    def _digest(self, email: str, code: str) -> str:
        return hmac.new(self.secret, f"{email}:{code}".encode(), hashlib.sha256).hexdigest()

    async def request_code(self, email: str, *, ip: str, pending_user_id: uuid.UUID | None) -> str:
        if not self.api_key:
            raise HTTPException(status_code=503, detail="Вход по email временно недоступен")
        ip_key = f"email-auth:rate:ip:{ip}"
        email_key = f"email-auth:rate:email:{hashlib.sha256(email.encode()).hexdigest()}"
        ip_count = await self.redis.incr(ip_key)
        email_count = await self.redis.incr(email_key)
        if ip_count == 1:
            await self.redis.expire(ip_key, 900)
        if email_count == 1:
            await self.redis.expire(email_key, 900)
        if ip_count > 10 or email_count > 5:
            raise HTTPException(status_code=429, detail="Слишком много попыток. Попробуйте позже")

        code = f"{secrets.randbelow(1_000_000):06d}"
        challenge_id = secrets.token_urlsafe(32)
        payload = {
            "email": email,
            "digest": self._digest(email, code),
            "attempts": 0,
            "user_id": str(pending_user_id) if pending_user_id else None,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "from": self.sender,
                    "to": [email],
                    "subject": f"{code} — код входа в NOVA VPN",
                    "text": f"Код входа в NOVA VPN: {code}. Он действует 10 минут.",
                    "html": (
                        "<div style='font-family:Arial,sans-serif'><h2>NOVA VPN</h2>"
                        "<p>Код входа:</p>"
                        "<p style='font-size:32px;font-weight:700;letter-spacing:8px'>"
                        f"{code}</p><p>Код действует 10 минут. "
                        "Никому его не сообщайте.</p></div>"
                    ),
                },
            )
        if response.status_code >= 300:
            raise HTTPException(
                status_code=503, detail="Не удалось отправить код. Попробуйте позже"
            )
        await self.redis.setex(
            f"email-auth:challenge:{challenge_id}", self.ttl, json.dumps(payload)
        )
        return challenge_id

    async def consume(self, challenge_id: str, code: str) -> tuple[str, uuid.UUID | None]:
        key = f"email-auth:challenge:{challenge_id}"
        raw = await self.redis.get(key)
        if raw is None:
            raise HTTPException(status_code=400, detail="Код устарел. Запросите новый")
        data = json.loads(raw)
        if int(data["attempts"]) >= 5:
            await self.redis.delete(key)
            raise HTTPException(status_code=400, detail="Слишком много неверных попыток")
        if not hmac.compare_digest(data["digest"], self._digest(data["email"], code)):
            data["attempts"] = int(data["attempts"]) + 1
            remaining = await self.redis.ttl(key)
            await self.redis.setex(key, max(1, remaining), json.dumps(data))
            raise HTTPException(status_code=400, detail="Неверный код")
        await self.redis.delete(key)
        return data["email"], uuid.UUID(data["user_id"]) if data.get("user_id") else None

    async def get_or_create_user(
        self,
        db: AsyncSession,
        email: str,
        pending_user_id: uuid.UUID | None,
        *,
        ip: str,
        request_id: str | None,
    ) -> User:
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:email))"), {"email": email})
        account = await db.scalar(select(EmailAccount).where(EmailAccount.email == email))
        now = datetime.now(UTC)
        if account is not None:
            if pending_user_id is not None and account.user_id != pending_user_id:
                raise HTTPException(
                    status_code=409,
                    detail="Этот email уже привязан к другому аккаунту",
                )
            user = await db.get(User, account.user_id)
            if user is None:
                raise RuntimeError("Email account points to a missing user")
            account.last_authenticated_at = now
            action = "identity.email.authenticated"
        else:
            user = await db.get(User, pending_user_id) if pending_user_id else None
            if user is None:
                user = User(
                    display_name=email.split("@", 1)[0],
                    locale="ru",
                    referral_code=secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12],
                )
                db.add(user)
                await db.flush()
                db.add(Wallet(user_id=user.id, currency="RUB"))
            db.add(EmailAccount(user_id=user.id, email=email, last_authenticated_at=now))
            action = "identity.email.linked"
        db.add(
            AuditLog(
                actor_type="user",
                actor_id=user.id,
                action=action,
                resource_type="user",
                resource_id=user.id,
                outcome="success",
                ip_address=ip,
                request_id=request_id,
            )
        )
        return user
