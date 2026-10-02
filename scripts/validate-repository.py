#!/usr/bin/env python3

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib


REPO_ROOT = Path(__file__).resolve().parent.parent
STACKS_ROOT = REPO_ROOT / "stacks"
COMPOSE_VARIABLE_PATTERN = re.compile(
    r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)"
)
# Top-level Compose secrets fed from the environment (secrets.<name>.environment).
COMPOSE_SECRET_ENVIRONMENT_PATTERN = re.compile(
    r"(?m)^ {4}environment: ([A-Z][A-Z0-9_]*)\s*$"
)
KOMODO_VARIABLE_PATTERN = re.compile(r"\[\[[A-Z][A-Z0-9_]*\]\]")
README_VARIABLE_BLOCK_PATTERN = re.compile(
    r"Shared stack values managed in Komodo:\n\n```text\n(?P<variables>.*?)\n```",
    re.DOTALL,
)
SAFE_AUTOMERGE_UPDATE_TYPES = {"digest", "patch", "pin"}
MONITORING_ROOT = STACKS_ROOT / "monitoring"
ALERT_RULES_DIRECTORY = MONITORING_ROOT / "prometheus" / "rules"
# Outside the directories the monitoring containers mount.
ALERT_RULE_TESTS_DIRECTORY = MONITORING_ROOT / "prometheus-tests"
ALERTMANAGER_DIRECTORY = MONITORING_ROOT / "alertmanager"
ALERT_MESSAGE_FIXTURES_DIRECTORY = MONITORING_ROOT / "alertmanager-tests"
# The Grafana theme plugin and its schemas (outside the directory Grafana serves).
THEME_PLUGIN_DIRECTORY = MONITORING_ROOT / "grafana" / "plugins" / "atlas-theme-app"
THEME_SCHEMA_DIRECTORY = MONITORING_ROOT / "grafana-tests"
# Plugins vendored from pjan/grafana-plugins releases by scripts/update-grafana-plugin.py.
GRAFANA_PLUGINS_DIRECTORY = MONITORING_ROOT / "grafana" / "plugins"
PLUGIN_RELEASES_FILE = MONITORING_ROOT / "grafana" / "plugin-releases.json"
THEME_MODES = ("light", "dark")
PALETTE_KEY_PATTERN = re.compile(r"[a-z]+[0-9]*")
PALETTE_STEP_KEY_PATTERN = re.compile(r"(?P<hue>[a-z]+)(?P<step>[1-9]00)")
PALETTE_REFERENCE_PATTERN = re.compile(
    r"atlas\.(?P<key>[a-z]+[0-9]*)(?:/(?P<alpha>[0-9.]+))?"
)
HEX_COLOR_PATTERN = re.compile(r"#[0-9a-f]{6}")
# Reads the alerting YAML files (the standard library has no YAML parser).
# renovate: datasource=docker depName=mikefarah/yq
YQ_IMAGE = "mikefarah/yq:4.53.6@sha256:cfc4eee658595834ef304eadb0c3ea721f3b7cb6404ad8b7cb909cc5b5145b23"
# The alert contract (README "Alerts").
ALERT_NAME_PATTERN = re.compile(r"[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)*")
ALERT_CHECK_PATTERN = re.compile(r"[a-z]+\.[a-z0-9]+(?:-[a-z0-9]+)*")
ALERT_SEVERITIES = {"critical", "warning"}
ALERT_SOURCES = {"prometheus", "backrest", "komodo"}
# Alerts without a check: no RAG tile, never sent to Discord.
CHECKLESS_ALERTS = {"Watchdog"}
REQUIRED_ALERT_ANNOTATIONS = {"title", "description"}
OPTIONAL_ALERT_ANNOTATIONS = {"target", "details", "link", "dashboard", "runbook"}
# Longer values are cut by atlas.tmpl; title 85 keeps the embed title at 100.
ALERT_ANNOTATION_LIMITS = {
    "title": 85,
    "description": 250,
    "target": 80,
    "details": 350,
}
ALERT_DASHBOARD_PREFIX = "https://grafana.atlas.vandaele.io/"
ALERT_RUNBOOK_PREFIX = "https://github.com/pjan/atlas#"
CHECK_STATUS_TEST_PATTERN = re.compile(r'atlas:check_status\{check="([^"]+)"\}')
# The Discord payload in alertmanager.yml, whose embeds the fixtures render.
DISCORD_EMBEDS_TEMPLATE = '{{ template "atlas.embeds" . }}'
ALERTMANAGER_TEMPLATES = "/etc/alertmanager/*.tmpl"
# Links: whole Markdown links joined by " · ", never a cut one.
DISCORD_LINKS_PATTERN = re.compile(
    r"\[[A-Za-z]+\]\([^()\s]+\)(?: · \[[A-Za-z]+\]\([^()\s]+\))*"
)
# Discord's limits for one webhook message (characters, not bytes).
DISCORD_MAX_EMBEDS = 10
DISCORD_MAX_FIELDS = 25
DISCORD_MAX_TITLE = 256
DISCORD_MAX_DESCRIPTION = 4096
DISCORD_MAX_FIELD_NAME = 256
DISCORD_MAX_FIELD_VALUE = 1024
DISCORD_MAX_FOOTER = 2048
DISCORD_MAX_TOTAL = 6000
# atlas.tmpl's embed colours: resolved, firing warning, firing critical.
ATLAS_COLOR_RESOLVED = 3066993
ATLAS_COLOR_WARNING = 15105570
ATLAS_COLOR_CRITICAL = 15158332
# atlas.tmpl's budget, which keeps every message under DISCORD_MAX_TOTAL.
ATLAS_MAX_EMBEDS = 4
ATLAS_MAX_TITLE = 100
ATLAS_MAX_DESCRIPTION = 250
ATLAS_MAX_FIELD_VALUES = {
    "Severity": 20,
    "Source": 20,
    "Target": 80,
    "Details": 358,
    "Links": 300,
}
# Routes that must stay LAN-only: they expose every backup secret.
LOCAL_ONLY_CADDY_ROUTES = {"backrest"}
ALLOWED_DIRECT_INPUT_ALIASES = {
    ("adguard", "DNS_BIND_IP", "NAS_LAN_IP"),
    ("caddy", "HTTP_BIND_IP", "NAS_LAN_IP"),
    ("rclone", "RCLONE_DATA_DIR", "DATA_DIR"),
}
DEPRECATED_VARIABLE_NAMES = {
    "CLOUDFLARED_TUNNEL_TOKEN",
    "HOMEPAGE_BAZARR_API_KEY",
    "HOMEPAGE_CLOUDFLARE_ACCOUNT_ID",
    "HOMEPAGE_CLOUDFLARE_TUNNEL_ID",
    "HOMEPAGE_LIDARR_API_KEY",
    "HOMEPAGE_PLEX_TOKEN",
    "HOMEPAGE_PROWLARR_API_KEY",
    "HOMEPAGE_QBITTORRENT_API_KEY",
    "HOMEPAGE_QBITTORRENT_PASSWORD",
    "HOMEPAGE_QBITTORRENT_USERNAME",
    "HOMEPAGE_RADARR_API_KEY",
    "HOMEPAGE_SABNZBD_API_KEY",
    "HOMEPAGE_SEERR_API_KEY",
    "HOMEPAGE_SONARR_API_KEY",
    "HOMEPAGE_UNIFI_URL",
    "HOMEPAGE_UPTIME_KUMA_SLUG",
    "QBITTORRENT_PASSWORD",
    "QBITTORRENT_USERNAME",
    "RECYCLARR_RADARR_API_KEY",
    "RECYCLARR_SONARR_API_KEY",
    "SOULARR_LIDARR_API_KEY",
    "SPOTTARR_SPOTNET_IMPORTADULTCONTENT",
    "SPOTTARR_SPOTNET_IMPORTBATCHSIZE",
    "SPOTTARR_SPOTNET_RETENTIONDAYS",
    "SPOTTARR_SPOTNET_RETRIEVEAFTER",
    "SPOTTARR_USENET_MAXCONNECTIONS",
    "SPOTTARR_USENET_USETLS",
    "UNPACKERR_LIDARR_API_KEY",
    "UNPACKERR_RADARR_API_KEY",
    "UNPACKERR_SONARR_API_KEY",
}

