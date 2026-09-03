#!/bin/sh
set -eu

base_dir="/opt/remnanode"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${base_dir}/backups/${timestamp}"
compose_file="${base_dir}/docker-compose.yml"
staged_compose="${base_dir}/compose.node.yml"
sysctl_file="/etc/sysctl.d/99-rovyn-vpn.conf"
service_file="/etc/systemd/system/rovyn-network-tuning.service"
compose_service_file="/etc/systemd/system/rovyn-node-compose.service"
watchdog_script="/usr/local/sbin/rovyn-node-watchdog"
watchdog_service_file="/etc/systemd/system/rovyn-node-watchdog.service"
watchdog_timer_file="/etc/systemd/system/rovyn-node-watchdog.timer"
renewal_hook="/etc/letsencrypt/renewal-hooks/deploy/remnanode-cert-deploy"
committed="false"

if [ "$(id -u)" -ne 0 ]; then
  echo "deploy_node_stability.sh must run as root" >&2
  exit 1
fi

for required in \
  "${staged_compose}" \
  "${base_dir}/99-rovyn-vpn.conf" \
  "${base_dir}/rovyn-network-tuning.service" \
  "${base_dir}/rovyn-node-compose.service" \
  "${base_dir}/rovyn-node-watchdog.sh" \
  "${base_dir}/rovyn-node-watchdog.service" \
  "${base_dir}/rovyn-node-watchdog.timer" \
  "${base_dir}/remnanode-cert-deploy.sh" \
  "${base_dir}/nginx-reality-fallback.conf" \
  "${base_dir}/reality-fallback.html" \
  "${base_dir}/ssl/fullchain.pem" \
  "${base_dir}/ssl/privkey.pem"
do
  if [ ! -f "${required}" ]; then
    echo "missing staged file: ${required}" >&2
    exit 1
  fi
done

install -d -m 0700 "${backup_dir}"
cp -a "${compose_file}" "${backup_dir}/docker-compose.yml"
if [ -f "${sysctl_file}" ]; then
  cp -a "${sysctl_file}" "${backup_dir}/99-rovyn-vpn.conf"
else
  : >"${backup_dir}/sysctl.was-absent"
fi
if [ -f "${service_file}" ]; then
  cp -a "${service_file}" "${backup_dir}/rovyn-network-tuning.service"
else
  : >"${backup_dir}/service.was-absent"
fi
if [ -f "${renewal_hook}" ]; then
  cp -a "${renewal_hook}" "${backup_dir}/remnanode-cert-deploy"
else
  : >"${backup_dir}/renewal-hook.was-absent"
fi
for watchdog_path in \
  "${watchdog_script}" \
  "${watchdog_service_file}" \
  "${watchdog_timer_file}"
do
  watchdog_name="$(basename "${watchdog_path}")"
  if [ -f "${watchdog_path}" ]; then
    cp -a "${watchdog_path}" "${backup_dir}/${watchdog_name}"
  else
    : >"${backup_dir}/${watchdog_name}.was-absent"
  fi
done

rollback() {
  if [ "${committed}" = "true" ]; then
    return
  fi
  echo "deployment failed; rolling node configuration back" >&2
  cp -a "${backup_dir}/docker-compose.yml" "${compose_file}"
  if [ -f "${backup_dir}/sysctl.was-absent" ]; then
    rm -f "${sysctl_file}"
  else
    cp -a "${backup_dir}/99-rovyn-vpn.conf" "${sysctl_file}"
  fi
  if [ -f "${backup_dir}/service.was-absent" ]; then
    systemctl disable --now rovyn-network-tuning.service >/dev/null 2>&1 || true
    rm -f "${service_file}"
  else
    cp -a "${backup_dir}/rovyn-network-tuning.service" "${service_file}"
  fi
  if [ -f "${backup_dir}/renewal-hook.was-absent" ]; then
    rm -f "${renewal_hook}"
  else
    cp -a "${backup_dir}/remnanode-cert-deploy" "${renewal_hook}"
  fi
  systemctl disable --now rovyn-node-watchdog.timer >/dev/null 2>&1 || true
  for watchdog_path in \
    "${watchdog_script}" \
    "${watchdog_service_file}" \
    "${watchdog_timer_file}"
  do
    watchdog_name="$(basename "${watchdog_path}")"
    if [ -f "${backup_dir}/${watchdog_name}.was-absent" ]; then
      rm -f "${watchdog_path}"
    else
      cp -a "${backup_dir}/${watchdog_name}" "${watchdog_path}"
    fi
  done
  systemctl daemon-reload
  sysctl --system >/dev/null 2>&1 || true
  docker compose -f "${compose_file}" up -d --remove-orphans >/dev/null 2>&1 || true
}
trap rollback EXIT HUP INT TERM

