#!/usr/bin/env python3
"""Vendor a released Grafana plugin from pjan/grafana-plugins into the monitoring stack.

Usage: python3 scripts/update-grafana-plugin.py <plugin-id> <version>
Example: python3 scripts/update-grafana-plugin.py pjan-statetimeline-panel 1.0.0

Downloads <plugin-id>-<version>.zip and its .sha256 from the GitHub release
<plugin-id>/v<version>, checks the checksum and the plugin's id and version, and
replaces stacks/monitoring/grafana/plugins/<plugin-id>/ with its contents. It records
the release (tag, commit, checksum, and a SHA-256 per file) in
stacks/monitoring/grafana/plugin-releases.json, which scripts/validate.sh checks the
directory against, and registers every file as a Grafana config_file in stacks.toml.
Behind a TLS-inspecting proxy, set SSL_CERT_FILE to a PEM file with its CA.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


REPOSITORY = "pjan/grafana-plugins"
REPO_ROOT = Path(__file__).resolve().parent.parent
MONITORING_ROOT = REPO_ROOT / "stacks" / "monitoring"
PLUGINS_DIRECTORY = MONITORING_ROOT / "grafana" / "plugins"
RELEASES_FILE = MONITORING_ROOT / "grafana" / "plugin-releases.json"
STACKS_FILE = REPO_ROOT / "stacks.toml"


def download(url: str) -> bytes:
    # Passed explicitly: not every Python build reads SSL_CERT_FILE for urllib's default context.
    context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE"))
    with urllib.request.urlopen(url, timeout=60, context=context) as response:
        return response.read()


def tag_commit(tag: str) -> str:
    output = subprocess.run(
        ["git", "ls-remote", f"https://github.com/{REPOSITORY}", f"refs/tags/{tag}^{{}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    if not output:
        sys.exit(f"tag {tag} not found in {REPOSITORY}")
    return output[0]


def register_config_files(plugin_id: str, files: list[str]) -> None:
    """Replace the stacks.toml config_files lines of this plugin with one per file."""
    prefix = f'  {{ path = "grafana/plugins/{plugin_id}/'
    lines = STACKS_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in lines if not line.startswith(prefix)]
    anchor = max(
        (index for index, line in enumerate(kept) if line.startswith('  { path = "grafana/plugins/')),
        default=None,
    )
    if anchor is None:
        sys.exit("stacks.toml has no grafana/plugins/ config_files to add the plugin after")
    entries = [
        f'{prefix}{path}", services = ["grafana"], requires = "Restart" }},\n' for path in files
    ]
    STACKS_FILE.write_text("".join(kept[: anchor + 1] + entries + kept[anchor + 1 :]), encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    plugin_id, version = sys.argv[1], sys.argv[2]
    tag = f"{plugin_id}/v{version}"
    zip_name = f"{plugin_id}-{version}.zip"
    base = f"https://github.com/{REPOSITORY}/releases/download/{tag}"
    release = f"https://github.com/{REPOSITORY}/releases/tag/{tag}"

    archive = download(f"{base}/{zip_name}")
    expected = download(f"{base}/{zip_name}.sha256").decode().split()[0]
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        sys.exit(f"{zip_name}: SHA-256 {actual}, release says {expected}")
    commit = tag_commit(tag)

    with tempfile.TemporaryDirectory() as temporary:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            names = zipped.namelist()
            if any(not name.startswith(f"{plugin_id}/") or ".." in Path(name).parts for name in names):
                sys.exit(f"{zip_name} has entries outside {plugin_id}/")
            zipped.extractall(temporary)
        extracted = Path(temporary) / plugin_id
        manifest = json.loads((extracted / "plugin.json").read_text(encoding="utf-8"))
        if manifest.get("id") != plugin_id or manifest.get("info", {}).get("version") != version:
            sys.exit(f"{zip_name}: plugin.json has id {manifest.get('id')}, version {manifest.get('info', {}).get('version')}")

        target = PLUGINS_DIRECTORY / plugin_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(extracted, target)

    files = sorted(path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file())
    releases = json.loads(RELEASES_FILE.read_text(encoding="utf-8")) if RELEASES_FILE.exists() else {}
    releases[plugin_id] = {
        "version": version,
        "tag": tag,
        "commit": commit,
        "release": release,
        "zipSha256": actual,
        "files": {path: hashlib.sha256((target / path).read_bytes()).hexdigest() for path in files},
    }
    RELEASES_FILE.write_text(json.dumps(releases, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    register_config_files(plugin_id, files)
    print(f"{plugin_id} {version} ({commit[:12]}): {len(files)} files in {target.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
