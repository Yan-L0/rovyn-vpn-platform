#!/usr/bin/env python3
"""Real database/API/Remnawave acceptance using an owned, short-lived subscription.

Run inside the API image with /opt/remnawave/monitor-bin mounted at /probe-bin.
Never logs sessions, subscription URLs, credentials, or returned documents.
"""
import asyncio
import hashlib
import json
import os
import secrets
import socket
import ssl
import struct
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI
from sqlalchemy import delete, select

from vpn_platform.api.account_v2 import router as account_router
from vpn_platform.api.admin import router as admin_router
from vpn_platform.api.device_accounts import router as device_router
from vpn_platform.api.routes import router as identity_router
from vpn_platform.api.orders import router as orders_router
from vpn_platform.core.config import get_settings
from vpn_platform.db.models import AuditLog, Order, OrderStatus, Plan, ServiceEvent, Subscription, SubscriptionStatus, SupportTicket, TelegramAccount, User, VpnAccount, VpnDevice
from vpn_platform.db.session import create_engine, create_session_factory
from vpn_platform.domain.vpn_provider import ProvisionUser
from vpn_platform.providers.remnawave import RemnawaveProvider
from vpn_platform.services.identity import IdentityService
from vpn_platform.services.provisioning import ProvisioningService
from vpn_platform.services.device_accounts import sync_device_access


def read(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise OSError("closed")
        data += chunk
    return data


def tunnel(port, host=b"www.gstatic.com"):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        sock.sendall(b"\x05\x01\x00")
        assert read(sock, 2) == b"\x05\x00"
        sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + struct.pack("!H", 443))
        reply = read(sock, 4)
        assert reply[1] == 0
        size = 4 if reply[3] == 1 else 16 if reply[3] == 4 else read(sock, 1)[0]
        read(sock, size + 2)
        return ssl.create_default_context().wrap_socket(sock, server_hostname=host.decode())
    except BaseException:
        sock.close()
        raise


def request204(sock):
    sock.sendall(b"GET /generate_204 HTTP/1.1\r\nHost: www.gstatic.com\r\nConnection: keep-alive\r\n\r\n")
    body = b""
    while b"\r\n\r\n" not in body and len(body) < 16384:
        chunk = sock.recv(4096)
        if not chunk:
            return False
        body += chunk
    return b" 204 " in body.split(b"\r\n", 1)[0]


def probe(port):
    try:
        with tunnel(port) as sock:
            return request204(sock)
    except (OSError, AssertionError):
        return False


def large_download(port, size):
    started = time.monotonic()
    count = 0
    status = False
    try:
        with tunnel(port,b"speed.cloudflare.com") as sock:
            sock.sendall(f"GET /__down?bytes={size} HTTP/1.1\r\nHost: speed.cloudflare.com\r\nConnection: close\r\n\r\n".encode())
            header = b""
            while b"\r\n\r\n" not in header:
                data = sock.recv(16384)
                if not data:
                    return False,count,0
                header += data
            head,body=header.split(b"\r\n\r\n",1)
            status=b" 200 " in head.split(b"\r\n",1)[0]
            count=len(body)
            while data:=sock.recv(16384):
                count+=len(data)
    except OSError:
        pass
    return status and count>=size, count, count*8/1_000_000/(time.monotonic()-started)


