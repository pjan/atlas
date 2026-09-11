#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)

sh "$script_dir/tests/test-atlas-hostfs.sh"
sh "$script_dir/tests/test-ensure-docker-network.sh"
sh "$script_dir/tests/test-wait-for-container-health.sh"
