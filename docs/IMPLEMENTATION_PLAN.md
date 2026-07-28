# Delivery plan

Status is evidence-based. A phase can be complete only when its test/report is
stored in the repository.

| Phase | Scope | Exit evidence | Status |
|---:|---|---|---|
| 0 | VPNUS/public UX analysis, GitHub/license review | `RESEARCH.md`, revisions and decisions | Complete |
| 1 | Architecture, data boundaries, threat model | diagrams, ADRs, threat register | Complete |
| 2 | Repository and dependency baseline | monorepo, license notices, pinned dependencies | In progress |
| 3 | Local environment | Compose, health/readiness, migrations, smoke test | In progress |
| 4 | Business backend | identity, catalog, order/payment state machines, ledger, subscription, referral, audit | Started |
| 5 | VPN adapter | Remnawave create/update/disable/usage/device flows, reconciliation | Started |
| 6 | Telegram bot | `/start`, referral, menu, Mini App, status/notifications/support | Started |
| 7 | Telegram Mini App | auth, dashboard, plans, connect, devices, referral, support | Started |
| 8 | Public site/account | original responsive pages, SEO and browser auth | Planned |
| 9 | Billing | YooKassa/SBP, T-Bank/SBP, Stars with verified webhooks | Planned |
| 10 | Subscription Edge | Go edge, Happ/v2RayTun formats, cache and rotation | Planned |
| 11 | Free service/MTProxy | isolated free profile and `mtg` deployment | Planned |
| 12 | Domains/mirrors | health probes, quorum state, rotation and signed config | Planned |
| 13 | Nodes/protocols | real VLESS Reality, XHTTP, gRPC, Hysteria2 acceptance | Planned |
| 14 | Monitoring/backups | SLO dashboards, alerts, encrypted backups, restore drill | Planned |
| 15 | Security | ASVS review, RBAC, secrets, hardening, supply chain | Planned |
| 16 | Load/resilience | measured API/subscription load and dependency failures | Planned |
| 17 | Staging | payment sandbox plus real disposable VPN topology | Planned |
| 18 | Production review | acceptance report, remaining risks, runbooks and sign-off | Planned |

## First vertical slice

The first usable slice is: Telegram opens Mini App → backend authenticates raw
initData → user sees server-owned plan/subscription state → sandbox webhook posts a
balanced ledger transaction → outbox provisions a Remnawave user → Subscription
Edge returns a link that imports into Happ and v2RayTun → disable/re-enable is
verified against a disposable VLESS Reality node.

Payment providers and the node acceptance environment require external accounts,
domains and servers; their credentials are injected only into staging secrets.
