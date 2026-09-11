#!/bin/sh

set -eu

# renovate: datasource=docker depName=busybox
ATLAS_INIT_IMAGE='busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0'

readonly ATLAS_INIT_IMAGE

ATLAS_HOSTFS_SOURCE_PREFIX=

case "${ATLAS_HOSTFS_TESTING:-0}" in
  1)
    if test -z "${ATLAS_HOSTFS_TEST_ROOT:-}"; then
      printf 'atlas-hostfs: error: ATLAS_HOSTFS_TEST_ROOT is required in test mode\n' >&2
      exit 65
    fi
    case "$ATLAS_HOSTFS_TEST_ROOT" in
      /*) ;;
      *) printf 'atlas-hostfs: error: ATLAS_HOSTFS_TEST_ROOT must be absolute\n' >&2; exit 65 ;;
    esac
    case "$ATLAS_HOSTFS_TEST_ROOT" in
      *','*) printf 'atlas-hostfs: error: ATLAS_HOSTFS_TEST_ROOT contains an unsupported character\n' >&2; exit 65 ;;
    esac
    test -d "$ATLAS_HOSTFS_TEST_ROOT" || {
      printf 'atlas-hostfs: error: ATLAS_HOSTFS_TEST_ROOT does not exist\n' >&2
      exit 65
    }
    ATLAS_HOSTFS_SOURCE_PREFIX=$(CDPATH= cd -- "$ATLAS_HOSTFS_TEST_ROOT" && pwd -P)
    ;;
  0)
    if test -n "${ATLAS_HOSTFS_TEST_ROOT:-}"; then
      printf 'atlas-hostfs: error: ATLAS_HOSTFS_TEST_ROOT requires ATLAS_HOSTFS_TESTING=1\n' >&2
      exit 65
    fi
    ;;
  *)
    printf 'atlas-hostfs: error: ATLAS_HOSTFS_TESTING must be 0 or 1\n' >&2
    exit 65
    ;;
esac

readonly ATLAS_HOSTFS_SOURCE_PREFIX

log() {
  printf 'atlas-hostfs: %s\n' "$*" >&2
}

fail() {
  log "error: $*"
  exit 65
}

usage() {
  cat <<'EOF'
Usage:
  atlas-hostfs.sh image-ref
  atlas-hostfs.sh ensure-base ABSOLUTE_BASE_PATH
  atlas-hostfs.sh ensure-dir ABSOLUTE_PATH UID GID OCTAL_MODE
  atlas-hostfs.sh ensure-shared-dir ABSOLUTE_DATA_PATH UID GID OCTAL_MODE
  atlas-hostfs.sh ensure-file ABSOLUTE_PATH UID GID OCTAL_MODE
  atlas-hostfs.sh assert-writable ABSOLUTE_PATH UID GID
  atlas-hostfs.sh install-file SOURCE ABSOLUTE_DESTINATION UID GID OCTAL_MODE
  atlas-hostfs.sh audit-tree ABSOLUTE_PRIVATE_TREE UID GID
  atlas-hostfs.sh repair-tree-owner ABSOLUTE_PRIVATE_TREE UID GID --confirm-private-tree
  atlas-hostfs.sh remove-canary ABSOLUTE_CANARY_PATH

Allowed NAS roots:
  /volume1/data
  /volume1/backups
  /volume2/appdata
  /volume2/tmp

Set ATLAS_HOSTFS_DRY_RUN=1 to validate and print an operation without changing data.
EOF
}

require_docker() {
  command -v docker >/dev/null 2>&1 || fail "docker is not available"
}

is_dry_run() {
  case "${ATLAS_HOSTFS_DRY_RUN:-0}" in
    0) return 1 ;;
    1) return 0 ;;
    *) fail "ATLAS_HOSTFS_DRY_RUN must be 0 or 1" ;;
  esac
}

validate_unsigned_integer() {
  label=$1
  value=$2

  case "$value" in
    ''|*[!0-9]*) fail "$label must be an unsigned integer" ;;
  esac
}

validate_mode() {
  mode=$1

  case "$mode" in
    [0-7][0-7][0-7][0-7]) ;;
    *) fail "mode must contain exactly four octal digits" ;;
  esac
}

validate_absolute_path() {
  path=$1

  case "$path" in
    /*) ;;
    *) fail "path must be absolute: $path" ;;
  esac

  case "$path" in
    */) fail "path must not end with a slash: $path" ;;
    *//*|*/./*|*/../*|*/.|*/..) fail "path contains a non-canonical segment: $path" ;;
    *'*'*|*'?'*|*'['*) fail "path contains a shell glob character: $path" ;;
    *','*) fail "path contains an unsupported character: $path" ;;
  esac

  if LC_ALL=C printf '%s' "$path" | grep -q '[[:cntrl:]]'; then
    fail "path contains a control character"
  fi
}

