# Tariff checkpoint investigation, 25 October 2026

## Findings

The reported prolonged loss of traffic is **not proven fixed** by this change.
Tariff terms and the implementation of their shared enforcement are separate
possible causes.

- Compared the active Mac Happ primary Hysteria credential with its XHTTP backup
  without logging either: same identity. Matched that identity to its provider
  account using a fingerprint. It is active, unexpired, with provider quota 0
  and a legacy core group; new 70/100-Mbit caps and FUP do not apply to it.
- Node policy sampled 16 groups, all Mbps 0 / quota 0 / FUP false. Six historical
  durable entries all had zero FUP start time and no throttled flag. Thus there
  is no evidence of the yearly ten-minute rule activating for this incident.
- Active client is now Happ 6.1.0 / Xray 26.9.9; IP bootstrap is in use. Its
  later errors at 19:20:35 and 19:22:18 UTC+5 overlap a successful panel monitor
  run at 19:21:14–19:21:54. Prior DNS mitigation was insufficient.
- Server Xray itself had been running since 23 October 06:54:09 UTC, despite
  its container starting on 22 October. Container uptime alone was not proof of
  core uptime. No contemporaneous core restart was found for the client errors.
- Firewall permits production ports, no separate 70/100-Mbit traffic shaper,
  conntrack 299/65536, no fail2ban service active.

## Confirmed implementation defect

The maintenance loop called `persist()` every second while holding the manager
mutex used by every authenticated TCP/UDP buffer, including legacy unlimited
groups. It rewrote and fsynced unchanged historical state. During investigation
the node had elevated I/O pressure; six small isolated file-sync measurements
were 13.1–31.9 ms, median 20.1 ms. This proves unnecessary stalls are possible,
but those samples alone do not explain a thirty-minute outage.

The fix caches the exact last successfully synchronized serialization and skips
disk I/O if it is unchanged. A validated existing startup state initializes the
cache. A changed quota reservation is still synchronized before forwarding;
FUP bucket/flag changes are still persisted. Cache advances only after BOTH
file fsync and directory fsync succeed. Failures on required writes still deny
traffic. No tariffs, counters, renewal epochs or revocation logic were reset.

## Verification and deployment

- Regression test fails on the old source, passes on the fix. It checks every
  maintenance tick rather than only final inode identity (inodes may be reused).
- Added tests for required reservation persistence, failure after a prior
  successful checkpoint, and changed FUP bucket persistence.
- Go race tests passed for dispatcher, credential protocol, VLESS, VMess
  encoding, Hysteria accounts and transport packages.
- Three isolated native TCP/UDP gates pass: no policy, tariff-enabled device
  revocation/isolation, tariff-enabled shared quota exhaustion. Both devices
  retain packet boundaries for payloads 32/900/1400/4096 bytes; revoked live and
  cached sessions fail while the retained device continues.
- Deployed core SHA256:
  `0de0efa1cc482b3b8d0ef36b56aac21ee0114fba9a2ddb154d781a3e66ddfa70`.
  Activation unit `rovyn-checkpoint-activation-20261025` exited 0. Hash verified
  inside the running remnanode container; applied policy healthy and fresh.
- Live observation after deployment: zero state inode changes across eight
  one-second ticks, identical checkpoint contents. Previously inode changed on
  each sampled tick. Fresh policy acknowledgement continues without state rewrites.
- Actual-node acceptance `rovyn-checkpoint-live-acceptance-v3-20261025` exited 0:
  six native live transport paths and four UDP paths; Vision large TLS download
  7.1 Mbit/s under an artificial 8-Mbit cap; shared quota stopped all devices and
  transports (second download stopped after 3,116,691 body bytes); new paid period
  restored all six clients; live/cached revocation and retained-device isolation;
  admin grant with deleted historical provider account; renewal, expiration and
  restoration without reviving a revoked device. Temporary accounts cleaned.
- Earlier actual-node v2 passed rate and exhaustion but failed with a five-second
  TLS handshake timeout during new-period restoration. The repeat added only a
  port diagnostic, kept the original timeouts/assertions, and passed. The single
  timeout remains unexplained; do not interpret the passing repeat as proof that
  all network stalls are resolved. Initial raw-env test could not connect to
  localhost PostgreSQL; it was replaced with the service's Compose environment.
- Six backend tariff terms/publisher tests pass; Ruff for the one-line acceptance
  diagnostic and `git diff --check` pass.

Build source and logs retained on panel:
`/opt/rovyn-tariff-checkpoint-20261025/source`.
Rollback binary/compose on node:
`/opt/remnanode/backups/tariffs-20261022-qbqtsjme` (inherited directory prefix).
Additional pre-activation state snapshot:
`/opt/remnanode/backups/policy-state-before-checkpoint-20261025.json`.
Restore only binary/compose if necessary, preserve CURRENT quota state; an old
state snapshot must not be used to give back already consumed traffic.

Long-session Happ recovery remains unverified. A clean short probe, working
panel subscription refresh, or removal of redundant checkpoints does not prove
the customer-visible prolonged outage is solved.