VALIDATION_VALUES = {
    "ALERTMANAGER_DATA_DIR": "/volume2/appdata/alertmanager",
    "APPDATA_DIR": "/volume2/appdata",
    "APP_URL": "http://speedtest.atlas.local",
    "BACKREST_CACHE_DIR": "/volume2/tmp/backrest/cache",
    "BACKREST_CONFIG_DIR": "/volume2/appdata/backrest/config",
    "BACKREST_DATA_DIR": "/volume2/appdata/backrest/data",
    "BACKREST_RESTORE_DIR": "/volume2/tmp/backrest/restore",
    "BACKUPS_DIR": "/volume1/backups",
    "BACKUP_DIR": "/volume1/backups/roonserver",
    "CONFIG_DIR": "/volume2/appdata/validation",
    "CONF_DIR": "/volume2/appdata/adguard/conf",
    "CRON_SCHEDULE": "15 4 * * *",
    "DATA_DIR": "/volume1/data",
    "DOWNLOADS_DIR": "/volume1/data/downloads",
    "DNS_BIND_IP": "127.0.0.1",
    "GRAFANA_ADMIN_PASSWORD": "validation-only-password",
    "GRAFANA_DATA_DIR": "/volume2/appdata/grafana",
    "GRAFANA_SECRET_KEY": "validation-only-secret-key",
    "GRAFANA_SECRETS_MANAGER_KEY": "validation-only-secrets-manager-key",
    "HTTP_BIND_IP": "127.0.0.1",
    "HTTP_PORT": "18080",
    "KOMETA_TIMES": "03:00",
    "KOMODO_BOOTSTRAP_DIR": "/volume2/docker/komodo",
    "LIDARR_API_KEY": "0123456789abcdef0123456789abcdef",
    "LIDARR_URL": "http://downloaders-vpn:8686",
    "LOG_TARGETS": "stdout",
    "MEDIA_DIR": "/volume1/data/media",
    "METRICS_DIR": "/volume1/backups/.metrics",
    "MUSIC_DIR": "/volume1/data/media/music",
    "NAS_LAN_IP": "127.0.0.1",
    "PGID": "10",
    "PROMETHEUS_DATA_DIR": "/volume2/appdata/prometheus",
    "PROTONVPN_PORT_FORWARD_ONLY": "on",
    "PROTONVPN_SERVER_COUNTRIES": "Netherlands",
    "PROTONVPN_VPN_PORT_FORWARDING": "on",
    "PUID": "999",
    "QBITTORRENT_API_KEY": "qbt_0123456789abcdefghijklmnopqr",
    "RADARR_URL": "http://downloaders-vpn:7878",
    "RADARR_API_KEY": "0123456789abcdef0123456789abcdef",
    "RCLONE_CACHE_DIR": "/volume2/tmp/rclone/cache",
    "RCLONE_CONFIG_DIR": "/volume2/appdata/rclone",
    "RCLONE_DATA_DIR": "/volume1/data",
    "ROON_INSTALL_BRANCH": "production",
    "SABNZBD_PORT": "8085",
    "SCRIPT_INTERVAL": "300",
    "SLSKD_COMPLETE_DIR": "/volume1/data/downloads/slskd/complete",
    "SLSKD_CONFIG_DIR": "/volume2/appdata/slskd",
    "SLSKD_INCOMPLETE_DIR": "/volume1/data/downloads/slskd/incomplete",
    "SONARR_URL": "http://downloaders-vpn:8989",
    "SONARR_API_KEY": "0123456789abcdef0123456789abcdef",
    "SOULARR_CONFIG_DIR": "/volume2/appdata/soularr",
    "SPEEDTEST_TRACKER_APP_KEY": "base64:dmFsaWRhdGlvbi1vbmx5",
    "SPEEDTEST_TRACKER_PRUNE_RESULTS_OLDER_THAN": "365",
    "SPEEDTEST_TRACKER_SCHEDULE": "6 */6 * * *",
    "SPEEDTEST_TRACKER_SERVERS": "",
    "SPOTTARR_SPOTNET_IMPORT_ADULT_CONTENT": "false",
    "SPOTTARR_SPOTNET_IMPORT_BATCH_SIZE": "500",
    "SPOTTARR_SPOTNET_RETENTION_DAYS": "1100",
    "SPOTTARR_SPOTNET_RETRIEVE_AFTER": "2025-01-01",
    "SPOTTARR_USENET_MAX_CONNECTIONS": "20",
    "SPOTTARR_USENET_PORT": "563",
    "SPOTTARR_USENET_USE_TLS": "true",
    "TRANSCODE_DIR": "/volume2/tmp/plex/transcode",
    "TZ": "Etc/UTC",
    "UMASK": "002",
    "TORRENTS_DIR": "/volume1/data/downloads/torrents",
    "USENET_DIR": "/volume1/data/downloads/usenet",
    "WORK_DIR": "/volume2/appdata/adguard/work",
}


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)

    def finish(self) -> None:
        if self.errors:
            for error in self.errors:
                print(f"validate-repository: {error}", file=sys.stderr)
            raise SystemExit(1)


def relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def compose_input_names(compose_text: str) -> set[str]:
    return set(COMPOSE_VARIABLE_PATTERN.findall(compose_text)) | set(
        COMPOSE_SECRET_ENVIRONMENT_PATTERN.findall(compose_text)
    )


def compose_environment(compose_file: Path) -> dict[str, str]:
    compose_text = compose_file.read_text(encoding="utf-8")
    environment = os.environ.copy()
    for variable in compose_input_names(compose_text):
        environment[variable] = VALIDATION_VALUES.get(variable, "validation-only")
    return environment


def render_compose(
    compose_file: Path,
    validation: Validation,
    environment: dict[str, str] | None = None,
) -> dict:
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(compose_file.parent),
        "-f",
        str(compose_file),
        "--profile",
        "*",
        "config",
        "--format",
        "json",
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment or compose_environment(compose_file),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        validation.errors.append(
            f"{relative(compose_file)} does not render: {result.stderr.strip()}"
        )
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        validation.errors.append(
            f"{relative(compose_file)} produced invalid JSON: {error}"
        )
        return {}


