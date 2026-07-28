# VPN Platform

Commercial VPN platform with a Telegram-first customer journey. The first release
uses Happ and v2RayTun as clients; the platform owns identity, billing,
subscriptions and device policy, while a replaceable provider adapter owns VPN
provisioning.

This repository is under active construction. Passing local tests proves only the
implemented components; it is not yet a production-readiness claim.

## Current scope

- FastAPI business API with Telegram Mini App authentication.
- aiogram Telegram bot that launches the Mini App.
- Unified React/TypeScript frontend: an original public landing page in a normal
  browser and a Telegram Mini App cabinet from the same build.
- `VPNProvider` boundary and a real Remnawave HTTP adapter.
- PostgreSQL/Redis local stack and fail-closed production configuration.
- Architecture, threat model, research and license baseline.

## Repository layout

```text
backend/       Business API, domain model and provider adapters
bot/           Telegram bot worker
miniapp/       Telegram Mini App
docs/          Architecture, research, security and delivery plan
infra/         Local/production infrastructure definitions
monitoring/    Observability configuration (later phase)
```

## Local start

1. Copy `.env.example` to `.env` and set `TELEGRAM_BOT_TOKEN`.
2. Set `TELEGRAM_AUTH_DEV_BYPASS=true` only for local browser development.
3. Run `docker compose --env-file .env -f infra/compose.local.yml up --build`.
4. Open `http://localhost:5173` for the public site and
   `http://localhost:5173/cabinet?login=1` for the browser login screen. Use
   `http://localhost:5173/cabinet?app=1` to enter the local cabinet through the
   explicit development bypass; API docs are at
   `http://localhost:8080/docs`.

The development bypass is rejected when `APP_ENV` is not `development` or
`test`. Payments and VPN provisioning do not have mock production fallbacks.

## Verification

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.lock
.venv/bin/pip install --no-deps -e backend -e bot
pnpm --dir miniapp install --frozen-lockfile
make test
```

Full container verification requires Docker Desktop. The tested development
baseline is Python 3.12 and Node.js 22.

## Design constraints

- No VPNUS name, logo, text or proprietary assets are included.
- Payment entitlement is created only after a verified server callback.
- Money is recorded through an append-only ledger, not mutable balance updates.
- Telegram `initData` is validated by the backend; `initDataUnsafe` is never an
  authority.
- The business database is independent from the VPN control plane.
- Provider errors fail closed and are retried through an outbox workflow.

See [architecture](docs/ARCHITECTURE.md), [threat model](docs/THREAT_MODEL.md),
and [delivery plan](docs/IMPLEMENTATION_PLAN.md).
