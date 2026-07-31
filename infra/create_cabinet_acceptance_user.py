#!/usr/bin/env python3
"""Create a short-lived production acceptance user and verify cabinet APIs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select

from vpn_platform.core.config import get_settings
from vpn_platform.db.models import (
    Plan,
    Subscription,
    SubscriptionStatus,
    User,
    VpnAccount,
    Wallet,
)
from vpn_platform.db.session import create_engine, create_session_factory
from vpn_platform.domain.vpn_provider import ProvisionUser
from vpn_platform.providers.remnawave import RemnawaveProvider
from vpn_platform.services.identity import IdentityService

OUTPUT = Path("/tmp/nova-cabinet-acceptance.json")  # noqa: S108
DISPLAY_NAME = "NOVA Cabinet Acceptance"
logger = logging.getLogger(__name__)


async def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    session_factory = create_session_factory(engine)
    provider = RemnawaveProvider(
        settings.REMNAWAVE_BASE_URL,
        settings.REMNAWAVE_API_TOKEN.get_secret_value(),
        settings.HTTP_TIMEOUT_SECONDS,
    )
    remote_id: str | None = None
    database_committed = False
    try:
        async with session_factory() as db:
            existing = await db.scalar(select(User).where(User.display_name == DISPLAY_NAME))
            if existing is not None:
                raise RuntimeError("acceptance user already exists")
            plan = await db.scalar(
                select(Plan)
                .where(Plan.active.is_(True))
                .order_by(Plan.sort_order, Plan.price_minor)
                .limit(1)
            )
            if plan is None:
                raise RuntimeError("no active production plan exists")

            now = datetime.now(UTC)
            expires_at = now + timedelta(days=7)
            user_id = uuid.uuid4()
            subscription_id = uuid.uuid4()
            username = f"cabinet_test_{secrets.token_hex(5)}"
            server_groups = settings.default_squad_uuids or tuple(plan.server_groups)
            if not server_groups:
                raise RuntimeError("acceptance user has no Remnawave squads")

            remote = await provider.create_user(
                ProvisionUser(
                    external_key=f"cabinet-acceptance:{subscription_id}",
                    username=username,
                    expire_at=expires_at,
                    traffic_limit_bytes=5 * 1024**3,
                    device_limit=2,
                    server_group_ids=server_groups,
                ),
                idempotency_key=f"cabinet-acceptance:{subscription_id}",
            )
            remote_id = remote.provider_id
            public_token = secrets.token_urlsafe(32)
            user = User(
                id=user_id,
                display_name=DISPLAY_NAME,
                locale="ru",
                referral_code=secrets.token_urlsafe(9).replace("-", "")[:12],
            )
            subscription = Subscription(
                id=subscription_id,
                user_id=user_id,
                plan_id=plan.id,
                status=SubscriptionStatus.ACTIVE,
                starts_at=now,
                expires_at=expires_at,
                traffic_limit_bytes=5 * 1024**3,
                device_limit=2,
                server_groups=list(server_groups),
                public_token_digest=hashlib.sha256(public_token.encode()).digest(),
            )
            db.add(user)
            await db.flush()
            db.add_all(
                [
                    Wallet(user_id=user_id, currency="RUB"),
                    subscription,
                ]
            )
            await db.flush()
            db.add(
                VpnAccount(
                    subscription_id=subscription_id,
                    provider="remnawave",
                    provider_user_id=remote.provider_id,
                    provider_username=remote.username,
                    desired_state={"acceptance": True},
                    observed_state={"status": remote.status.value},
                    reconciled_at=now,
                )
            )
            issued = await IdentityService().issue_session(
                db,
                user_id,
                user_agent="nova-production-acceptance",
                ip_address="127.0.0.1",
                ttl=timedelta(hours=2),
            )
            await db.commit()
            database_committed = True

        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8080",
            cookies={"vpn_session": issued.token},
            timeout=30,
        ) as client:
            checks: dict[str, int] = {}
            documents: dict[str, object] = {}
            for name, path in (
                ("me", "/api/v1/me"),
                ("access", "/api/v2/subscription/access"),
                ("traffic", "/api/v2/traffic/year"),
                ("devices", "/api/v2/devices"),
            ):
                response = await client.get(path)
                checks[name] = response.status_code
                response.raise_for_status()
                documents[name] = response.json()

        access = documents["access"]
        traffic = documents["traffic"]
        devices = documents["devices"]
        if (
            not isinstance(access, dict)
            or access.get("subscription_url") != remote.subscription_url
        ):
            raise RuntimeError("cabinet access URL does not match Remnawave")
        if not isinstance(traffic, dict) or len(traffic.get("months", [])) != 12:
            raise RuntimeError("cabinet traffic response does not contain 12 months")
        if not isinstance(devices, list):
            raise RuntimeError("cabinet devices response is invalid")

        output_document = json.dumps(
            {
                "user_id": str(user_id),
                "provider_user_id": remote.provider_id,
                "username": remote.username,
                "expires_at": expires_at.isoformat(),
                "subscription_url": remote.subscription_url,
                "checks": checks,
                "traffic_source": traffic.get("source_status"),
                "device_count": len(devices),
            }
        )
        await asyncio.to_thread(OUTPUT.write_text, output_document)
        await asyncio.to_thread(os.chmod, OUTPUT, 0o600)
        print(f"acceptance_user={remote.username}")
        print(f"expires_at={expires_at.isoformat()}")
        print("api_checks=" + ",".join(f"{key}:{value}" for key, value in checks.items()))
        print(f"traffic_source={traffic.get('source_status')}")
        print(f"device_count={len(devices)}")
        return 0
    except Exception:
        if remote_id is not None and not database_committed:
            try:
                await provider.delete_user(remote_id)
            except Exception:
                logger.exception("Failed to remove rejected Remnawave acceptance user")
        raise
    finally:
        await provider.close()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
