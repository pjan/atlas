#!/bin/sh

set -eu

container=${1:-}
timeout_seconds=${2:-180}
interval_seconds=${3:-5}

if test "$#" -lt 1 || test "$#" -gt 3 || test -z "$container"; then
  echo "usage: wait-for-container-health.sh CONTAINER [TIMEOUT_SECONDS [INTERVAL_SECONDS]]" >&2
  exit 64
fi

case "$timeout_seconds" in
  ''|*[!0-9]*)
    echo "wait-for-container-health: timeout must be a positive integer" >&2
    exit 64
    ;;
esac

case "$interval_seconds" in
  ''|*[!0-9]*)
    echo "wait-for-container-health: interval must be a positive integer" >&2
    exit 64
    ;;
esac

if test "$timeout_seconds" -eq 0 || test "$interval_seconds" -eq 0; then
  echo "wait-for-container-health: timeout and interval must be positive" >&2
  exit 64
fi

command -v docker >/dev/null 2>&1 || {
  echo "wait-for-container-health: docker is not available" >&2
  exit 69
}

elapsed_seconds=0
while :; do
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || true)"
  if test "$status" = "healthy"; then
    exit 0
  fi

  if test "$elapsed_seconds" -ge "$timeout_seconds"; then
    docker logs --tail 80 "$container" >&2 || true
    echo "wait-for-container-health: $container did not become healthy within ${timeout_seconds}s; current status: ${status:-missing}" >&2
    exit 1
  fi

  sleep_seconds=$interval_seconds
  remaining_seconds=$((timeout_seconds - elapsed_seconds))
  if test "$sleep_seconds" -gt "$remaining_seconds"; then
    sleep_seconds=$remaining_seconds
  fi

  sleep "$sleep_seconds"
  elapsed_seconds=$((elapsed_seconds + sleep_seconds))
done
