# Transport recovery and checks

The node uses REALITY/RAW, gRPC TLS, XHTTP TLS and Hysteria2. These share
one VPS; they do not provide independent host or provider redundancy.

## Node checks

`rovyn-node-watchdog.timer` checks management/health ports, TCP 443/8443/2096
and UDP 443. Three consecutive local failures trigger a bounded node restart
with a five-minute cooldown. TLS fallback failure and a certificate expiring
within 14 days are reported as service failures without restarting Xray.
The fallback Nginx supports HTTP/2 and listens only on localhost port 9443.

## End-to-end checks on the existing panel server

Install `rovyn-transport-monitor.sh` as `/usr/local/sbin/rovyn-transport-monitor`
and the matching service/timer under `/etc/systemd/system/`. Install
`run_transport_acceptance.py` and `test_node_transports.py` in `/opt/remnawave/`,
and `verify_subscription_outputs.py` with its helper in `/opt/vpn-platform/infra/`.
Substitute deployment domains in the public examples before installation.
Enable `rovyn-transport-monitor.timer` after a successful manual service run.
Copy `/usr/local/bin/xray` from the installed `remnawave/node:2.7.0` image to
`/opt/remnawave/monitor-bin/xray` (mode 0755) on the panel host. The scheduled
monitor uses this same core as a temporary local process, avoiding eight Docker
container starts per run. Fault injection still uses isolated Docker clients.

Approximately every five minutes after the previous run, the monitor creates
short-lived test users, requests their generated subscription, sends an HTTPS
request through each Happ VPN outbound and validates both subscription formats.
Test users are deleted in `finally` blocks and have a two-hour expiry as a fallback.
Runs are locked and bounded. It does not restart the node on an external failure:
the test website, panel or network could be responsible.

Inspect `journalctl -u rovyn-transport-monitor.service` and
`/var/lib/rovyn-transport-monitor/latest` on the panel host. Failures set a
nonzero service result; no Telegram notifications are configured.

## Network-loss test

On the panel server, with no other manual acceptance run in progress:

```sh
E2E_HAPP_JSON=1 E2E_OUTAGE_SECONDS=15 E2E_TIMEOUT=8 \
  python3 -u /opt/remnawave/run_transport_acceptance.py
```

Each disposable Xray client uses its own Docker bridge and loopback-only SOCKS
port. The test first verifies traffic, disconnects only that client's network,
confirms a request fails, waits 15 seconds, reconnects the network and retries
for up to roughly 60 seconds. The client process is not restarted. Containers
and networks are removed in cleanup. Production network interfaces and firewall
rules are not changed.

On 2026-09-07 all four generated Happ outbounds passed this test. Observed
post-reconnection request times were RAW 0.1s, gRPC 1.1s, XHTTP 0.1s and
Hysteria2 0.3s. These are a single server-side experiment, not a latency promise.
This does not emulate iOS suspension, its VPN extension or a real Wi-Fi/LTE
handover; those still require device testing.
