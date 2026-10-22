#!/usr/bin/env bash
# Activate the new API before the finite catalog, with image rollback on failure.
set -Eeuo pipefail
trap 'printf "API activation failed at line %s\n" "$LINENO" >&2' ERR
cd /opt/vpn-platform
previous_image="$(docker inspect vpn-platform-api-1 --format '{{.Image}}')"
readonly previous_image
docker image tag "$previous_image" vpn-platform-api:pre-tariff-activation
docker image tag vpn-platform-api vpn-platform-api:tariffs-20261022
if ! docker compose --env-file .env.production -f infra/compose.prod.yml \
  up -d --no-deps --wait --wait-timeout 120 api; then
  docker image tag "$previous_image" vpn-platform-api:latest
  docker compose --env-file .env.production -f infra/compose.prod.yml \
    up -d --no-deps --force-recreate --wait --wait-timeout 120 api
  exit 1
fi
printf 'API with shared traffic policies is ready; catalog was not modified by this step.\n'
