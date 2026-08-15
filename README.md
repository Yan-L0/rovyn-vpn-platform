# Rovyn VPN Platform

Rovyn is a Telegram-first VPN service: users open a Mini App from the bot, buy
a plan through YooKassa SBP, receive a personal Remnawave subscription URL and
manage connected devices in one responsive web interface.

This repository contains the full application and deployment definitions. It
does **not** contain production secrets, private keys, customer data, payment
credentials or live node credentials.

## What is included

- FastAPI backend: authentication, catalog, orders, YooKassa webhook, device
  policy, traffic data and the Remnawave provider adapter.
- aiogram bot with a compact UX: one `Личный кабинет` button and Telegram's
  `Открыть VPN` menu button.
- React/Vite public site and Telegram Mini App, including the responsive
  cabinet design and the source mockup in `mockups/biorg-responsive-v1/`.
- Docker Compose stacks for local development, production, the Remnawave node
  and the subscription page.
- Operational scripts for profile provisioning, certificate deployment,
  transport checks, backups and recovery.

## Architecture

```text
Telegram bot ──opens──> Mini App / public site
                              │
                              ▼
                         FastAPI backend
                    ┌─────────┼──────────┐
                    ▼         ▼          ▼
               PostgreSQL   Redis    YooKassa SBP
                              │
                              ▼
                         Remnawave panel ──> Remnawave node / Xray
```

The application owns identity, payments, orders, subscriptions, device policy
and the user cabinet. Remnawave owns VPN configuration and runtime traffic
statistics. The boundary is implemented by `VPNProvider`, allowing a provider
replacement without rewriting the business layer.

## Prerequisites

- Docker Engine with Docker Compose v2.
- Node.js 22+ and pnpm 11+ for frontend-only work.
- Python 3.12+ for backend tests and scripts.
- A Telegram bot token from BotFather.
- A YooKassa shop configured for SBP, plus its webhook credentials.
- A running Remnawave panel and a registered Remnawave node.
- HTTPS domains for the public site/API and the Remnawave panel.

## 1. Clone and configure

```bash
git clone https://github.com/Yan-L0/rovyn-vpn-platform.git
cd rovyn-vpn-platform
cp .env.example .env
```

Open `.env` and set at minimum:

```dotenv
TELEGRAM_BOT_TOKEN=...
SESSION_SECRET=at-least-32-random-characters
REMNAWAVE_API_TOKEN=...
YOOKASSA_SHOP_ID=...
YOOKASSA_SECRET_KEY=...
```

For local browser development only, set `TELEGRAM_AUTH_DEV_BYPASS=true`.
Never enable that flag in production.

## 2. Run locally

```bash
docker compose --env-file .env -f infra/compose.local.yml up --build
```

Open:

- Public site: `http://localhost:5173`
- Local Mini App view: `http://localhost:5173/cabinet?app=1`
- API documentation: `http://localhost:8080/docs`

Stop the stack with:

```bash
docker compose --env-file .env -f infra/compose.local.yml down
```

## 3. Verify before deploying

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.lock
.venv/bin/pip install --no-deps -e backend -e bot
pnpm --dir miniapp install --frozen-lockfile
make test
make lint
```

The cabinet design can be reviewed separately from the running backend:

```bash
cd mockups/biorg-responsive-v1
python3 -m http.server 4180
```

Then visit `http://127.0.0.1:4180/`.

## 4. Prepare production application server

1. Install Docker and Docker Compose.
2. Clone the repository to `/opt/vpn-platform`.
3. Copy `.env.production.example` to `/opt/vpn-platform/.env.production`.
4. Fill every placeholder with real credentials. Keep this file outside Git.
5. Configure TLS reverse proxy using `infra/Caddyfile`; replace example domains
   with your own domains.
6. Start the app and bot:

```bash
cd /opt/vpn-platform
docker compose --env-file .env.production -f infra/compose.prod.yml --profile telegram up -d --build
```

7. Confirm readiness:

```bash
curl --fail https://YOUR_APP_DOMAIN/health/ready
docker compose --env-file .env.production -f infra/compose.prod.yml ps
```

The expected API response contains `postgres`, `redis` and `vpn_provider` set
to `true`.

## 5. Configure the Remnawave node

The node is deliberately separate from the application server. On the node:

1. Install Docker.
2. Create the Remnawave node in the panel and obtain its `.env` values.
3. Place the node environment file beside `infra/compose.node.yml`.
4. Ensure certificates are available at `/opt/remnanode/ssl`.
5. Start the node stack:

```bash
cd /opt/vpn-platform/infra
docker compose --env-file .env -f compose.node.yml up -d
```

6. In Remnawave, provision the server groups and profiles. The supplied scripts
   cover VLESS + TCP/RAW + Reality and Hysteria2; use the transport acceptance
   scripts before giving profiles to customers.

Do not expose the node control port to the public Internet. Only allow the
Remnawave panel to reach it.

## 6. Configure Telegram and YooKassa

1. Set the Mini App URL in BotFather to `https://YOUR_APP_DOMAIN`.
2. Start the `bot` compose profile. On startup it registers `/cabinet`, `/help`
   and `/paysupport`, plus the `Открыть VPN` menu button.
3. In YooKassa, configure the webhook:

```text
https://YOUR_APP_DOMAIN/api/v1/payments/yookassa/webhook
```

4. Make a small SBP test payment and verify the order is marked paid before a
   Remnawave subscription is issued.

## Updating production safely

Build first, then recreate only the changed service. Example for the Mini App:

```bash
cd /opt/vpn-platform
docker compose --env-file .env.production -f infra/compose.prod.yml build miniapp
docker compose --env-file .env.production -f infra/compose.prod.yml up -d --no-deps --force-recreate miniapp
curl --fail https://YOUR_APP_DOMAIN/cabinet
```

Before every production change, tag the current image and copy the changed
files to a dated backup directory. Keep deployment notes and rollback details
in a private operator workspace.

## Security essentials

- Never commit `.env`, `.env.production`, SSH keys, YooKassa secrets, bot
  tokens, Remnawave API tokens or database dumps.
- Telegram `initData` is verified server-side. `initDataUnsafe` is not trusted.
- Production must run with `TELEGRAM_AUTH_DEV_BYPASS=false`.
- YooKassa webhook payloads are re-verified through YooKassa before
  provisioning access.
- The payment ledger is append-only; do not replace it with mutable balances.
- Keep the application database independent from the VPN control plane.

## Project notes

Private architecture and operations notes are intentionally kept outside this
public repository.
