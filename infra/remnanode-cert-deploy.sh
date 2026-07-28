#!/bin/sh
set -eu

certificate_name="${RENEWED_LINEAGE:-/etc/letsencrypt/live/node.vpn.example}"
target_dir="/opt/remnanode/ssl"

install -d -m 0755 "${target_dir}"
install -m 0644 "${certificate_name}/fullchain.pem" "${target_dir}/fullchain.pem"
install -m 0600 "${certificate_name}/privkey.pem" "${target_dir}/privkey.pem"

if docker container inspect remnanode >/dev/null 2>&1; then
  docker restart remnanode >/dev/null
fi
if docker ps --format '{{.Names}}' | grep -qx rovyn-reality-fallback; then
  docker restart rovyn-reality-fallback >/dev/null
fi
