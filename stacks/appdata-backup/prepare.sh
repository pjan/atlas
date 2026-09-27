#!/bin/sh

# Provision the backup directories on Volume 1. RunStackService does not run
# stack pre_deploy hooks, so the Action runs this service before every backup.

set -eu

ensure_dir() {
  path=$1
  mode=$2

  if test -L "$path"; then
    printf 'prepare: error: refusing symbolic link: %s\n' "$path" >&2
    exit 1
  fi
  mkdir -p "$path"
  chown 0:0 "$path"
  chmod "$mode" "$path"
  printf 'prepare: ensured %s %s\n' "$mode" "$path" >&2
}

ensure_dir /backups/appdata 0700
ensure_dir /backups/appdata/snapshots 0700
ensure_dir /backups/.metrics 0755
