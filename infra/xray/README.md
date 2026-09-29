# Credential-scoped session revocation

Pinned upstream: XTLS/Xray-core v26.3.27, commit
`d2758a023cd7f4174a5a5fa4ff66e487d4342ba0`. Upstream MPL-2.0 applies to
modified source files; retain its LICENSE when distributing a build.

Remnawave Node 2.7.0's privileged socket destruction is IP-scoped: it may
disconnect unrelated devices behind NAT and does not reliably revoke existing
Hysteria QUIC sessions. This patch signals revocation on the authenticated
MemoryUser generation and closes its VLESS connection or Hysteria QUIC session.
Other users and later generations of the same username are unaffected.

Run `bash infra/xray/build.sh` with Go 1.26.1. The script verifies the upstream
commit, runs race tests and a loopback two-device TCP/UDP acceptance test. It
does not deploy. Build output and source are retained for audit.

Deployment requirements:

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