def komodo_toml_text(toml_text: str) -> str:
    """Mirror Komodo's escape_between_triple_string before parsing.

    Komodo doubles every backslash between triple double quotes, so those
    strings behave as literal strings in Resource Sync. Parsing the same
    transformed text keeps validation identical to what Komodo deploys.
    """
    sections = toml_text.split('"""')
    return '"""'.join(
        section.replace("\\", "\\\\") if index % 2 else section
        for index, section in enumerate(sections)
    )


def load_stacks_toml() -> dict:
    stacks_text = (REPO_ROOT / "stacks.toml").read_text(encoding="utf-8")
    return tomllib.loads(komodo_toml_text(stacks_text))


def load_repository(validation: Validation) -> tuple[dict, dict]:
    try:
        stacks_data = load_stacks_toml()
    except (OSError, tomllib.TOMLDecodeError) as error:
        validation.errors.append(f"stacks.toml is invalid: {error}")
        stacks_data = {}

    try:
        with (REPO_ROOT / "renovate.json").open(encoding="utf-8") as file:
            renovate_data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        validation.errors.append(f"renovate.json is invalid: {error}")
        renovate_data = {}

    return stacks_data, renovate_data


def validate_stack_inventory(
    stacks_data: dict,
    compose_files: list[Path],
    validation: Validation,
) -> dict[str, dict]:
    entries = stacks_data.get("stack", [])
    stacks_by_name: dict[str, dict] = {}
    run_directories: dict[str, list[str]] = {}

    for entry in entries:
        name = entry.get("name")
        config = entry.get("config", {})
        run_directory = config.get("run_directory")
        validation.require(
            isinstance(name, str) and bool(name),
            "a [[stack]] entry is missing its name",
        )
        if not isinstance(name, str) or not name:
            continue
        validation.require(name not in stacks_by_name, f"duplicate stack name: {name}")
        stacks_by_name[name] = entry
        if isinstance(run_directory, str):
            run_directories.setdefault(run_directory, []).append(name)
        else:
            validation.errors.append(f"stack {name} has no run_directory")

        for file_path in config.get("file_paths", []):
            declared_file = REPO_ROOT / str(run_directory) / file_path
            validation.require(
                declared_file.is_file(),
                f"stack {name} declares missing file: {relative(declared_file)}",
            )

        for config_file in config.get("config_files", []):
            declared_file = REPO_ROOT / str(run_directory) / config_file["path"]
            validation.require(
                declared_file.is_file(),
                f"stack {name} declares missing config_file: {relative(declared_file)}",
            )

    validation.require("komodo" not in stacks_by_name, "Komodo must not be managed")

    compose_directories = {relative(path.parent) for path in compose_files}
    declared_directories = {
        run_directory
        for run_directory in run_directories
        if run_directory.startswith("stacks/")
    }
    for run_directory in sorted(compose_directories | declared_directories):
        names = run_directories.get(run_directory, [])
        validation.require(
            len(names) == 1,
            f"{run_directory} must have exactly one stack entry; found {names}",
        )
        validation.require(
            run_directory in compose_directories,
            f"stack run directory has no compose.yaml: {run_directory}",
        )

    return stacks_by_name


def validate_stack_environment(
    compose_file: Path,
    stack: dict,
    validation: Validation,
) -> None:
    environment = stack.get("config", {}).get("environment", "")
    input_names = []
    for line in environment.splitlines():
        if not line.strip():
            continue
        name, separator, value = line.partition("=")
        name = name.strip()
        validation.require(
            bool(separator) and bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", name)),
            f"stack {stack['name']} has an invalid environment assignment: {line}",
        )
        if separator:
            input_names.append(name)
            reference = re.fullmatch(
                r"\[\[([A-Z][A-Z0-9_]*)\]\]",
                value.strip(),
            )
            if reference is not None and name != reference.group(1):
                alias = (stack["name"], name, reference.group(1))
                validation.require(
                    alias in ALLOWED_DIRECT_INPUT_ALIASES,
                    f"stack {stack['name']} input {name} aliases Komodo variable "
                    f"{reference.group(1)} without an approved adapter",
                )

    duplicate_names = {
        name for name in input_names if input_names.count(name) > 1
    }
    for name in sorted(duplicate_names):
        validation.errors.append(
            f"stack {stack['name']} defines environment input more than once: {name}"
        )

    for name in input_names:
        validation.require(
            "_VAR_" not in name,
            f"stack {stack['name']} environment input uses an upstream adapter name: {name}",
        )

    compose_inputs = compose_input_names(compose_file.read_text(encoding="utf-8"))
    stack_inputs = set(input_names)
    for name in sorted(compose_inputs - stack_inputs):
        validation.errors.append(
            f"stack {stack['name']} does not provide Compose input: {name}"
        )
    for name in sorted(stack_inputs - compose_inputs):
        validation.errors.append(
            f"stack {stack['name']} provides unused Compose input: {name}"
        )


def validate_variable_contract(stacks_data: dict, validation: Validation) -> None:
    stacks_text = (REPO_ROOT / "stacks.toml").read_text(encoding="utf-8")
    readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    declared_names = [
        variable["name"] for variable in stacks_data.get("variable", [])
    ]
    validation.require(
        len(declared_names) == len(set(declared_names)),
        "stacks.toml contains duplicate [[variable]] names",
    )
    referenced_names = {
        token[2:-2] for token in KOMODO_VARIABLE_PATTERN.findall(stacks_text)
    }
    external_names = referenced_names - set(declared_names)

    match = README_VARIABLE_BLOCK_PATTERN.search(readme_text)
    validation.require(
        match is not None,
        "README.md lacks the shared Komodo variable inventory",
    )
    documented_names = set()
    if match is not None:
        documented_lines = match.group("variables").splitlines()
        for line in documented_lines:
            validation.require(
                bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", line)),
                f"README.md has an invalid Komodo variable name: {line}",
            )
        validation.require(
            documented_lines == sorted(documented_lines),
            "README.md shared Komodo variable inventory must be sorted",
        )
        validation.require(
            len(documented_lines) == len(set(documented_lines)),
            "README.md shared Komodo variable inventory contains duplicates",
        )
        documented_names = set(documented_lines)

    for name in sorted(external_names - documented_names):
        validation.errors.append(f"README.md does not document Komodo variable: {name}")
    for name in sorted(documented_names - external_names):
        validation.errors.append(f"README.md documents unused Komodo variable: {name}")

    implementation_text = f"{stacks_text}\n{readme_text}"
    for name in sorted(DEPRECATED_VARIABLE_NAMES):
        if re.search(rf"\b{re.escape(name)}\b", implementation_text):
            validation.errors.append(f"deprecated variable name remains: {name}")

    for name in sorted(set(declared_names) | external_names):
        validation.require(
            "_VAR_" not in name,
            f"repository-controlled variable uses an upstream adapter name: {name}",
        )


def validate_image(image: str | None, context: str, validation: Validation) -> None:
    validation.require(bool(image), f"{context} has no image")
    if not image:
        return
    tagged_reference = image.split("@", 1)[0]
    final_component = tagged_reference.rsplit("/", 1)[-1]
    validation.require(":" in final_component, f"{context} image is untagged: {image}")
    if ":" in final_component:
        tag = final_component.rsplit(":", 1)[-1]
        validation.require(tag != "latest", f"{context} uses latest: {image}")


