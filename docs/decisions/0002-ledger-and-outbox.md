# ADR 0002: Double-entry ledger and transactional outbox

Status: accepted, 2026-07-21.

## Decision

Wallet balances are derived from immutable posted `ledger_entries` grouped by
`wallet_transactions`. Each transaction must have at least two non-zero postings
whose signed minor-unit amounts sum to zero. Refunds use reversing transactions;
posted entries are not edited.

Payment entitlement and `service_events` are committed in one PostgreSQL
transaction. External VPN and notification side effects run after commit.

## Consequences

- Financial history can be reconciled and audited.
- A provider outage cannot erase or half-commit a paid order.
- Workers must implement idempotency, leases, bounded retries and dead-letter
  escalation.
- Database constraints/triggers and concurrent replay tests are release gates.
