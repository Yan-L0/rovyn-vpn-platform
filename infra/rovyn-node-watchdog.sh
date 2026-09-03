#!/usr/bin/env bash
set -Eeuo pipefail

readonly container_name="remnanode"
readonly state_directory="/run/rovyn-node-watchdog"
readonly failure_file="${state_directory}/failures"
readonly restart_file="${state_directory}/last-restart"
readonly failure_threshold=3
readonly restart_cooldown_seconds=300

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
  [[ "$(docker inspect --format '{{.State.Running}}' "$container_name" 2>/dev/null || true)" == "true" ]] \
    && port_is_listening tcp 2222 \
    && port_is_listening tcp 61000 \
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
install -d -m 0755 "$state_directory"

exec 9>"${state_directory}/lock"
if ! flock -n 9; then
  log "another watchdog check is still running"
  exit 0
fi

if node_is_ready; then
  printf '0\n' >"$failure_file"
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
docker restart --time 20 "$container_name" >/dev/null

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