def validate_renovate_config(renovate_data: dict, validation: Validation) -> None:
    validation.require(
        renovate_data.get("automerge") is False,
        "Renovate must disable global automerge",
    )

    package_rules = renovate_data.get("packageRules", [])
    if not isinstance(package_rules, list):
        validation.errors.append("Renovate packageRules must be a list")
        return

    safe_automerge_rule_found = False
    for index, rule in enumerate(package_rules, start=1):
        if not isinstance(rule, dict):
            validation.errors.append(f"Renovate package rule {index} must be an object")
            continue
        if rule.get("automerge") is not True:
            continue

        update_types = rule.get("matchUpdateTypes")
        if (
            not isinstance(update_types, list)
            or not update_types
            or not all(isinstance(update_type, str) for update_type in update_types)
        ):
            validation.errors.append(
                f"Renovate package rule {index} enables automerge without matchUpdateTypes"
            )
            continue

        update_type_set = set(update_types)
        unsafe_update_types = update_type_set - SAFE_AUTOMERGE_UPDATE_TYPES
        validation.require(
            not unsafe_update_types,
            f"Renovate package rule {index} automerges unsafe update types: "
            f"{sorted(unsafe_update_types)}",
        )
        if update_type_set == SAFE_AUTOMERGE_UPDATE_TYPES:
            safe_automerge_rule_found = True

    validation.require(
        safe_automerge_rule_found,
        "Renovate must automerge patch, pin, and digest updates after validation",
    )


def validate_service_policy(
    compose_file: Path,
    service_name: str,
    service: dict,
    validation: Validation,
) -> None:
    context = f"{relative(compose_file)} service {service_name}"
    validate_image(service.get("image"), context, validation)

    logging = service.get("logging", {})
    validation.require(
        logging.get("driver") == "json-file",
        f"{context} must use json-file logging",
    )
    options = logging.get("options", {})
    validation.require(
        options.get("max-size") == "10m" and options.get("max-file") == "3",
        f"{context} must rotate logs at 10m with three files",
    )
    validation.require(bool(service.get("mem_limit")), f"{context} has no mem_limit")
    validation.require(bool(service.get("pids_limit")), f"{context} has no pids_limit")
    validation.require(bool(service.get("cpus")), f"{context} has no cpus limit")
    validation.require(
        "no-new-privileges:true" in service.get("security_opt", []),
        f"{context} must enable no-new-privileges",
    )


def validate_bind_mount_policy(
    compose_file: Path,
    rendered: dict,
    validation: Validation,
    *,
    require_all_binds_long_syntax: bool = True,
) -> None:
    lines = compose_file.read_text(encoding="utf-8").splitlines()
    declarations: list[tuple[int, list[str]]] = []

    for index, line in enumerate(lines):
        if line.strip() != "- type: bind":
            continue
        item_indent = len(line) - len(line.lstrip(" "))
        block = [line]
        for following_line in lines[index + 1 :]:
            stripped = following_line.strip()
            if stripped and not stripped.startswith("#"):
                indent = len(following_line) - len(following_line.lstrip(" "))
                if indent <= item_indent:
                    break
            block.append(following_line)
        declarations.append((index + 1, block))

    rendered_bind_count = sum(
        1
        for service in rendered.get("services", {}).values()
        for mount in service.get("volumes", [])
        if mount.get("type") == "bind"
    )
    if require_all_binds_long_syntax:
        validation.require(
            len(declarations) == rendered_bind_count,
            f"{relative(compose_file)} must declare every bind using long syntax; "
            f"found {len(declarations)} declarations for {rendered_bind_count} binds",
        )

    for line_number, block in declarations:
        target = "unknown"
        bind_indent = None
        create_host_path_disabled = False
        for block_index, block_line in enumerate(block):
            stripped = block_line.strip()
            if stripped.startswith("target:"):
                target = stripped.partition(":")[2].strip()
            if stripped == "bind:":
                bind_indent = len(block_line) - len(block_line.lstrip(" "))
                for bind_line in block[block_index + 1 :]:
                    if not bind_line.strip() or bind_line.lstrip().startswith("#"):
                        continue
                    indent = len(bind_line) - len(bind_line.lstrip(" "))
                    if indent <= bind_indent:
                        break
                    if bind_line.strip() == "create_host_path: false":
                        create_host_path_disabled = True
                        break
                break
        validation.require(
            create_host_path_disabled,
            f"{relative(compose_file)}:{line_number} bind {target} must set "
            "create_host_path: false",
        )


