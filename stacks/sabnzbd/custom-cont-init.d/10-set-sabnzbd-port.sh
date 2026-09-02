#!/usr/bin/with-contenv bash
set -euo pipefail

port="${SABNZBD_PORT:-8085}"
target='--server "$FAMILY"'
desired="--server \"0.0.0.0:${port}\""

case "$port" in
  ''|*[!0-9]*)
    echo "Invalid SABNZBD_PORT: $port" >&2
    exit 1
    ;;
esac

patch_runner() {
  local service_run="$1"
  local tmp

  if grep -Fq -- "$desired" "$service_run"; then
    return 0
  fi

  if ! grep -Fq -- "$target" "$service_run"; then
    echo "Unexpected SABnzbd service runner; refusing to patch $service_run" >&2
    return 1
  fi

  tmp="$(mktemp)"
  sed 's|--server "\$FAMILY"|--server "0.0.0.0:'"${port}"'"|g' "$service_run" > "$tmp"
  cat "$tmp" > "$service_run"
  rm -f "$tmp"
}

if [[ -n "${SABNZBD_SERVICE_RUN:-}" ]]; then
  patch_runner "$SABNZBD_SERVICE_RUN"
  exit 0
fi

shopt -s nullglob
service_runs=(
  /etc/s6-overlay/s6-rc.d/svc-sabnzbd/run
  /run/s6/db/servicedirs/svc-sabnzbd/run
  /run/s6-rc:s6-rc-init:*/servicedirs/svc-sabnzbd/run
)

if [[ ${#service_runs[@]} -eq 0 ]]; then
  echo "No SABnzbd service runners found" >&2
  exit 1
fi

for service_run in "${service_runs[@]}"; do
  patch_runner "$service_run"
done
