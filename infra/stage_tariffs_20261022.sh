#!/usr/bin/env bash
# Panel only. Back up and build; deliberately do not activate the catalog.
set -Eeuo pipefail
umask 077
trap 'printf "Tariff staging failed at line %s\n" "$LINENO" >&2' ERR
readonly release=/opt/rovyn-tariffs/release.tar.gz
readonly backup=/opt/rovyn-tariffs/backups
[[ -f "$release" ]]
[[ -d /opt/vpn-platform/backend ]]
[[ ! -e "$backup" ]]
mkdir -p -- "$backup"
docker image tag vpn-platform-api rovyn-backup-api:20261022
docker image tag vpn-platform-miniapp rovyn-backup-miniapp:20261022
tar -czf "$backup/app-source.tar.gz" --exclude=node_modules --exclude=dist --exclude=__pycache__ \
  -C /opt/vpn-platform backend miniapp infra/compose.prod.yml
docker exec vpn-platform-postgres-1 pg_dump -U vpn -d vpn -Fc > "$backup/application.dump"
tar -xzf "$release" -C /opt/vpn-platform
cd /opt/vpn-platform
docker compose --env-file .env.production -f infra/compose.prod.yml build api miniapp
docker compose --env-file .env.production -f infra/compose.prod.yml run --rm --no-deps api \
  alembic upgrade 0006_transport_policy
printf 'Builds ready; schema expanded; catalog remains unchanged.\n'
