#!/usr/bin/env bash
# Runs on the existing panel server. Failed external probes are recorded,
# not used to restart a healthy node indiscriminately.
set -Eeuo pipefail
umask 077
readonly base_dir=/opt/remnawave
readonly state_dir=/var/lib/rovyn-transport-monitor
for command in flock timeout python3; do
  command -v "$command" >/dev/null || exit 1
done
install -d -m 0700 "$state_dir"
exec 9>"$state_dir/lock"
flock -n 9 || exit 0
status=0
printf 'started=%s\n' "$(date -u +%FT%TZ)"
if ! timeout --kill-after=15 240 env E2E_HAPP_JSON=1 E2E_TIMEOUT=10 \
  E2E_XRAY_BIN=/opt/remnawave/monitor-bin/xray \
  python3 -u "$base_dir/run_transport_acceptance.py"; then
  status=1
fi
if ! timeout --kill-after=15 120 python3 -u \
  /opt/vpn-platform/infra/verify_subscription_outputs.py; then
  status=1
fi
result_file="$(mktemp "$state_dir/result.XXXXXX")"
trap 'rm -f "$result_file"' EXIT
printf 'checked=%s\nstatus=%s\n' "$(date -u +%FT%TZ)" "$status" >"$result_file"
mv "$result_file" "$state_dir/latest"
printf 'transport_monitor_status=%s\n' "$status"
exit "$status"
