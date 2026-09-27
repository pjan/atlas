# Atlas

Repository holding the configuration of all my Docker Compose stacks for my NAS, deployed with [Komodo](https://komo.do/), updated with [Renovate](https://docs.renovatebot.com/).

## Environment

This repository manages Docker Compose stacks for the `Atlas` NAS.

- NAS: UGREEN DXP4800 Pro
- NAS LAN IP: `192.168.2.200`
- NAS checkout/bootstrap directory: `/volume2/docker/komodo`
- Periphery workspace directory: `/volume2/komodo`
- Komodo Core URL: `http://192.168.2.200:9120`
- Caddy HTTP entrypoint: `http://192.168.2.200:80`
- Local DNS zone: `*.atlas.local`
- Public application zone: `*.atlas.vandaele.io` through Cloudflare Tunnel and Caddy
- Remote access: Tailscale (on the UniFi router) for private access, with selected Caddy applications also available through Cloudflare Access-protected public hostnames
- Timezone: `Asia/Singapore`, set once in the Komodo `TZ` variable (see [Timezone And Schedules](#timezone-and-schedules))

## One-Time NAS Preparation

### 1. Free Port 80 In UGOS

UGOS can bind ports `80` and `443` with its built-in nginx service. The current Atlas Caddy stack only binds port `80`, so port `80` must be free for clean local hostnames such as `http://sonarr.atlas.local`. Port `443` only needs to be freed if Atlas later adds HTTPS on Caddy.

In the UGOS dashboard:

1. Open `Control Panel`.
2. Open `Device Connection`.
3. Open `Portal Settings`.
4. Uncheck the option that redirects port `80` to the portal HTTP port. If you later add HTTPS on Caddy, also uncheck the option for port `443`.
5. Apply the change.

Verify over SSH:

```sh
sudo ss -ltnp | grep ':80' || echo "port 80 is free"
```

Expected result: no UGOS/nginx listener on `0.0.0.0:80`.

### 2. Configure UniFi Local DNS

On the UniFi Dream Machine, configure local DNS so app subdomains resolve to the NAS.

For newer UniFi Network versions, the DNS record UI is usually under one of these paths:

```text
Settings > Policy Engine > DNS > Create DNS Record
Settings > Policy Table > Create New Policy > DNS
```

Host (A) wildcard record:

```text
hostname *.atlas.local, value 192.168.2.200
```

### 3. Bootstrap Komodo Manually

Komodo manages the app stacks, but Komodo itself is bootstrapped manually. Do not rely on Komodo to update/restart itself.

SSH into the NAS:

```sh
ssh <nas-user>@192.168.2.200
sudo -i
cd /volume2/docker/komodo
```

Copy the contents of this repository’s `komodo/` directory into `/volume2/docker/komodo`, then copy `.env.example` to the untracked `.env` file and edit `/volume2/docker/komodo/.env`. Never commit the runtime `.env` file.

Generate separate values:

```sh
openssl rand -base64 32
openssl rand -base64 32
openssl rand -base64 32
openssl rand -base64 64
```

Use them together with the non-random required values:

```env
KOMODO_DATABASE_USERNAME=<mongo-root-username>
KOMODO_DATABASE_PASSWORD=<32-byte random value>
KOMODO_INIT_ADMIN_PASSWORD=<32-byte random value>
KOMODO_WEBHOOK_SECRET=<32-byte random value>
KOMODO_JWT_SECRET=<64-byte random value>
COMPOSE_KOMODO_BACKUPS_PATH=/volume1/backups/komodo
PERIPHERY_ROOT_DIRECTORY=/volume2/komodo
```

`PERIPHERY_ROOT_DIRECTORY` is Periphery's workspace for repositories, stacks, builds, and related state. It does not need to equal the bootstrap directory. For containerized Periphery, it must be bind-mounted at the identical path inside and outside the container; `komodo/compose.yaml` does this automatically from the variable.

Before the first start, create the two writable bind sources on the NAS. Run this from the root shell opened above; it creates only missing directories and rejects symbolic-link destinations:

```sh
umask 027
for path in /volume1/backups/komodo /volume2/komodo; do
  if test -L "$path"; then
    echo "refusing symbolic-link directory: $path" >&2
    exit 1
  fi
  mkdir -p "$path"
  test -d "$path" && test -w "$path" || {
    echo "Komodo directory is not writable: $path" >&2
    exit 1
  }
done
```

Compose uses `create_host_path: false` for both mounts. A missing or mistyped path therefore stops deployment instead of silently creating an empty `root:root` directory. Existing installations need no migration when both paths already exist.

Before starting Komodo, confirm no example placeholder remains:

```sh
if grep -n '<replace-' .env; then
  echo "replace every placeholder before starting Komodo" >&2
  exit 1
fi
```

Now start Komodo:

```sh
docker compose --env-file .env -f compose.yaml up -d
```

The same command is used both for first bootstrap and for applying later changes to `compose.yaml` or `.env`. Docker Compose recreates only containers whose effective configuration changed and preserves the named volumes used for Mongo data and Komodo keys.

Important operational notes:

- `KOMODO_INIT_ADMIN_PASSWORD` only affects initial admin creation. If Komodo has already initialized, change the admin password in the Komodo UI.
- Changing `KOMODO_DATABASE_PASSWORD` after Mongo has initialized does not rotate the existing Mongo user password. Rotate the Mongo user inside Mongo before changing this value on a live install.
- Changing `KOMODO_JWT_SECRET` invalidates existing login sessions.
- If GitHub or another system sends Komodo webhooks, `KOMODO_WEBHOOK_SECRET` must match that sender.
- `COMPOSE_KOMODO_BACKUPS_PATH` must point at the persistent NAS directory prepared before startup. Docker is not allowed to create it implicitly.

For repository validation without a runtime `.env`, point Compose's service-level environment file at the example explicitly:

```sh
KOMODO_ENV_FILE=.env.example \
docker compose --env-file komodo/.env.example -f komodo/compose.yaml config --quiet
```

## Komodo Resource Sync

Komodo should be configured with a Resource Sync that reads `stacks.toml` from this repository on branch `main`.

Recommended Resource Sync settings:

```toml
[[resource_sync]]
name = "atlas"
description = "Atlas stack definitions"

[resource_sync.config]
git_provider = "github.com"
repo = "pjan/atlas"
branch = "main"
resource_path = ["stacks.toml"]
include_variables = true
include_resources = true
```

This NAS does not expose Komodo webhooks publicly. Instead, Komodo polls for resource updates. The polling interval is configured in the copied `.env`:

```env
KOMODO_RESOURCE_POLL_INTERVAL="5-min"
```

Normal workflow:

```text
Push to main -> wait for Komodo polling -> execute Resource Sync -> Komodo applies stack definitions
```

Komodo doubles every backslash between triple double quotes (`"""`) before parsing `stacks.toml`, so those strings are literal: `\` at a line end stays a shell line continuation, and escape sequences such as `\.` or `\n` are not interpreted. Avoid backslash escapes inside `"""` hook commands (for example, write `[.]` in a regular expression). `scripts/validate-repository.py` applies the same transformation, so validation sees what Komodo deploys.

## Deploying Stack Changes

After pushing changes to `main`:

1. Open Komodo.
2. Wait for the `atlas` Resource Sync to show pending changes.
3. Review the diff.
4. Execute the sync.

## Timezone And Schedules

The Komodo variable `TZ` (declared in `stacks.toml`) is the single source of local time for Atlas. Every stack passes `TZ = [[TZ]]` to its containers, so application logs and container-internal schedules (Recyclarr, Kometa, Speedtest Tracker, Plex) run in that timezone.

Two places cannot read the Komodo variable and must be changed by hand when `TZ` changes:

- Komodo Core's own procedures use `TZ` in `/volume2/docker/komodo/.env`. Update it and run `docker compose --env-file .env -f compose.yaml up -d` in `/volume2/docker/komodo`.
- Schedules configured inside application UIs: the Plex maintenance window (`Settings > Scheduled Tasks`) and the Roon scheduled backup (`Settings > Backups`).

Changing `TZ` in `stacks.toml` only updates the Komodo variable. Stack configurations contain the literal `TZ = [[TZ]]`, and Resource Sync compares raw configuration, so executing the sync does not redeploy any stack. Containers keep the old timezone until their stack is redeployed. Redeploy `gluetun` first and wait until it is healthy, then redeploy the remaining running stacks. Do not redeploy Gluetun in the same batch as the VPN-bound stacks: their pre-deploy check could pass against the old Gluetun container before it is replaced.

Nightly schedule in local time:

```text
01:00  Komodo procedure: Backup Core Database           (Core .env TZ)
02:00  Plex maintenance window opens (until 04:30)      (Plex UI)
03:00  Komodo procedure: Global Auto Update             (Core .env TZ)
03:00  Kometa run (KOMETA_TIMES)                        (TZ)
04:00  Roon scheduled backup                            (Roon UI)
04:15  Recyclarr sync (CRON_SCHEDULE)                   (TZ)
05:00  Komodo Action: appdata-backup (APPDATA_BACKUP_HOUR, see Backups)   (TZ)
06:00  Komodo procedure: Rotate Server Keys             (Core .env TZ)
```

Keep new scheduled work out of the 04:30–06:30 window, which is reserved for the nightly backups.

## Backups

### What Is Backed Up Where

| Data | Local copy | Written by |
|---|---|---|
| Application state (`/volume2/appdata`) and the Komodo bootstrap directory (`/volume2/docker/komodo`) | `/volume1/backups/appdata` | `appdata-backup` Action, daily at `APPDATA_BACKUP_HOUR` |
| Komodo database | `/volume1/backups/komodo` | Komodo procedure "Backup Core Database", daily at 01:00, 14 kept |
| Plex database | `/volume1/backups/plex` | Plex scheduled task, every three days |
| Roon database | `/volume1/backups/roonserver` | Roon scheduled backup, daily at 04:00 |

Off-site, Backrest copies all of `/volume1/backups` to the Google Shared Drive `Atlas` every day at 06:00 (see [Off-Site Backups With Backrest](#off-site-backups-with-backrest)).

The appdata copy excludes `roonserver` (covered by Roon's own backups), monitoring data (`prometheus` and `grafana`, see [Monitoring](#monitoring)), Plex caches, codecs, drivers, logs, and crash reports, and AdGuard query logs. The rules live in `stacks/appdata-backup/filters.txt`.

### Nightly Appdata Snapshot

The `appdata-backup` Komodo Action is defined in `stacks.toml`. It runs every hour and acts only when the local hour in `TZ` equals `APPDATA_BACKUP_HOUR`:

1. Restart any stacks that an interrupted run left stopped. The list is kept in the runtime Komodo variable `APPDATA_BACKUP_STOPPED_STACKS`, which the Action creates itself and which must not be added to `stacks.toml`. `run_at_startup` repeats this recovery whenever Core starts.
2. Run the `prepare` service, which creates `/volume1/backups/appdata` (`0700`), its `snapshots` directory, and `/volume1/backups/.metrics`.
3. Run `backup check` before anything is stopped. It fails unless the sentinel `/volume2/appdata/.atlas-backup-source` exists and the source holds at least 500 files and at least 60% of the previous snapshot's file count.
4. Record every running stack except `appdata-backup`, `backrest`, `caddy`, `cloudflared`, `flaresolverr`, `gluetun`, `monitoring`, and `roonserver`, then stop them in parallel.
5. Only if every stop succeeded, run `backup run`: a new dated snapshot under `snapshots/`, hard-linked against the previous one with `rsync --link-dest`, so unchanged files take no extra space. `latest` then points at it, and `.last-success` records its time. Snapshots older than 14 days are pruned, always keeping at least 7.
6. Start every recorded stack independently, even when a previous step failed.
7. Ping Healthchecks (`HEALTHCHECKS_APPDATA_PING_URL`) with success or failure, and fail the Action on any error.

The `appdata-backup` stack is never deployed. Both services use the `manual` Compose profile, so an accidental deploy fails with `no service selected` instead of starting a copy while applications run. `backup.sh` also writes `/volume1/backups/.metrics/atlas_backups.prom` for monitoring.

Create the sentinel only after confirming that `/volume2/appdata` is complete:

```sh
touch /volume2/appdata/.atlas-backup-source
```

The sentinel is part of every snapshot, so restoring appdata from a snapshot restores it too.

To run a backup immediately, run the `appdata-backup-now` Action in Komodo. The Komodo UI cannot pass arguments to an Action, so this wrapper calls `appdata-backup` with `FORCE=true`.

### Off-Site Backups With Backrest

The `backrest` stack runs [Backrest](https://github.com/garethgeorge/backrest), a web UI and scheduler for restic. Its UI is reachable only on the LAN at `http://backrest.atlas.local`: it holds every repository password and destination credential, so it has no public hostname, and the validator enforces that through `LOCAL_ONLY_CADDY_ROUTES`. Backrest also requires its own login.

Layout inside the container:

| Path | Host | Purpose |
|---|---|---|
| `/sources/<name>` | read-only source binds | What can be backed up. Today only `/sources/volume1-backups` (`/volume1/backups`). |
| `/config` | `/volume2/appdata/backrest/config` | `config.json`, `rclone/rclone.conf`, service-account keys, and SSH keys (`.backrest-ssh`) |
| `/data` | `/volume2/appdata/backrest/data` | Operation history and logs |
| `/cache` | `/volume2/tmp/backrest/cache` | restic cache, one per repository, disposable |
| `/restore` | `/volume2/tmp/backrest/restore` | Target for restores from the UI |

Naming conventions:

- An **rclone remote** is a named section in `/config/rclone/rclone.conf`, named after its destination, for example `gdrive-atlas` for the `Atlas` Shared Drive.
- A **repository** is named `<rclone remote>-<folder>`, for example `gdrive-atlas-backups` for `rclone:gdrive-atlas:backups`, so several repositories can share one destination. Each repository has its own restic password. Backrest repository IDs cannot be renamed.
- A **plan** is named `<instance>-<source>`, for example `atlas-volume1-backups`, and points at one repository.
- Each plan has its own Healthchecks check; repository-level hooks (Discord on any error) apply to every plan that uses the repository.

Current configuration:

| Item | Value |
|---|---|
| rclone remote | `[gdrive-atlas]`: `type = drive`, `scope = drive`, `service_account_file = /config/rclone/io-vandaele-atlas-backrest.json`, `team_drive = <Atlas Shared Drive ID>` |
| Repository | `gdrive-atlas-backups`, URI `rclone:gdrive-atlas:backups`, flag `--pack-size=64`, auto unlock, weekly prune and check (last-run clock), Discord hook on any error |
| Plan | `atlas-volume1-backups`: source `/sources/volume1-backups`, excluding `#recycle`, `manual`, and `komodo-pre-rebuild-*`; daily at 06:00 (local clock); keep 7 daily, 4 weekly, 12 monthly |
| Plan hooks | Pre-check on snapshot start with `ON_ERROR_FATAL` (fails unless the appdata snapshot is complete and younger than 26 hours); Healthchecks on snapshot start, success, warning, skipped, and error |

The restic password and the service-account key are also stored inside the backup itself (in the appdata snapshot of `/volume2/appdata/backrest`), so they must be kept in the password manager too; without them the off-site copy cannot be opened.

Restore from the off-site copy on the NAS:

1. In Backrest, open the plan or repository, choose a snapshot, and restore the needed path to `/restore/<name>`.
2. On the NAS, stop the affected stack and copy the files into place, for example:

   ```sh
   rsync -aH --numeric-ids \
     /volume2/tmp/backrest/restore/<name>/sources/volume1-backups/appdata/latest/appdata/<app>/ \
     /volume2/appdata/<app>/
   ```

3. Start the stack and remove the restore directory.

Restore without the NAS, from a computer with `restic` and `rclone` (for example `brew install restic rclone`), using the password-manager copies of the restic password, the service-account key, and the Shared Drive ID:

```sh
mkdir -p ~/atlas-restore && cd ~/atlas-restore
# Save the service-account key here as io-vandaele-atlas-backrest.json.
cat > rclone.conf <<EOF
[gdrive-atlas]
type = drive
scope = drive
service_account_file = $PWD/io-vandaele-atlas-backrest.json
team_drive = <Atlas Shared Drive ID>
EOF
export RCLONE_CONFIG="$PWD/rclone.conf"
export RESTIC_REPOSITORY=rclone:gdrive-atlas:backups
restic snapshots   # prompts for the restic password
restic restore latest --target ./restore \
  --include /sources/volume1-backups/komodo \
  --include /sources/volume1-backups/appdata
```

### Adding Another Backrest Backup

- **New source:** add a read-only bind to `stacks/backrest/compose.yaml` mounted at `/sources/<name>` (long syntax, `create_host_path: false`), provide its host path through the stack environment, and redeploy `backrest`.
- **New destination:** for Google Drive, add the service account as `Content manager` to the Shared Drive and add a `[<remote-name>]` section to `/config/rclone/rclone.conf` (a different Shared Drive only needs another `team_drive`; another Google account needs its own key file). For native restic backends such as B2, S3, or SFTP, set the backend variables on the repository in the Backrest UI instead; SFTP keys live in `/config/.backrest-ssh`. Then create the repository with a new password stored in the password manager, and add the repository-level Discord hook.
- **New plan:** point it at the source and repository, give it its own Healthchecks check, and schedule it so it does not overlap the 04:30–06:30 window or other plans on the same repository.
- Raise `mem_limit` in `stacks/backrest/compose.yaml` if large sources make restic run out of memory.

### Restoring From The Local Snapshot

Restore one application:

```sh
# 1. Stop the stack in Komodo.
# 2. Copy the snapshot back, preserving ownership and modes:
rsync -aH --numeric-ids --delete \
  /volume1/backups/appdata/latest/appdata/<app>/ /volume2/appdata/<app>/
# 3. Start the stack in Komodo.
```

Replace `latest` with `snapshots/<YYYY-MM-DD_HHMMSS>` to restore an older state. `--delete` makes the application directory match the snapshot exactly; leave it out to only add and overwrite files.

## Disaster Recovery: Rebuilding Volume 2

Volume 2 holds Docker, the Komodo bootstrap directory, Periphery's workspace, and all application state under `/volume2/appdata` and `/volume2/tmp`. Volume 1 holds media, downloads, and `/volume1/backups`, including Komodo's daily database backups in `/volume1/backups/komodo` (the 14 most recent are kept) and Roon backups in `/volume1/backups/roonserver`. Application appdata is not backed up off Volume 2, so after a Volume 2 loss every application except Komodo and Roon starts from a fresh configuration.

1. Reinstall the UGOS Docker app on Volume 2 and confirm `docker info --format '{{.DockerRootDir}}'` reports `/volume2/@docker`.
2. Keep a copy of the Komodo backups before Core starts pruning them: `cp -a /volume1/backups/komodo /volume1/backups/komodo-pre-rebuild-<date>`.
3. Recreate `/volume2/komodo` and `/volume2/docker/komodo`, place `komodo/compose.yaml` there, and restore `.env` from `/volume1/backups/appdata/latest/komodo-bootstrap/.env` (or the password manager). Without either, create a new `.env` as described in [Bootstrap Komodo Manually](#3-bootstrap-komodo-manually); new secrets are fine because the restore brings back the users with their existing passwords.
4. Start only Mongo. Do not start Core yet: a fresh Core creates an admin user, the `atlas` server, and default procedures that collide with the restored ones.

   ```sh
   docker compose --env-file .env -f compose.yaml up -d mongo
   ```

5. Restore the newest backup folder into the empty database:

   ```sh
   DB_USER=$(sed -n 's/^KOMODO_DATABASE_USERNAME=//p' .env)
   DB_PASS=$(sed -n 's/^KOMODO_DATABASE_PASSWORD=//p' .env)
   docker run --rm \
     --network komodo_default \
     -v /volume1/backups/komodo:/backups:ro \
     -e KOMODO_CLI_DATABASE_TARGET_ADDRESS=mongo:27017 \
     -e KOMODO_CLI_DATABASE_TARGET_USERNAME="$DB_USER" \
     -e KOMODO_CLI_DATABASE_TARGET_PASSWORD="$DB_PASS" \
     -e KOMODO_CLI_DATABASE_TARGET_DB_NAME=komodo \
     ghcr.io/moghtech/komodo-cli:<core-version> \
     km database restore -y --restore-folder <YYYY-MM-DD_HH-MM-SS>
   ```

   Then pause the nightly appdata backup until application state is restored:

   ```sh
   docker exec komodo-mongo mongosh --quiet -u "$DB_USER" -p "$DB_PASS" --authenticationDatabase admin komodo \
     --eval 'db.Action.updateOne({ name: "appdata-backup" }, { $set: { "config.schedule_enabled": false } })'
   unset DB_USER DB_PASS
   ```

   The sentinel check already refuses an empty source, so this is a second guard.

6. Restore application state before deploying any stack, so first-run setup is not needed:

   ```sh
   rsync -aH --numeric-ids /volume1/backups/appdata/latest/appdata/ /volume2/appdata/
   ```

   Re-enable the `appdata-backup` Action schedule in Komodo afterwards (`Actions > appdata-backup > Config`). If no appdata snapshot exists, continue without it and create the sentinel once the applications are configured again.

7. Start Core and Periphery with `docker compose --env-file .env -f compose.yaml up -d` and log in with the restored admin password. The restored `atlas` server still expects the old Periphery public key. Open `Servers > atlas > Confirm Public Key` and accept the new key only after checking that it matches the `Public Key` line in `docker logs komodo-periphery`.
8. Do not execute the `atlas` Resource Sync yet. With `deploy = true`, it deploys every stack that is not running at once, before first-run steps such as the AdGuard wizard (port `3000`), the Plex claim token, and the SABnzbd host whitelist can be handled. Deploy stacks manually instead, one wave at a time:

   ```text
   caddy, adguard
   gluetun (verify the public IP and forwarded port)
   qbittorrent, sabnzbd
   flaresolverr, prowlarr, sonarr, radarr, lidarr
   recyclarr (before Library Import, so the TRaSH profiles exist)
   bazarr, spottarr, slskd, autobrr, qui
   unpackerr, seerr, houndarr, soularr
   plex, kometa, roonserver
   remaining stacks
   ```

   Execute the Resource Sync only once every stack that should run is running; it should then find nothing to deploy.

9. If application state could not be restored, note that restored secrets that Atlas passes to an application stay valid, for example the Proton VPN key, the Gluetun control key, slskd and Spottarr credentials, the Cloudflare tunnel token, the Speedtest Tracker app key, and the Homepage Komodo API key. Keys that an application generates itself do not: after each first-run setup, copy the new Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, SABnzbd, qBittorrent, Seerr, Plex server, and Speedtest Tracker API keys or tokens into their Komodo variables before deploying the stacks that consume them.
10. For Roon, choose `Restore a backup` on the first start of the new core, select `/RoonBackups`, and unauthorize the old core when prompted.

## Host Filesystem Provisioning

Komodo Periphery runs in a container. A plain `mkdir`, `chown`, or `cp` in a stack hook operates inside that container unless the destination is mounted there. Docker bind mounts, however, are resolved by the NAS Docker daemon. If a short bind source is absent, Docker can create it on the NAS as `root:root` even when a preceding Periphery command appeared to prepare it.

Atlas avoids that namespace mismatch with `scripts/atlas-hostfs.sh`. The helper asks the NAS Docker daemon to run a pinned, short-lived BusyBox container against one of these allowlisted roots:

```text
/volume1/data
/volume1/backups
/volume2/appdata
/volume2/tmp
```

Normal directory preparation is nonrecursive and includes a real write probe using the requested UID/GID. Shared media-directory preparation preserves an existing owner while enforcing the intended group and top-level mode; a missing directory is created with the application identity. Managed runtime files can be created when absent and have owner/mode enforced without replacing existing content. Recursive owner repair is limited to one private appdata or scratch tree, requires an explicit confirmation argument, and must not be used against shared media.

The helper foundation is installed before production stack hooks are migrated. Until a stack's `pre_deploy` command calls this helper, its existing permission behavior is unchanged.

### Local Helper Tests

Run from the repository root with Docker available:

```sh
./scripts/test-phase-1.sh
```

The test suite covers allowlist rejection, dry-run behavior, atomic managed-file installation, symlink rejection, write probes, private-tree audit/repair on native Linux bind filesystems, constrained canary cleanup, and concurrent Docker network creation. Docker Desktop virtualizes bind ownership, so its test uses a native Docker volume to prove `1000:1000` ownership and write behavior.

### NAS Canary From Periphery

Run the canary after these changes are on `main` and the Atlas Resource Sync has cloned the updated repository. Start on the NAS:

```sh
ssh <nas-user>@192.168.2.200
sudo -i

ATLAS_HOSTFS=$(docker exec komodo-periphery sh -eu -c '
  find "${PERIPHERY_ROOT_DIRECTORY:?}" \
    -type f \
    -path "*/scripts/atlas-hostfs.sh" \
    -print \
    | head -n 1
')

test -n "$ATLAS_HOSTFS"
printf 'Using helper: %s\n' "$ATLAS_HOSTFS"
```

If more than one checkout exists, do not use `head -n 1`; select the path belonging to the active Atlas Resource Sync checkout.

First run the non-production integration suite inside Periphery:

```sh
ATLAS_TESTS=$(dirname "$ATLAS_HOSTFS")/test-phase-1.sh
docker exec komodo-periphery sh "$ATLAS_TESTS"
```

Then create one private-appdata canary as `1000:1000` and one shared-data canary as `999:10`:

```sh
docker exec komodo-periphery sh "$ATLAS_HOSTFS" ensure-dir \
  /volume2/appdata/.atlas-permission-test 1000 1000 0750

docker exec komodo-periphery sh "$ATLAS_HOSTFS" ensure-dir \
  /volume1/data/.atlas-permission-test 999 10 2775
```

Verify from the NAS host:

```sh
stat -c '%u:%g %a %n' \
  /volume2/appdata/.atlas-permission-test \
  /volume1/data/.atlas-permission-test
```

Expected output contains:

```text
1000:1000 750 /volume2/appdata/.atlas-permission-test
999:10 2775 /volume1/data/.atlas-permission-test
```

Clean up only through the constrained canary command:

```sh
docker exec komodo-periphery sh "$ATLAS_HOSTFS" remove-canary \
  /volume2/appdata/.atlas-permission-test

docker exec komodo-periphery sh "$ATLAS_HOSTFS" remove-canary \
  /volume1/data/.atlas-permission-test
```

Do not run `repair-tree-owner` against production appdata during the canary phase. Audit and migrate one stopped application at a time in the next deployment phase.

### Helper Troubleshooting

- `docker is not available`: confirm `/var/run/docker.sock` is mounted in Periphery and the `docker` CLI is present.
- `bind source path does not exist`: confirm `/volume1` and `/volume2` exist on the NAS and the test checkout path is identity-mounted through `PERIPHERY_ROOT_DIRECTORY`.
- Owner/mode assertion failure: check `docker info` for user namespace remapping and inspect NAS ACLs with `getfacl`.
- Write-probe failure after correct `stat`: inspect inherited UGOS ACLs before changing Unix modes.
- Never fix a shared-media failure with `chown -R /volume1/data`.

## Required Non-Default Variables

Atlas keeps a small set of values outside repo-tracked defaults. Create them in Komodo before deploying the stacks that need them.

Bootstrap `.env` values for `komodo/`:

```text
KOMODO_DATABASE_USERNAME
KOMODO_DATABASE_PASSWORD
KOMODO_INIT_ADMIN_PASSWORD
KOMODO_WEBHOOK_SECRET
KOMODO_JWT_SECRET
COMPOSE_KOMODO_BACKUPS_PATH
PERIPHERY_ROOT_DIRECTORY
```

Shared stack values managed in Komodo:

```text
BAZARR_API_KEY
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_TUNNEL_ID
CLOUDFLARE_TUNNEL_TOKEN
GLUETUN_CONTROL_API_KEY
GRAFANA_ADMIN_PASSWORD
GRAFANA_SECRET_KEY
HEALTHCHECKS_APPDATA_PING_URL
HOMEPAGE_ADGUARD_PASSWORD
HOMEPAGE_ADGUARD_USERNAME
HOMEPAGE_CLOUDFLARE_API_TOKEN
HOMEPAGE_KOMODO_API_KEY
HOMEPAGE_KOMODO_API_SECRET
HOMEPAGE_SPEEDTEST_TRACKER_API_KEY
HOMEPAGE_UNIFI_API_KEY
KOMETA_PLEX_TOKEN
KOMETA_TMDB_API_KEY
LIDARR_API_KEY
PLEX_SERVER_TOKEN
PROTONVPN_WIREGUARD_PRIVATE_KEY
PROWLARR_API_KEY
QBITTORRENT_API_KEY
RADARR_API_KEY
SABNZBD_API_KEY
SEERR_API_KEY
SLSKD_API_KEY
SLSKD_JWT_KEY
SLSKD_SLSK_PASSWORD
SLSKD_SLSK_USERNAME
SLSKD_WEB_PASSWORD
SLSKD_WEB_USERNAME
SONARR_API_KEY
SPEEDTEST_TRACKER_APP_KEY
SPOTTARR_NEWZNAB_API_KEY
SPOTTARR_USENET_HOSTNAME
SPOTTARR_USENET_PASSWORD
SPOTTARR_USENET_USERNAME
UNIFI_URL
UPTIME_KUMA_SLUG
```

Komodo variables use uppercase snake case and are named for the service or
resource that owns the value. Compose files translate those names to any
upstream-specific environment names. Homepage's required `HOMEPAGE_VAR_*`
prefix therefore appears only inside the Homepage container environment and
its configuration placeholders, not in Komodo variable names or stack inputs.

Generate `QBITTORRENT_API_KEY` in qBittorrent under `Options > WebUI >
Authentication > API Key`, then store the complete `qbt_...` value in Komodo.
Homepage uses this key for stateless Web API access; it does not replace the
qBittorrent WebUI username and password used for interactive login.

Optional or temporary values:

```text
PLEX_CLAIM
```

`PLEX_CLAIM` is usually only needed for a fresh Plex claim flow and should be cleared after the server is attached.

### Plex Claim Token

When deploying Plex for the first time, `PLEX_CLAIM` needs to be set. It is a short-lived token from `https://plex.tv/claim` that attaches the new Plex server to your Plex account during first startup.

To claim a fresh Plex install:

1. Generate a claim token at `https://plex.tv/claim`.
2. Set `PLEX_CLAIM` on the Plex stack in Komodo.
3. Deploy Plex.
4. Confirm the server appears in your Plex account.
5. Clear `PLEX_CLAIM` and redeploy Plex so the expired token is not retained.

If restoring an existing Plex `/config` with a valid `Preferences.xml`, a claim token is usually not required.

### Plex Storage

Plex stores its database, metadata, preferences, claim state, and authentication tokens under `/volume2/appdata/plex`. The pre-deploy hook provisions only the top-level private directory as `999:10` with mode `0750`; existing nested ownership is repaired only after a stopped private-tree audit. Back up this directory before migration and preserve its ownership and permissions.

The disposable transcode directory is `/volume2/tmp/plex/transcode`, provisioned as `999:10` with mode `0770`. It does not need to be backed up. Plex mounts `/volume1/data/media` read-only, and deployment must never recursively change ownership or permissions in that shared library tree.

Plex's scheduled database backups go to `/volume1/backups/plex`, mounted at `/backups`, so they survive a Volume 2 failure. The pre-deploy hook provisions that directory as `999:10` with mode `0750`. In Plex `Settings > Scheduled Tasks`, keep `Backup database every three days` enabled and set `Backup directory` to `/backups`.

All Plex bind sources use `create_host_path: false`, so missing appdata, media, transcode, or backup paths fail instead of becoming Docker-created `root:root` directories. Plex keeps the direct `192.168.2.200:32400` listener for native clients and discovery, while the browser UI remains available through `http://plex.atlas.local`.

In Plex `Settings > Network`, set `LAN Networks` to `192.168.2.0/24`. Plex runs on a Docker bridge network and otherwise treats LAN clients as remote, applying remote bandwidth limits and transcoding. Do not add Docker subnets: Caddy-proxied public traffic would then count as local. Leave `List of IP addresses and networks that are allowed without auth` empty.

### Roon Server Storage

The pinned Roon Server image runs its server processes as `root`. Its private state lives under `/volume2/appdata/roonserver`; the pre-deploy hook provisions only that top-level directory as `0:0` with mode `0750`. It does not recursively change the existing Roon database tree.

Roon mounts `/volume1/data/media/music` read-only. The hook preserves the existing owner of that shared path, enforces group `10` and mode `2775` on its top-level directory, and verifies that the shared media identity can write there for the surrounding download workflow. It never recursively changes the music library.

Roon backups live under `/volume1/backups/roonserver`. The hook provisions only that child as `0:10` with mode `2770`; existing backup contents keep their current ownership and modes. All three bind sources use `create_host_path: false`, and Roon receives a two-minute stop grace period for clean database shutdown.

### AdGuard Storage

The pinned AdGuard Home image runs as `root`. Its work and configuration directories live under `/volume2/appdata/adguard`, and the pre-deploy hook provisions the app root plus `work` and `conf` as `0:0` with mode `0750`. Existing files, including `AdGuardHome.yaml`, are not recursively modified.

Both bind sources use `create_host_path: false`, so a missing preflight path fails closed rather than being silently created by Docker. DNS remains bound only to `[[NAS_LAN_IP]]:53` over TCP and UDP. Deploy AdGuard separately from other stacks because its restart temporarily interrupts Atlas DNS.

Atlas deliberately keeps the AdGuard Home web interface on container port `3000` after the initial setup. The Caddy route and container healthcheck both depend on `http.address` remaining `0.0.0.0:3000`. During a fresh installation or a restore without the existing `AdGuardHome.yaml`, select port `3000` in the setup wizard instead of the normal port `80`.

Verify the persisted listener without printing the adjacent user configuration:

```sh
docker exec adguard awk '/^http:/ { in_http=1; next } in_http && /^[^[:space:]]/ { exit } in_http && /^[[:space:]]+address:/ { print; exit }' /opt/adguardhome/conf/AdGuardHome.yaml
```

The expected result is `address: 0.0.0.0:3000`. If DNS works but `http://adguard.atlas.local` does not, check this value before changing Caddy or exposing a temporary host UI port.

### Kometa Tokens

Kometa reads repo-tracked config files from `stacks/kometa/config/`, but secrets stay in Komodo variables.

Required Komodo variables:

```text
KOMETA_PLEX_TOKEN
KOMETA_TMDB_API_KEY
```

Use a Plex token generated for Kometa, not the Plex server token from `Preferences.xml`.

Kometa has no Atlas web route. It runs on the configured `KOMETA_TIMES` schedule and reaches Plex through `http://plex:32400` on `media_network`. Runtime configuration, cache, reports, and assets live under `/volume2/appdata/kometa`; the pre-deploy hook explicitly provisions the configured `assets` directory. Preserve that private tree with owner `999:10` and mode `0750` when backing it up.

Kometa intentionally has no Docker healthcheck. Its scheduled process can remain alive while an individual metadata run fails, so a process-only check would not prove successful work. Monitor completion and errors in the Kometa run logs and alert when the expected daily run does not complete.

The repository-managed `config.yml`, `collections/movies.yml`, and `collections/tv.yml` files trigger a full Kometa redeploy. Before Compose starts, the pre-deploy hook atomically installs them into appdata and verifies their SHA-256 checksums. `config.yml` uses mode `0600`; collection definitions use `0640`. The tracked configuration contains token placeholders, while the actual Plex and TMDb credentials remain required Komodo variables.

Do not repair Kometa with an unrestricted recursive `chown`. Stop the container, audit `/volume2/appdata/kometa`, and use `repair-tree-owner` only when the private-tree audit reports ownership mismatches.

### Plex Token For Homepage

The Homepage Plex widget needs a Plex auth token. For Atlas, the simplest source is the `PlexOnlineToken` stored in Plex's `Preferences.xml` after the server has been claimed and signed in to your Plex account.

Run this on the NAS:

```sh
docker exec plex sh -lc 'sed -n '\''s/.*PlexOnlineToken="\([^"]*\)".*/\1/p'\'' "/config/Library/Application Support/Plex Media Server/Preferences.xml"'
```

Expected result: a single token value with no surrounding XML.

If you want to read it directly from the host-mounted config directory instead of through the container, run:

```sh
sed -n 's/.*PlexOnlineToken="\([^"]*\)".*/\1/p' "/volume2/appdata/plex/Library/Application Support/Plex Media Server/Preferences.xml"
```

Set the returned value in Komodo as:

```text
PLEX_SERVER_TOKEN
```

Then redeploy `homepage` so the updated environment variable is injected into the container.

Notes:

- This only works after Plex has been successfully claimed and signed in to your Plex account.
- If the command returns nothing, first confirm Plex is claimed and the server is visible in your Plex account.
- Plex documents a browser-based way to obtain an `X-Plex-Token` from the Plex Web App XML view. The `Preferences.xml` method above is the more direct Atlas-specific approach for the Homepage variable.
- If you reset your Plex password and sign out connected devices, Plex tokens can be invalidated. If the Homepage Plex widget stops working after an account security change, fetch the token again and update `PLEX_SERVER_TOKEN`.

### Seerr

The `seerr` stack runs Seerr behind Caddy at:

```text
http://seerr.atlas.local
```

Deploy order:

1. Deploy `seerr`.
2. Deploy or redeploy `caddy`.
3. Complete first-run setup.

On first setup, configure these services inside Seerr:

```text
Plex URL: http://plex:32400
Sonarr URL: http://downloaders-vpn:8989
Radarr URL: http://downloaders-vpn:7878
```

Use the API keys from Sonarr and Radarr, then choose the correct root folders and quality profiles in Seerr. Lidarr and music requests are intentionally out of scope for the baseline integration.

Operational notes:

- This stack does not expose a direct host port. Access is Caddy-only through `http://seerr.atlas.local`.
- Seerr relies on its own auth plus Plex auth. There is no Caddy Basic Auth gate.
- The container runs as UID/GID `1000:1000`. The pre-deploy step nonrecursively provisions `[[APPDATA_DIR]]/seerr` and its `logs` child; existing nested ownership is audited and repaired only during a stopped migration.
- `[[APPDATA_DIR]]/seerr` should be backed up with its ownership and permissions preserved.
- Protect the public Seerr hostname with Cloudflare Access and retain application authentication.

### Arr Storage Policy

Sonarr, Radarr, Prowlarr, Lidarr, and Bazarr use LinuxServer's configured UID/GID `999:10`. Their private configuration directories under `/volume2/appdata` are provisioned nonrecursively with mode `0750`; a stopped migration may audit and repair nested ownership, but normal deployments never recursively change an existing tree.

Sonarr, Radarr, Lidarr, and Bazarr mount the existing `/volume1/data` tree at `/data`. Only the exact media and completed-download children required by Sonarr, Radarr, and Lidarr are provisioned with mode `2775`. Existing media-directory owners are preserved, while new directories and downloader-owned paths use `999:10`. Prowlarr intentionally mounts no shared data. Never recursively change ownership across `/volume1/data`; inspect shared paths and ACLs individually if a write probe fails.

All writable Arr bind mounts use `create_host_path: false`. The corresponding pre-deploy hook must succeed before Compose starts, preventing Docker from silently replacing a missing NAS source with a `root:root` directory.

### Arr Authentication

In Sonarr, Radarr, Lidarr, and Prowlarr, set `Authentication` to `Forms` and `Authentication Required` to `Enabled`. Enable `Forms` authentication in Bazarr as well. Do not choose `Disabled for Local Addresses`: every request, including public Cloudflare Tunnel traffic, reaches these applications from Caddy's private Docker address, so all clients would be treated as local.

### Bazarr

The `bazarr` stack runs Bazarr behind Caddy at:

```text
http://bazarr.atlas.local
```

Deploy order:

1. Deploy `bazarr`.
2. Deploy or redeploy `homepage` if the dashboard entry is not hot-reloaded.
3. Deploy or redeploy `caddy`.
4. Complete first-run setup.

On first setup, configure these services inside Bazarr:

```text
Sonarr URL: http://127.0.0.1:8989
Radarr URL: http://127.0.0.1:7878
```

Use the API keys from Sonarr and Radarr. Keep Bazarr path mappings empty if Bazarr, Sonarr, and Radarr all use matching `/data/...` container paths.

Operational notes:

- This stack does not expose a direct host port. Access is Caddy-only through `http://bazarr.atlas.local`.
- Bazarr mounts the same `[[DATA_DIR]]` tree at `/data` as Sonarr, Radarr, and Lidarr so subtitle writes happen beside the media files without path translation.
- Store subtitles `Alongside Media File` unless there is a deliberate media-library reason to do otherwise.
- Subtitle providers may require separate credentials. Some providers may need anti-captcha services, but FlareSolverr is not a general captcha solver for Bazarr.
- Keep `/volume2/appdata/bazarr` private with mode `0750` because it contains provider credentials and app tokens.

### FlareSolverr

The `flaresolverr` stack runs FlareSolverr as an internal HTTP API for Prowlarr. It has no Atlas URL, no Caddy route, and no direct host port.

Prowlarr reaches FlareSolverr inside Gluetun's shared network namespace:

```text
FlareSolverr URL: http://127.0.0.1:8191
```

Deploy order:

1. Deploy `flaresolverr`.
2. Configure Prowlarr only for indexers that need it.

In Prowlarr, add FlareSolverr under `Settings -> Indexer Proxies`. Use an explicit tag such as `flaresolverr`, then apply the same tag only to matching indexers that actually need Cloudflare challenge handling. A FlareSolverr proxy with no matching tagged indexers may appear disabled in Prowlarr.

Operational notes:

- Do not expose FlareSolverr through Caddy or a host port.
- FlareSolverr runs in `network_mode: "container:gluetun"` with Prowlarr and the other VPN-bound media apps. Keep it internal-only and address it over `127.0.0.1:8191` from Prowlarr.
- Treat FlareSolverr as optional and fragile infrastructure. If an indexer fails, try alternate indexer base URLs before changing Atlas networking.
- Browser-based challenge solving is memory-heavy. The stack has a higher memory cap than the Arr services and should be watched if Atlas is under memory pressure.
- FlareSolverr sessions should be cleaned up by clients when they are no longer needed. Avoid permanent sessions unless there is a clear reason.

### Spottarr

The `spottarr` stack runs Spottarr as a Spotnet-backed Newznab indexer behind Caddy at:

```text
http://spottarr.atlas.local
```

Spottarr is VPN-bound through Gluetun. Caddy reaches it through:

```text
http://downloaders-vpn:8383
```

Deploy order:

1. Create the required Komodo secrets.
2. Deploy or redeploy `gluetun`.
3. Deploy `spottarr`.
4. Deploy or redeploy `homepage` if the dashboard entry is not hot-reloaded.
5. Deploy or redeploy `caddy`.

Required Komodo secrets:

```text
SPOTTARR_USENET_HOSTNAME
SPOTTARR_USENET_USERNAME
SPOTTARR_USENET_PASSWORD
SPOTTARR_NEWZNAB_API_KEY
```

The maintenance API is intentionally disabled by default. If you want `/scalar`, `/openapi/v1.json`, or the reimport/reindex API, add `ADMIN__APIKEY` to the stack environment and back it with a `SPOTTARR_ADMIN_API_KEY` Komodo secret.

Prefer adding Spottarr to Prowlarr as a `Generic Newznab` indexer, then syncing from Prowlarr to the Arr apps. Use:

```text
URL: http://127.0.0.1:8383
API Path: /newznab/api
API key: SPOTTARR_NEWZNAB_API_KEY
```

Spottarr 1.20 serves the Newznab API under `/newznab/api`. The Generic Newznab default API path `/api` returns an empty `404`, which Prowlarr reports as `Root element is missing`. Make sure neither field has leading or trailing whitespace; Prowlarr concatenates them.

Operational notes:

- This stack does not expose a direct host port. Access is Caddy-only through `http://spottarr.atlas.local`.
- Spottarr stores its SQLite data in `/volume2/appdata/spottarr`, mounted at `/data`.
- The container is not a LinuxServer image. It runs with Compose `user: "999:10"` rather than LSIO `PUID`/`PGID` environment variables.
- Keep `/volume2/appdata/spottarr` private because it contains index state and may reveal Usenet-backed search behavior.
- Coordinate `SPOTTARR_USENET_MAX_CONNECTIONS` with SABnzbd and provider limits.
- Start with the default `SPOTTARR_SPOTNET_RETRIEVE_AFTER=2026-01-01T00:00:00Z`; moving earlier increases first-import time, storage, memory pressure, and Usenet request volume.

### Recyclarr

The `recyclarr` stack runs Recyclarr as a background TRaSH Guides sync worker for Sonarr and Radarr. It has no web UI, no Caddy route, and no direct host ports.

Recyclarr reaches the VPN-bound Arr services through Gluetun's `downloaders-vpn` alias:

```text
Sonarr URL: http://downloaders-vpn:8989
Radarr URL: http://downloaders-vpn:7878
```

Before deploying, ensure the canonical Sonarr and Radarr API-key variables exist in Komodo:

```text
SONARR_API_KEY
RADARR_API_KEY
```

The repo-managed Recyclarr config lives at:

```text
stacks/recyclarr/config/configs/atlas.yml
```

Runtime state is stored in `/volume2/appdata/recyclarr`, and disposable logs/resources are stored in `/volume2/tmp/recyclarr`. Keep `/volume2/appdata/recyclarr` private because it contains sync state and may contain future local secrets if the stack is changed to use `secrets.yml`.

Deploy order:

1. Create `SONARR_API_KEY` and `RADARR_API_KEY` if they do not already exist.
2. Confirm `sonarr` and `radarr` are deployed and healthy.
3. Deploy `recyclarr`.
4. Run a preview sync from the Recyclarr stack directory.
5. Run the first real sync only after reviewing the preview.

First-sync commands on Atlas:

```sh
docker compose -f compose.yaml exec recyclarr recyclarr sync --preview
docker compose -f compose.yaml exec recyclarr recyclarr sync
```

Operational notes:

- Recyclarr is pinned to an exact Docker tag and updated through Renovate.
- Recyclarr runs rootless as UID/GID `1000:1000`; it does not use `PUID` or `PGID`.
- Config changes through Resource Sync do not require a Recyclarr restart. The next cron run reads the updated YAML from the read-only bind mount.
- The scheduled sync runs daily at `04:15` according to `TZ`.
- Recyclarr v1 intentionally manages Sonarr and Radarr only. Lidarr is not supported by Recyclarr and is out of scope.
- Before the first real sync, inventory existing Sonarr and Radarr quality profile names. If Recyclarr should adopt an existing profile, temporarily add `name: <existing profile name>` under the matching `trash_id`, run one real sync, then either keep that name or remove it to let the guide name take over. Skipping this can create duplicate profiles.
- If Recyclarr reports `Access to the path '/config/state' is denied`, stop the container and audit `/volume2/appdata/recyclarr` and `/volume2/tmp/recyclarr` with `atlas-hostfs.sh audit-tree`. Run `repair-tree-owner` only for a tree that reports ownership mismatches, then redeploy; do not replace this process with an unrestricted recursive `chown`.
- Recyclarr intentionally has no Docker healthcheck. Its `supercronic` scheduler remains alive after an individual sync failure, so process liveness is not a success signal. Treat preview output, sync logs, and last-success alerting as the operational health indicators.

### Houndarr

The `houndarr` stack runs controlled, rate-limited missing and cutoff searches for Sonarr, Radarr, and Lidarr. Its built-in UI is available locally through Caddy at:

```text
http://houndarr.atlas.local
http://houndarr.atlas.vandaele.io
```

Deploy order:

1. Confirm `gluetun`, `sonarr`, `radarr`, and `lidarr` are deployed and healthy.
2. Deploy `houndarr`.
3. Deploy or redeploy `homepage` if the dashboard entry is not hot-reloaded.
4. Deploy or redeploy `caddy`.
5. Create the Houndarr administrator account immediately and add the Arr instances.

Use the existing Arr API keys with these internal URLs:

```text
Sonarr URL: http://downloaders-vpn:8989
Radarr URL: http://downloaders-vpn:7878
Lidarr URL: http://downloaders-vpn:8686
```

Start with small batches, conservative per-instance hourly API caps, download-queue backpressure, and long per-item cooldowns. Houndarr actively triggers searches, so aggressive settings can exhaust indexer limits or generate an unexpectedly large download queue.

Operational notes:

- Houndarr has no direct host port. Require Cloudflare Access before reaching `houndarr.atlas.vandaele.io`.
- The container runs explicitly as `999:10` with all capabilities dropped, a read-only root filesystem, and writable state only at `/volume2/appdata/houndarr`.
- `/volume2/appdata/houndarr` contains the SQLite database, encrypted Arr credentials, and encryption master key. It is provisioned as `0700`; back it up with ownership and permissions preserved.
- The healthcheck uses the unauthenticated `/api/health` endpoint. Its ten-minute start period accommodates database migrations without marking an upgrade unhealthy prematurely.
- Keep `HOUNDARR_SECURE_COOKIES` disabled while the plain-HTTP local URL remains in use; secure cookies would not be sent to `houndarr.atlas.local`.

### Unpackerr

The `unpackerr` stack extracts archived downloads reported by Sonarr, Radarr, and Lidarr. It is a background worker with no application UI, Caddy route, or direct host port.

Before deploying, ensure the canonical Arr API-key variables exist in Komodo:

```text
SONARR_API_KEY
RADARR_API_KEY
LIDARR_API_KEY
```

Deploy order:

1. Create the three canonical API-key variables if they do not already exist.
2. Confirm `gluetun`, `sonarr`, `radarr`, and `lidarr` are deployed and healthy.
3. Deploy `unpackerr`.
4. Confirm the startup log reports all three Arr instances and `/data/downloads` as their fallback path.

Unpackerr reaches the Arr APIs through `media_network` at `downloaders-vpn` and mounts only the shared download subtree:

```text
Host: /volume1/data/downloads
Container: /data/downloads
```

This preserves the exact `/data/downloads/...` paths reported by the Arr applications without granting Unpackerr access to the managed media library. Torrent and Usenet protocol names are both enabled, extracted files use mode `0664`, and extracted directories use mode `0775`. Original archives are retained by default so torrent seeding is not broken.

Operational notes:

- The container runs as `999:10`, drops all capabilities, uses a read-only root filesystem, and has a `1g` memory limit for extraction bursts.
- Prometheus metrics listen on port `5656` inside the container. Unpackerr joins `monitoring_network` so Prometheus can scrape them; the port is not published on the host and has no Caddy route. The Docker healthcheck uses the loopback address.
- The healthcheck proves the worker and its local webserver are alive, not that every Arr API key remains valid. Monitor Unpackerr logs for API, path, extraction, retry, and import errors.
- The pre-deploy hook waits for Gluetun and all three Arr containers, then provisions only `/volume1/data/downloads` with the shared ownership policy. Never repair the entire `/volume1/data` tree recursively.

### Soularr And slskd

Soularr is a background bridge between Lidarr's wanted albums and the `slskd` Soulseek client. The only UI is slskd, behind Caddy at:

```text
http://slskd.atlas.local
http://slskd.atlas.vandaele.io
```

Soularr and slskd are separate Komodo stacks so the automation worker can be updated without interrupting the Soulseek client or its downloads. Soularr's built-in UI is intentionally disabled in v1 because it has no authentication. It has no route or direct host port; inspect its logs through Komodo or Docker. slskd is Caddy-only and requires the configured web credentials. Protect `slskd.atlas.vandaele.io` with Cloudflare Access and route that tunnel hostname to `http://caddy:80`. slskd reuses the existing Gluetun namespace used by qBittorrent and SABnzbd, and its UI is reachable through Gluetun's `downloaders-vpn` alias.

Before deploying, create these Komodo variables. Use a dedicated Soulseek account and separate random values of at least 16 characters for the slskd API key and JWT key:

```text
SLSKD_SLSK_USERNAME
SLSKD_SLSK_PASSWORD
SLSKD_WEB_USERNAME
SLSKD_WEB_PASSWORD
SLSKD_JWT_KEY
SLSKD_API_KEY
LIDARR_API_KEY
```

Deploy order:

1. Create the variables and deploy or redeploy `gluetun` so port `5030` is available through its Docker networks.
2. When migrating from the former combined stack, stop it and remove only its `slskd` and `soularr` containers; preserve all bind-mounted app data and downloads.
3. Confirm `gluetun` is healthy, then deploy `slskd` and wait for its authenticated healthcheck to pass.
4. Deploy `soularr`; its pre-deploy hook waits for Gluetun, Lidarr, and slskd to be healthy.
5. Deploy or redeploy `caddy` after Resource Sync so both slskd hostnames are loaded live.
6. Sign in to slskd, confirm its VPN integration reports the shared Gluetun connection as healthy, then test one wanted Lidarr album.

The Proton forwarded port remains assigned to qBittorrent. slskd's dynamic port-forwarding integration is disabled because two processes cannot bind the same forwarded port in one network namespace. slskd still uses the VPN for all peer traffic, but without its own forwarded listener it may be unable to connect directly to some passive peers and may return fewer results than a dedicated forwarded setup.

After confirming the migration works, the now-unused `/volume2/appdata/slskd-gluetun` directory may be removed manually.

The completed-download path is deliberately mapped three ways:

```text
slskd writes: /downloads
Soularr sees: /downloads
Lidarr sees: /data/downloads/slskd/complete
```

Do not add slskd as a Lidarr download client or create a Lidarr remote path mapping; Soularr passes the Lidarr-visible path directly. Keep Lidarr automatic importing enabled and its music root folder at `/data/media/music`.

`/volume2/appdata/slskd` contains slskd configuration, credentials, transfer state, and database data, so back it up with its `0700` permissions preserved. `/volume2/appdata/soularr` uses mode `0750` and contains only worker state, the failed-import denylist, and logs; back it up only if retaining that operational history matters. The Soulseek download root and its completed/incomplete children use mode `2775` for Lidarr imports; never recursively change ownership across that shared tree.

Do not configure an slskd shared directory without an explicit sharing policy: a configured shared directory is indexed and offered to Soulseek peers. In particular, do not mount the managed music library as a share. Keep slskd remote configuration disabled because it could expose stored credentials.

For monitoring, configure Uptime Kuma against slskd's authenticated API only with `X-API-Key`; an unauthenticated UI `401` is not a health signal. Soularr intentionally has no Docker healthcheck because its scheduler loop continues after an individual acquisition failure. Monitor the freshness and results of `/volume2/appdata/soularr/soularr.log`, and also watch the independent `slskd` and shared `gluetun` logs for VPN or acquisition failures.

### Gluetun And VPN-Bound Media Services

The VPN-bound media applications are split from Gluetun so the VPN container can be reused across stacks. Autobrr, qBittorrent, SABnzbd, Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, FlareSolverr, Spottarr, and slskd share that same Gluetun network namespace.

The pinned Gluetun image runs as `root`. Its server cache and runtime state live under `/volume2/appdata/gluetun`; the pre-deploy hook provisions only that top-level directory as `0:0` with mode `0750`, without recursively changing existing content. The bind uses `create_host_path: false`, so a missing or failed preflight path cannot silently become a Docker-created directory.

In Docker terms, Autobrr, qBittorrent, SABnzbd, Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, FlareSolverr, Spottarr, and slskd do not join `media_network` or `proxy_network` directly. They use `network_mode: "container:gluetun"`, and Caddy or other non-VPN containers reach the routed services through Gluetun's `downloaders-vpn` network alias.

Before deploying Gluetun, create the Proton VPN WireGuard private key as a Komodo secret:

```text
PROTONVPN_WIREGUARD_PRIVATE_KEY
GLUETUN_CONTROL_API_KEY
```

Generate this key from a Proton VPN WireGuard configuration. Use a paid Proton VPN plan if you want port forwarding, select a P2P server, and enable the Proton NAT-PMP/port-forwarding option when generating the WireGuard config. Do not enable Moderate NAT on that Proton config if you want port forwarding.

Generate `GLUETUN_CONTROL_API_KEY` with `docker run --rm qmcgaw/gluetun:v3.41.1 genkey` or another high-entropy secret generator. The same Komodo secret is passed to Gluetun for control-server API authentication and to Homepage for its Gluetun widget.

The VPN country and Proton server filters are configurable through Komodo variables:

```text
PROTONVPN_SERVER_COUNTRIES=Netherlands
PROTONVPN_PORT_FORWARD_ONLY=on
PROTONVPN_VPN_PORT_FORWARDING=on
```

Gluetun is configured for Proton VPN WireGuard, which is preferred here over OpenVPN for lower overhead and simpler credentials. `PORT_FORWARD_ONLY=on` restricts selection to Proton servers that support P2P/port forwarding, and `VPN_PORT_FORWARDING=on` enables Gluetun's native Proton port forwarding integration.

When Proton allocates or removes a forwarded port, Gluetun calls qBittorrent's local Web API inside the shared network namespace and updates qBittorrent's listening port. For this to work, qBittorrent must have Web UI access enabled on port `8080` and must allow localhost API access without authentication. In qBittorrent, disable router UPnP/NAT-PMP because Proton's forwarded VPN port is managed by Gluetun, not by the LAN router.

If Gluetun cannot find a matching server, choose another `PROTONVPN_SERVER_COUNTRIES` value or temporarily set `PROTONVPN_PORT_FORWARD_ONLY=off` while troubleshooting. Disabling `PROTONVPN_PORT_FORWARD_ONLY` allows non-P2P servers but removes the assumption that Proton port forwarding is available.

Deploy order matters:

1. Deploy `gluetun`.
2. Deploy or redeploy `qbittorrent`.
3. Deploy or redeploy `autobrr`.
4. Deploy or redeploy `sabnzbd`.
5. Deploy or redeploy `flaresolverr`.
6. Deploy or redeploy `slskd`.
7. Deploy or redeploy `sonarr`.
8. Deploy or redeploy `radarr`.
9. Deploy or redeploy `lidarr`.
10. Deploy or redeploy `prowlarr`.
11. Deploy or redeploy `bazarr`.
12. Deploy or redeploy `spottarr`.
13. Deploy or redeploy `recyclarr`.
14. Deploy or redeploy `houndarr`.
15. Deploy or redeploy `unpackerr`.
16. Deploy or redeploy `homepage`.
17. Deploy or redeploy `caddy`.

If Gluetun is recreated, every container sharing its network namespace must be recreated, not merely restarted, so it reattaches to the current namespace. That includes Autobrr, qBittorrent, SABnzbd, Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, FlareSolverr, Spottarr, and slskd. The repo encodes this with `after = ["gluetun"]`-style dependencies and `extra_args = ["--force-recreate"]` on each VPN-bound stack.

Komodo `after = ["gluetun"]` affects dependency ordering during Resource Sync deploys. If Gluetun is deployed manually outside a dependency-aware sync/procedure, explicitly redeploy all VPN-bound stacks afterwards; their `--force-recreate` deploy args handle the required namespace reattachment.

qBittorrent and SABnzbd are available at:

```text
http://qbittorrent.atlas.local
http://sabnzbd.atlas.local
```

There are no direct Autobrr, qBittorrent, or SABnzbd host UI ports. Keep UI access Caddy-only unless an emergency LAN-bound port is deliberately added to the Gluetun stack.

On first startup, LinuxServer qBittorrent prints the temporary admin password in the container logs. Log in, change the password, then configure these paths:

```text
Incomplete torrents: /data/downloads/torrents/incomplete
Completed torrents: /data/downloads/torrents/completed
Series category: /data/downloads/torrents/completed/series
Movies category: /data/downloads/torrents/completed/movies
Music category: /data/downloads/torrents/completed/music
```

Keep `/volume2/appdata/qbittorrent` private because it contains credentials and session state. The stack provisions it as `0750`; torrent directories remain group-writable with mode `2775` for media imports. Never recursively change ownership across `/volume1/data` during qBittorrent recovery.

Configure Sonarr, Radarr, and Lidarr download clients to use:

```text
Host: 127.0.0.1
Port: 8080
```

SABnzbd uses port `8085` inside Gluetun's shared network namespace because qBittorrent already uses `8080`. The repo-managed LinuxServer custom init script patches SABnzbd's service runner before startup so the web UI binds `0.0.0.0:8085`. Treat `SABNZBD_PORT=8085` and the custom init script as the source of truth for the internal listening port.

SABnzbd validates the HTTP `Host` header to protect against DNS-rebinding attacks. Because Caddy preserves the incoming hostname, add both Atlas hostnames under `Config > Special > host_whitelist`:

```text
sabnzbd.atlas.local, sabnzbd.atlas.vandaele.io
```

Keep the entries lowercase and comma-separated. Do not disable the check with a wildcard or rewrite the upstream `Host` header in Caddy. The setting persists in `/volume2/appdata/sabnzbd/sabnzbd.ini` and does not require a Komodo variable or secret. See the [SABnzbd hostname-verification documentation](https://sabnzbd.org/wiki/extra/hostname-check.html) for background.

On a fresh install, SABnzbd rejects `sabnzbd.atlas.local` before the setting can be changed in the UI. After the first deploy has created `sabnzbd.ini` and the container is healthy, set the whitelist over SSH before the first visit:

```sh
docker stop sabnzbd
sed -i 's/^host_whitelist = .*/host_whitelist = sabnzbd.atlas.local, sabnzbd.atlas.vandaele.io/' \
  /volume2/appdata/sabnzbd/sabnzbd.ini
docker start sabnzbd
```

If the hostname check prevents all UI access, recover over SSH:

```sh
docker stop sabnzbd
sudo vi /volume2/appdata/sabnzbd/sabnzbd.ini
```

Under `[misc]`, set:

```ini
host_whitelist = sabnzbd.atlas.local, sabnzbd.atlas.vandaele.io
```

Then restart the container:

```sh
docker start sabnzbd
```

On first startup, configure SABnzbd through Caddy and keep `External internet access` disabled or limited. Configure these paths:

```text
Incomplete downloads: /data/downloads/usenet/incomplete
Completed downloads: /data/downloads/usenet/completed
Series category: /data/downloads/usenet/completed/series
Movies category: /data/downloads/usenet/completed/movies
Music category: /data/downloads/usenet/completed/music
```

Configure Sonarr, Radarr, and Lidarr SABnzbd download clients to use:

```text
Host: 127.0.0.1
Port: 8085
```

Keep `/volume2/appdata/sabnzbd` private because it contains SABnzbd API keys and Usenet provider credentials. The stack provisions it as `0700`; download directories remain group-writable with mode `2775` for media imports. Never recursively change ownership across `/volume1/data` during SABnzbd recovery.

For Sonarr, use category `series` and root folder `/data/media/series`. For Radarr, use category `movies` and root folder `/data/media/movies`.

For Lidarr, use category `music`, completed downloads `/data/downloads/torrents/completed/music`, and root folder `/data/media/music`.

Configure Prowlarr's Lidarr app integration to use:

```text
URL: http://127.0.0.1:8686
API key: copied from Lidarr
```

Proton VPN provides Gluetun-managed VPN port forwarding on supported paid-plan servers. qBittorrent's listening port is updated through Gluetun's `VPN_PORT_FORWARDING_UP_COMMAND` and reset through `VPN_PORT_FORWARDING_DOWN_COMMAND` when forwarding is removed.

Homepage reads Gluetun through the internal control server at `http://downloaders-vpn:8000` using `GLUETUN_CONTROL_API_KEY`. The control server is exposed only on Docker networks, not through Caddy or a host port.

Gluetun logs the successful qBittorrent port update as `ERROR [port forwarding] ... URL:http://127.0.0.1:8080/api/v2/app/setPreferences [0/0] -> "-" [1]` because `wget -nv` writes its success line to stderr. Confirm the result with `docker exec gluetun cat /tmp/gluetun/forwarded_port` and qBittorrent's listening port. Proton servers intermittently refuse NAT-PMP mappings (`read udp ...:5351: recvfrom: connection refused`); reconnect the VPN to try another server.

Gluetun looks up its public IP only when the VPN connects. Gluetun `v3.41.3` stops trying fallback lookup services once the first configured service is rate-limited, which leaves the public IP empty (`all fetchers failed: %!w(<nil>)`) until the container restarts. slskd then waits indefinitely with `Waiting for VPN client; IP: ?`. The stack therefore sets `PUBLICIP_API=cloudflare,ifconfigco,ip2location`, leaving out ipinfo, which rate-limits shared VPN addresses.

To reconnect the VPN without recreating Gluetun or the containers that share its network namespace, use the control server. A reconnect selects a new server, repeats the public IP lookup, and retries port forwarding:

```sh
GK=$(docker exec gluetun sh -c 'printenv HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE | sed -n "s/.*\"apikey\":\"\([^\"]*\)\".*/\1/p"')
for s in stopped running; do
  docker run --rm --network container:gluetun curlimages/curl:8.16.0 -fsS \
    -X PUT -H "X-API-Key: $GK" -H 'Content-Type: application/json' \
    -d "{\"status\":\"$s\"}" http://127.0.0.1:8000/v1/vpn/status
  echo; sleep 5
done
unset GK
```

Do not use `docker restart gluetun` once VPN-bound containers are attached; it replaces the namespace and every dependent stack must then be redeployed.

### Autobrr

The `autobrr` stack monitors tracker IRC announcements and feeds, then sends matching releases to configured download clients or Arr applications. It is VPN-bound through Gluetun and available locally through Caddy at:

```text
http://autobrr.atlas.local
http://autobrr.atlas.vandaele.io
```

Deploy order:

1. Deploy `gluetun`.
2. Deploy or redeploy `qbittorrent`.
3. Deploy `autobrr`.
4. Deploy or redeploy `homepage` if the dashboard entry is not hot-reloaded.
5. Deploy or redeploy `caddy`.
6. Create the Autobrr administrator account immediately, then configure only the indexers and actions you intend to use.

Because Autobrr and the download applications share Gluetun's network namespace, use loopback URLs for Atlas services in that namespace:

```text
qBittorrent: http://127.0.0.1:8080
SABnzbd: http://127.0.0.1:8085
Sonarr: http://127.0.0.1:8989
Radarr: http://127.0.0.1:7878
Lidarr: http://127.0.0.1:8686
```

Operational notes:

- Autobrr has no direct host port. Require Cloudflare Access before reaching `autobrr.atlas.vandaele.io`.
- `/volume2/appdata/autobrr` contains its SQLite database, login state, tracker credentials, and downloader credentials. It is provisioned as `0700`; back it up with ownership and permissions preserved.
- The image's own update check is disabled because Renovate manages the pinned Docker tag.
- The readiness healthcheck verifies both the HTTP server and SQLite database.
- Autobrr uses `network_mode: "container:gluetun"`, so it must be force-recreated after Gluetun is recreated. Its Komodo dependency and deploy args enforce that during dependency-aware syncs.
- Start with narrowly scoped filters and conservative action limits. A broad or malformed filter can enqueue large numbers of downloads quickly.

### qui

The `qui` stack runs qui as a separate qBittorrent management UI behind Caddy at:

```text
http://qui.atlas.local
```

qui is not a qBittorrent alternative WebUI theme. It connects to qBittorrent through the qBittorrent Web API. The existing qBittorrent UI remains available at `http://qbittorrent.atlas.local`.

Deploy order:

1. Deploy `gluetun`.
2. Deploy or redeploy `qbittorrent`.
3. Deploy `qui`.
4. Deploy or redeploy `caddy`.

After first deploy, create the qui admin account immediately. Wait until qBittorrent is reachable before adding the Atlas qBittorrent instance:

```sh
docker exec qui wget --no-verbose --tries=1 --spider http://downloaders-vpn:8080
```

Add qBittorrent in qui with:

```text
Name: Atlas qBittorrent
URL: http://downloaders-vpn:8080
Username: qBittorrent username
Password: qBittorrent password
```

If adding Prowlarr indexers in qui, use:

```text
URL: http://downloaders-vpn:9696
API key: copied from Prowlarr
```

Operational notes:

- There is no direct qui host port. Access is Caddy-only through `http://qui.atlas.local`.
- qui does not run in Gluetun's network namespace. It is only a control UI and should not share the VPN container lifecycle.
- Keep qui authentication enabled. Do not set `QUI__AUTH_DISABLED=true`.
- The stack mounts `[[DATA_DIR]]/downloads/torrents` at the container path `/data/downloads/torrents` (via `TORRENTS_DIR`) to enable qui's filesystem-dependent features. This path deliberately matches qBittorrent's own `/data/downloads/torrents` mapping so the save paths qui reads from the qBittorrent API resolve correctly on qui's filesystem. This mount grants qui read/write/delete capability over torrent downloads; switch it to `:ro` in `stacks/qui/compose.yaml` if only read-only browsing is wanted.
- `[[APPDATA_DIR]]/qui` contains the qui database, admin/session state, and qBittorrent credentials. It is provisioned as private appdata with mode `0700` and should be backed up; never recursively change ownership across the shared torrent tree during recovery.
- Require Cloudflare Access before reaching qui through `qui.atlas.vandaele.io`.

### Rclone

The `rclone` stack runs the official `rclone gui` web UI behind Caddy at:

```text
http://rclone.atlas.local
```

Deploy order:

1. Deploy `rclone`.
2. Deploy or redeploy `caddy`.

Use the normal hostname below. Caddy redirects first-time GUI loads to the rclone launcher URL so the web UI knows how to reach the same-origin RC API:

```text
http://rclone.atlas.local/
```

Operational notes:

- `rclone.atlas.local` and `rclone.atlas.vandaele.io` are privileged management surfaces. Anyone who reaches either hostname can manage configured remotes and read or write the mounted local data path.
- The rclone RC API runs with `--no-auth` on a dedicated `rclone_network` that only Caddy and rclone join. Require Cloudflare Access on `rclone.atlas.vandaele.io`; application-level authentication does not protect this endpoint.
- This stack mounts all of `[[DATA_DIR]]` at `/data`. That was chosen for flexibility, not least privilege.
- `rclone.conf` contains remote credentials and tokens. It is provisioned with `0600` permissions and should be backed up from `[[APPDATA_DIR]]/rclone`.
- `user-dirs.dirs` is repository-managed and triggers a redeploy so its read-only bind always references the current file.
- Do not use the UI self-update flow. Upgrade `rclone` by bumping the image tag in this repository.
- The upstream UI still shows `Mounts` and `Serves`. This stack does not provision FUSE mount support, and it does not publish or route `rclone serve` listeners beyond the main UI hostname.

### Uptime Kuma

The `uptime-kuma` stack runs Uptime Kuma behind Caddy at:

```text
http://uptime.atlas.local
```

Deploy order:

1. Deploy `uptime-kuma`.
2. Deploy or redeploy `caddy`.

On first login, create the Uptime Kuma admin user and enable two-factor authentication. There is no Caddy Basic Auth gate; protect `uptime.atlas.vandaele.io` with Cloudflare Access. LAN and tailnet traffic to the local hostname remains HTTP, while Cloudflare terminates public TLS at the edge.

This stack intentionally does not mount `/var/run/docker.sock`. Docker socket access is effectively host-level Docker control if Uptime Kuma is compromised. Monitor Atlas through HTTP routes, DNS checks, TCP checks, and push monitors instead.

Recommended initial monitors:

```text
HTTP: http://komodo.atlas.local
HTTP: http://sonarr.atlas.local
HTTP: http://radarr.atlas.local
HTTP: http://prowlarr.atlas.local
HTTP: http://lidarr.atlas.local
HTTP: http://seerr.atlas.local
HTTP: http://seerr.atlas.local/api/v1/settings/public
HTTP: http://sabnzbd.atlas.local
HTTP: http://adguard.atlas.local
HTTP: http://uptime.atlas.local
HTTP: http://homepage.atlas.local
HTTP: http://speedtest.atlas.local
HTTP: http://rclone.atlas.local/
TCP: 192.168.2.200:53
DNS: sonarr.atlas.local against resolver 192.168.2.200, expected 192.168.2.200
DNS: komodo.atlas.local against resolver 192.168.2.200, expected 192.168.2.200
Push: future backup jobs or stack-health poller
```

Use 60-second intervals for core infra, 120-second intervals for media apps, and at least two retries to avoid noisy alerts during stack redeploys.

Operational notes:

- The Uptime Kuma image runs as UID/GID `1000:1000` because the image ships with a `node` user at that ID and `/app/data` is owned by that user.
- `[[APPDATA_DIR]]/uptime-kuma` contains monitor config, credentials, notification tokens, and database state. It is provisioned with `0700` permissions and should be backed up.
- Browser/Chromium monitors are not validated in this stack. The full image is used so they remain available for later testing, but HTTP, TCP, DNS, and push monitors are the supported baseline.
- The recommended monitor list above is manual Uptime Kuma UI state, not repo-backed configuration.

### Speedtest Tracker

Speedtest Tracker runs behind Caddy at:

```text
http://speedtest.atlas.local
```

Before deploying, create `SPEEDTEST_TRACKER_APP_KEY` in Komodo. This is mapped to the container's required `APP_KEY` environment variable; the shorter name is the upstream Speedtest Tracker/Laravel name, while the Komodo value is namespaced for this repo. Generate it with:

```sh
echo -n 'base64:'; openssl rand -base64 32
```

After first login, change Speedtest Tracker's default application credentials.

The stack uses SQLite under `[[APPDATA_DIR]]/speedtest-tracker`, runs a scheduled test every six hours by default with `SPEEDTEST_TRACKER_SCHEDULE=6 */6 * * *`, and prunes results older than 365 days by default. Set `SPEEDTEST_TRACKER_SERVERS` to a comma-separated list of Ookla server IDs if you want pinned test servers; otherwise Speedtest Tracker will choose automatically.

For the Homepage widget, log in to Speedtest Tracker, create a bearer token at `/admin/api-tokens` with `Read Results`, and save it in Komodo as `HOMEPAGE_SPEEDTEST_TRACKER_API_KEY`.

The Homepage widget calls Speedtest Tracker's latest-result API. On a fresh install it will log 404s until at least one speedtest result exists; run an initial test manually from the Speedtest Tracker UI or wait for the first scheduled run.

### Cloudflared

The `cloudflared` stack runs a remotely managed Cloudflare Tunnel connector for Atlas. It joins `proxy_network` and has no host ports; Cloudflare edge traffic is forwarded into Caddy over Docker networking.

Before deploying, create a remotely managed tunnel in Cloudflare Zero Trust and save the tunnel token in Komodo:

```text
CLOUDFLARE_TUNNEL_TOKEN
```

Deploy order:

1. Deploy or redeploy `caddy`.
2. Deploy `cloudflared`.

For each public hostname in the Cloudflare Tunnel dashboard, point the service at Caddy:

```text
Service: http://caddy:80
```

Define each public hostname exactly once. Do not use `http://<app>.atlas.local` as the tunnel service: that adds an unnecessary dependency on Atlas DNS and rewrites the origin host to the local hostname. Sending every public hostname to `http://caddy:80` keeps routing declarative in Caddy and preserves the incoming `*.atlas.vandaele.io` host for matching.

Caddy routes by HTTP host. The shared `atlas_reverse_proxy` snippet creates paired `*.atlas.local` and `*.atlas.vandaele.io` routes. The specialized rclone snippet also defines both hostnames. For a custom paired route, use:

```caddyfile
http://speedtest.atlas.local, http://speedtest.atlas.vandaele.io {
	reverse_proxy speedtest-tracker:80
}
```

Cloudflare's origin HTTP Host Header override can also route a public hostname to an existing `atlas.local` site block, but use it carefully. Some apps generate redirects, callback URLs, CSRF origins, or absolute links from the Host header they receive.

Use Cloudflare Access policies on the public hostnames for admin-facing services. The tunnel removes inbound port exposure, but it does not replace application authentication.

### Homepage

The `homepage` stack runs Homepage behind Caddy at:

```text
http://homepage.atlas.local
```

Homepage config is managed declaratively in:

```text
stacks/homepage/config/
```

Deploy order:

1. Create or populate the Homepage widget variables in Komodo.
2. Deploy `homepage`.
3. Deploy or redeploy `caddy`.

Operational notes:

- Homepage is exposed through Caddy only. There is no direct Homepage host port.
- Homepage does not mount `/var/run/docker.sock` and does not use Docker label discovery in the baseline setup.
- `HOMEPAGE_ALLOWED_HOSTS` contains both canonical hosts: `homepage.atlas.local` and `homepage.atlas.vandaele.io`.
- Homepage widget credentials stay in canonical Komodo variables. The Compose adapter maps them into Homepage's required `HOMEPAGE_VAR_*` container variables; that upstream-only prefix is not used for Komodo variables or stack inputs.
- `LOG_TARGETS=stdout` keeps Homepage from trying to create `/app/config/logs` inside the read-only config mount.
- Resource Sync updates `stacks/homepage/config/*` through `config_files` with `requires = "None"`, so normal YAML, CSS, and JS edits do not force a container restart.
- After Homepage config file changes land through Resource Sync, use Homepage's refresh icon to regenerate the static UI. A `homepage` redeploy is only needed for environment-variable changes or when adding new local static assets.
- Caddy route changes still require an explicit `caddy` deploy or redeploy after Resource Sync so the Caddy `post_deploy` reload hook updates the live config.

## Monitoring

The `monitoring` stack runs Prometheus, node-exporter, blackbox-exporter, and Grafana on the private `monitoring_network`. Only Grafana also joins `proxy_network`, and it is reachable at `http://grafana.atlas.local` and at `https://grafana.atlas.vandaele.io`, which must be protected by Cloudflare Access; Grafana also requires its own login. Prometheus has no host port and no web route; query it through Grafana.

The nightly `appdata-backup` Action never stops the `monitoring` stack, and its data is not backed up: `/volume2/appdata/prometheus` (90 days, at most 20 GB) and `/volume2/appdata/grafana` (Grafana's SQLite database) are excluded. Only configuration is kept, in git: Prometheus, blackbox, and Grafana provisioning in this repository, and dashboards in `pjan/atlas-dashboards`. After losing Volume 2, Grafana starts with an empty database: the admin login comes from `GRAFANA_ADMIN_PASSWORD`, the datasource (and alerting) from provisioning, and the dashboards return once Git Sync is reconnected with the token from the password manager. Extra users, service accounts, and alert history are lost. Scrapes run every 30 seconds and probes every 60 seconds.

Resource Sync only runs `compose up -d` when a tracked config file changes, which does not recreate an unchanged container. Prometheus and blackbox therefore reload `stacks/monitoring/prometheus/prometheus.yml` and `stacks/monitoring/blackbox/blackbox.yml` automatically, and the stack restarts Grafana in `post_deploy` so provisioning changes apply. `scripts/validate.sh` checks both configurations with the pinned images (`promtool check config`, `blackbox_exporter --config.check`).

Current signals:

| Job | What it checks |
|---|---|
| `node` | CPU, memory, filesystems, md RAID, btrfs, and the backup textfile metrics in `/volume1/backups/.metrics` |
| `smartctl` | SMART health, NVMe wear, spare, critical warnings, media errors, and temperatures for `sda` (Seagate 12 TB, Volume 1), `nvme0` (Lexar 512 GB, Volume 2), and `nvme1` (TWSC 128 GB, UGOS system disk) |
| `probe_routes` | Every deployed `*.atlas.local` Caddy route (UniFi DNS, Caddy, and the application; 401 and 403 count as healthy) |
| `probe_tcp` | AdGuard DNS `:53`, Caddy `:80`, Komodo `:9120`, Plex `:32400`, and Roon Server `:9330` on `192.168.2.200` |
| `probe_dns_atlas_local` | UniFi resolves `sonarr.atlas.local` to `192.168.2.200` |
| `probe_dns_external` | AdGuard resolves an external name |
| `probe_cloudflare_access` | Public hostnames answer with the Cloudflare Access login redirect |
| `probe_internet` | Outbound HTTPS from the NAS |
| `probe_health` | Application health through Caddy: Servarr `/ping` must report `OK` (fails when the app cannot reach its database), Plex `/identity` must contain a `machineIdentifier` (through Caddy and directly on `:32400`), Grafana `/api/health` must report the database `ok`, SABnzbd must report its version, Caddy must answer `ok`, and Komodo, Seerr, Autobrr, Houndarr, qui, and Spottarr health endpoints must return 200 |
| `caddy` | Caddy's own metrics per hostname (requests, errors, latency) on the internal listener `:2020` |
| `cloudflared` | Tunnel metrics, including `cloudflared_tunnel_ha_connections`, on `:2000` |
| `unpackerr` | Extraction metrics on `:5656` |

smartctl-exporter addresses disks by their stable `/dev/disk/by-id` names (`wwn-*` and `nvme-eui.*`, which avoid publishing serial numbers). Docker resolves those names when the container is created, so recreate the `monitoring` stack after adding or replacing a disk and update the device list in `stacks/monitoring/compose.yaml`. It runs as root with only those devices and the `SYS_RAWIO` (SATA) and `SYS_ADMIN` (NVMe) capabilities. smartctl cannot infer the device type from those names, so every device is listed with its type (`;sat` or `;nvme`).

Volume 1 is a single 12 TB disk (`md1` is RAID 1 with one member), so it has no redundancy: media and the local backups share one disk. The off-site Backrest copy protects `/volume1/backups`; media are not protected.

Caddy, cloudflared, and Unpackerr join `monitoring_network` for scraping; their metrics ports are not published on the host. Public `*.atlas.vandaele.io` hostnames answer `404` for `/metrics` and `/prometheus`, so application metrics endpoints (for example slskd and Speedtest Tracker) are never exposed through Cloudflare.

Grafana provisions the Prometheus datasource (uid `prometheus`) from `stacks/monitoring/grafana/provisioning/`. Grafana runs with a read-only root filesystem, so plugin preinstallation and automatic plugin updates are disabled (`GF_PLUGINS_PREINSTALL_DISABLED`, `GF_PLUGINS_PREINSTALL_AUTO_UPDATE`): plugin versions come only from the pinned image. The app plugins Grafana installed on its first start (Advisor, Explore Traces, Logs Drilldown, Metrics Drilldown, Pyroscope) remain in `/volume2/appdata/grafana/plugins`, are no longer updated, and do not return after a Volume 2 loss. Grafana 13 ships Prometheus as a bundled plugin, and a failed startup update would otherwise leave it unregistered. Dashboards are kept in the private `pjan/atlas-dashboards` repository with Grafana Git Sync, using a fine-grained token scoped to that repository only. Do not create dashboards outside synced folders: anything else exists only in `grafana.db`.

Secrets never go into Prometheus, blackbox, or exporter configuration files. Exporters that accept environment variables receive keys from Komodo variables; services that read secret files use `/run/secrets`.

`GRAFANA_SECRET_KEY` encrypts secrets stored in Grafana (contact points, the Git Sync token). Set it before Grafana's first start, keep it in the password manager, and never change it afterwards. `GRAFANA_ADMIN_PASSWORD` only applies on first start; change the password in Grafana later.

## Caddy Configuration

Caddy config is stored declaratively in the repository:

```text
stacks/caddy/conf/Caddyfile
stacks/caddy/conf/sites/*.caddy
```

The root `Caddyfile` imports all site files:

```caddyfile
import sites/*.caddy
```

`http://caddy.atlas.local` and `http://caddy.atlas.vandaele.io` return a static `200 ok` health response. They do not proxy or expose Caddy's admin API.

To add a new app route:

1. Add a new file under `stacks/caddy/conf/sites/`.
2. Add the file to the Caddy stack `config_files` list in `stacks.toml`.
3. Ensure the app container joins `proxy_network`, or proxy to `host.docker.internal` for host services.
4. Push to `main`, execute Resource Sync, then explicitly deploy or redeploy `caddy` so the `post_deploy` reload hook applies the live config.

Most application UIs are exposed only through Caddy, using paired `*.atlas.local` and `*.atlas.vandaele.io` hostnames. Public hostnames must be protected by appropriate Cloudflare Access policies. Routes listed in `LOCAL_ONLY_CADDY_ROUTES` in `scripts/validate-repository.py` (currently `backrest`) are LAN-only and must not get a public hostname. Plex is the direct-port exception and still publishes `192.168.2.200:32400/tcp` for native client discovery and direct access.

Validation note:

- Caddy imports all site files on every validation run.

Example app route:

```caddyfile
http://example.atlas.local {
	reverse_proxy example:1234
}
```

Example host-service route:

```caddyfile
http://hostapp.atlas.local {
	reverse_proxy host.docker.internal:1234
}
```

## Renovate

Renovate is configured in `renovate.json`.

To enable it:

1. Install the hosted Renovate GitHub App.
2. Grant access to this repository.
3. Merge the Renovate onboarding PR if one is opened.

Renovate will open PRs for Docker image and CI dependency updates. Renovate-managed PR automerge is limited to patch, pin, and digest updates, with platform automerge disabled: Renovate waits until the PR branch is up to date and all status checks, including `Validate Atlas`, pass before merging. Minor, major, and replacement updates require manual review. Failed or pending updates remain open. Validation commands that run `docker run` during `pre_deploy` derive their image from the stack's own `compose.yaml`, so there is no separate pinned validation image to keep in sync. Komodo polling will detect merged changes to `main`; execute Resource Sync and deploy the affected stack.

## Repository Validation

Run the complete local validation suite from the repository root:

```sh
./scripts/validate.sh
```

The suite renders every managed stack and the manual Komodo bootstrap with deterministic validation values, validates Caddy with the pinned image, exercises the host-filesystem and network helpers, and checks repository policy. Policy checks cover stack/run-directory consistency, declared files, Caddy site registration, relative bind configuration, fail-closed bind mounts, pinned image tags, security/resource/logging controls, shell syntax, Komodo interpolation tags, and tracked runtime secrets or OS metadata.

GitHub Actions runs the same command for pull requests and pushes to `main`. Workflow actions are pinned by commit SHA, and CI receives read-only repository permissions.
