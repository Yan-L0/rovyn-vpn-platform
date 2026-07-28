# Phase 1 report — Architecture

Date: 2026-07-21

## Completed

- Defined the business platform, bot, Mini App, provider adapter, Subscription
  Edge and infrastructure boundaries.
- Documented system, authentication, payment, provisioning and trust-zone flows.
- Defined identifiers, financial invariants, token storage and outbox rules.
- Accepted ADRs for provider isolation, double-entry accounting and Telegram
  session exchange.
- Built a STRIDE-based threat register with measurable release gates.

## Files changed

- `docs/ARCHITECTURE.md`
- `docs/THREAT_MODEL.md`
- `docs/decisions/0001-provider-boundary.md`
- `docs/decisions/0002-ledger-and-outbox.md`
- `docs/decisions/0003-telegram-session-auth.md`

## Verification

The architecture was cross-checked against the required database entities,
payment flow, Telegram security rules, device limitations, Happ/v2RayTun client
scope and provider replacement requirement. Its first ports are exercised by the
12-test initial suite.

## Remaining risks

- Deployment-level HA, capacity values and DDoS controls cannot be finalized
  before staging regions/providers are known.
- Hysteria2, gaming, LTE and free routing remain gated by protocol E2E evidence.
- Legal retention periods and payment fiscalization details require the launch
  jurisdiction/business entity.

## Next phase

Complete dependency license/SBOM automation and freeze explicit Alembic operations
for Phase 2/3, then implement the first paid provisioning vertical slice.
