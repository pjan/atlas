#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
helper="$repo_root/scripts/wait-for-container-health.sh"
test_root=$(mktemp -d "${TMPDIR:-/tmp}/atlas-container-health-test.XXXXXX")
mock_bin="$test_root/bin"

fail() {
  printf 'test-wait-for-container-health: %s\n' "$*" >&2
  exit 1
}

expect_failure() {
  if "$@" >/dev/null 2>&1; then
    fail "command unexpectedly succeeded: $*"
  fi
}

cleanup() {
  rm -rf "$test_root"
}

trap cleanup EXIT HUP INT TERM
mkdir -p "$mock_bin"

cat > "$mock_bin/docker" <<'EOF'
#!/bin/sh

set -eu

case "${1:-}" in
  inspect)
    count=$(cat "$MOCK_INSPECT_COUNT" 2>/dev/null || true)
    count=${count:-0}
    count=$((count + 1))
    printf '%s\n' "$count" > "$MOCK_INSPECT_COUNT"
    case "$MOCK_DOCKER_SCENARIO" in
      healthy)
        echo healthy
        ;;
      delayed)
        if test "$count" -ge 3; then
          echo healthy
        else
          echo starting
        fi
        ;;
      missing)
        exit 1
        ;;
      timeout)
        echo starting
        ;;
      *)
        exit 2
        ;;
    esac
    ;;
  logs)
    printf '%s\n' "$*" >> "$MOCK_DOCKER_LOG"
    echo "mock container logs"
    ;;
  *)
    exit 2
    ;;
esac
EOF

cat > "$mock_bin/sleep" <<'EOF'
#!/bin/sh

set -eu
printf '%s\n' "$1" >> "$MOCK_SLEEP_LOG"
EOF

chmod +x "$mock_bin/docker" "$mock_bin/sleep"

export PATH="$mock_bin:$PATH"
export MOCK_INSPECT_COUNT="$test_root/inspect-count"
export MOCK_DOCKER_LOG="$test_root/docker.log"
export MOCK_SLEEP_LOG="$test_root/sleep.log"

expect_failure sh "$helper"
expect_failure sh "$helper" gluetun 0
expect_failure sh "$helper" gluetun invalid
expect_failure sh "$helper" gluetun 10 0

MOCK_DOCKER_SCENARIO=healthy
export MOCK_DOCKER_SCENARIO
: > "$MOCK_INSPECT_COUNT"
: > "$MOCK_DOCKER_LOG"
: > "$MOCK_SLEEP_LOG"
sh "$helper" gluetun 10 5
test "$(cat "$MOCK_INSPECT_COUNT")" = 1 || fail "healthy container was inspected more than once"
test ! -s "$MOCK_SLEEP_LOG" || fail "healthy container triggered a sleep"
test ! -s "$MOCK_DOCKER_LOG" || fail "healthy container triggered log output"

MOCK_DOCKER_SCENARIO=delayed
export MOCK_DOCKER_SCENARIO
: > "$MOCK_INSPECT_COUNT"
: > "$MOCK_DOCKER_LOG"
: > "$MOCK_SLEEP_LOG"
sh "$helper" gluetun 10 5
test "$(cat "$MOCK_INSPECT_COUNT")" = 3 || fail "delayed health used an unexpected number of inspections"
test "$(cat "$MOCK_SLEEP_LOG")" = "$(printf '5\n5')" || fail "delayed health used unexpected sleep intervals"
test ! -s "$MOCK_DOCKER_LOG" || fail "delayed health triggered log output"

MOCK_DOCKER_SCENARIO=timeout
export MOCK_DOCKER_SCENARIO
: > "$MOCK_INSPECT_COUNT"
: > "$MOCK_DOCKER_LOG"
: > "$MOCK_SLEEP_LOG"
error_output="$test_root/timeout.err"
if sh "$helper" gluetun 10 5 2> "$error_output"; then
  fail "timeout scenario unexpectedly succeeded"
fi
test "$(cat "$MOCK_INSPECT_COUNT")" = 3 || fail "timeout used an unexpected number of inspections"
test "$(cat "$MOCK_SLEEP_LOG")" = "$(printf '5\n5')" || fail "timeout used unexpected sleep intervals"
grep -F 'logs --tail 80 gluetun' "$MOCK_DOCKER_LOG" >/dev/null || fail "timeout did not request container logs"
grep -F 'gluetun did not become healthy within 10s; current status: starting' "$error_output" >/dev/null || fail "timeout diagnostic is incomplete"

MOCK_DOCKER_SCENARIO=missing
export MOCK_DOCKER_SCENARIO
: > "$MOCK_INSPECT_COUNT"
: > "$MOCK_DOCKER_LOG"
: > "$MOCK_SLEEP_LOG"
error_output="$test_root/missing.err"
if sh "$helper" gluetun 5 5 2> "$error_output"; then
  fail "missing-container scenario unexpectedly succeeded"
fi
grep -F 'current status: missing' "$error_output" >/dev/null || fail "missing-container diagnostic is incomplete"

printf 'test-wait-for-container-health: passed\n'
