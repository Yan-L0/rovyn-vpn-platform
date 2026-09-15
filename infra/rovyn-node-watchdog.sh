#!/usr/bin/env bash
set -Eeuo pipefail

readonly container_name="remnanode"
readonly state_directory="/run/rovyn-node-watchdog"
readonly failure_file="${state_directory}/failures"
readonly restart_file="${state_directory}/last-restart"
readonly failure_threshold=3
readonly restart_cooldown_seconds=300
readonly fallback_hostname="${ROVYN_NODE_FALLBACK_HOSTNAME:-node.vpn.example}"

log() {
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    log "missing required command: $1"
    exit 1
  }
}

port_is_listening() {
  local -r protocol="$1"
  local -r port="$2"

  if [[ "$protocol" == "udp" ]]; then
    ss -H -lun | awk -v port=":${port}" '$4 ~ port "$" { found=1 } END { exit !found }'
  else
    ss -H -ltn | awk -v port=":${port}" '$4 ~ port "$" { found=1 } END { exit !found }'
  fi
}

node_is_ready() {
  [[ "$(timeout 5 docker inspect --format '{{.State.Running}}' "$container_name" 2>/dev/null || true)" == "true" ]] \
    && port_is_listening tcp 2222 \
    && port_is_listening tcp 61000 \
    && port_is_listening tcp 443 \
    && port_is_listening tcp 2096 \
    && port_is_listening udp 443
}

read_counter() {
  local value="0"
  if [[ -r "$failure_file" ]]; then
    value="$(<"$failure_file")"
  fi
  [[ "$value" =~ ^[0-9]+$ ]] || value="0"
  printf '%s' "$value"
}

require_command docker
require_command ss
require_command awk
require_command flock
require_command timeout
require_command curl
require_command openssl
install -d -m 0755 "$state_directory"

exec 9>"${state_directory}/lock"
if ! flock -n 9; then
  log "another watchdog check is still running"
  exit 0
fi

if node_is_ready; then
  printf '0\n' >"$failure_file"
  if ! curl --silent --show-error --fail --max-time 8 \
    --resolve "${fallback_hostname}:9443:127.0.0.1" \
    "https://${fallback_hostname}:9443/health" >/dev/null; then
    log "TLS fallback failed; inspect Nginx/certificate (node restart skipped)"
    exit 1
  fi
  if ! openssl x509 -checkend 1209600 -noout \
    -in /opt/remnanode/ssl/fullchain.pem >/dev/null; then
    log "TLS certificate expires within 14 days; inspect certbot renewal"
    exit 1
  fi
  exit 0
fi

failures="$(read_counter)"
failures=$((failures + 1))
printf '%s\n' "$failures" >"$failure_file"
log "node readiness check failed (${failures}/${failure_threshold})"

if (( failures < failure_threshold )); then
  exit 0
fi

now="$(date +%s)"
last_restart="0"
if [[ -r "$restart_file" ]]; then
  last_restart="$(<"$restart_file")"
fi
[[ "$last_restart" =~ ^[0-9]+$ ]] || last_restart="0"
if (( now - last_restart < restart_cooldown_seconds )); then
  log "restart suppressed by cooldown"
  exit 0
fi

log "restarting ${container_name} after confirmed failures"
printf '%s\n' "$now" >"$restart_file"
timeout 35 docker restart --time 20 "$container_name" >/dev/null

for _ in {1..30}; do
  if node_is_ready; then
    printf '0\n' >"$failure_file"
    log "node recovered"
    exit 0
  fi
  sleep 2
done

log "node did not recover after restart"
exit 1