class DatagramProbe:
    def __init__(self, port):
        self.control = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.control.sendall(b"\x05\x01\x00")
        assert read(self.control, 2) == b"\x05\x00"
        self.control.sendall(b"\x05\x03\x00\x01" + b"\x00" * 6)
        assert read(self.control, 4) == b"\x05\x00\x00\x01"
        address = socket.inet_ntoa(read(self.control, 4))
        port = struct.unpack("!H", read(self.control, 2))[0]
        self.target = ("127.0.0.1" if address == "0.0.0.0" else address, port)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.settimeout(3)

    def probe(self):
        transaction = secrets.token_bytes(12)
        host = b"stun.cloudflare.com"
        payload = struct.pack("!HHI", 1, 0, 0x2112A442) + transaction
        packet = b"\x00\x00\x00\x03" + bytes([len(host)]) + host + struct.pack("!H", 3478) + payload
        # UDP/STUN is lossy. Retransmit the same transaction, never accept an
        # unrelated delayed reply, and still require revoked links to fail all tries.
        for attempt in range(3):
            try:
                self.udp.sendto(packet, self.target)
                response = self.udp.recv(4096)
                offset = 10 if response[3] == 1 else 22 if response[3] == 4 else 7 + response[4]
                if response[offset:offset + 2] == b"\x01\x01" and response[offset + 8:offset + 20] == transaction:
                    if attempt:
                        print(f"udp_probe_retransmissions={attempt}", flush=True)
                    return True
            except OSError:
                continue
        return False

    def close(self):
        self.control.close()
        self.udp.close()