validate_base() {
  base=$1
  validate_absolute_path "$base"

  case "$base" in
    /volume1/data|/volume1/backups|/volume2/appdata|/volume2/tmp) ;;
    *) fail "base path is not allowlisted: $base" ;;
  esac
}

base_for_child() {
  path=$1
  validate_absolute_path "$path"

  case "$path" in
    /volume1/data/*) printf '%s\n' /volume1/data ;;
    /volume1/backups/*) printf '%s\n' /volume1/backups ;;
    /volume2/appdata/*) printf '%s\n' /volume2/appdata ;;
    /volume2/tmp/*) printf '%s\n' /volume2/tmp ;;
    *) fail "path is not below an allowlisted root: $path" ;;
  esac
}

container_path_for() {
  path=$1
  base=$2
  relative=${path#"$base"}
  printf '/host%s\n' "$relative"
}

host_source_for() {
  logical_path=$1
  printf '%s%s\n' "$ATLAS_HOSTFS_SOURCE_PREFIX" "$logical_path"
}

validate_private_tree() {
  path=$1
  validate_absolute_path "$path"

  case "$path" in
    /volume2/appdata/*)
      relative=${path#/volume2/appdata/}
      ;;
    /volume2/tmp/*)
      relative=${path#/volume2/tmp/}
      ;;
    *)
      fail "recursive operations are limited to private appdata or private scratch trees: $path"
      ;;
  esac

  case "$relative" in
    ''|*/*) fail "recursive operations require exactly one private tree below the base: $path" ;;
  esac
}

validate_canary_path() {
  path=$1
  validate_absolute_path "$path"

  case "$path" in
    /volume1/data/.atlas-permission-test|\
    /volume1/backups/.atlas-permission-test|\
    /volume2/appdata/.atlas-permission-test|\
    /volume2/tmp/.atlas-permission-test) ;;
    *) fail "remove-canary accepts only an exact Atlas canary path: $path" ;;
  esac
}