def tracked_files() -> set[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return {
        REPO_ROOT / item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    }


def validate_relative_binds(
    compose_file: Path,
    rendered: dict,
    stack: dict,
    validation: Validation,
) -> None:
    stack_directory = compose_file.parent.resolve()
    config_paths = {
        (stack_directory / item["path"]).resolve()
        for item in stack.get("config", {}).get("config_files", [])
    }

    for service_name, service in rendered.get("services", {}).items():
        for mount in service.get("volumes", []):
            if mount.get("type") != "bind":
                continue
            source = Path(mount["source"]).resolve()
            try:
                source.relative_to(stack_directory)
            except ValueError:
                continue

            if source.is_file():
                required_files = {source}
            else:
                required_files = {
                    path.resolve()
                    for path in source.rglob("*")
                    if path.is_file() and path.name != ".DS_Store"
                }
            missing = required_files - config_paths
            for path in sorted(missing):
                validation.errors.append(
                    f"{relative(compose_file)} service {service_name} relative bind "
                    f"contains unregistered config file: {relative(path)}"
                )


def validate_caddy(stacks_by_name: dict[str, dict], validation: Validation) -> None:
    caddy = stacks_by_name.get("caddy", {})
    config = caddy.get("config", {})
    validation.require("after" not in caddy, "Caddy must not depend on app stacks")

    site_paths = {
        path.relative_to(STACKS_ROOT / "caddy").as_posix()
        for path in (STACKS_ROOT / "caddy" / "conf" / "sites").glob("*.caddy")
    }
    registered_sites = {
        item["path"]
        for item in config.get("config_files", [])
        if item.get("path", "").startswith("conf/sites/")
    }
    validation.require(
        site_paths == registered_sites,
        f"Caddy site registration mismatch: {sorted(site_paths ^ registered_sites)}",
    )

    caddy_hostnames = set()
    for site_path in (STACKS_ROOT / "caddy" / "conf" / "sites").glob("*.caddy"):
        site_text = site_path.read_text(encoding="utf-8")
        caddy_hostnames.update(
            re.findall(
                r"https?://([a-z0-9.-]+\.atlas\.(?:local|vandaele\.io))",
                site_text,
            )
        )
        for match in re.finditer(
            r"(?m)^\s*import\s+(?:atlas_reverse_proxy|atlas_rclone)\s+([a-z0-9-]+)\b",
            site_text,
        ):
            route_name = match.group(1)
            caddy_hostnames.add(f"{route_name}.atlas.local")
            caddy_hostnames.add(f"{route_name}.atlas.vandaele.io")

    local_route_names = {
        hostname.removesuffix(".atlas.local")
        for hostname in caddy_hostnames
        if hostname.endswith(".atlas.local")
    }
    public_route_names = {
        hostname.removesuffix(".atlas.vandaele.io")
        for hostname in caddy_hostnames
        if hostname.endswith(".atlas.vandaele.io")
    }
    validation.require(
        not (LOCAL_ONLY_CADDY_ROUTES & public_route_names),
        "LAN-only Caddy routes must not define public hostnames: "
        f"{sorted(LOCAL_ONLY_CADDY_ROUTES & public_route_names)}",
    )
    validation.require(
        local_route_names - LOCAL_ONLY_CADDY_ROUTES == public_route_names,
        "Caddy routes must define matching local and public hostnames: "
        f"{sorted((local_route_names - LOCAL_ONLY_CADDY_ROUTES) ^ public_route_names)}",
    )

    for item in config.get("config_files", []):
        if item.get("path", "").startswith("conf/"):
            validation.require(
                item.get("requires") == "Restart",
                f"Caddy config must require Restart: {item.get('path')}",
            )

    post_deploy = config.get("post_deploy", {}).get("command", "")
    for required in (
        'test "$reloaded" = true',
        "caddy adapt --pretty",
        "http://127.0.0.1:2019/config/",
        "Caddy live config is missing expected hostname",
    ):
        validation.require(required in post_deploy, f"Caddy post_deploy lacks: {required}")


def validate_hooks(stacks_by_name: dict[str, dict], validation: Validation) -> None:
    variable_names = set()
    for stack in stacks_by_name.values():
        for hook_name in ("pre_deploy", "post_deploy"):
            command = stack.get("config", {}).get(hook_name, {}).get("command")
            if not command:
                continue
            stripped = KOMODO_VARIABLE_PATTERN.sub("", command)
            validation.require(
                "[[" not in stripped and "]]" not in stripped,
                f"stack {stack['name']} {hook_name} contains an invalid Komodo variable tag",
            )
            variable_names.update(
                token[2:-2] for token in KOMODO_VARIABLE_PATTERN.findall(command)
            )
            result = subprocess.run(
                ["sh", "-n"],
                input=command,
                capture_output=True,
                text=True,
            )
            validation.require(
                result.returncode == 0,
                f"stack {stack['name']} {hook_name} has invalid shell: {result.stderr.strip()}",
            )

    declared_variables = {
        item["name"] for item in load_stacks_toml().get("variable", [])
    }
    for name in sorted(variable_names - declared_variables):
        validation.errors.append(f"Komodo hook references undeclared variable: {name}")

    stacks_text = (REPO_ROOT / "stacks.toml").read_text(encoding="utf-8")
    validation.require(
        "docker network inspect" not in stacks_text
        and "docker network create" not in stacks_text,
        "stacks.toml must use ensure-docker-network.sh for network creation",
    )


def validate_tracked_files(tracked: set[Path], validation: Validation) -> None:
    for path in sorted(tracked):
        name = path.name
        lowered = name.lower()
        relative_path = relative(path)
        validation.require(name != ".env", f"tracked runtime environment: {relative_path}")
        validation.require(name != ".DS_Store", f"tracked OS metadata: {relative_path}")
        validation.require(
            not lowered.endswith((".pem", ".key", ".p12", ".pfx", ".secret")),
            f"tracked secret-like file: {relative_path}",
        )
        validation.require(
            lowered not in {"id_rsa", "id_ed25519"},
            f"tracked private key: {relative_path}",
        )


def validate_komodo_compose(validation: Validation) -> None:
    compose_file = REPO_ROOT / "komodo" / "compose.yaml"
    example = (REPO_ROOT / "komodo" / ".env.example").read_text(encoding="utf-8")
    rendered_example = re.sub(r"<replace-[^>]+>", "validation-only", example)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as environment_file:
        environment_file.write(rendered_example)
        environment_file.flush()
        environment = {
            **os.environ,
            "COMPOSE_KOMODO_BACKUPS_PATH": "/volume1/backups/komodo",
            "KOMODO_DATABASE_PASSWORD": "validation-only",
            "KOMODO_DATABASE_USERNAME": "komodo",
            "KOMODO_ENV_FILE": environment_file.name,
            "PERIPHERY_ROOT_DIRECTORY": "/volume2/komodo",
        }
        rendered = render_compose(compose_file, validation, environment)

    rendered_text = json.dumps(rendered)
    validation.require(
        "<replace-" not in rendered_text,
        "Komodo validation rendered an example secret placeholder",
    )
    for service_name, service in rendered.get("services", {}).items():
        validate_image(
            service.get("image"),
            f"{relative(compose_file)} service {service_name}",
            validation,
        )

    mongo = rendered.get("services", {}).get("mongo", {})
    validation.require(
        mongo.get("pids_limit") == 512,
        "Komodo Mongo must set pids_limit to 512",
    )
    validation.require(
        "no-new-privileges:true" in mongo.get("security_opt", []),
        "Komodo Mongo must enable no-new-privileges",
    )

    validate_bind_mount_policy(
        compose_file,
        rendered,
        validation,
        require_all_binds_long_syntax=False,
    )

    expected_writable_binds = {
        ("core", "/backups"): "/volume1/backups/komodo",
        ("periphery", "/volume2/komodo"): "/volume2/komodo",
    }
    for (service_name, target), expected_source in expected_writable_binds.items():
        mounts = [
            mount
            for mount in rendered.get("services", {})
            .get(service_name, {})
            .get("volumes", [])
            if mount.get("target") == target
        ]
        validation.require(
            len(mounts) == 1,
            f"Komodo service {service_name} must mount {target} exactly once",
        )
        if len(mounts) != 1:
            continue
        mount = mounts[0]
        validation.require(
            mount.get("type") == "bind" and mount.get("source") == expected_source,
            f"Komodo service {service_name} has an unexpected {target} bind source",
        )


def validate_required_compose_inputs(
    compose_file: Path,
    variable_names: tuple[str, ...],
    validation: Validation,
) -> None:
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(compose_file.parent),
        "-f",
        str(compose_file),
        "config",
        "--quiet",
    ]

    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as environment_file:
        command[2:2] = ["--env-file", environment_file.name]
        for variable in variable_names:
            environment = compose_environment(compose_file)
            environment.pop(variable, None)
            result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )
            validation.require(
                result.returncode != 0 and f"{variable} is required" in result.stderr,
                f"{relative(compose_file)} must reject a missing {variable}",
            )


def load_alerting_yaml(validation: Validation) -> dict[Path, dict]:
    """Parse the alerting YAML files in one yq container run.

    yq prints one compact JSON line per document, tagged with its file and
    document index, so a file with a second document is rejected.
    """
    paths = [
        *sorted(ALERT_RULES_DIRECTORY.glob("*.yml")),
        *sorted(ALERT_RULE_TESTS_DIRECTORY.glob("*.yml")),
        ALERTMANAGER_DIRECTORY / "alertmanager.yml",
    ]
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{MONITORING_ROOT}:/monitoring:ro",
            YQ_IMAGE,
            "-o=json",
            "-I=0",
            '{"file": filename, "index": document_index, "document": .}',
            *(
                f"/monitoring/{path.relative_to(MONITORING_ROOT).as_posix()}"
                for path in paths
            ),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        validation.errors.append(
            f"alerting YAML is not valid (yq): {result.stderr.strip()}"
        )
        return {}

    documents: dict[Path, dict] = {}
    for line in result.stdout.splitlines():
        entry = json.loads(line)
        path = MONITORING_ROOT / entry["file"].removeprefix("/monitoring/")
        if entry["index"] != 0:
            validation.errors.append(f"{relative(path)} must be a single YAML document")
        elif not isinstance(entry["document"], dict):
            validation.errors.append(f"{relative(path)} must be a YAML mapping")
        else:
            documents[path] = entry["document"]
    return documents


