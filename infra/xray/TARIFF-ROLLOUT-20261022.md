# Tariff rollout, 22 October 2026

Approved catalog for new purchases/renewals: MONTH 111 RUB / 25 GiB / 70 Mbit/s;
HALF_YEAR 560 RUB / 200 GiB / 100 Mbit/s; YEAR 960 RUB / unlimited quota.
Year: rolling 600-second delivered-download average >100 Mbit/s triggers a
100 Mbit/s cap in both directions; recover after 900 seconds in which the
rolling 60-second download average remains below 10 Mbit/s. Terms appear in
the catalog. Existing subscription snapshots retain their prior terms.

## Architecture and limits

- One deployed node, confirmed in Remnawave DB. This implementation does not
  aggregate limits across multiple nodes. Revisit before adding a second node.
- Xray v26.7.28 with existing credential revocation patch plus tariff patch.
  Dispatcher getLink/WrapLink share authenticated-user limits across transports.
  Managed runtime disables splice via CanSpliceCopy=3 after flow initialization.
  UDP buffers retain their packet boundaries. Limiter waits cancel on credential
  revocation and stream interruption; delivery is checked again after pacing.
- Group key is subscription UUID plus renewal epoch. Device UUID changes do not
  reset usage or FUP. Remnawave's internal t_id (not user/provider UUID) is the
  Xray email; checked installed backend 2.8.1 and node SDK code.
- Panel publishes validated JSON every five seconds over a dedicated restricted
  SSH key, source-IP restricted and forced to the receiver command. No user
  deployment private key is copied. Unknown identities are denied until mapped.
  API waits for publisher acknowledgement and core reload before returning links.
- Durable quota reservations are fsynced before forwarding. After a
  core restart unused reservation headroom is conservatively charged, at most
  4 MiB per finite group/restart. This prevents a restart from restoring quota.
  A non-fitting final buffer closes the group; at most that buffer's remaining
  tail is conservatively charged instead of permitting small reconnects.
  FUP state is checkpointed every second. Invalid state fails closed.
- Provider traffic counters use userTraffic.usedTrafficBytes in Remnawave 2.8.1.
  Missing counters raise errors rather than becoming zero. Renewal UI baselines
  preserve actual current-cycle usage without resetting other device counters.

## Rollout and verification

Completed: production DB revision `0007_tariffs_20261022`, updated API and
miniapp, node limiter and restricted publisher all active. Public catalog and
cabinet HTTP 200 checked. Readiness includes PostgreSQL, Redis, provider, and
fresh applied traffic-policy ACK; all four checks pass.

Final Linux core SHA256:
`7bee38a348a2b3a63b4bb3c8a222e62ac2094decb1a7c92e0367cfab7cefb22a`.
The running container binary hash was checked, not just its host bind source.
Core build/race tests and both tariff-enabled loopback gates passed.
75 backend tests, Ruff/mypy, frontend build/lint, shell syntax, diff check pass.

Actual-node acceptance `rovyn-tariff-finite-acceptance-v2-20261022` exited 0
before catalog activation. After activation,
`rovyn-tariff-catalog-acceptance-20261022` also exited 0:

- Real large Vision TLS transfer: 7.1 Mbit/s with an artificial 8-Mbit test cap.
- A 4-MiB shared fixture stopped its second large download after 3,113,527
  additional body bytes; both devices and all protocols then denied traffic.
- A new paid-period epoch restored retained credentials without replacing links.
- All three transports denied revoked live/cached connections while retained
  connections and reconnects worked. UDP associations proved the same isolation.
- Admin grant with a deleted historical provider account, renewal, expiration,
  restoration, and non-revival of revoked devices all passed.
- Temporary accounts were cleaned by their owned-ID fixture cleanup.

Independent transport probes passed 9/9 HTTPS/STUN and 3/3 two-megabyte HTTPS
downloads. Transport monitor completed status 0 at 2026-10-22T07:35:04Z; its
timer and policy publisher are enabled. Restricted SSH command was tested:
requesting `true` with the publisher key ran only the receiver and was rejected
as invalid policy, rather than executing the shell command.

## Operational limits

Remnawave per-device quotas remain zero: the core owns the **shared** quota.
Consequently Happ's subscription-userinfo meter may display unlimited/per-device
figures. The cabinet uses the fresh core counter for finite shared quotas and
shows exhaustion with a renewal action. Do not advertise the client meter as a
shared remaining-balance source without a separate metadata integration.

The initial pre-tariff API acceptance saw one retained Reality reconnect fail
while its existing session stayed up. Both final full acceptance runs retained
the reconnect assertions and passed. Initial finite testing also exposed a
small quota-tail usability gap (now closes the group on a non-fitting packet)
and interference from the old unlimited-only reconciler (API upgraded before
catalog activation). No failing gate was removed or treated as a pass.

## Audit / rollback assets

Panel workspace: `/opt/rovyn-tariffs`. Original application source/database
backups: `/opt/rovyn-tariffs/backups/{app-source.tar.gz,application.dump}`;
original image tags `rovyn-backup-api:20261022`,
`rovyn-backup-miniapp:20261022`. The later
`vpn-platform-api:pre-tariff-activation` tag supports shared quotas and is the
preferred API fallback. Do not restore the original unlimited-only reconciler
while finite subscriptions exist.

Node final activation unit: `rovyn-tariff-activation-20261022-verified`.
Previous tariff-aware core/compose:
`/opt/remnanode/backups/tariffs-20261022-723s4pbk`. Preserve
`/opt/remnanode/tariffs/policy.json.state` on rollback. Never restore a stock or
pre-tariff core while shared finite plans are active: provider quotas are zero.
Prefer a verified tariff-aware fallback or forward fix. Initial SSH-attached
activation was interrupted and rolled back; subsequent activations ran through
independent systemd units and their actual container checksums were verified.

Receiver: `/usr/local/sbin/rovyn-receive-tariff-policy`; publisher key and pinned
node known-host key remain in the panel workspace (never print the private key).
Only initialize empty state before first activation; preparation refuses to
reset missing state for an already configured node. Source/Go build and stopped
acceptance containers are retained for audit.

Initial staging rejected macOS AppleDouble metadata in the migration directory.
Only generated sidecars were removed, Dockerignore guards added, and clean
archives/images rebuilt. Catalog SQL was checked for implicit JSON-colon bind
parameters before applying it; `jsonb_build_object` avoids that driver issue.
