# Development iteration 01

Date: 2026-07-21

## Implemented

- Monorepo, local Compose topology, CI and pinned Python/Node lockfiles.
- Thirty-two-table business schema covering identity, sessions, plans,
  subscriptions, VPN mappings, orders, payments, double-entry wallet ledger,
  referrals, promotions, devices, support, domains, RBAC, audit, webhook replay,
  idempotency and outbox events.
- Telegram Mini App HMAC validation with duplicate-field, expiry, future-time and
  constant-time signature checks.
- Database-backed rotating sessions and server-owned referral codes.
- `VPNProvider` port and an executable Remnawave v2.8.1 adapter. Conflict retries
  resolve only when the deterministic business key matches.
- aiogram 3 `/start` handler and Mini App-first menu.
- Original responsive React/TypeScript Mini App shell with dashboard, plans,
  connection, device, referral, wallet and support journeys.
- Unified public website and Telegram Mini App frontend with a shared original
  NOVA visual system. Normal browser navigation renders the landing, while a
  verified Telegram context (or the local `?app=1` flag) renders the cabinet.
- The customer cabinet now has two responsive layouts from one component tree:
  a mobile Telegram layout with bottom navigation and a wider browser layout
  with a full sidebar, available locally at `/cabinet?app=1`.
- Rebuilt the local browser cabinet from the supplied VPNUS `full-access`
  reference: black icon rail, large rounded application stage, centered account
  controls, referral analytics grid and three continuously cross-fading teal
  gradient states. The same component tree collapses into a mobile Mini App
  layout while retaining the original NOVA identity and assets.
- Recalibrated the desktop cabinet against six Retina reference captures and the
  live site's computed viewport scale. The resulting desktop geometry uses an
  80 px navigation rail, 35 px stage radius, 253 px home column and 320 px
  secondary-page column. Support now includes the four reference FAQ rows and a
  blurred modal; Settings now mirrors the subscription, account, login-method
  and information card hierarchy from the supplied captures.
- Added an original glass browser-authentication screen at `/cabinet?login=1`
  with email and Telegram entry affordances. Existing session restoration and
  Telegram Mini App authentication remain fail-closed; email delivery is not
  presented as active until a real mail/OTP provider is implemented.
- Fail-closed production settings and honest capability handling: no fake VPN,
  payment or traffic data.

## Verification results

- `ruff`: passed.
- `mypy --strict`: passed for backend source.
- `pytest`: 12 passed; measured source coverage 61% for the currently imported
  modules.
- Telegram validation: 6 positive/negative cases passed.
- Remnawave adapter: create mapping, authorization, idempotent conflict resolution
  and unsupported online-count behaviour passed with local HTTP transport.
- Unified site/Mini App: ESLint passed; TypeScript passed; Vite production build
  passed (234.76 kB JS, 72.63 kB gzip). Docker Compose configuration validation
  also passed after adding the dual-mode frontend build settings.
- Visual browser QA passed for the compact desktop dashboard, referral screen,
  support screen, FAQ dialog and settings screen using deterministic local mock
  data. Docker image refresh was not rerun after this UI pass because Docker
  Desktop was manually paused; the production frontend build itself passed.
- Alembic offline PostgreSQL DDL generation passed: 479 lines, 32 business tables
  plus the Alembic version table.
- Docker Compose build and local container smoke test passed on 2026-07-22:
  PostgreSQL and Redis became healthy, the initial Alembic migration completed,
  the API became healthy, and the Mini App returned HTTP 200.
- Application smoke checks passed for `/health/live`, `/health/ready`, the plans
  catalog, development Telegram authorization, and the authenticated `/me` route.
  The readiness response reports `vpn_provider: false` until a Remnawave instance
  and credentials are configured; this is expected in local UI development.
- Mobile browser QA at 390×844 passed for the fail-closed authorization screen;
  a technical network error was found and replaced with a user-safe message.

## Not yet implemented

Orders/payment provider APIs, subscription provisioning worker, Subscription
Edge, live devices, admin UI and real VPN node acceptance remain
in their planned phases. The current repository is a tested foundation, not a
production-ready service.

## Inputs needed later

No credentials are needed for continued local development. Staging Phase 9 and
13 will require Telegram bot credentials, payment sandbox accounts, domains and
at least one disposable VPN/control-plane server.

## Local registry note

The local Compose and application Dockerfiles use the public AWS ECR mirror for
official Docker Library images. This avoids a reproducible Docker Desktop →
Docker Hub manifest `EOF` observed on 2026-07-22; image versions and upstream
contents remain unchanged.
