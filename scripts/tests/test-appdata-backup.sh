#!/bin/sh
# Runs stacks/appdata-backup/backup.sh in its pinned image against a test
# tree: Jupyter environments and caches are neither copied nor counted, and
# everything else in the homes is (README "Jupyter").

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P)
stack="$repo_root/stacks/appdata-backup"
image=$(sed -n 's|^ *image: *\(instrumentisto/rsync-ssh:[^ ]*\)$|\1|p' "$stack/compose.yaml" | head -n 1)
test_root=$(mktemp -d "${TMPDIR:-/tmp}/atlas-appdata-backup-test.XXXXXX")

fail() {
  printf 'test-appdata-backup: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  # Files written by the root container; remove them from inside one.
  docker run --rm -v "$test_root:/t" --entrypoint /bin/sh "$image" -c 'rm -rf /t/*' >/dev/null 2>&1 || true
  rm -rf "$test_root"
}

trap cleanup EXIT HUP INT TERM
test -n "$image" || fail "no rsync image in $stack/compose.yaml"

source=$test_root/appdata
homes=$source/jupyterhub/home
mkdir -p "$source/sonarr" "$test_root/bootstrap" "$test_root/backups/appdata/snapshots" \
  "$test_root/backups/.metrics" "$test_root/backups/komodo" "$test_root/backups/plex" "$test_root/backups/roonserver"
touch "$source/.atlas-backup-source" "$source/sonarr/config.xml"

files() {
  directory=$1
  count=$2
  mkdir -p "$directory"
  i=0
  while test "$i" -lt "$count"; do
    i=$((i + 1))
    touch "$directory/f$i"
  done
}

# Kept: notebooks, manifests, kernelspecs, ~/.local, and look-alike siblings.
mkdir -p "$homes/alice/proj" "$homes/alice/envs" "$homes/alice/.local/share/jupyter/kernels/proj" "$homes/bob"
touch "$homes/alice/nb.ipynb" "$homes/alice/proj/pyproject.toml" "$homes/alice/proj/uv.lock" \
  "$homes/alice/envs/geo.yml" "$homes/alice/.local/share/jupyter/kernels/proj/kernel.json" "$homes/bob/notes.md"
# A marker in a home itself is ignored: the home stays in the backup.
touch "$homes/alice/pyvenv.cfg"
files "$homes/alice/starXdir" 2
files "$homes/alice/brack" 2
newline_dir="$homes/bob/new
line"
files "$newline_dir" 2
touch "$newline_dir/pyvenv.cfg"

# Left out: virtualenvs, conda environments, caches (with a nested venv).
files "$homes/alice/proj/.venv/lib" 5
touch "$homes/alice/proj/.venv/pyvenv.cfg"
files "$homes/alice/proj/.venv/lib/inner" 2
touch "$homes/alice/proj/.venv/lib/inner/pyvenv.cfg"
files "$homes/alice/ds/bin" 3
touch "$homes/alice/ds/pyvenv.cfg"
files "$homes/alice/envs/geo/conda-meta" 2
touch "$homes/alice/envs/geo/conda-meta/history"
files "$homes/alice/star*dir" 2
touch "$homes/alice/star*dir/pyvenv.cfg"
files "$homes/alice/br[a]ck" 2
touch "$homes/alice/br[a]ck/pyvenv.cfg"
files "$homes/alice/.cache/uv" 4
files "$homes/bob/.conda/pkgs" 3

run_backup() {
  docker run --rm --network none --read-only --tmpfs /tmp --user 0:0 \
    --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add DAC_READ_SEARCH \
    --cap-add FOWNER --cap-add FSETID --security-opt no-new-privileges:true \
    -e APPDATA_BACKUP_MIN_FILES=1 \
    -v "$source:/source/appdata:ro" -v "$test_root/bootstrap:/source/komodo-bootstrap:ro" \
    -v "$test_root/backups/komodo:/inspect/komodo:ro" -v "$test_root/backups/plex:/inspect/plex:ro" \
    -v "$test_root/backups/roonserver:/inspect/roonserver:ro" \
    -v "$test_root/backups/appdata:/target" -v "$test_root/backups/.metrics:/metrics" \
    -v "$stack/backup.sh:/backup.sh:ro" -v "$stack/filters.txt:/filters.txt:ro" \
    --entrypoint /bin/sh "$image" /backup.sh "$1"
}

run_backup check 2> "$test_root/check.log" || { cat "$test_root/check.log" >&2; fail "backup check failed"; }
run_backup run 2> "$test_root/run.log" || { cat "$test_root/run.log" >&2; fail "backup run failed"; }

snapshot=$test_root/backups/appdata/latest/appdata
test -d "$snapshot" || fail "no snapshot written"

for kept in sonarr/config.xml jupyterhub/home/alice/nb.ipynb jupyterhub/home/alice/pyvenv.cfg \
  jupyterhub/home/alice/proj/pyproject.toml jupyterhub/home/alice/proj/uv.lock jupyterhub/home/alice/envs/geo.yml \
  jupyterhub/home/alice/.local/share/jupyter/kernels/proj/kernel.json jupyterhub/home/bob/notes.md \
  jupyterhub/home/alice/starXdir/f1 jupyterhub/home/alice/brack/f1; do
  test -e "$snapshot/$kept" || fail "missing from snapshot: $kept"
done
test -e "$snapshot/jupyterhub/home/bob/new
line/pyvenv.cfg" || fail "a name with a newline must stay in the backup"

for left_out in jupyterhub/home/alice/proj/.venv jupyterhub/home/alice/ds jupyterhub/home/alice/envs/geo \
  'jupyterhub/home/alice/star*dir' 'jupyterhub/home/alice/br[a]ck' jupyterhub/home/alice/.cache \
  jupyterhub/home/bob/.conda/pkgs; do
  test ! -e "$snapshot/$left_out" || fail "copied although left out: $left_out"
done

# The completeness check counts what is copied (nothing in this tree is left
# out by filters.txt, so the two must be equal).
copied=$(find "$snapshot" -type f | wc -l | tr -d ' ')
recorded=$(cat "$test_root/backups/appdata/latest/.atlas-file-count")
test "$copied" = "$recorded" || fail "recorded count $recorded, but $copied files copied"
grep -q 'jupyter: leaving out 7 environment and cache directories' "$test_root/run.log" \
  || { cat "$test_root/run.log" >&2; fail "expected 7 left-out directories (nested venv folded into its parent)"; }

echo 'test-appdata-backup: passed'
