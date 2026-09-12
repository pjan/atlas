#!/usr/bin/env python3

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
KOMODO_VARIABLE_PATTERN = re.compile(r"\[\[[A-Z][A-Z0-9_]*\]\]")
README_VARIABLE_BLOCK_PATTERN = re.compile(
    r"Shared stack values managed in Komodo:\n\n```text\n(?P<variables>.*?)\n```",
    re.DOTALL,
)
SAFE_AUTOMERGE_UPDATE_TYPES = {"digest", "patch", "pin"}
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
HOMEPAGE_REQUIRED_INPUTS = (
    "BAZARR_API_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_TUNNEL_ID",
    "GLUETUN_CONTROL_API_KEY",
    "HOMEPAGE_ADGUARD_PASSWORD",
    "HOMEPAGE_ADGUARD_USERNAME",
    "HOMEPAGE_CLOUDFLARE_API_TOKEN",
    "HOMEPAGE_KOMODO_API_KEY",
    "HOMEPAGE_KOMODO_API_SECRET",
    "HOMEPAGE_SPEEDTEST_TRACKER_API_KEY",
    "HOMEPAGE_UNIFI_API_KEY",
    "LIDARR_API_KEY",
    "PLEX_SERVER_TOKEN",
    "PROWLARR_API_KEY",
    "QBITTORRENT_API_KEY",
    "RADARR_API_KEY",
    "SABNZBD_API_KEY",
    "SEERR_API_KEY",
    "SLSKD_API_KEY",
    "SONARR_API_KEY",
    "UNIFI_URL",
    "UPTIME_KUMA_SLUG",
)

VALIDATION_VALUES = {
    "APP_URL": "http://speedtest.atlas.local",
    "BACKUP_DIR": "/volume1/backups/roonserver",
    "CONFIG_DIR": "/volume2/appdata/validation",
    "CONF_DIR": "/volume2/appdata/adguard/conf",
    "CRON_SCHEDULE": "15 4 * * *",
    "DATA_DIR": "/volume1/data",
    "DOWNLOADS_DIR": "/volume1/data/downloads",
    "DNS_BIND_IP": "127.0.0.1",
    "HOMEPAGE_ALLOWED_HOSTS": (
        "homepage.atlas.local,homepage.atlas.vandaele.io"
    ),
    "HTTP_BIND_IP": "127.0.0.1",
    "HTTP_PORT": "18080",
    "KOMETA_TIMES": "04:30",
    "LIDARR_API_KEY": "0123456789abcdef0123456789abcdef",
    "LIDARR_URL": "http://downloaders-vpn:8686",
    "LOG_TARGETS": "stdout",
    "MEDIA_DIR": "/volume1/data/media",
    "MUSIC_DIR": "/volume1/data/media/music",
    "NAS_LAN_IP": "127.0.0.1",
    "PGID": "10",
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


def compose_environment(compose_file: Path) -> dict[str, str]:
    compose_text = compose_file.read_text(encoding="utf-8")
    environment = os.environ.copy()
    for variable in COMPOSE_VARIABLE_PATTERN.findall(compose_text):
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


def load_repository(validation: Validation) -> tuple[dict, dict]:
    try:
        with (REPO_ROOT / "stacks.toml").open("rb") as file:
            stacks_data = tomllib.load(file)
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

    compose_inputs = set(
        COMPOSE_VARIABLE_PATTERN.findall(compose_file.read_text(encoding="utf-8"))
    )
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
        local_route_names == public_route_names,
        "Caddy routes must define matching local and public hostnames: "
        f"{sorted(local_route_names ^ public_route_names)}",
    )

    homepage_services = (
        STACKS_ROOT / "homepage" / "config" / "services.yaml"
    ).read_text(encoding="utf-8")
    homepage_hostnames = {
        hostname
        for hostname in re.findall(
            r"(?m)^\s*href:\s+https?://([^/\s]+)", homepage_services
        )
        if hostname.endswith(".atlas.local")
        or hostname.endswith(".atlas.vandaele.io")
    }
    missing_homepage_routes = homepage_hostnames - caddy_hostnames
    validation.require(
        not missing_homepage_routes,
        "Homepage Atlas URLs lack Caddy routes: "
        f"{sorted(missing_homepage_routes)}",
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

    with (REPO_ROOT / "stacks.toml").open("rb") as file:
        declared_variables = {
            item["name"] for item in tomllib.load(file).get("variable", [])
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
    validate_tracked_files(tracked, validation)
    validate_komodo_compose(validation)
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
    validate_required_compose_inputs(
        STACKS_ROOT / "homepage" / "compose.yaml",
        HOMEPAGE_REQUIRED_INPUTS,
        validation,
    )
    validation.finish()
    print(
        f"validate-repository: validated {rendered_projects} stack Compose projects"
    )


if __name__ == "__main__":
    main()
