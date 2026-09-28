#!/bin/sh

# Nightly appdata snapshot for Atlas.
#
# Modes:
#   check  Verify the source looks complete. Run before any stack is stopped.
#   run    Verify the source again, then write a dated, hard-linked snapshot.
#
# Layout under /target (/volume1/backups/appdata):
#   snapshots/YYYY-MM-DD_HHMMSS/{appdata,komodo-bootstrap}/
#   latest -> snapshots/<newest successful snapshot>
#   .last-success   epoch seconds of the newest successful snapshot
#   .in-progress    present only while a snapshot is being written

set -eu

mode=${1:-run}
source_root=/source
appdata=$source_root/appdata
sentinel=$appdata/.atlas-backup-source
target=/target
snapshots=$target/snapshots
metrics_file=/metrics/atlas_backups.prom
min_files=${APPDATA_BACKUP_MIN_FILES:-500}
min_ratio=${APPDATA_BACKUP_MIN_RATIO_PERCENT:-60}
keep_days=${APPDATA_BACKUP_KEEP_DAYS:-14}
keep_min=${APPDATA_BACKUP_KEEP_MIN:-7}
snapshot_pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}$'

started_at=$(date +%s)
source_files=0
vanished=0

log() {
  printf 'appdata-backup: %s\n' "$*" >&2
}

fail() {
  log "error: $*"
  exit 1
}

newest_mtime() {
  directory=$1
  newest=$(find "$directory" -type f -exec stat -c %Y {} + 2>/dev/null | sort -n | tail -n 1)
  printf '%s' "${newest:-0}"
}

write_metrics() {
  exit_code=$1
  finished_at=$(date +%s)
  last_success=0
  if test -f "$target/.last-success"; then
    last_success=$(cat "$target/.last-success")
  fi
  snapshot_count=0
  if test -d "$snapshots"; then
    snapshot_count=$(ls -1 "$snapshots" | grep -Ec "$snapshot_pattern" || true)
  fi
  temporary="$metrics_file.tmp"
  {
    echo '# HELP atlas_backup_last_run_timestamp_seconds Unix time of the last backup job run.'
    echo '# TYPE atlas_backup_last_run_timestamp_seconds gauge'
    echo "atlas_backup_last_run_timestamp_seconds{set=\"appdata\",mode=\"$mode\"} $finished_at"
    echo '# HELP atlas_backup_last_exit_code Exit code of the last backup job run.'
    echo '# TYPE atlas_backup_last_exit_code gauge'
    echo "atlas_backup_last_exit_code{set=\"appdata\",mode=\"$mode\"} $exit_code"
    echo '# HELP atlas_backup_last_success_timestamp_seconds Unix time of the newest successful snapshot.'
    echo '# TYPE atlas_backup_last_success_timestamp_seconds gauge'
    echo "atlas_backup_last_success_timestamp_seconds{set=\"appdata\"} $last_success"
    echo '# HELP atlas_backup_duration_seconds Duration of the last backup job run.'
    echo '# TYPE atlas_backup_duration_seconds gauge'
    echo "atlas_backup_duration_seconds{set=\"appdata\",mode=\"$mode\"} $((finished_at - started_at))"
    echo '# HELP atlas_backup_files Source files counted by the last backup job run.'
    echo '# TYPE atlas_backup_files gauge'
    echo "atlas_backup_files{set=\"appdata\"} $source_files"
    echo '# HELP atlas_backup_snapshots Local appdata snapshots present.'
    echo '# TYPE atlas_backup_snapshots gauge'
    echo "atlas_backup_snapshots{set=\"appdata\"} $snapshot_count"
    echo '# HELP atlas_backup_rsync_vanished_files 1 if rsync reported vanished source files.'
    echo '# TYPE atlas_backup_rsync_vanished_files gauge'
    echo "atlas_backup_rsync_vanished_files{set=\"appdata\"} $vanished"
    echo '# HELP atlas_backup_newest_file_timestamp_seconds Newest file modification time per backup set.'
    echo '# TYPE atlas_backup_newest_file_timestamp_seconds gauge'
    for set in komodo plex roonserver; do
      echo "atlas_backup_newest_file_timestamp_seconds{set=\"$set\"} $(newest_mtime "/inspect/$set")"
    done
  } > "$temporary"
  chmod 0644 "$temporary"
  mv -f "$temporary" "$metrics_file"
}

