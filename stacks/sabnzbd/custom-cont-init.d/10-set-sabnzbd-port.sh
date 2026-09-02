#!/usr/bin/with-contenv bash
set -euo pipefail

port="${SABNZBD_PORT:-8085}"
service_run="${SABNZBD_SERVICE_RUN:-/etc/s6-overlay/s6-rc.d/svc-sabnzbd/run}"
target='--server "$FAMILY"'
desired="--server \"0.0.0.0:${port}\""

case "$port" in
  ''|*[!0-9]*)
    echo "Invalid SABNZBD_PORT: $port" >&2
    exit 1
    ;;
esac

if grep -Fq -- "$desired" "$service_run"; then
  exit 0
fi

if ! grep -Fq -- "$target" "$service_run"; then
  echo "Unexpected SABnzbd service runner; refusing to patch $service_run" >&2
  exit 1
fi

tmp="$(mktemp)"
sed 's|--server "\$FAMILY"|--server "0.0.0.0:'"${port}"'"|g' "$service_run" > "$tmp"
cat "$tmp" > "$service_run"
rm -f "$tmp"
