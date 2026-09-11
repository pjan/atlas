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

HTTP_BIND_IP=127.0.0.1 HTTP_PORT=18080 \
  docker compose -f stacks/caddy/compose.yaml run --rm --no-deps caddy \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

git diff --check
echo 'validate: passed'