def github_heading_anchors(markdown: str) -> set[str]:
    """Anchors GitHub generates for Markdown headings outside code fences."""
    anchors = set()
    seen: dict[str, int] = {}
    in_fence = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        match = re.fullmatch(r"#{1,6} +(.+?)[ #]*", line)
        if in_fence or match is None:
            continue
        anchor = re.sub(r"[^\w\- ]", "", match.group(1).lower()).replace(" ", "-")
        if anchor in seen:
            seen[anchor] += 1
            anchor = f"{anchor}-{seen[anchor]}"
        else:
            seen[anchor] = 0
        anchors.add(anchor)
    return anchors


def validate_alert_rule(
    rule_file: Path,
    rule: dict,
    readme_anchors: set[str],
    validation: Validation,
) -> str | None:
    """Check one alerting rule against the alert contract; return its check."""
    name = rule.get("alert")
    context = f"{relative(rule_file)} alert {name}"
    labels = rule.get("labels", {})
    annotations = rule.get("annotations", {})
    validation.require(
        isinstance(name, str) and bool(ALERT_NAME_PATTERN.fullmatch(name)),
        f"{context} must have a CamelCase name",
    )

    if name in CHECKLESS_ALERTS:
        expected_labels = {"source"}
    else:
        expected_labels = {"check", "severity", "source"}
    validation.require(
        set(labels) == expected_labels,
        f"{context} must have exactly the labels {sorted(expected_labels)}",
    )
    validation.require(
        labels.get("source") in ALERT_SOURCES,
        f"{context} source must be one of {sorted(ALERT_SOURCES)}",
    )
    check = labels.get("check")
    if name not in CHECKLESS_ALERTS:
        validation.require(
            labels.get("severity") in ALERT_SEVERITIES,
            f"{context} severity must be one of {sorted(ALERT_SEVERITIES)}",
        )
        validation.require(
            isinstance(check, str) and bool(ALERT_CHECK_PATTERN.fullmatch(check)),
            f"{context} check must look like <area>.<name>",
        )

    for key in sorted(REQUIRED_ALERT_ANNOTATIONS - set(annotations)):
        validation.errors.append(f"{context} lacks the annotation {key}")
    known_annotations = REQUIRED_ALERT_ANNOTATIONS | OPTIONAL_ALERT_ANNOTATIONS
    for key in sorted(set(annotations) - known_annotations):
        validation.errors.append(f"{context} has an unknown annotation {key}")
    for key, value in annotations.items():
        validation.require(
            isinstance(value, str) and bool(value.strip()),
            f"{context} annotation {key} must be a non-empty string",
        )
    for key, limit in ALERT_ANNOTATION_LIMITS.items():
        value = annotations.get(key, "")
        validation.require(
            len(value) <= limit,
            f"{context} annotation {key} is longer than {limit} characters",
        )

    dashboard = annotations.get("dashboard")
    if dashboard is not None:
        validation.require(
            dashboard.startswith(ALERT_DASHBOARD_PREFIX),
            f"{context} dashboard must start with {ALERT_DASHBOARD_PREFIX}",
        )
    runbook = annotations.get("runbook")
    if runbook is not None:
        anchor = runbook.removeprefix(ALERT_RUNBOOK_PREFIX)
        validation.require(
            runbook.startswith(ALERT_RUNBOOK_PREFIX) and anchor in readme_anchors,
            f"{context} runbook must be {ALERT_RUNBOOK_PREFIX}<README heading "
            f"anchor>: {runbook}",
        )
    return check


def validate_alert_rules(
    documents: dict[Path, dict], validation: Validation
) -> None:
    readme_anchors = github_heading_anchors(
        (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    )
    rule_files = sorted(ALERT_RULES_DIRECTORY.glob("*.yml"))
    validation.require(bool(rule_files), "no Prometheus rule files found")

    # (check, severity) -> number of alerting rules
    severity_rules: dict[tuple[str, str], int] = {}
    catalogue: set[str] = set()
    for rule_file in rule_files:
        document = documents.get(rule_file, {})
        for group in document.get("groups", []):
            for rule in group.get("rules", []):
                if "alert" in rule:
                    check = validate_alert_rule(
                        rule_file, rule, readme_anchors, validation
                    )
                    if check:
                        key = (check, rule.get("labels", {}).get("severity"))
                        severity_rules[key] = severity_rules.get(key, 0) + 1
                elif rule.get("record") == "atlas:check_catalogue":
                    catalogue.add(rule.get("labels", {}).get("check"))

    # A tile maps to one cause per severity.
    for (check, severity), count in sorted(severity_rules.items()):
        validation.require(
            count == 1,
            f"check {check} has {count} {severity} alerting rules; at most one "
            "warning and one critical rule per check",
        )
    checks = {check for check, _ in severity_rules}

    validation.require(
        catalogue == checks,
        "atlas:check_catalogue must list exactly the checks of the alert rules: "
        f"{sorted(map(str, catalogue ^ checks))}",
    )

    # Every check needs a promtool case in which it turns amber or red.
    covered: set[str] = set()
    for test_file in sorted(ALERT_RULE_TESTS_DIRECTORY.glob("*.yml")):
        document = documents.get(test_file, {})
        for test in document.get("tests", []):
            for case in test.get("promql_expr_test", []):
                match = CHECK_STATUS_TEST_PATTERN.fullmatch(case.get("expr", "").strip())
                samples = case.get("exp_samples", [])
                values = {sample.get("value") for sample in samples}
                if match is not None and values & {1, 2}:
                    covered.add(match.group(1))
    for check in sorted(checks - covered):
        validation.errors.append(
            f"check {check} has no promtool test in which "
            "atlas:check_status turns 1 or 2"
        )


def render_discord_embeds(image: str, fixture: Path, validation: Validation) -> object:
    """Render the Discord embeds for one fixture (template.Data JSON) with amtool."""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "amtool",
            "-v",
            f"{ALERTMANAGER_DIRECTORY}:/etc/alertmanager:ro",
            "-v",
            f"{fixture.parent}:/fixtures:ro",
            image,
            "template",
            "render",
            f"--template.glob={ALERTMANAGER_TEMPLATES}",
            f"--template.text={DISCORD_EMBEDS_TEMPLATE}",
            f"--template.data=/fixtures/{fixture.name}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        validation.errors.append(
            f"{relative(fixture)} does not render: {result.stderr.strip()}"
        )
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        validation.errors.append(f"{relative(fixture)} renders invalid JSON: {error}")
        return None


def expected_embed_color(alert: dict) -> int:
    """Green when resolved; red for a firing critical alert, orange otherwise."""
    if alert.get("status") != "firing":
        return ATLAS_COLOR_RESOLVED
    if alert.get("labels", {}).get("severity") == "critical":
        return ATLAS_COLOR_CRITICAL
    return ATLAS_COLOR_WARNING


