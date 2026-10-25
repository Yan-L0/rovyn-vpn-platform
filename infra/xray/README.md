# Credential-scoped session revocation

Pinned upstream: XTLS/Xray-core v26.7.28, commit
`5ca6f4b7d4dc20a881d4330e498892697627ec0c`. Upstream MPL-2.0 applies to
modified source files; retain its LICENSE when distributing a build.

Remnawave Node 2.7.0's privileged socket destruction is IP-scoped: it may
disconnect unrelated devices behind NAT and does not reliably revoke existing
Hysteria QUIC sessions. This patch signals revocation on the authenticated
MemoryUser generation and closes its VLESS connection or Hysteria QUIC session.
Other users and later generations of the same username are unaffected.
Route-specific Hysteria credential views share their canonical generation's
revocation signal; they must not create independently authorized sessions.

This version also accepts Hysteria UDP when newer clients omit the QUIC
max_datagram_frame_size advertisement after 1 September 2026. The former
26.3.27 server could pass HTTPS health checks while losing all returned UDP.
Validate actual bidirectional UDP with both current and older client binaries;
an HTTPS-only observatory cannot detect that failure.

Run `bash infra/xray/build.sh` with Go 1.26.1. The script verifies the upstream
commit, runs race tests and a loopback two-device TCP/UDP acceptance test. It
does not deploy. Build output and source are retained for audit.
For a mixed-version loopback gate, run
`python3 infra/test_session_revocation.py NEW_SERVER_BINARY OLD_CLIENT_BINARY`.

The build also includes `tariff-policy.patch` and `tariff_policy*.go`. Quotas
and bandwidth are shared by paid subscription, using Remnawave's `t_id` as the
authenticated Xray email. Enable only with the restricted publisher/receiver
and persistent state directory configured. The core reports the exact applied
policy SHA256 and health; publisher ACKs expire after 15 seconds. Unknown users
are blocked until their policy is applied. The API waits before issuing links.
See [tariff rollout](TARIFF-ROLLOUT-20261022.md) for timing, reservation semantics,
single-node limits, and rollback requirements. Never remove the writable tariff
mount or reset its state to regain quota. Bootstrap an empty state only before
the first activation; preserve it through upgrades and machine restarts.

Unchanged durable checkpoints are cached after successful file and directory
sync (or a validated startup read). The one-second maintenance loop must not
fsync an identical checkpoint while holding the shared traffic mutex. Changed
quota reservations still sync before forwarding; changed FUP state still
checkpoints. See [checkpoint investigation](TARIFF-CHECKPOINT-20261025.md).

Deployment requirements:

The primary `infra/compose.node.yml` now contains the core mount and omits
NET_ADMIN. Install the verified binary before using it. The optional overlay is
only for older compose files: explicit `docker compose -f ...` commands do not
implicitly include docker-compose.override.yml. Never rely on that implicit
overlay to preserve the revocation guarantee through boot or redeployment.

- Back up the live node compose file and retain its image before changing it.
- Mount the verified Linux binary read-only at `/usr/local/bin/xray`.
- Remove NET_ADMIN from the node to prevent the IP-scoped kill fallback.
  This also removes capabilities used by privileged IP/socket plugins; review
  these before enabling. Host firewall rules remain independent.
- Recreate only remnanode (one-time connection interruption). Verify Reality,
  XHTTP, Hysteria, same-NAT isolation and UDP with disposable accounts.
- Only then enable `REMNAWAVE_DEVICE_SESSION_REVOCATION_ENABLED=true` in the API.
  Keep the default false on nodes without the patch.

Rollback: first disable the API feature, restore the backed-up compose and
recreate remnanode with its original image/core. Existing personalized accounts
remain in the database, but strict live revocation is not guaranteed without
the patched core. Do not advertise that capability after rollback.

Rebase and rerun all acceptance tests for every Xray or Remnawave upgrade.
This is a maintained local patch, not an upstream guarantee.
