#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
helper="$repo_root/scripts/ensure-docker-network.sh"
network="atlas-network-test-$$"

fail() {
  printf 'test-ensure-docker-network: %s\n' "$*" >&2
  exit 1
}

expect_failure() {
  if "$@" >/dev/null 2>&1; then
    fail "command unexpectedly succeeded: $*"
  fi
}

cleanup() {
  docker network rm "$network" >/dev/null 2>&1 || true
}

trap cleanup EXIT HUP INT TERM

expect_failure sh "$helper" unsupported-network
expect_failure sh "$helper" "$network"
ATLAS_NETWORK_DRY_RUN=1 sh "$helper" rclone_network

ATLAS_NETWORK_TESTING=1 ATLAS_NETWORK_DRY_RUN=1 \
  sh "$helper" "$network"
expect_failure docker network inspect "$network"

pids=
for attempt in 1 2 3 4 5 6 7 8; do
  ATLAS_NETWORK_TESTING=1 sh "$helper" "$network" &
  pids="$pids $!"
done

for pid in $pids; do
  wait "$pid"
done

docker network inspect "$network" >/dev/null
ATLAS_NETWORK_TESTING=1 sh "$helper" "$network"

printf 'test-ensure-docker-network: passed\n'
