# Threat model

Method: STRIDE with abuse-case review. This is a living baseline, not a completed
security audit.

## Assets

- Payment funds, wallet ledger and entitlements.
- Telegram identities, sessions and support correspondence.
- Subscription tokens and VPN credentials.
- Provider API tokens, payment webhook secrets and signing keys.
- Node/control-plane availability and routing configuration.
- Audit evidence and backups.

## Trust boundaries

Telegram client → Mini App → public API; payment provider → webhook; public
subscription client → Subscription Edge; business workers → VPN control plane;
control plane → nodes; operators → admin API; application → PostgreSQL/Redis.

## Priority threats and controls

| Threat | Impact | Required controls | Evidence gate |
|---|---|---|---|
| Forged/stale Telegram initData | Account takeover | Server-side HMAC, maximum age, constant-time compare, one-time session rotation | Unit vectors + integration test |
| IDOR/BOLA on users/devices/orders | Cross-account disclosure/revoke | Resource lookup always scoped to session user; opaque IDs; authorization tests | Negative API test matrix |
| Price/plan/amount tampering | Financial loss | Server-side catalog and order snapshot; webhook amount/currency/status verification | Provider sandbox tests |
| Webhook replay/race | Duplicate credit/entitlement | Unique provider event ID, row lock, state machine, idempotency record | Concurrent replay test |
| Ledger corruption | Unexplained balance | Double-entry journal, immutable posted entries, DB constraints, reconciliation | Property tests + daily reconciliation |
| Subscription token leak | VPN theft | 256-bit tokens, hash at rest, rotation, rate limiting, minimal logs | Token rotation E2E |
| Provider/API compromise | All VPN accounts exposed | Least-scope token, isolated adapter, secret manager, egress allow-list, rotation | Staging rotation drill |
| Malicious client headers | Config injection/cache poisoning | Strict UA mapping, no user-controlled template execution, canonical cache keys | Fuzz tests |
| XSS in Telegram/user names | Session theft/UI abuse | Context escaping, CSP, no unsafe HTML, sanitised logs | Browser security tests |
| CSRF/session fixation | Unauthorized mutations | HttpOnly Secure SameSite cookie, session rotation, origin checks and CSRF token | Auth integration tests |
| Redis outage | Auth/rate-limit degradation | Fail closed on security counters; DB-backed durable jobs; bounded local readiness | Failure test |
| PostgreSQL outage | Inconsistent payment/provisioning | No side effect before durable commit; non-ready state; webhook retry response | Failure test |
| Node/control-plane split brain | Traffic/accounting errors | Idempotent desired-state reconciliation, monotonic counters, dedupe checkpoints | Restart/reconnect suite |
| Insider admin abuse | Fraud/privacy breach | RBAC, MFA/passkeys, four-eyes for finance/credentials, tamper-evident audit | Role tests + audit review |
| Dependency/container compromise | Remote code execution | Lockfiles, SBOM, signature/provenance checks, image scanning, pinned digests | CI policy |
| DDoS/resource exhaustion | Loss of service | CDN/WAF, per-route distributed limits, queue bounds, caches, separate subscription edge | Measured load tests |

## Privacy posture

The service must not log browsing destinations or DNS queries. Store only data
needed for service delivery: account identity, aggregate usage, device presence,
payment/audit records and short-lived operational IP data with documented
retention. Support and security logs redact tokens, credentials, Telegram init
data, payment payload secrets and full IP addresses where possible.

## Security gates

Production is blocked until payment sandbox replay tests, Telegram auth tests,
authorization tests, VPN connection acceptance, backup restore, secret rotation,
dependency scan and measured load/resilience reports pass. “DDoS protected” and
“production ready” are not valid claims without recorded evidence and scope.
