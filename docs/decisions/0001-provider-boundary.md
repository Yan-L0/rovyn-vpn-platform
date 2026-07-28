# ADR 0001: Isolate the VPN control plane behind `VPNProvider`

Status: accepted, 2026-07-21.

## Decision

Business modules depend only on the typed `VPNProvider` port. Remnawave v2.8.1 is
the first production adapter and remains a separately deployed AGPL service.
Provider UUIDs, observed state and reconciliation timestamps live in
`vpn_accounts`; they never replace business subscription identifiers.

VortexUI may be added as a separate adapter only after its qualification suite.

## Consequences

- Billing, Telegram and frontend code do not change when a provider changes.
- Provisioning is asynchronous, idempotent and recoverable through the outbox.
- Provider-specific capabilities can be unavailable without fabricated data.
- Adapters require contract tests and staging acceptance against exact versions.
