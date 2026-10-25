# Happ call routing and transport recovery

`infra/configure_call_recovery.py` installs per-host XRAY_JSON templates on
Remnawave 2.8+. Run without arguments for a read-only plan; use `--apply` to
create a mode-0600 backup and assign the templates. `--restore <snapshot>`
restores host template assignments and previously managed template contents.
No node restart is required. Users must refresh their subscription and reconnect.

The templates preserve direct subscription bootstrap and LAN access. Public UDP
is routed through the VPN before regional bypass rules. Telegram/Discord domain
rules precede regional rules. REALITY carries public UDP through an injected
XHTTP outbound, avoiding Vision's UDP/443 interception. Other profiles carry UDP
through their selected transport, with an observed fallback. Credentials remain
per-user and are injected by Remnawave; templates contain no shared user keys.

Each profile probes its primary outbound with Xray Observatory every 30 seconds.
When it is observed unavailable, new connections use the backup: REALITY → XHTTP,
XHTTP → Hysteria2, Hysteria2 → XHTTP. Established streams are not migrated.
All transports currently share one physical node; this cannot cover node/provider
outages. Hysteria2 fallback also requires working UDP between client and node.
REALITY media uses XHTTP directly, so an XHTTP outage still affects that media path.

Hourly subscription refresh remains enabled. It is distinct from tunnel recovery.
No Provider-ID-only Happ headers are assumed to work. OS sleep, app termination,
startup VPN permissions, and desktop HTTP-proxy-only mode still need client-side
handling. Desktop voice applications need VPN/TUN capture, not just an HTTP proxy.

## Endpoint bootstrap without DNS

`configure_node_bootstrap.py --domain <current-node-domain> --address <public-node-IP>`
previews a narrow update to the three `ROVYN_` transport hosts. Add `--apply` to
save a private rollback snapshot and change only their connection addresses.
Explicit TLS/REALITY SNI must already be present and must not derive from the
address. Certificates and their verification stay enabled. Backups injected by
the recovery templates inherit these host addresses too.

This removes the need to resolve the node's own hostname before connecting to
either transport. It does not remove DNS needed for destination websites, fix
Happ's embedded core, or provide another physical node. On a node IP migration,
update the addresses again. Re-running the original provisioning script can
restore hostname addresses: reapply bootstrap afterwards and verify outputs.
Clients need to refresh the subscription and reconnect to use the new endpoints.

Before publishing an address change, set `E2E_BOOTSTRAP_IP=<candidate-IP>` when
running `probe_call_paths.py`; it changes only disposable client configurations.
Repeat with `E2E_FORCE_PRIMARY_DOWN=1` to exercise fallback. After publication,
run the probe without that override and run `verify_subscription_outputs.py`
with `E2E_EXPECTED_NODE_IP=<published-IP>` to check URI links and every Happ
primary/backup, including explicit TLS names. Restore using
`configure_node_bootstrap.py --restore <snapshot>` if acceptance fails.

Validation: `python3 infra/test_call_recovery_config.py` checks route ordering.
On the panel, `probe_call_paths.py` creates a disposable user and launches isolated
Xray clients using the actual subscription routing. It tests HTTPS and two public
STUN services per profile. `E2E_FORCE_PRIMARY_DOWN=1` points only the temporary
client's primary outbound at a closed local port to test fallback from startup.
It does not interrupt the production node, and it does not simulate an ongoing
phone call or a device waking from sleep. Temporary users and containers are
removed in `finally` blocks. The ordinary transport probe continues testing each
primary independently, so a healthy fallback cannot conceal a broken primary.

References:
- https://xtls.github.io/en/config/outbounds/vless.html
- https://xtls.github.io/en/config/routing.html
- https://xtls.github.io/en/config/observatory.html
- https://github.com/HappDev/happ_su/blob/main/dev-docs/app-management.md
- https://github.com/remnawave/backend/blob/2.8.1/src/modules/subscription-template/generators/xray-json.generator.service.ts
