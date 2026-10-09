#!/bin/sh
# Runs scripts/theme-probe.mjs in the Playwright image: it renders a Grafana dashboard in
# Atlas Light, Atlas Dark, and after a live switch, and reports the colours the browser draws.
# Slow and manual: run it only when pjan asks (README.md, Monitoring), never from
# validate.sh or CI.
#
# Usage: GRAFANA_URL=https://grafana.atlas.vandaele.io GRAFANA_USER=pjan sh scripts/theme-probe.sh
# It asks for the Grafana password unless GRAFANA_PASSWORD is set.
# Optional: DASHBOARD=/d/<uid>?from=now-24h&to=now (default Atlas Containers).
# From Docker Desktop, a Grafana on this machine is http://host.docker.internal:<port>.
# Behind a TLS-inspecting proxy, set NODE_EXTRA_CA_CERTS to a PEM file with its CA, so npm
# in the container can reach the registry.

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PLAYWRIGHT_IMAGE='mcr.microsoft.com/playwright:v1.64.0-noble@sha256:06a9939e57531807f8d5fd76ce44b53165ffb7d7501d87ab10e285c20b1e971f'
# The npm package must match the browsers in the image: take its version from the tag.
playwright_version=${PLAYWRIGHT_IMAGE#*:v}
playwright_version=${playwright_version%%-*}

: "${GRAFANA_URL:?set GRAFANA_URL}" "${GRAFANA_USER:?set GRAFANA_USER}"
if [ -z "${GRAFANA_PASSWORD:-}" ]; then
  printf 'Grafana password for %s: ' "$GRAFANA_USER" >&2
  trap 'stty echo' EXIT INT TERM
  stty -echo
  IFS= read -r GRAFANA_PASSWORD
  stty echo
  printf '\n' >&2
fi
export GRAFANA_PASSWORD

set --
if [ -n "${NODE_EXTRA_CA_CERTS:-}" ]; then
  set -- -v "$NODE_EXTRA_CA_CERTS:/probe/ca.pem:ro" -e NODE_EXTRA_CA_CERTS=/probe/ca.pem
fi

docker run --rm --init --ipc=host "$@" \
  -e GRAFANA_URL -e GRAFANA_USER -e GRAFANA_PASSWORD -e DASHBOARD \
  -v "$script_dir/theme-probe.mjs:/probe/theme-probe.mjs:ro" \
  "$PLAYWRIGHT_IMAGE" sh -c "
    mkdir -p /tmp/probe && cp /probe/theme-probe.mjs /tmp/probe/ && cd /tmp/probe &&
    npm install --loglevel=error --no-audit --no-fund playwright@$playwright_version >/dev/null &&
    node theme-probe.mjs"