ensure_base() (
  base=$1
  validate_base "$base"

  case "$base" in
    /volume1/*) volume=/volume1 ;;
    /volume2/*) volume=/volume2 ;;
  esac
  source_path=$(host_source_for "$volume")

  if is_dry_run; then
    log "dry-run ensure-base path=$base"
    return 0
  fi

  require_docker
  log "ensuring base path $base"
  docker run --rm \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add DAC_OVERRIDE \
    --mount "type=bind,src=$source_path,dst=/host$volume" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c 'test ! -L "$1"; mkdir -p "$1"; test ! -L "$1"' _ "/host$base"
)

assert_writable() (
  path=$1
  uid=$2
  gid=$3

  validate_unsigned_integer uid "$uid"
  validate_unsigned_integer gid "$gid"
  base=$(base_for_child "$path")
  container_path=$(container_path_for "$path" "$base")
  base_source_path=$(host_source_for "$base")
  target_source_path=$(host_source_for "$path")

  if is_dry_run; then
    log "dry-run assert-writable path=$path uid=$uid gid=$gid"
    return 0
  fi

  require_docker
  docker run --rm \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add DAC_READ_SEARCH \
    --mount "type=bind,src=$base_source_path,dst=/host,readonly" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c '
      target=$1
      relative=${target#/host/}
      current=/host
      previous_ifs=$IFS
      IFS=/
      set -- $relative
      IFS=$previous_ifs

      for component do
        current="$current/$component"
        test ! -L "$current"
        test -d "$current"
      done

      test "$(realpath "$target")" = "$target"
    ' _ "$container_path"

  docker run --rm \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --user "$uid:$gid" \
    --mount "type=bind,src=$target_source_path,dst=/target" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c '
      target=$1
      test -d "$target"
      test "$(realpath "$target")" = "$target"
      umask 077
      probe=$(mktemp "$target/.atlas-write-test.XXXXXX") || {
        printf "atlas-hostfs: write probe failed path=%s uid=%s gid=%s\n" \
          "$target" "$2" "$3" >&2
        exit 1
      }
      trap '\''rm -f "$probe"'\'' EXIT HUP INT TERM
      rm -f "$probe"
      trap - EXIT HUP INT TERM
    ' _ /target "$uid" "$gid"

  log "write probe passed path=$path uid=$uid gid=$gid"
)

ensure_dir() (
  path=$1
  uid=$2
  gid=$3
  mode=$4

  validate_unsigned_integer uid "$uid"
  validate_unsigned_integer gid "$gid"
  validate_mode "$mode"
  base=$(base_for_child "$path")
  container_path=$(container_path_for "$path" "$base")
  source_path=$(host_source_for "$base")

  if is_dry_run; then
    log "dry-run ensure-dir path=$path uid=$uid gid=$gid mode=$mode"
    return 0
  fi

  ensure_base "$base"
  require_docker
  log "ensuring directory path=$path uid=$uid gid=$gid mode=$mode"
  docker run --rm \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add CHOWN \
    --cap-add DAC_OVERRIDE \
    --cap-add FOWNER \
    --mount "type=bind,src=$source_path,dst=/host" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c '
      target=$1
      uid=$2
      gid=$3
      mode=$4
      relative=${target#/host/}
      current=/host
      previous_ifs=$IFS
      IFS=/
      set -- $relative
      IFS=$previous_ifs

      for component do
        current="$current/$component"
        test ! -L "$current"
        if test ! -e "$current"; then
          mkdir "$current"
          chown "$uid:$gid" "$current"
          chmod "$mode" "$current"
        fi
        test -d "$current"
      done

      test "$(realpath "$target")" = "$target"
      chown "$uid:$gid" "$target"
      chmod "$mode" "$target"

      actual=$(stat -c "%u:%g %a" "$target")
      expected="$uid:$gid ${mode#0}"
      test "$actual" = "$expected"
    ' _ "$container_path" "$uid" "$gid" "$mode"

  assert_writable "$path" "$uid" "$gid"
)

ensure_shared_dir() (
  path=$1
  uid=$2
  gid=$3
  mode=$4

  case "$path" in
    /volume1/data/*) ;;
    *) fail "ensure-shared-dir accepts only a child of /volume1/data: $path" ;;
  esac
  validate_unsigned_integer uid "$uid"
  validate_unsigned_integer gid "$gid"
  validate_mode "$mode"
  base=$(base_for_child "$path")
  container_path=$(container_path_for "$path" "$base")
  source_path=$(host_source_for "$base")

  if is_dry_run; then
    log "dry-run ensure-shared-dir path=$path create_uid=$uid gid=$gid mode=$mode"
    return 0
  fi

  ensure_base "$base"
  require_docker
  log "ensuring shared directory path=$path create_uid=$uid gid=$gid mode=$mode owner=preserve"
  docker run --rm \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add CHOWN \
    --cap-add DAC_OVERRIDE \
    --cap-add FOWNER \
    --mount "type=bind,src=$source_path,dst=/host" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c '
      target=$1
      uid=$2
      gid=$3
      mode=$4
      relative=${target#/host/}
      current=/host
      previous_ifs=$IFS
      IFS=/
      set -- $relative
      IFS=$previous_ifs

      for component do
        current="$current/$component"
        test ! -L "$current"
        if test ! -e "$current"; then
          mkdir "$current"
          chown "$uid:$gid" "$current"
          chmod "$mode" "$current"
        fi
        test -d "$current"
      done

      test "$(realpath "$target")" = "$target"
      owner=$(stat -c "%u" "$target")
      chgrp "$gid" "$target"
      chmod "$mode" "$target"

      actual=$(stat -c "%u:%g %a" "$target")
      expected="$owner:$gid ${mode#0}"
      test "$actual" = "$expected"
    ' _ "$container_path" "$uid" "$gid" "$mode"

  assert_writable "$path" "$uid" "$gid"
)

ensure_file() (
  path=$1
  uid=$2
  gid=$3
  mode=$4

  validate_unsigned_integer uid "$uid"
  validate_unsigned_integer gid "$gid"
  validate_mode "$mode"
  base=$(base_for_child "$path")
  container_path=$(container_path_for "$path" "$base")
  base_source_path=$(host_source_for "$base")
  target_source_path=$(host_source_for "$path")

  if is_dry_run; then
    log "dry-run ensure-file path=$path uid=$uid gid=$gid mode=$mode"
    return 0
  fi

  require_docker
  log "ensuring file path=$path uid=$uid gid=$gid mode=$mode"
  docker run --rm \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add CHOWN \
    --cap-add DAC_OVERRIDE \
    --cap-add FOWNER \
    --mount "type=bind,src=$base_source_path,dst=/host" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c '
      target=$1
      uid=$2
      gid=$3
      mode=$4
      parent=${target%/*}
      relative=${parent#/host/}
      current=/host
      previous_ifs=$IFS
      IFS=/
      set -- $relative
      IFS=$previous_ifs

      for component do
        current="$current/$component"
        test ! -L "$current"
        test -d "$current"
      done

      test "$(realpath "$parent")" = "$parent"
      test ! -L "$target"
      if test ! -e "$target"; then
        umask 077
        : > "$target"
      fi
      test -f "$target"
      chown "$uid:$gid" "$target"
      chmod "$mode" "$target"

      actual=$(stat -c "%u:%g %a" "$target")
      expected="$uid:$gid ${mode#0}"
      test "$actual" = "$expected"
    ' _ "$container_path" "$uid" "$gid" "$mode"

  docker run --rm \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --user "$uid:$gid" \
    --mount "type=bind,src=$target_source_path,dst=/target" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c 'test -f /target; test -r /target; test -w /target'

  log "file access probe passed path=$path uid=$uid gid=$gid"
)

checksum_stdin() (
  docker run --rm -i \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c 'sha256sum | cut -d " " -f 1'
)

checksum_file() (
  path=$1
  base=$2
  container_path=$3
  source_path=$(host_source_for "$base")

  docker run --rm \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add DAC_READ_SEARCH \
    --mount "type=bind,src=$source_path,dst=/host,readonly" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c 'test -f "$1"; sha256sum "$1" | cut -d " " -f 1' _ "$container_path"
)

install_file() (
  source_file=$1
  destination=$2
  uid=$3
  gid=$4
  mode=$5

  test -f "$source_file" || fail "source file does not exist: $source_file"
  test ! -L "$source_file" || fail "source file must not be a symlink: $source_file"
  validate_unsigned_integer uid "$uid"
  validate_unsigned_integer gid "$gid"
  validate_mode "$mode"
  base=$(base_for_child "$destination")
  container_destination=$(container_path_for "$destination" "$base")
  source_path=$(host_source_for "$base")
  destination_parent=${destination%/*}

  if is_dry_run; then
    log "dry-run install-file source=$source_file destination=$destination uid=$uid gid=$gid mode=$mode"
    return 0
  fi

  ensure_dir "$destination_parent" "$uid" "$gid" 0750
  require_docker
  log "installing managed file source=$source_file destination=$destination uid=$uid gid=$gid mode=$mode"
  docker run --rm -i \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add CHOWN \
    --cap-add DAC_OVERRIDE \
    --cap-add FOWNER \
    --mount "type=bind,src=$source_path,dst=/host" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c '
      destination=$1
      uid=$2
      gid=$3
      mode=$4
      test ! -L "$destination"
      test "$(realpath "${destination%/*}")" = "${destination%/*}"
      temporary="${destination}.atlas-tmp.$$"
      cleanup() { rm -f "$temporary"; }
      trap cleanup EXIT HUP INT TERM
      umask 077
      cat > "$temporary"
      chown "$uid:$gid" "$temporary"
      chmod "$mode" "$temporary"
      mv -f "$temporary" "$destination"
      trap - EXIT HUP INT TERM
    ' _ "$container_destination" "$uid" "$gid" "$mode" < "$source_file"

  source_checksum=$(checksum_stdin < "$source_file")
  destination_checksum=$(checksum_file "$destination" "$base" "$container_destination")
  test "$source_checksum" = "$destination_checksum" || fail "checksum mismatch after installing $destination"
  log "checksum verified destination=$destination"
)

audit_tree() (
  path=$1
  uid=$2
  gid=$3

  validate_private_tree "$path"
  validate_unsigned_integer uid "$uid"
  validate_unsigned_integer gid "$gid"
  base=$(base_for_child "$path")
  container_path=$(container_path_for "$path" "$base")
  source_path=$(host_source_for "$base")

  if is_dry_run; then
    log "dry-run audit-tree path=$path uid=$uid gid=$gid"
    return 0
  fi

  require_docker
  log "auditing private tree path=$path expected=$uid:$gid"
  docker run --rm \
    --network none \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add DAC_READ_SEARCH \
    --mount "type=bind,src=$source_path,dst=/host,readonly" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c '
      target=$1
      uid=$2
      gid=$3
      test -d "$target"
      test "$(realpath "$target")" = "$target"
      mismatches=/tmp/atlas-owner-mismatches
      find "$target" -xdev ! -type l \( ! -user "$uid" -o ! -group "$gid" \) -print > "$mismatches"
      count=$(wc -l < "$mismatches" | tr -d " ")
      if test "$count" -ne 0; then
        cat "$mismatches"
        printf "mismatch-count: %s\\n" "$count" >&2
        exit 3
      fi
      printf "mismatch-count: 0\\n" >&2
    ' _ "$container_path" "$uid" "$gid"
)

repair_tree_owner() (
  path=$1
  uid=$2
  gid=$3
  confirmation=$4

  validate_private_tree "$path"
  validate_unsigned_integer uid "$uid"
  validate_unsigned_integer gid "$gid"
  test "$confirmation" = --confirm-private-tree || fail "repair requires --confirm-private-tree"
  base=$(base_for_child "$path")
  container_path=$(container_path_for "$path" "$base")
  source_path=$(host_source_for "$base")

  if is_dry_run; then
    log "dry-run repair-tree-owner path=$path uid=$uid gid=$gid"
    return 0
  fi

  if audit_tree "$path" "$uid" "$gid"; then
    log "private tree already has the expected owner path=$path"
    return 0
  else
    audit_status=$?
    test "$audit_status" -eq 3 || return "$audit_status"
  fi

  require_docker
  log "repairing private tree owner path=$path uid=$uid gid=$gid"
  docker run --rm \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add CHOWN \
    --cap-add DAC_OVERRIDE \
    --cap-add FOWNER \
    --mount "type=bind,src=$source_path,dst=/host" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c '
      target=$1
      uid=$2
      gid=$3
      test -d "$target"
      test "$(realpath "$target")" = "$target"
      find "$target" -xdev ! -type l -exec chown "$uid:$gid" {} +
    ' _ "$container_path" "$uid" "$gid"

  audit_tree "$path" "$uid" "$gid"
)

remove_canary() (
  path=$1
  validate_canary_path "$path"
  base=$(base_for_child "$path")
  container_path=$(container_path_for "$path" "$base")
  source_path=$(host_source_for "$base")

  if is_dry_run; then
    log "dry-run remove-canary path=$path"
    return 0
  fi

  require_docker
  log "removing canary path=$path"
  docker run --rm \
    --network none \
    --read-only \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add DAC_OVERRIDE \
    --cap-add FOWNER \
    --mount "type=bind,src=$source_path,dst=/host" \
    "$ATLAS_INIT_IMAGE" \
    sh -eu -c '
      target=$1
      if test -e "$target" || test -L "$target"; then
        test ! -L "$target"
        test "$(realpath "$target")" = "$target"
        rm -rf "$target"
      fi
    ' _ "$container_path"
)

command=${1:-}

case "$command" in
  image-ref)
    test "$#" -eq 1 || { usage >&2; exit 64; }
    printf '%s\n' "$ATLAS_INIT_IMAGE"
    ;;
  ensure-base)
    test "$#" -eq 2 || { usage >&2; exit 64; }
    ensure_base "$2"
    ;;
  ensure-dir)
    test "$#" -eq 5 || { usage >&2; exit 64; }
    ensure_dir "$2" "$3" "$4" "$5"
    ;;
  ensure-shared-dir)
    test "$#" -eq 5 || { usage >&2; exit 64; }
    ensure_shared_dir "$2" "$3" "$4" "$5"
    ;;
  ensure-file)
    test "$#" -eq 5 || { usage >&2; exit 64; }
    ensure_file "$2" "$3" "$4" "$5"
    ;;
  assert-writable)
    test "$#" -eq 4 || { usage >&2; exit 64; }
    assert_writable "$2" "$3" "$4"
    ;;
  install-file)
    test "$#" -eq 6 || { usage >&2; exit 64; }
    install_file "$2" "$3" "$4" "$5" "$6"
    ;;
  audit-tree)
    test "$#" -eq 4 || { usage >&2; exit 64; }
    audit_tree "$2" "$3" "$4"
    ;;
  repair-tree-owner)
    test "$#" -eq 5 || { usage >&2; exit 64; }
    repair_tree_owner "$2" "$3" "$4" "$5"
    ;;
  remove-canary)
    test "$#" -eq 2 || { usage >&2; exit 64; }
    remove_canary "$2"
    ;;
  *)
    usage >&2
    exit 64
    ;;
esac