def discord_message_problems(embeds: object, alerts: list[dict]) -> list[str]:
    """Discord's webhook limits and atlas.tmpl's budget for one message."""
    if not isinstance(embeds, list) or not embeds:
        return ["embeds that are not a non-empty list"]
    alert_count = len(alerts)
    problems = []
    expected_embeds = min(alert_count, ATLAS_MAX_EMBEDS, DISCORD_MAX_EMBEDS)
    if len(embeds) != expected_embeds:
        problems.append(f"{len(embeds)} embeds for {alert_count} alerts")
    title_limit = min(DISCORD_MAX_TITLE, ATLAS_MAX_TITLE)
    description_limit = min(DISCORD_MAX_DESCRIPTION, ATLAS_MAX_DESCRIPTION)

    total = 0
    for index, embed in enumerate(embeds, start=1):
        context = f"embed {index}"
        color = embed.get("color")
        if index <= alert_count and color != expected_embed_color(alerts[index - 1]):
            problems.append(f"{context} colour {color}")
        title = embed.get("title", "")
        description = embed.get("description", "")
        footer = embed.get("footer", {}).get("text", "")
        fields = embed.get("fields", [])
        total += len(title) + len(description) + len(footer)
        if not 0 < len(title) <= title_limit:
            problems.append(f"{context} title of {len(title)} characters")
        if not 0 < len(description) <= description_limit:
            problems.append(f"{context} description of {len(description)} characters")
        if len(footer) > DISCORD_MAX_FOOTER or not footer.endswith(
            f" alert {index}/{alert_count}"
        ):
            problems.append(f"{context} footer {footer!r}")
        if len(fields) > DISCORD_MAX_FIELDS:
            problems.append(f"{context} with {len(fields)} fields")
        for field in fields:
            name = field.get("name", "")
            value = field.get("value", "")
            total += len(name) + len(value)
            value_limit = min(
                DISCORD_MAX_FIELD_VALUE,
                ATLAS_MAX_FIELD_VALUES.get(name, DISCORD_MAX_FIELD_VALUE),
            )
            if not 0 < len(name) <= DISCORD_MAX_FIELD_NAME:
                problems.append(f"{context} field name of {len(name)} characters")
            if not 0 < len(value) <= value_limit:
                problems.append(f"{context} field {name} of {len(value)} characters")
            if name == "Details" and "```" in value[3:-3]:
                problems.append(f"{context} Details that close their code block early")
            if name == "Links" and not DISCORD_LINKS_PATTERN.fullmatch(value):
                problems.append(f"{context} Links that are not whole Markdown links")
    if total > DISCORD_MAX_TOTAL:
        problems.append(f"{total} characters in total")
    return problems


