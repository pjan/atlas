#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
hostfs="$repo_root/scripts/atlas-hostfs.sh"
test_root="$repo_root/validation-output/atlas-hostfs-test.$$"
image=$(sh "$hostfs" image-ref)
test_volume="atlas-hostfs-test-$$"

fail() {
  printf 'test-atlas-hostfs: %s\n' "$*" >&2
  exit 1
}

expect_failure() {
  if "$@" >/dev/null 2>&1; then
    fail "command unexpectedly succeeded: $*"
  fi
}

cleanup() {
  docker volume rm "$test_volume" >/dev/null 2>&1 || true
  if test -d "$test_root"; then
    docker run --rm \
      --network none \
      --mount "type=bind,src=$test_root,dst=/cleanup" \
      "$image" \
      rm -rf /cleanup/volume1 /cleanup/volume2 /cleanup/source.txt \
      >/dev/null 2>&1 || true
    rm -rf "$test_root"
  fi
}

trap cleanup EXIT HUP INT TERM

mkdir -p "$test_root/volume1" "$test_root/volume2"

bind_owner=$(docker run --rm \
  --network none \
  --mount "type=bind,src=$test_root/volume2,dst=/host" \
  "$image" \
  sh -eu -c '
    mkdir /host/ownership-probe
    chown 1000:1000 /host/ownership-probe
    stat -c "%u:%g" /host/ownership-probe
    rmdir /host/ownership-probe
  ')

if test "$bind_owner" = 1000:1000; then
  test_uid=1000
  test_gid=1000
  wrong_uid=0
else
  test_uid=0
  test_gid=0
  wrong_uid=1000
  printf 'test-atlas-hostfs: bind ownership is virtualized; using 0:0 for bind-path integration\n' >&2
fi

docker volume create "$test_volume" >/dev/null
actual=$(docker run --rm \
  --network none \
  --read-only \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  --cap-add CHOWN \
  --cap-add DAC_OVERRIDE \
  --cap-add FOWNER \
  --mount "type=volume,src=$test_volume,dst=/data" \
  "$image" \
  sh -eu -c '
    mkdir /data/private
    chown 1000:1000 /data/private
    chmod 0750 /data/private
    stat -c "%u:%g %a" /data/private
  ')
test "$actual" = '1000:1000 750' || fail "native volume ownership failed: $actual"
docker run --rm \
  --network none \
  --read-only \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  --user 1000:1000 \
  --mount "type=volume,src=$test_volume,dst=/data" \
  "$image" \
  sh -eu -c 'probe=$(mktemp /data/private/.write-test.XXXXXX); rm -f "$probe"'

export ATLAS_HOSTFS_TESTING=1
export ATLAS_HOSTFS_TEST_ROOT=$test_root

ATLAS_HOSTFS_DRY_RUN=1 sh "$hostfs" ensure-dir \
  /volume2/appdata/dry-run 1000 1000 0750
test ! -e "$test_root/volume2/appdata/dry-run"

expect_failure env ATLAS_HOSTFS_DRY_RUN=1 sh "$hostfs" ensure-dir \
  /etc/atlas 1000 1000 0750
expect_failure env ATLAS_HOSTFS_DRY_RUN=1 sh "$hostfs" ensure-dir \
  /volume2/appdata 1000 1000 0750
expect_failure env ATLAS_HOSTFS_DRY_RUN=1 sh "$hostfs" ensure-dir \
  /volume2/appdata/../escape 1000 1000 0750
expect_failure env ATLAS_HOSTFS_DRY_RUN=1 sh "$hostfs" ensure-dir \
  /volume2/appdata/unsupported,path 1000 1000 0750
expect_failure env ATLAS_HOSTFS_DRY_RUN=1 sh "$hostfs" ensure-dir \
  /volume2/appdata/test invalid 1000 0750
expect_failure env ATLAS_HOSTFS_DRY_RUN=1 sh "$hostfs" ensure-dir \
  /volume2/appdata/test 1000 1000 775
expect_failure env ATLAS_HOSTFS_DRY_RUN=1 sh "$hostfs" repair-tree-owner \
  /volume1/data/library 999 10 --confirm-private-tree

sh "$hostfs" ensure-dir /volume2/appdata/test-private "$test_uid" "$test_gid" 0700
chmod 000 "$test_root/volume2/appdata"
sh "$hostfs" assert-writable /volume2/appdata/test-private "$test_uid" "$test_gid"
sh "$hostfs" audit-tree /volume2/appdata/test-private "$test_uid" "$test_gid"
chmod 0755 "$test_root/volume2/appdata"

actual=$(docker run --rm \
  --network none \
  --mount "type=bind,src=$test_root/volume2/appdata,dst=/host,readonly" \
  "$image" \
  stat -c '%u:%g %a' /host/test-private)
test "$actual" = "$test_uid:$test_gid 700" || fail "unexpected directory metadata: $actual"

printf 'managed configuration\n' > "$test_root/source.txt"
sh "$hostfs" install-file \
  "$test_root/source.txt" \
  /volume2/appdata/test-private/config.txt \
  "$test_uid" "$test_gid" 0600

actual=$(docker run --rm \
  --network none \
  --mount "type=bind,src=$test_root/volume2/appdata,dst=/host,readonly" \
  "$image" \
  sh -eu -c 'stat -c "%u:%g %a" /host/test-private/config.txt; cat /host/test-private/config.txt')
expected=$(printf '%s:%s 600\nmanaged configuration' "$test_uid" "$test_gid")
test "$actual" = "$expected" || fail "managed file content or metadata is incorrect"

sh "$hostfs" audit-tree /volume2/appdata/test-private "$test_uid" "$test_gid"

if test "$bind_owner" = 1000:1000; then
  docker run --rm \
    --network none \
    --mount "type=bind,src=$test_root/volume2/appdata,dst=/host" \
    "$image" \
    sh -eu -c 'touch /host/test-private/wrong-owner; chown "$1:$2" /host/test-private/wrong-owner' \
    _ "$wrong_uid" "$test_gid"

  expect_failure sh "$hostfs" audit-tree /volume2/appdata/test-private "$test_uid" "$test_gid"
  ATLAS_HOSTFS_DRY_RUN=1 sh "$hostfs" repair-tree-owner \
    /volume2/appdata/test-private "$test_uid" "$test_gid" --confirm-private-tree
  expect_failure sh "$hostfs" audit-tree /volume2/appdata/test-private "$test_uid" "$test_gid"
  sh "$hostfs" repair-tree-owner \
    /volume2/appdata/test-private "$test_uid" "$test_gid" --confirm-private-tree
  sh "$hostfs" audit-tree /volume2/appdata/test-private "$test_uid" "$test_gid"
else
  printf 'test-atlas-hostfs: recursive repair test requires native Linux bind ownership; skipped\n' >&2
fi

mkdir -p "$test_root/outside"
ln -s "$test_root/outside" "$test_root/volume2/appdata/escape"
expect_failure sh "$hostfs" ensure-dir \
  /volume2/appdata/escape/child "$test_uid" "$test_gid" 0750
test ! -e "$test_root/outside/child"

sh "$hostfs" ensure-dir \
  /volume2/appdata/.atlas-permission-test "$test_uid" "$test_gid" 0750
sh "$hostfs" remove-canary /volume2/appdata/.atlas-permission-test
test ! -e "$test_root/volume2/appdata/.atlas-permission-test"
expect_failure sh "$hostfs" remove-canary /volume2/appdata/test-private

printf 'test-atlas-hostfs: passed\n'
