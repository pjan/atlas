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

VALIDATION_VALUES = {
    "APP_KEY": "base64:dmFsaWRhdGlvbi1vbmx5",
    "APP_URL": "http://speedtest.atlas.local",
    "BACKUP_DIR": "/volume1/backups/roonserver",
    "CONFIG_DIR": "/volume2/appdata/validation",
    "CONF_DIR": "/volume2/appdata/adguard/conf",
    "CRON_SCHEDULE": "15 4 * * *",
    "DATA_DIR": "/volume1/data",
    "DNS_BIND_IP": "127.0.0.1",
    "HOMEPAGE_ALLOWED_HOSTS": (
        "homepage.atlas.local,homepage.atlas.vandaele.io"
    ),
    "HTTP_BIND_IP": "127.0.0.1",
    "HTTP_PORT": "18080",
    "KOMETA_TIMES": "04:30",
    "LOG_TARGETS": "stdout",
    "MEDIA_DIR": "/volume1/data/media",
    "MUSIC_DIR": "/volume1/data/media/music",
    "NAS_LAN_IP": "127.0.0.1",
    "PGID": "10",
    "PROTONVPN_PORT_FORWARD_ONLY": "on",
    "PROTONVPN_SERVER_COUNTRIES": "Netherlands",
    "PROTONVPN_VPN_PORT_FORWARDING": "on",
    "PUID": "999",
    "PRUNE_RESULTS_OLDER_THAN": "365",
    "RADARR_URL": "http://downloaders-vpn:7878",
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
    "SOULARR_CONFIG_DIR": "/volume2/appdata/soularr",
    "SPEEDTEST_SCHEDULE": "6 */6 * * *",
    "SPEEDTEST_SERVERS": "",
    "SPOTNET_IMPORTADULTCONTENT": "false",
    "SPOTNET_IMPORTBATCHSIZE": "500",
    "SPOTNET_RETENTIONDAYS": "1100",
    "SPOTNET_RETRIEVEAFTER": "2025-01-01",
    "TRANSCODE_DIR": "/volume2/tmp/plex/transcode",
    "TZ": "Etc/UTC",
    "UMASK": "002",
    "TORRENTS_DIR": "/volume1/data/downloads/torrents",
    "USENET_DIR": "/volume1/data/downloads/usenet",
    "USENET_MAXCONNECTIONS": "20",
    "USENET_PORT": "563",
    "USENET_USETLS": "true",
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

    for mount in service.get("volumes", []):
        if mount.get("type") != "bind":
            continue
        validation.require(
            mount.get("bind", {}).get("create_host_path") is False,
            f"{context} bind {mount.get('target')} must set create_host_path=false",
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


def main() -> None:
    os.chdir(REPO_ROOT)
    validation = Validation()
    stacks_data, _ = load_repository(validation)
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
        if stack:
            validate_relative_binds(
                compose_file, rendered, stack, validation
            )

    validate_caddy(stacks_by_name, validation)
    validate_hooks(stacks_by_name, validation)
    validate_tracked_files(tracked, validation)
    validate_komodo_compose(validation)
    validation.finish()
    print(
        f"validate-repository: validated {rendered_projects} stack Compose projects"
    )


if __name__ == "__main__":
    main()