on_exit() {
  status=$?
  trap - EXIT
  rm -f "$target/.in-progress"
  write_metrics "$status" || log "warning: could not write metrics"
  exit "$status"
}

count_source_files() {
  find "$appdata" \
    \( -path "$appdata/roonserver" -o -path "$appdata/prometheus" \
    -o -path "$appdata/alertmanager" -o -path "$appdata/grafana" \) -prune \
    -o -type f -print | wc -l | tr -d ' '
}

check_source() {
  test -d "$appdata" || fail "source $appdata is missing"
  test -f "$sentinel" || fail "sentinel $sentinel is missing; create it only after confirming /volume2/appdata is complete"

  source_files=$(count_source_files)
  previous_files=0
  if test -f "$target/latest/.atlas-file-count"; then
    previous_files=$(cat "$target/latest/.atlas-file-count")
  fi
  required=$((previous_files * min_ratio / 100))
  if test "$required" -lt "$min_files"; then
    required=$min_files
  fi
  test "$source_files" -ge "$required" ||
    fail "source has $source_files files; at least $required required (previous snapshot: $previous_files)"
  log "source check passed: $source_files files (required $required)"
}

prune_snapshots() {
  cutoff=$(date -d "@$((started_at - keep_days * 86400))" +%Y-%m-%d_%H%M%S)
  ls -1 "$snapshots" | grep -E "$snapshot_pattern" | sort |
    awk -v cutoff="$cutoff" -v keep="$keep_min" '
      { names[NR] = $0 }
      END {
        for (i = 1; i <= NR - keep; i++) {
          if (names[i] < cutoff) print names[i]
        }
      }
    ' |
    while IFS= read -r name; do
      log "pruning snapshot $name"
      rm -rf "${snapshots:?}/$name"
    done
}

run_snapshot() {
  test -d "$snapshots" || fail "$snapshots is missing; run the prepare service first"

  for stale in "$snapshots"/*.partial; do
    if test -d "$stale"; then
      log "removing incomplete snapshot $(basename "$stale")"
      rm -rf "$stale"
    fi
  done

  : > "$target/.in-progress"
  name=$(date +%Y-%m-%d_%H%M%S)
  partial="$snapshots/$name.partial"

  set -- -aH --numeric-ids --filter='merge /filters.txt'
  if test -d "$target/latest/"; then
    set -- "$@" "--link-dest=$target/latest/"
  fi

  log "writing snapshot $name"
  rsync_status=0
  rsync "$@" "$source_root/" "$partial/" || rsync_status=$?
  case "$rsync_status" in
    0) ;;
    24)
      vanished=1
      log "warning: some source files vanished during the transfer"
      ;;
    *)
      rm -rf "$partial"
      fail "rsync exited with status $rsync_status"
      ;;
  esac

  printf '%s\n' "$source_files" > "$partial/.atlas-file-count"
  mv "$partial" "$snapshots/$name"
  rm -f "$target/latest"
  ln -s "snapshots/$name" "$target/latest"
  printf '%s\n' "$started_at" > "$target/.last-success.tmp"
  mv -f "$target/.last-success.tmp" "$target/.last-success"
  log "snapshot $name complete"

  prune_snapshots
}

trap on_exit EXIT

case "$mode" in
  check)
    check_source
    ;;
  run)
    check_source
    run_snapshot
    ;;
  *)
    fail "unknown mode: $mode (expected check or run)"
    ;;
esac
