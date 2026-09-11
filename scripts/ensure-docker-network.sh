#!/bin/sh

set -eu

network=${1:-}

if test "$#" -ne 1 || test -z "$network"; then
  echo "usage: ensure-docker-network.sh NETWORK" >&2
  exit 64
fi

case "$network" in
  proxy_network|media_network) ;;
  atlas-network-test-*)
    test "${ATLAS_NETWORK_TESTING:-0}" = 1 || {
      echo "test network names require ATLAS_NETWORK_TESTING=1" >&2
      exit 65
    }
    ;;
  *)
    echo "unsupported Atlas network: $network" >&2
    exit 65
    ;;
esac

if test "${ATLAS_NETWORK_DRY_RUN:-0}" = 1; then
  echo "ensure-docker-network: dry-run network=$network" >&2
  exit 0
fi

command -v docker >/dev/null 2>&1 || {
  echo "ensure-docker-network: docker is not available" >&2
  exit 69
}

if docker network inspect "$network" >/dev/null 2>&1; then
  exit 0
fi

if docker network create "$network" >/dev/null 2>&1; then
  exit 0
fi

docker network inspect "$network" >/dev/null 2>&1