async def main():
    tariff_test = os.environ.get("E2E_TARIFF_ACCEPTANCE") == "1"
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    factory = create_session_factory(engine)
    provider = RemnawaveProvider(settings.REMNAWAVE_BASE_URL, settings.REMNAWAVE_API_TOKEN.get_secret_value())
    app = FastAPI()
    app.include_router(account_router)
    app.include_router(device_router)
    app.include_router(admin_router)
    app.include_router(identity_router)
    app.include_router(orders_router)
    app.state.payment_provider = None
    # Only this in-process test app recognizes the disposable account as owner.
    test_telegram_id = 8_000_000_000_000 + secrets.randbelow(1_000_000_000)
    app.state.settings = settings.model_copy(update={"BOT_OWNER_TELEGRAM_IDS": str(test_telegram_id)})
    app.state.vpn_provider = provider
    app.state.session_factory = factory
    user_id, sub_id = uuid.uuid4(), uuid.uuid4()
    renewal_id, renewal_order_id = uuid.uuid4(), uuid.uuid4()
    historical_id = uuid.uuid4()
    remote_ids = []
    processes, sessions, datagrams = [], [], []
    revoked_credentials = set()

    def credentials(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"id", "password", "auth"} and isinstance(item, str) and item:
                    yield item
                else:
                    yield from credentials(item)
        elif isinstance(value, list):
            for item in value:
                yield from credentials(item)
    try:
        async with factory() as db:
            plan = await db.scalar(select(Plan).where(Plan.active.is_(True)).limit(1))
            now = datetime.now(UTC)
            remote = await provider.create_user(ProvisionUser(
                external_key=f"device-accept:{sub_id}", username=f"qa_{sub_id.hex}",
                expire_at=now + timedelta(hours=1), traffic_limit_bytes=0, device_limit=2,
                server_group_ids=settings.default_squad_uuids), f"qa:{sub_id}")
            remote_ids.append(remote.provider_id)
            db.add(User(id=user_id, display_name="Temporary device acceptance", referral_code=secrets.token_hex(10)))
            await db.flush()
            db.add(TelegramAccount(user_id=user_id, telegram_id=test_telegram_id, first_name="Acceptance"))
            db.add(Subscription(id=sub_id, user_id=user_id, plan_id=plan.id,
                status=SubscriptionStatus.ACTIVE, starts_at=now, expires_at=now + timedelta(hours=1),
                traffic_limit_bytes=4 * 1024**2 if tariff_test else 0,
                access_policy={"mbps": 8} if tariff_test else {},
                device_limit=2, isolated_devices=False,
                server_groups=list(settings.default_squad_uuids), public_token_digest=hashlib.sha256(secrets.token_bytes(32)).digest()))
            await db.flush()
            db.add(VpnAccount(subscription_id=sub_id, provider="remnawave", provider_user_id=remote.provider_id,
                              provider_username=remote.username, desired_state={}, observed_state={}))
            session = await IdentityService().issue_session(db, user_id, user_agent="isolation-test", ip_address="127.0.0.1")
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://acceptance",
            cookies={"vpn_session": session.token}, headers={"X-CSRF-Token": session.csrf_token}, timeout=40) as client:
            assert (await client.get("/api/v1/me")).status_code == 200
            assert (await client.get("/api/v1/catalog/plans")).status_code == 200
            assert (await client.get("/api/v2/referrals/summary")).status_code == 200
            ticket = await client.post("/api/v2/support/tickets", json={
                "subject": "Disposable product acceptance", "body": "Temporary automated check"})
            assert ticket.status_code == 201
            assert len((await client.get("/api/v2/support/tickets")).json()) == 1
            denied = await client.post("/api/v1/admin/grants", headers={"X-CSRF-Token": "wrong"},
                json={"telegram_id": test_telegram_id, "plan_id": str(plan.id)})
            assert denied.status_code == 403
            if not settings.YOOKASSA_ENABLED:
                payment = await client.post("/api/v1/orders", json={"plan_id": str(plan.id)},
                    headers={"Idempotency-Key": f"qa:{user_id}"})
                assert payment.status_code == 503
            print("session_catalog_csrf_and_payment_gate=PASS", flush=True)
            assert (await client.post("/api/v2/device-accounts/migrate")).status_code == 204
            first_id, second_id = uuid.uuid4(), uuid.uuid4()
            one = {"request_id": str(first_id), "name": "Test phone"}
            two = {"request_id": str(second_id), "name": "Test TV"}
            responses = await asyncio.gather(client.post("/api/v2/device-accounts", json=one), client.post("/api/v2/device-accounts", json=two))
            assert [r.status_code for r in responses] == [200, 200], "device creation failed"
            docs = [r.json() for r in responses]
            assert docs[0]["subscription_url"] != docs[1]["subscription_url"]
            retry = await client.post("/api/v2/device-accounts", json=one)
            assert retry.status_code == 200 and retry.json()["id"] == str(first_id)
            extra = await client.post("/api/v2/device-accounts", json={"request_id": str(uuid.uuid4()), "name": "Over limit"})
            assert extra.status_code == 409
            print("api_create_retry_limit=PASS", flush=True)
            with tempfile.TemporaryDirectory(prefix="device-isolation-") as directory:
                async with httpx.AsyncClient(timeout=20) as fetcher:
                    for owner_index, document in enumerate(docs):
                        headers = {"User-Agent": "Happ/5.8.0/ios", "x-hwid": f"acceptance-device-{owner_index}-12345"}
                        response = await fetcher.get(document["subscription_url"], headers=headers)
                        response.raise_for_status()
                        configs = response.json()
                        assert isinstance(configs, list) and len(configs) == 3
                        denied = await fetcher.get(document["subscription_url"], headers={**headers, "x-hwid": "different-device-67890"})
                        assert denied.headers.get("x-hwid-limit") == "true" or denied.headers.get("x-hwid-max-devices-reached") == "true" or denied.status_code == 404
                        for index, config in enumerate(configs):
                            port = 12880 + owner_index * 3 + index
                            primary = next(o for o in config["outbounds"] if o["tag"] == "proxy")
                            if owner_index == 0:
                                revoked_credentials.update(credentials(primary))
                            native = {"log": {"loglevel": "none"}, "outbounds": [primary],
                                "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "socks", "settings": {"udp": True}}]}
                            path = Path(directory) / f"{port}.json"
                            path.write_text(json.dumps(native))
                            path.chmod(0o600)
                            process = subprocess.Popen(["/probe-bin/xray", "run", "-c", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            processes.append(process)
                    await asyncio.sleep(2)
                for port in range(12880, 12886):
                    sock = await asyncio.to_thread(tunnel, port)
                    sessions.append(sock)
                    assert await asyncio.to_thread(request204, sock), "baseline transport failed"
                print("six_live_transports_and_hwid=PASS", flush=True)
                # XHTTP and Hysteria carry the call UDP paths. Keep associations open.
                for port in (12881, 12882, 12884, 12885):
                    udp = DatagramProbe(port)
                    datagrams.append(udp)
                    assert await asyncio.to_thread(udp.probe), "baseline UDP failed"
                print("four_live_udp_paths=PASS", flush=True)
                if tariff_test:
                    # A real large TLS transfer reaches Vision's direct-copy
                    # state; its rate must still obey this temporary 8-Mbit cap.
                    complete, count, mbps = await asyncio.to_thread(large_download,12880,1_000_000)
                    assert complete, "large Vision transfer failed"
                    assert 0 < mbps <= 8.8, f"Vision bypassed speed limit: {mbps:.1f} Mbps"
                    print(f"vision_large_tls_rate={mbps:.1f}_Mbps_expected_max_8.8=PASS", flush=True)
                    complete, count, _ = await asyncio.to_thread(large_download,12883,8_000_000)
                    print(f"quota_download_bytes_before_stop={count}", flush=True)
                    assert not complete and count > 100_000, "finite quota did not stop download"
                    for port in range(12880,12886):
                        assert not await asyncio.to_thread(probe,port), "device or protocol bypassed shared quota"
                    for udp in datagrams:
                        assert not await asyncio.to_thread(udp.probe), "live UDP bypassed quota"
                    print("finite_shared_quota_all_devices_protocols=PASS", flush=True)
                    # Simulate another paid period only on this owned fixture.
                    async with factory() as db:
                        sub = await db.get(Subscription,sub_id)
                        sub.access_policy={"mbps":8,"epoch":str(uuid.uuid4())}
                        sub.traffic_limit_bytes=4*1024**2
                        await db.commit()
                    restored_link = await client.post(f"/api/v2/device-accounts/{second_id}/link")
                    assert restored_link.status_code == 200, f"new-period link status={restored_link.status_code}"
                    for sock in sessions:
                        sock.close()
                    sessions.clear()
                    for udp in datagrams:
                        udp.close()
                    datagrams.clear()
                    for port in range(12880,12886):
                        print(f"new_paid_period_probe_port={port}", flush=True)
                        sock=await asyncio.to_thread(tunnel,port)
                        sessions.append(sock)
                        assert await asyncio.to_thread(request204,sock)
                    for port in (12881,12882,12884,12885):
                        udp=DatagramProbe(port)
                        datagrams.append(udp)
                        assert await asyncio.to_thread(udp.probe)
                    print("new_paid_period_restores_retained_credentials=PASS", flush=True)
                removed = await client.delete(f"/api/v2/device-accounts/{first_id}")
                assert removed.status_code == 204
                await asyncio.sleep(3)
                checks = []
                for index in range(3):
                    try:
                        live = await asyncio.to_thread(request204, sessions[index])
                    except OSError:
                        live = False
                    cached = await asyncio.to_thread(probe, 12880 + index)
                    retained = await asyncio.to_thread(probe, 12883 + index)
                    try:
                        retained_live = await asyncio.to_thread(request204, sessions[index + 3])
                    except OSError:
                        retained_live = False
                    print(f"transport_{index}: revoked_live={live}, revoked_cached={cached}, retained_new={retained}, retained_live={retained_live}", flush=True)
                    checks.append(not live and not cached and retained and retained_live)
                for index, udp in enumerate(datagrams):
                    live = await asyncio.to_thread(udp.probe)
                    print(f"udp_{index}: passes_traffic={live}, expected={index >= 2}", flush=True)
                    checks.append(live == (index >= 2))
                assert all(checks), "live/cached revocation or retained-device isolation failed"
                print("udp_revocation_and_isolation=PASS", flush=True)
                assert (await client.post("/api/v2/device-accounts", json=one)).status_code == 410
                assert (await client.post(f"/api/v2/device-accounts/{first_id}/link")).status_code == 410
                assert len((await client.get("/api/v2/devices")).json()) == 1
                print("revoke_live_cached_and_other_device=PASS", flush=True)
                # Removed URL must never supply usable cached credentials again.
                async with httpx.AsyncClient(timeout=20) as fetcher:
                    denied = await fetcher.get(docs[0]["subscription_url"], headers={"User-Agent": "Happ/5.8.0/ios", "x-hwid": "acceptance-device-0-12345"})
                    # Remnawave may return a VLESS-shaped disabled-account stub.
                    # The protocol name alone does not make it a usable credential.
                    assert revoked_credentials
                    assert denied.status_code != 200 or not any(
                        value in denied.text for value in revoked_credentials
                    ), "revoked subscription reissued original credentials"
                print("revoked_subscription_does_not_return=PASS", flush=True)
                async with factory() as db:
                    # Reproduce the production failure: an older subscription's
                    # provider account has been deleted but its local reference remains.
                    old = await provider.create_user(ProvisionUser(
                        external_key=f"qa-history:{historical_id}", username=f"qa_{historical_id.hex}",
                        expire_at=datetime.now(UTC) + timedelta(hours=1), traffic_limit_bytes=0,
                        device_limit=1, server_group_ids=settings.default_squad_uuids), f"qa:{historical_id}")
                    await provider.delete_user(old.provider_id)
                    db.add(Subscription(id=historical_id, user_id=user_id, plan_id=plan.id,
                        status=SubscriptionStatus.EXPIRED, starts_at=now - timedelta(days=2),
                        expires_at=now - timedelta(days=1), traffic_limit_bytes=0, device_limit=1,
                        isolated_devices=False, server_groups=[],
                        public_token_digest=hashlib.sha256(secrets.token_bytes(32)).digest()))
                    await db.flush()
                    db.add(VpnAccount(subscription_id=historical_id, provider="remnawave",
                        provider_user_id=old.provider_id, provider_username=old.username,
                        desired_state={}, observed_state={}))
                    await db.commit()
                assert (await client.get("/api/v1/admin/access")).json()["is_owner"]
                assert (await client.get(f"/api/v1/admin/users/{test_telegram_id}")).json()["found"]
                grant = await client.post("/api/v1/admin/grants", json={
                    "telegram_id": test_telegram_id, "plan_id": str(plan.id), "device_limit": 2,
                    "comment": "Disposable acceptance grant"})
                assert grant.status_code == 200, f"admin grant failed: {grant.status_code}"
                assert grant.json()["subscription_url"] is None
                assert (await client.get("/api/v2/subscription/access")).status_code == 200
                history = await client.get("/api/v2/traffic/year")
                assert history.status_code == 200
                assert history.json()["source_status"] == "stale"
                async with factory() as db:
                    assert (await db.get(Subscription, sub_id)).status == SubscriptionStatus.ACTIVE
                print("admin_grant_with_deleted_historical_account_and_history=PASS", flush=True)
                # Synthetic order belongs only to this disposable user; no payment API.
                async with factory() as db:
                    original = await db.get(Subscription, sub_id)
                    original_expiry = original.expires_at
                    renewal_start = datetime.now(UTC)
                    db.add(Subscription(id=renewal_id, user_id=user_id, plan_id=plan.id,
                        status=SubscriptionStatus.PENDING, starts_at=renewal_start,
                        expires_at=renewal_start + timedelta(days=1), traffic_limit_bytes=0,
                        device_limit=2, isolated_devices=True,
                        server_groups=list(settings.default_squad_uuids),
                        public_token_digest=hashlib.sha256(secrets.token_bytes(32)).digest()))
                    db.add(Order(id=renewal_order_id, user_id=user_id, plan_id=plan.id,
                        status=OrderStatus.PAID, amount_minor=0, currency="RUB",
                        plan_snapshot={}, idempotency_key=f"qa-renewal:{renewal_order_id}"))
                    db.add(ServiceEvent(aggregate_type="order", aggregate_id=renewal_order_id,
                        event_type="provision", payload={"subscription_id": str(renewal_id)},
                        idempotency_key=f"provision-order:{renewal_order_id}",
                        available_at=renewal_start))
                    await db.flush()
                    service = ProvisioningService(provider, default_server_group_ids=settings.default_squad_uuids)
                    result = await service.provision_order(db, order_id=renewal_order_id)
                    assert result.fulfilled, "renewal provisioning failed"
                    assert result.subscription.expires_at == original_expiry + timedelta(days=1)
                    again = await service.provision_order(db, order_id=renewal_order_id)
                    assert again.subscription.expires_at == result.subscription.expires_at
                    rows = list((await db.scalars(select(VpnDevice).where(VpnDevice.subscription_id == renewal_id))).all())
                    assert {row.id for row in rows} == {first_id, second_id}
                    assert next(row for row in rows if row.id == first_id).status == "revoked"
                    await db.commit()
                retained_link = await client.post(f"/api/v2/device-accounts/{second_id}/link")
                assert retained_link.status_code == 200
                assert retained_link.json()["subscription_url"] == docs[1]["subscription_url"]
                assert await asyncio.to_thread(probe, 12885), "retained device lost access after renewal"
                print("renewal_preserves_devices_links_and_expiry=PASS", flush=True)
                async with factory() as db:
                    renewed = await db.get(Subscription, renewal_id)
                    saved_expiry = renewed.expires_at
                    saved_start = renewed.starts_at
                    renewed.starts_at = datetime.now(UTC) - timedelta(days=2)
                    renewed.expires_at = datetime.now(UTC) - timedelta(seconds=10)
                    await sync_device_access(db, provider, renewed)
                    await db.commit()
                assert not await asyncio.to_thread(probe, 12885), "expired device still works"
                async with factory() as db:
                    renewed = await db.get(Subscription, renewal_id)
                    renewed.expires_at = saved_expiry
                    renewed.starts_at = saved_start
                    await sync_device_access(db, provider, renewed)
                    await db.commit()
                # Node user updates and a closed QUIC session reconnect asynchronously.
                restored = False
                for _ in range(10):
                    if await asyncio.to_thread(probe, 12885):
                        restored = True
                        break
                    await asyncio.sleep(1)
                assert restored, "restored expiry did not restore retained device"
                assert not await asyncio.to_thread(probe, 12882), "revoked device revived"
                print("expiry_restore_does_not_revive_revoked_device=PASS", flush=True)
    finally:
        for udp in datagrams:
            udp.close()
        for sock in sessions:
            sock.close()
        for process in processes:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        async with factory() as db:
            remote_ids += list((await db.scalars(select(VpnDevice.provider_user_id).where(
                VpnDevice.subscription_id.in_([sub_id, renewal_id]), VpnDevice.provider_user_id.is_not(None)))).all())
            remote_ids += list((await db.scalars(select(VpnAccount.provider_user_id).where(
                VpnAccount.subscription_id.in_([sub_id, renewal_id])))).all())
            for provider_id in set(remote_ids):
                await provider.delete_user(provider_id)
            await db.execute(delete(ServiceEvent).where(ServiceEvent.aggregate_id == renewal_order_id))
            await db.execute(delete(Order).where(Order.id == renewal_order_id))
            await db.execute(delete(AuditLog).where(AuditLog.actor_id == user_id))
            await db.execute(delete(SupportTicket).where(SupportTicket.user_id == user_id))
            await db.execute(delete(Subscription).where(Subscription.id.in_([sub_id, renewal_id, historical_id])))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await provider.close()
        await engine.dispose()
        print("temporary_accounts_cleaned=true", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
