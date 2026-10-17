# Product verification — 17 October 2026

## Findings and repairs

Manual grants returned HTTP 500 when personal-device synchronization visited a
historical VpnAccount whose remote user had been deleted. Confirmed from the
production traceback and reproduced with a disposable subscription. Disabling
and checking disconnection of an already absent account now succeeds. Failed
disable actions for an existing account and provider outages still propagate.
Grant synchronization failures return a controlled HTTP 502 and roll back the
local transaction.

Traffic-history HTTP 404 previously marked the local paid subscription expired
and returned empty totals. History failure now preserves paid access and stored
totals, reporting the source as stale. Deleted remote history is not reconstructed
or represented as measured zero traffic.

Live acceptance found the node had reverted to stock Xray and NET_ADMIN: its
explicit `docker compose -f docker-compose.yml` launch omitted the optional
override. The verified core remained on disk with SHA-256
`ee66d03d1b1b19cdb165c8a546d43a71d45566b6bd73657c8c2bb49d20d97845`.
Restored that core, removed NET_ADMIN and moved its read-only mount into the
primary compose and staged compose. The repository node definition now includes
the mount and fails if the core file is absent. The deployment script checks
the executable before changing the node. A brief controlled node restart was
performed under the existing user authorization.

## Evidence

- 62 backend tests pass, including deleted-account revocation, provider failure,
  grant rollback, unavailable history preserving access, email-code validation,
  Telegram signatures, payment adapter and order/provisioning behavior.
- Backend mypy, backend Ruff, frontend lint, TypeScript/Vite build pass.
  One existing Starlette warning concerns the deprecated spelling of HTTP 422.
- Live acceptance container `rovyn-product-audit-final-20261017` completed with
  exit 0 using a separate API image, the real PostgreSQL and the actual VPN node.
- Authenticated session, catalog, referral summary, temporary support ticket,
  CSRF rejection, payment-disabled gate pass.
- Device creation, retry, slot limit, per-link HWID limit pass.
- Reality, XHTTP and Hysteria: six active TCP paths pass; revocation stops the
  removed device's live and cached connections. Retained same-IP sessions remain
  connected. XHTTP/Hysteria UDP revocation and isolation pass.
- Manual owner grant with a deliberately deleted historical remote account
  passes, then subscription access and history APIs return HTTP 200. The history
  API reports stale and does not expire the subscription.
- Renewal keeps device IDs/links and revoked status; provisioning retry does not
  double-extend. Expiry blocks traffic and restoration reconnects Hysteria without
  restarting its client, while the revoked credential remains blocked.
- Temporary acceptance identities, subscriptions, remote users, support ticket
  and synthetic order were cleaned up. No real customer's subscription was
  manually granted by the test. The test-only owner setting exists solely in
  the in-process ASGI application, not in production configuration.
- Public login and catalog HTTP 200; unauthenticated admin access HTTP 401.
  Production readiness reports PostgreSQL, Redis and VPN provider ready.

## Deployment and rollback

The fixed API is deployed as `vpn-platform-api:audit-20261017` tagged for the
normal Compose service. The final acceptance passed before publication.
Rollback source, database dump and previous API image archive are retained at
`/opt/vpn-platform/.deploy-backups/product-audit-20261017/`.
Node compose backups are at `/opt/remnanode/backups/product-audit-20261017/`.

## Remaining product limitations

YooKassa is disabled and its credentials are absent in production. Purchasing
access cannot be considered operational until the merchant credentials and
webhook setup are supplied and a payment flow is verified. No real charge was
made by this audit.

Resend credentials are configured and email challenge logic is tested. Actual
mailbox delivery and the full browser/Telegram account-linking journey were not
verified by sending mail or using a real customer's credentials in this audit.

Historical statistics for deleted Remnawave users remain unavailable. Stored
statistics are preserved with a stale status; completeness is not claimed.

These results verify the listed paths and transports; they are not a claim that
every possible device, ISP, client sleep/resume sequence or browser has been
exhaustively tested.
