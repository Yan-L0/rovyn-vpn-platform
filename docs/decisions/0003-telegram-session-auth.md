# ADR 0003: Telegram initData exchange for server sessions

Status: accepted, 2026-07-21.

## Decision

The Mini App sends raw Telegram `initData` once to the business API. The API
validates its HMAC and age, upserts the Telegram account under a transaction lock
and returns an opaque, HttpOnly database-backed session cookie plus a CSRF token.
Frontend data and `initDataUnsafe` never authorize a user or financial action.

The local bypass is explicit and configuration validation rejects it in staging
or production.

## Consequences

- Telegram user fields can be treated as signed only inside the exchange.
- Session revocation, rotation and audit are controlled by the service.
- Mini App and browser account can converge on the same authorization layer.
- Session cleanup, CSRF enforcement and authorization-matrix tests remain
  mandatory before mutating endpoints ship.
