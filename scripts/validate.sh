#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd -P)
cd "$repo_root"

command -v docker >/dev/null 2>&1
command -v python3 >/dev/null 2>&1

find scripts -type f -name '*.sh' -exec sh -n {} \;
python3 scripts/validate-repository.py

sh scripts/test-phase-1.sh
sh scripts/ensure-docker-network.sh media_network
sh scripts/ensure-docker-network.sh proxy_network
sh scripts/ensure-docker-network.sh rclone_network
sh scripts/ensure-docker-network.sh youtarr_network
sh scripts/ensure-docker-network.sh dispatcharr_network
sh scripts/ensure-docker-network.sh monitoring_network

compose_image() {
  sed -n "s|^ *image: *\($2\)\$|\1|p" "$1" | head -n 1
}

prometheus_image=$(compose_image stacks/monitoring/compose.yaml 'prom/prometheus:[^ ]*')
docker run --rm --entrypoint promtool \
  -v "$repo_root/stacks/monitoring/prometheus:/etc/prometheus:ro" \
  "$prometheus_image" check config /etc/prometheus/prometheus.yml

# Alert rules and their unit tests, which live outside the mounted directory.
docker run --rm --entrypoint sh \
  -v "$repo_root/stacks/monitoring:/monitoring:ro" \
  "$prometheus_image" -c \
  'promtool check rules /monitoring/prometheus/rules/*.yml &&
   promtool test rules /monitoring/prometheus-tests/*.yml'

# validate-repository.py renders the Discord message fixtures with amtool.
alertmanager_image=$(compose_image stacks/monitoring/compose.yaml 'prom/alertmanager:[^ ]*')
docker run --rm --entrypoint amtool \
  -v "$repo_root/stacks/monitoring/alertmanager:/etc/alertmanager:ro" \
  "$alertmanager_image" check-config /etc/alertmanager/alertmanager.yml

blackbox_image=$(compose_image stacks/monitoring/compose.yaml 'prom/blackbox-exporter:[^ ]*')
docker run --rm \
  -v "$repo_root/stacks/monitoring/blackbox:/etc/blackbox_exporter:ro" \
  "$blackbox_image" --config.file=/etc/blackbox_exporter/blackbox.yml --config.check

# Caddy is built from stacks/caddy/Dockerfile. Validation provisions the
# Cloudflare DNS module, which only accepts a well-formed token.
HTTP_BIND_IP=127.0.0.1 HTTP_PORT=18080 \
  CLOUDFLARE_DNS_API_TOKEN=atlasvalidationdummytoken0000000000000 \
  docker compose -f stacks/caddy/compose.yaml build caddy
HTTP_BIND_IP=127.0.0.1 HTTP_PORT=18080 \
  CLOUDFLARE_DNS_API_TOKEN=atlasvalidationdummytoken0000000000000 \
  docker compose -f stacks/caddy/compose.yaml run --rm --no-deps caddy \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

git diff --check
echo 'validate: passed'