def schema_problems(value: object, schema: dict, root: dict, path: str) -> list[str]:
    """The JSON Schema keywords Grafana's theme schema uses."""
    if "$ref" in schema:
        target: object = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]  # type: ignore[index]
        return schema_problems(value, target, root, path)  # type: ignore[arg-type]
    if "anyOf" in schema:
        if all(schema_problems(value, option, root, path) for option in schema["anyOf"]):
            return [f"{path}: matches none of the allowed forms"]
        return []
    if "const" in schema and value != schema["const"]:
        return [f"{path}: must be {schema['const']!r}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: must be one of {schema['enum']}"]
    types = {
        "object": dict, "array": list, "string": str, "boolean": bool,
        "number": (int, float), "integer": int,
    }
    expected = schema.get("type")
    if expected and (
        not isinstance(value, types[expected])
        or (expected in ("number", "integer") and isinstance(value, bool))
    ):
        return [f"{path}: must be a {expected}"]
    problems: list[str] = []
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(f"{path}: must be at least {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(f"{path}: must be at most {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            problems.append(f"{path}: must be above {schema['exclusiveMinimum']}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{path}: missing {key}")
        for key, item in value.items():
            if key in properties:
                problems += schema_problems(item, properties[key], root, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                problems.append(f"{path}: unknown key {key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                problems += schema_problems(
                    item, schema["additionalProperties"], root, f"{path}.{key}"
                )
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            problems += schema_problems(item, schema["items"], root, f"{path}[{index}]")
    return problems


def palette_references(node: object, path: str) -> list[tuple[str, str, str | None]]:
    """(path, key, alpha) for every atlas.<key> or atlas.<key>/<alpha> in a JSON tree."""
    if isinstance(node, str):
        return [
            (path, match["key"], match["alpha"])
            for match in PALETTE_REFERENCE_PATTERN.finditer(node)
        ]
    if isinstance(node, dict):
        return [
            reference
            for key, item in node.items()
            for reference in palette_references(item, f"{path}.{key}")
        ]
    if isinstance(node, list):
        return [
            reference
            for index, item in enumerate(node)
            for reference in palette_references(item, f"{path}[{index}]")
        ]
    return []


def palette_steps(value: str) -> list[tuple[str, int]]:
    """The stepped palette references in a string: "atlas.emerald400" -> [("emerald", 400)]."""
    steps = []
    for match in PALETTE_REFERENCE_PATTERN.finditer(value):
        step = PALETTE_STEP_KEY_PATTERN.fullmatch(match["key"])
        if step and not match["alpha"]:
            steps.append((step["hue"], int(step["step"])))
    return steps


def mirroring_problems(light: object, dark: object, where: str) -> list[str]:
    """The mirroring rule: in dark, every stepped colour is the same hue at 1000 - the light
    step. Values without palette steps (backgrounds, alphas, CSS) are not compared."""
    if isinstance(light, dict) and isinstance(dark, dict):
        problems = []
        if set(light) != set(dark):
            problems.append(f"{where} has different keys in light and dark")
        for key in sorted(set(light) & set(dark)):
            problems += mirroring_problems(light[key], dark[key], f"{where}.{key}")
        return problems
    if isinstance(light, list) and isinstance(dark, list):
        problems = []
        if len(light) != len(dark):
            problems.append(f"{where} has different lengths in light and dark")
        for index, (a, b) in enumerate(zip(light, dark)):
            problems += mirroring_problems(a, b, f"{where}[{index}]")
        return problems
    if isinstance(light, int) and isinstance(dark, int) and not isinstance(light, bool):
        if dark != 1000 - light:
            return [f"{where} is {light} in light, so {1000 - light} in dark (not {dark})"]
        return []
    if isinstance(light, str) and isinstance(dark, str):
        a, b = palette_steps(light), palette_steps(dark)
        expected = [(hue, 1000 - step) for hue, step in a]
        if a and b and b != expected:
            wanted = ", ".join(f"atlas.{hue}{step}" for hue, step in expected)
            return [f"{where} is {light} in light, so {wanted} in dark (not {dark})"]
    return []


def validate_theme_plugin(validation: Validation) -> None:
    """atlas-theme.json against Grafana's theme schema, every palette reference resolves, dark
    steps mirror light ones (1000 - step)."""
    theme_path = THEME_PLUGIN_DIRECTORY / "atlas-theme.json"
    theme_file = relative(theme_path)
    try:
        theme = json.loads(theme_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        validation.require(False, f"theme plugin: {error}")
        return
    grafana_schema = json.loads(
        (THEME_SCHEMA_DIRECTORY / "grafana-theme.schema.json").read_text(encoding="utf-8")
    )

    validation.require(
        set(theme) == {"$comment", "palette", "themes", "names"},
        f"{theme_file}: top-level keys must be $comment, palette, themes, names",
    )
    palette = theme.get("palette", {})
    for key, color in palette.items():
        validation.require(
            bool(PALETTE_KEY_PATTERN.fullmatch(key))
            and bool(HEX_COLOR_PATTERN.fullmatch(color)),
            f"{theme_file}: palette.{key} must be a lowercase #rrggbb colour "
            "with a [a-z]+[0-9]* key",
        )
    themes = theme.get("themes", {})
    for mode in THEME_MODES:
        definition = themes.get(mode, {})
        for problem in schema_problems(
            definition, grafana_schema, grafana_schema, f"themes.{mode}"
        ):
            validation.require(False, f"{theme_file}: {problem}")
        validation.require(
            definition.get("colors", {}).get("mode") == mode,
            f"{theme_file}: themes.{mode}.colors.mode must be {mode}",
        )
    for path, key, alpha in palette_references(theme, "$"):
        validation.require(
            key in palette, f"{theme_file}: {path} refers to unknown palette key {key}"
        )
        validation.require(
            alpha is None or bool(re.fullmatch(r"0|1|0?\.[0-9]+", alpha)),
            f"{theme_file}: {path} has alpha {alpha}; use a number from 0 to 1",
        )
    names = theme.get("names", {})
    for where, light, dark in (
        ("themes.*", themes.get("light", {}), themes.get("dark", {})),
        ("names.*", names.get("light", {}), names.get("dark", {})),
    ):
        for problem in mirroring_problems(light, dark, where):
            validation.require(False, f"{theme_file}: {problem}")


def validate_alert_messages(
    documents: dict[Path, dict], validation: Validation
) -> None:
    compose_text = (MONITORING_ROOT / "compose.yaml").read_text(encoding="utf-8")
    image_match = re.search(r"(?m)^ +image: (prom/alertmanager:\S+)$", compose_text)
    validation.require(
        image_match is not None, "monitoring has no prom/alertmanager image"
    )

    # The fixtures render only the embeds; the rest of the payload is fixed.
    config = documents.get(ALERTMANAGER_DIRECTORY / "alertmanager.yml", {})
    receivers = {
        receiver.get("name"): receiver for receiver in config.get("receivers", [])
    }
    webhooks = receivers.get("discord", {}).get("webhook_configs", [])
    payload = webhooks[0].get("payload", {}) if len(webhooks) == 1 else {}
    validation.require(
        payload == {
            "allowed_mentions": {"parse": []},
            "embeds": DISCORD_EMBEDS_TEMPLATE,
        },
        "Alertmanager receiver discord must have one webhook whose payload is "
        f"allowed_mentions.parse [] and embeds {DISCORD_EMBEDS_TEMPLATE!r}",
    )
    validation.require(
        ALERTMANAGER_TEMPLATES in config.get("templates", []),
        f"Alertmanager templates must include {ALERTMANAGER_TEMPLATES}",
    )
    if image_match is None:
        return

    fixtures = sorted(ALERT_MESSAGE_FIXTURES_DIRECTORY.glob("*.json"))
    validation.require(bool(fixtures), "no Alertmanager message fixtures found")
    for fixture in fixtures:
        alerts = json.loads(fixture.read_text(encoding="utf-8"))["alerts"]
        embeds = render_discord_embeds(image_match.group(1), fixture, validation)
        if embeds is None:
            continue
        for problem in discord_message_problems(embeds, alerts):
            validation.errors.append(
                f"{relative(fixture)} renders a Discord message with {problem}"
            )


def validate_vendored_plugins(validation: Validation) -> None:
    """Each plugin in plugin-releases.json matches its release: the same files with the same
    SHA-256, and plugin.json's id and version; Grafana allows it as an unsigned plugin."""
    try:
        releases = json.loads(PLUGIN_RELEASES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        validation.require(False, f"plugin releases: {error}")
        return
    compose = (MONITORING_ROOT / "compose.yaml").read_text(encoding="utf-8")
    allowed = re.search(r"GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=(\S+)", compose)
    allowed_ids = set(allowed.group(1).split(",")) if allowed else set()
    for plugin_id, release in sorted(releases.items()):
        directory = GRAFANA_PLUGINS_DIRECTORY / plugin_id
        label = f"vendored plugin {plugin_id}"
        files = {
            path.relative_to(directory).as_posix(): path
            for path in directory.rglob("*")
            if path.is_file() and path.name != ".DS_Store"
        }
        recorded = release.get("files", {})
        validation.require(
            set(files) == set(recorded),
            f"{label}: files differ from its release: {sorted(set(files) ^ set(recorded))} "
            "(run scripts/update-grafana-plugin.py)",
        )
        for name in sorted(set(files) & set(recorded)):
            digest = hashlib.sha256(files[name].read_bytes()).hexdigest()
            validation.require(
                digest == recorded[name],
                f"{label}: {name} differs from its release (run scripts/update-grafana-plugin.py)",
            )
        try:
            manifest = json.loads((directory / "plugin.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            validation.require(False, f"{label}: plugin.json: {error}")
            continue
        validation.require(manifest.get("id") == plugin_id, f"{label}: plugin.json id is {manifest.get('id')}")
        validation.require(
            manifest.get("info", {}).get("version") == release.get("version"),
            f"{label}: plugin.json version differs from plugin-releases.json",
        )
        validation.require(
            release.get("tag") == f"{plugin_id}/v{release.get('version')}",
            f"{label}: tag {release.get('tag')} does not match its version",
        )
        validation.require(
            plugin_id in allowed_ids,
            f"{label}: not in GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS",
        )


def main() -> None:
    os.chdir(REPO_ROOT)
    validation = Validation()
    stacks_data, renovate_data = load_repository(validation)
    compose_files = sorted(STACKS_ROOT.glob("*/compose.yaml"))
    stacks_by_name = validate_stack_inventory(stacks_data, compose_files, validation)
    tracked = tracked_files()

    rendered_projects = 0
    for compose_file in compose_files:
        rendered = render_compose(compose_file, validation)
        if rendered:
            rendered_projects += 1
        stack = stacks_by_name.get(compose_file.parent.name, {})
        for service_name, service in rendered.get("services", {}).items():
            validate_service_policy(compose_file, service_name, service, validation)
        validate_bind_mount_policy(compose_file, rendered, validation)
        if stack:
            validate_stack_environment(compose_file, stack, validation)
            validate_relative_binds(
                compose_file, rendered, stack, validation
            )

    validate_caddy(stacks_by_name, validation)
    validate_hooks(stacks_by_name, validation)
    validate_variable_contract(stacks_data, validation)
    validate_renovate_config(renovate_data, validation)
    alerting_documents = load_alerting_yaml(validation)
    validate_alert_rules(alerting_documents, validation)
    validate_alert_messages(alerting_documents, validation)
    validate_tracked_files(tracked, validation)
    validate_komodo_compose(validation)
    validate_theme_plugin(validation)
    validate_vendored_plugins(validation)
    validate_required_compose_inputs(
        STACKS_ROOT / "recyclarr" / "compose.yaml",
        ("SONARR_API_KEY", "RADARR_API_KEY"),
        validation,
    )
    validate_required_compose_inputs(
        STACKS_ROOT / "unpackerr" / "compose.yaml",
        ("SONARR_API_KEY", "RADARR_API_KEY", "LIDARR_API_KEY"),
        validation,
    )
    validation.finish()
    print(
        f"validate-repository: validated {rendered_projects} stack Compose projects"
    )


if __name__ == "__main__":
    main()