docker compose -f "${staged_compose}" config -q
bash -n "${base_dir}/rovyn-node-watchdog.sh"
docker run --rm \
  --network host \
  -v "${base_dir}/nginx-reality-fallback.conf:/etc/nginx/nginx.conf:ro" \
  -v "${base_dir}/reality-fallback.html:/usr/share/nginx/html/index.html:ro" \
  -v "${base_dir}/ssl:/etc/nginx/ssl:ro" \
  nginx:1.28.3-alpine nginx -t
systemd-analyze verify "${base_dir}/rovyn-network-tuning.service"

install -m 0644 "${base_dir}/99-rovyn-vpn.conf" "${sysctl_file}"
install -m 0644 "${base_dir}/rovyn-network-tuning.service" "${service_file}"
install -m 0644 "${base_dir}/rovyn-node-compose.service" "${compose_service_file}"
install -m 0755 "${base_dir}/rovyn-node-watchdog.sh" "${watchdog_script}"
install -m 0644 "${base_dir}/rovyn-node-watchdog.service" "${watchdog_service_file}"
install -m 0644 "${base_dir}/rovyn-node-watchdog.timer" "${watchdog_timer_file}"
install -m 0755 "${base_dir}/remnanode-cert-deploy.sh" "${renewal_hook}"
install -m 0600 "${staged_compose}" "${compose_file}"

sysctl --system >/dev/null
systemctl daemon-reload
systemd-analyze verify "${watchdog_service_file}" "${watchdog_timer_file}"
systemctl enable --now rovyn-network-tuning.service
systemctl enable --now rovyn-node-compose.service
systemctl enable --now rovyn-node-watchdog.timer
docker compose -f "${compose_file}" up -d --remove-orphans

attempt=0
fallback_health=""
node_running=""
management_ready="false"
while [ "${attempt}" -lt 40 ]; do
  fallback_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' rovyn-reality-fallback 2>/dev/null || true)"
  node_running="$(docker inspect -f '{{.State.Running}}' remnanode 2>/dev/null || true)"
  if ss -H -lnt | grep -q ':2222 '; then
    management_ready="true"
  else
    management_ready="false"
  fi
  if [ "${fallback_health}" = "healthy" ] \
    && [ "${node_running}" = "true" ] \
    && [ "${management_ready}" = "true" ]
  then
    break
  fi
  attempt=$((attempt + 1))
  sleep 2
done

if [ "${fallback_health}" != "healthy" ] \
  || [ "${node_running}" != "true" ] \
  || [ "${management_ready}" != "true" ]
then
  echo "containers did not become healthy in time" >&2
  exit 1
fi

systemctl start rovyn-node-watchdog.service
if ! systemctl is-active --quiet rovyn-node-watchdog.timer; then
  echo "node watchdog timer is not active" >&2
  exit 1
fi

if ! curl --silent --show-error --fail \
  --resolve node.vpn.example:9443:127.0.0.1 \
  https://node.vpn.example:9443/health >/dev/null
then
  echo "local TLS fallback health check failed" >&2
  exit 1
fi

committed="true"
trap - EXIT HUP INT TERM
echo "node_stability_deployment=complete"
echo "backup=${backup_dir}"
