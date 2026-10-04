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
- Caddy HTTPS entrypoint: `https://<app>.atlas.vandaele.io` on `192.168.2.200:443`, with one Let's Encrypt wildcard certificate (see [Caddy Configuration](#caddy-configuration))
- Application hostnames: `https://<app>.atlas.vandaele.io` everywhere. On the LAN and Tailscale, Atlas DNS (UniFi, AdGuard) sends them to Caddy on the NAS; from the internet, they go through the Cloudflare Tunnel to Caddy
- Old LAN hostnames: `http://<app>.atlas.local` redirects to `https://<app>.atlas.vandaele.io`
- Remote access: Tailscale (on the UniFi router) for private access, with selected Caddy applications also available through Cloudflare Access-protected public hostnames
- Login: authentik at `https://auth.atlas.vandaele.io` (see [authentik](#authentik)); Grafana is the first application behind it
- Timezone: `Asia/Singapore`, set once in the Komodo `TZ` variable (see [Timezone And Schedules](#timezone-and-schedules))

## One-Time NAS Preparation

### 1. Free Port 80 In UGOS

UGOS can bind ports `80` and `443` with its built-in nginx service. Caddy binds both: `443` serves `https://<app>.atlas.vandaele.io`, and `80` redirects to it, so both must be free.

In the UGOS dashboard:

1. Open `Control Panel`.
2. Open `Device Connection`.
3. Open `Portal Settings`.
4. Uncheck the options that redirect ports `80` and `443` to the portal.
5. Apply the change.

Verify over SSH:

```sh
sudo ss -ltnp | grep -E ':(80|443) ' || echo "ports 80 and 443 are free"
```

Expected result: no UGOS/nginx listener on `0.0.0.0:80` or `0.0.0.0:443`.

### 2. Configure UniFi Local DNS

On the UniFi Dream Machine, configure local DNS so app hostnames resolve to the NAS. LAN clients, the NAS, and its containers ask UniFi (DHCP hands out `192.168.2.1`; the NAS's `dnsmasq` on `127.0.0.1` forwards to it).

For newer UniFi Network versions, the DNS record UI is usually under one of these paths:

```text
Settings > Policy Engine > DNS > Create DNS Record
Settings > Policy Table > Create New Policy > DNS
```

Host (A) wildcard records:

```text
hostname *.atlas.vandaele.io, value 192.168.2.200
hostname *.atlas.local, value 192.168.2.200   (old hostnames, redirected to HTTPS)
```

Tailscale devices ask AdGuard (`192.168.2.200`, the Tailscale global nameserver with "Override DNS servers" on), which does not forward local names to UniFi. In AdGuard, add the same record under **Filters > DNS rewrites**: domain `*.atlas.vandaele.io`, answer `192.168.2.200`. It is stored in `AdGuardHome.yaml` in appdata, not in this repository.

Never create a `*.atlas` record in Cloudflare: public DNS has one proxied CNAME per public route, pointing at the tunnel (see [Cloudflared](#cloudflared)), and a wildcard there catches every hostname without its own record.

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
- `docker ps` shows the health of all three containers. Core is healthy when its API answers `/version`. Periphery serves no port, so it is healthy only while it holds a connection to Core on port 9120, which it drops when login fails, for example after a key mismatch. If `PERIPHERY_CORE_ADDRESS` moves off port 9120, update the port in the Periphery healthcheck.

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

- Komodo Core's own procedures and the `appdata-backup` Action's schedule use `TZ` in `/volume2/docker/komodo/.env` (Komodo does not interpolate variables in schedules). Update it and run `docker compose --env-file .env -f compose.yaml up -d` in `/volume2/docker/komodo`.
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
05:00  Komodo Action: appdata-backup (see Backups)    (Core .env TZ)
06:00  Komodo procedure: Rotate Server Keys             (Core .env TZ)
```

Keep new scheduled work out of the 04:30–06:30 window, which is reserved for the nightly backups.

## Backups

### What Is Backed Up Where

| Data | Local copy | Written by |
|---|---|---|
| Application state (`/volume2/appdata`) and the Komodo bootstrap directory (`/volume2/docker/komodo`) | `/volume1/backups/appdata` | `appdata-backup` Action, daily at 05:00 |
| Komodo database | `/volume1/backups/komodo` | Komodo procedure "Backup Core Database", daily at 01:00, 14 kept |
| Plex database | `/volume1/backups/plex` | Plex scheduled task, every three days |
| Roon database | `/volume1/backups/roonserver` | Roon scheduled backup, daily at 04:00 |

Off-site, Backrest copies all of `/volume1/backups` to the Google Shared Drive `Atlas` every day at 06:00 (see [Off-Site Backups With Backrest](#off-site-backups-with-backrest)).

The appdata copy excludes `roonserver` (covered by Roon's own backups), monitoring data (`prometheus`, `alertmanager`, and `grafana`, see [Monitoring](#monitoring)), Plex caches, codecs, drivers, logs, and crash reports, and AdGuard query logs. The rules live in `stacks/appdata-backup/filters.txt`.

### Nightly Appdata Snapshot

The `appdata-backup` Komodo Action is defined in `stacks.toml`. It runs daily at 05:00 in Core's timezone (`schedule = "0 0 5 * * *"`; Komodo does not interpolate variables in schedules, so the hour is written in the Action):

1. Run the `appdata-backup-recover` Action, which restarts any stacks that an interrupted run left stopped. The list is kept in the runtime Komodo variable `APPDATA_BACKUP_STOPPED_STACKS`, which the recover Action creates itself and which must not be added to `stacks.toml`. The recover Action also runs whenever Core starts (`run_at_startup`), and first waits up to 5 minutes for Periphery, which may connect after Core when the NAS boots.
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

To run a backup immediately, run the `appdata-backup` Action in Komodo.

### Off-Site Backups With Backrest

The `backrest` stack runs [Backrest](https://github.com/garethgeorge/backrest), a web UI and scheduler for restic. Its UI is reachable only on the LAN at `https://backrest.atlas.vandaele.io`: it holds every repository password and destination credential, so it is not on the Cloudflare Tunnel and has no public DNS record; the validator keeps it off Caddy's tunnel listener through `LOCAL_ONLY_CADDY_ROUTES`. Backrest also requires its own login.

Layout inside the container:

| Path | Host | Purpose |
|---|---|---|
| `/sources/<name>` | read-only source binds | What can be backed up. Today only `/sources/volume1-backups` (`/volume1/backups`). |
| `/config` | `/volume2/appdata/backrest/config` | `config.json`, `rclone/rclone.conf`, service-account keys, and SSH keys (`.backrest-ssh`) |
| `/data` | `/volume2/appdata/backrest/data` | Operation history and logs |
| `/cache` | `/volume2/tmp/backrest/cache` | restic cache, one per repository, disposable |
| `/restore` | `/volume2/tmp/backrest/restore` | Target for restores from the UI |
| `/metrics` | `/volume1/backups/.metrics` (read-write) | `atlas_offsite.prom`, written by the plan's metrics hook for Prometheus |

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
| Plan hooks | Pre-check on snapshot start with `ON_ERROR_FATAL` (fails unless the appdata snapshot is complete and younger than 26 hours); the [metrics hook](#off-site-backup-metrics) on snapshot success, warning, and error; Healthchecks on snapshot start, success, warning, skipped, and error |

#### Off-Site Backup Metrics

The plan's metrics hook writes the result of every snapshot to `/metrics/atlas_offsite.prom` (`/volume1/backups/.metrics`), which node-exporter reads, so the [off-site backup alerts](#off-site-backup) and the dashboards see it. Hooks live in Backrest's `/config/config.json`, not in this repository, so the script is kept here. Add it in the Backrest UI: open the plan `atlas-volume1-backups`, add a hook of type **Command** with the conditions `CONDITION_SNAPSHOT_SUCCESS`, `CONDITION_SNAPSHOT_WARNING`, and `CONDITION_SNAPSHOT_ERROR`, error behaviour `ON_ERROR_IGNORE`, and this command:

```sh
#!/bin/sh
# Atlas: off-site backup metrics for Prometheus (README "Off-Site Backups With Backrest").
set -eu
out=/metrics/atlas_offsite.prom
tmp=/metrics/.atlas_offsite.tmp
now={{ .CurTime.Unix }}
{{ if eq .Event.String "CONDITION_SNAPSHOT_SUCCESS" }}code=0
{{ else if eq .Event.String "CONDITION_SNAPSHOT_WARNING" }}code=3
{{ else }}code=1
{{ end -}}
{{ with .SnapshotStats }}added={{ .DataAdded }}
{{ else }}added=0
{{ end -}}
# Untrusted text: printable ASCII without quotes or backslashes, at most 200 characters.
error=$(printf '%s' {{ .ShellEscape .Error }} | tr '\n\r\t' '   ' | tr -cd ' -~' | tr -d '"`\\'"'" | cut -c 1-200)
last_success=$(awk '$1 == "atlas_offsite_last_success_timestamp_seconds" { print $2 }' "$out" 2>/dev/null || true)
case $last_success in ''|*[!0-9]*) last_success=0 ;; esac
if [ "$code" -ne 1 ]; then last_success=$now; fi
cat > "$tmp" <<PROM
# HELP atlas_offsite_last_run_timestamp_seconds Unix time the last off-site snapshot finished.
# TYPE atlas_offsite_last_run_timestamp_seconds gauge
atlas_offsite_last_run_timestamp_seconds $now
# HELP atlas_offsite_last_success_timestamp_seconds Unix time of the last successful or partial off-site snapshot.
# TYPE atlas_offsite_last_success_timestamp_seconds gauge
atlas_offsite_last_success_timestamp_seconds $last_success
# HELP atlas_offsite_last_exit_code Result of the last off-site snapshot: 0 success, 3 partial, 1 error.
# TYPE atlas_offsite_last_exit_code gauge
atlas_offsite_last_exit_code $code
# HELP atlas_offsite_last_duration_seconds Duration of the last off-site snapshot.
# TYPE atlas_offsite_last_duration_seconds gauge
atlas_offsite_last_duration_seconds {{ printf "%.0f" .Duration.Seconds }}
# HELP atlas_offsite_last_bytes_added Bytes the last off-site snapshot added to the repository.
# TYPE atlas_offsite_last_bytes_added gauge
atlas_offsite_last_bytes_added $added
# HELP atlas_offsite_last_error_info Error of the last off-site snapshot (empty on success).
# TYPE atlas_offsite_last_error_info gauge
atlas_offsite_last_error_info{error="$error"} 1
PROM
chmod 0644 "$tmp"
mv -f "$tmp" "$out"
```

- Backrest renders the command as a Go template before running it. `.SnapshotStats` is empty when the snapshot fails before restic runs (for example when the pre-check fails), hence the `with`. The error text is untrusted: it is shell-quoted by `ShellEscape`, then reduced to at most 200 printable ASCII characters without quotes or backslashes, so it is a valid label value.
- The metrics are `atlas_offsite_last_run_timestamp_seconds`, `atlas_offsite_last_success_timestamp_seconds` (a failed snapshot keeps the previous value), `atlas_offsite_last_exit_code` (0 success, 3 partial, 1 error), `atlas_offsite_last_duration_seconds`, `atlas_offsite_last_bytes_added`, and `atlas_offsite_last_error_info{error}`. They must not reuse the `atlas_backup_*` names of `atlas_backups.prom`: node-exporter drops a metric whose HELP text differs between two files.
- The file is written to a temporary name that node-exporter ignores and then renamed, so node-exporter never reads a partial file. Backrest runs as root with `DAC_OVERRIDE`, so it can write to the root-owned directory; the file is `0644` for node-exporter (`65534`).
- The hook is for this plan only: another plan needs its own file name and metric labels.
- Order matters when setting it up (or after a rebuild): deploy `backrest` first (the `/metrics` bind), then add the hook, then run the plan with **Backup now** and check the file on the NAS: `cat /volume1/backups/.metrics/atlas_offsite.prom`. Until that file exists, `OffsiteBackupStale` fires (a missing file counts as stale), so deploy `monitoring` with the off-site rules only after it is there.

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

9. If application state could not be restored, note that restored secrets that Atlas passes to an application stay valid, for example the Proton VPN key, the Gluetun control key, slskd and Spottarr credentials, the Cloudflare tunnel token, and the Speedtest Tracker app key. Keys that an application generates itself do not: after each first-run setup, copy the new Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, SABnzbd, and qBittorrent API keys into their Komodo variables before deploying the stacks that consume them.
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
AUTHENTIK_BOOTSTRAP_EMAIL
AUTHENTIK_BOOTSTRAP_PASSWORD
AUTHENTIK_POSTGRES_PASSWORD
AUTHENTIK_SECRET_KEY
BAZARR_API_KEY
CLOUDFLARE_DNS_API_TOKEN
CLOUDFLARE_TUNNEL_TOKEN
DISCORD_ALERTS_WEBHOOK_URL
GLUETUN_CONTROL_API_KEY
GRAFANA_ADMIN_PASSWORD
GRAFANA_OIDC_CLIENT_SECRET
GRAFANA_SECRETS_MANAGER_KEY
GRAFANA_SECRET_KEY
HEALTHCHECKS_APPDATA_PING_URL
HEALTHCHECKS_WATCHDOG_PING_URL
KOMETA_PLEX_TOKEN
KOMETA_TMDB_API_KEY
KOMODO_MONITORING_API_KEY
KOMODO_MONITORING_API_SECRET
LIDARR_API_KEY
PROTONVPN_WIREGUARD_PRIVATE_KEY
PROWLARR_API_KEY
QBITTORRENT_API_KEY
RADARR_API_KEY
SABNZBD_API_KEY
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
```

Komodo variables use uppercase snake case and are named for the service or
resource that owns the value. Compose files translate those names to any
upstream-specific environment names.

Mark every variable that holds a key, password, token, or webhook URL as
secret in Komodo. Komodo redacts only secret variables in logs and in the
deployed `docker compose config`, which any user with Read on a stack can
retrieve, including the monitoring service user.

Generate `QBITTORRENT_API_KEY` in qBittorrent under `Options > WebUI >
Authentication > API Key`, then store the complete `qbt_...` value in Komodo.
The monitoring stack (json-exporter) uses this key for stateless Web API access;
it does not replace the qBittorrent WebUI username and password used for
interactive login.

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

All Plex bind sources use `create_host_path: false`, so missing appdata, media, transcode, or backup paths fail instead of becoming Docker-created `root:root` directories. Plex keeps the direct `192.168.2.200:32400` listener for native clients and discovery, while the browser UI remains available through `https://plex.atlas.vandaele.io`.

In Plex `Settings > Network`, set `LAN Networks` to `192.168.2.0/24`. Plex runs on a Docker bridge network and otherwise treats LAN clients as remote, applying remote bandwidth limits and transcoding. Do not add Docker subnets: Caddy-proxied public traffic would then count as local. Leave `List of IP addresses and networks that are allowed without auth` empty.

### Roon Server Storage

The pinned Roon Server image runs its server processes as `root`. Its private state lives under `/volume2/appdata/roonserver`; the pre-deploy hook provisions only that top-level directory as `0:0` with mode `0750`. It does not recursively change the existing Roon database tree.

Roon mounts `/volume1/data/media/music` read-only. The hook preserves the existing owner of that shared path, enforces group `10` and mode `2775` on its top-level directory, and verifies that the shared media identity can write there for the surrounding download workflow. It never recursively changes the music library.

Roon backups live under `/volume1/backups/roonserver`. The hook provisions only that child as `0:10` with mode `2770`; existing backup contents keep their current ownership and modes. All three bind sources use `create_host_path: false`, and Roon receives a two-minute stop grace period for clean database shutdown.

### AdGuard Storage

The pinned AdGuard Home image runs as `root`. Its work and configuration directories live under `/volume2/appdata/adguard`, and the pre-deploy hook provisions the app root plus `work` and `conf` as `0:0` with mode `0750`. Existing files, including `AdGuardHome.yaml`, are not recursively modified.

Both bind sources use `create_host_path: false`, so a missing preflight path fails closed rather than being silently created by Docker. DNS remains bound only to `[[NAS_LAN_IP]]:53` over TCP and UDP. Deploy AdGuard separately from other stacks because its restart temporarily interrupts Atlas DNS.

Atlas deliberately keeps the AdGuard Home web interface on container port `3000` after the initial setup. The Caddy route and container healthcheck both depend on `http.address` remaining `0.0.0.0:3000`. The healthcheck also asks AdGuard on `127.0.0.1:53` for `localhost` and requires the answer `127.0.0.1`, which AdGuard serves from the container's hosts file without any upstream, so an internet outage does not make it unhealthy. It therefore also depends on `dns.bind_hosts` including `0.0.0.0`, on filtering and **Use hosts file** staying enabled, and on `127.0.0.1` not being blocked in the access settings. During a fresh installation or a restore without the existing `AdGuardHome.yaml`, select port `3000` in the setup wizard instead of the normal port `80`.

Verify the persisted listener without printing the adjacent user configuration:

```sh
docker exec adguard awk '/^http:/ { in_http=1; next } in_http && /^[^[:space:]]/ { exit } in_http && /^[[:space:]]+address:/ { print; exit }' /opt/adguardhome/conf/AdGuardHome.yaml
```

The expected result is `address: 0.0.0.0:3000`. If DNS works but `https://adguard.atlas.vandaele.io` does not, check this value before changing Caddy or exposing a temporary host UI port.

### Kometa Tokens

Kometa reads repo-tracked config files from `stacks/kometa/config/`, but secrets stay in Komodo variables.

Required Komodo variables:

```text
KOMETA_PLEX_TOKEN
KOMETA_TMDB_API_KEY
```

Use a Plex token generated for Kometa, not the Plex server token from `Preferences.xml`.

Kometa has no Atlas web route. It runs on the configured `KOMETA_TIMES` schedule and reaches Plex through `http://plex:32400` on `media_network`. Runtime configuration, cache, reports, and assets live under `/volume2/appdata/kometa`; the pre-deploy hook explicitly provisions the configured `assets` directory. Preserve that private tree with owner `999:10` and mode `0750` when backing it up.

Kometa's Docker healthcheck, shown in the dashboard's Health column, reads `/volume2/appdata/kometa/logs/meta.log` rather than checking that the scheduler process is alive, because the scheduler survives failed runs. Kometa starts a fresh `meta.log` for every run and keeps the previous nine as `meta-1.log` to `meta-9.log`, so the file always holds the current or latest run. Healthy means the latest run reached its `Finished … Run` footer without a `[CRITICAL]` line or a `Library Connection Failed` line, and finished less than 26 hours ago (the daily 03:00 run plus margin for slow runs). A run in progress counts as healthy while it has no critical error and its log was written in the last six hours. After a start or restart, the container stays healthy for 26 hours while it waits for its first scheduled run, unless the latest log already records a failure. Unhealthy therefore means Kometa could not load its config or reach TMDb, Plex was unreachable or in maintenance, a library failed to connect, the run crashed or was killed (for example by the memory limit) before it finished, or no successful run happened in 26 hours. Collection, item, and overlay errors and warnings do not make it unhealthy, so still review the summary at the end of `meta.log` after config changes. A failed run stays unhealthy until the next successful run; after fixing the cause, recheck immediately with `docker exec -e KOMETA_RUN=True kometa s6-setuidgid abc python3 /app/kometa/kometa.py --config /config/config.yml`, but not while a scheduled run is in progress. The `-e KOMETA_RUN=True` is required because Kometa's environment variables override its `--run` flag.

The repository-managed `config.yml`, `collections/movies.yml`, and `collections/tv.yml` files trigger a full Kometa redeploy. Before Compose starts, the pre-deploy hook atomically installs them into appdata and verifies their SHA-256 checksums. `config.yml` uses mode `0600`; collection definitions use `0640`. The tracked configuration contains token placeholders, while the actual Plex and TMDb credentials remain required Komodo variables.

Do not repair Kometa with an unrestricted recursive `chown`. Stop the container, audit `/volume2/appdata/kometa`, and use `repair-tree-owner` only when the private-tree audit reports ownership mismatches.

### Seerr

The `seerr` stack runs Seerr behind Caddy at:

```text
https://seerr.atlas.vandaele.io
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

- This stack does not expose a direct host port. Access is Caddy-only through `https://seerr.atlas.vandaele.io`.
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
https://bazarr.atlas.vandaele.io
```

Deploy order:

1. Deploy `bazarr`.
2. Deploy or redeploy `caddy`.
3. Complete first-run setup.

On first setup, configure these services inside Bazarr:

```text
Sonarr URL: http://127.0.0.1:8989
Radarr URL: http://127.0.0.1:7878
```

Use the API keys from Sonarr and Radarr. Keep Bazarr path mappings empty if Bazarr, Sonarr, and Radarr all use matching `/data/...` container paths.

Operational notes:

- This stack does not expose a direct host port. Access is Caddy-only through `https://bazarr.atlas.vandaele.io`.
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
https://spottarr.atlas.vandaele.io
```

Spottarr is VPN-bound through Gluetun. Caddy reaches it through:

```text
http://downloaders-vpn:8383
```

Deploy order:

1. Create the required Komodo secrets.
2. Deploy or redeploy `gluetun`.
3. Deploy `spottarr`.
4. Deploy or redeploy `caddy`.

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

- This stack does not expose a direct host port. Access is Caddy-only through `https://spottarr.atlas.vandaele.io`.
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
- Recyclarr's Docker healthcheck, shown in the dashboard's Health column, reads Recyclarr's own per-run debug logs in `/volume2/tmp/recyclarr/logs/cli` rather than checking that `supercronic` is alive, because the scheduler survives failed syncs. Healthy means the newest real sync (scheduled or manual `recyclarr sync`) finished without an `ERR` or `FTL` line or a failed pipeline, and finished less than 26 hours ago (the daily 04:15 run plus margin for slow runs). After a start or restart, the container stays healthy for 26 hours while it waits for its first sync. While a sync is running, the previous result stands. Previews and commands such as `recyclarr list` do not count as syncs. Unhealthy therefore means Sonarr or Radarr was unreachable or rejected its API key, the guide or config could not be loaded, a pipeline failed, the sync was killed before it finished, or no successful sync happened in 26 hours. Recyclarr warnings, such as an unknown `trash_id` or a failed guide fetch that falls back to cached files, do not make it unhealthy, so still review sync output after config changes. A failed sync stays unhealthy until the next successful sync; after fixing the cause, run `recyclarr sync` to recheck immediately. A preview does not clear it, and a partial sync such as `recyclarr sync sonarr` clears it even if the other service is still broken. If you change `CRON_SCHEDULE` to run less often than daily, raise the 26-hour limit in `compose.yaml` to match.

### Houndarr

The `houndarr` stack runs controlled, rate-limited missing and cutoff searches for Sonarr, Radarr, and Lidarr. Its built-in UI is available locally through Caddy at:

```text
https://houndarr.atlas.vandaele.io
http://houndarr.atlas.vandaele.io
```

Deploy order:

1. Confirm `gluetun`, `sonarr`, `radarr`, and `lidarr` are deployed and healthy.
2. Deploy `houndarr`.
3. Deploy or redeploy `caddy`.
4. Create the Houndarr administrator account immediately and add the Arr instances.

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
- `HOUNDARR_SECURE_COOKIES=true`: every client reaches Houndarr over HTTPS.

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
https://slskd.atlas.vandaele.io
http://slskd.atlas.vandaele.io
```

Soularr and slskd are separate Komodo stacks so the automation worker can be updated without interrupting the Soulseek client or its downloads. Soularr's built-in UI is intentionally disabled in v1 because it has no authentication. It has no route or direct host port; inspect its logs through Komodo or Docker. slskd is Caddy-only and requires the configured web credentials. Protect `slskd.atlas.vandaele.io` with Cloudflare Access and route that tunnel hostname to `http://caddy:8080`. slskd reuses the existing Gluetun namespace used by qBittorrent and SABnzbd, and its UI is reachable through Gluetun's `downloaders-vpn` alias.

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

Soularr's Docker healthcheck, shown in the dashboard's Health column, reads `/volume2/appdata/soularr/soularr.log` rather than probing a port, because Soularr runs as a scheduled script every `SCRIPT_INTERVAL` (900 seconds) and has no API with its UI disabled. Healthy means the most recent completed run ended normally ("No releases wanted", "Soularr finished", or "releases failed to find a match … still wanted") without a Lidarr or slskd connection error, and the next run is not overdue by more than 300 seconds. While a run is in progress, the previous run's result stands, unless the current run has already logged a connection error or has written nothing for two hours, which usually means a hung slskd request. Unhealthy therefore means Lidarr or slskd was unreachable, Lidarr rejected the API key, the run crashed, or the scheduler loop stopped. Nothing to download and albums that are not found on Soulseek both count as healthy. Individual peer, download, and import failures are not health failures, so still review the log for acquisition results, and watch the independent `slskd` and shared `gluetun` logs for VPN failures. A failed run stays unhealthy until the next run succeeds, up to 15 minutes later; restart Soularr after fixing a dependency to recheck immediately.

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

Generate `GLUETUN_CONTROL_API_KEY` with `docker run --rm qmcgaw/gluetun:v3.41.1 genkey` or another high-entropy secret generator. The same Komodo secret is passed to Gluetun for control-server API authentication and to the monitoring stack (json-exporter) for its VPN and port-forward checks.

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
16. Deploy or redeploy `caddy`.

If Gluetun is recreated, every container sharing its network namespace must be recreated, not merely restarted, so it reattaches to the current namespace. That includes Autobrr, qBittorrent, SABnzbd, Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, FlareSolverr, Spottarr, and slskd. The repo encodes this with `after = ["gluetun"]`-style dependencies and `extra_args = ["--force-recreate"]` on each VPN-bound stack.

Komodo `after = ["gluetun"]` affects dependency ordering during Resource Sync deploys. If Gluetun is deployed manually outside a dependency-aware sync/procedure, explicitly redeploy all VPN-bound stacks afterwards; their `--force-recreate` deploy args handle the required namespace reattachment.

qBittorrent and SABnzbd are available at:

```text
https://qbittorrent.atlas.vandaele.io
https://sabnzbd.atlas.vandaele.io
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

The monitoring stack (json-exporter) reads Gluetun through the internal control server at `http://downloaders-vpn:8000` using `GLUETUN_CONTROL_API_KEY`. The control server is exposed only on Docker networks, not through Caddy or a host port.

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
https://autobrr.atlas.vandaele.io
http://autobrr.atlas.vandaele.io
```

Deploy order:

1. Deploy `gluetun`.
2. Deploy or redeploy `qbittorrent`.
3. Deploy `autobrr`.
4. Deploy or redeploy `caddy`.
5. Create the Autobrr administrator account immediately, then configure only the indexers and actions you intend to use.

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
https://qui.atlas.vandaele.io
```

qui is not a qBittorrent alternative WebUI theme. It connects to qBittorrent through the qBittorrent Web API. The existing qBittorrent UI remains available at `https://qbittorrent.atlas.vandaele.io`.

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

- There is no direct qui host port. Access is Caddy-only through `https://qui.atlas.vandaele.io`.
- qui does not run in Gluetun's network namespace. It is only a control UI and should not share the VPN container lifecycle.
- Keep qui authentication enabled. Do not set `QUI__AUTH_DISABLED=true`.
- The stack mounts `[[DATA_DIR]]/downloads/torrents` at the container path `/data/downloads/torrents` (via `TORRENTS_DIR`) to enable qui's filesystem-dependent features. This path deliberately matches qBittorrent's own `/data/downloads/torrents` mapping so the save paths qui reads from the qBittorrent API resolve correctly on qui's filesystem. This mount grants qui read/write/delete capability over torrent downloads; switch it to `:ro` in `stacks/qui/compose.yaml` if only read-only browsing is wanted.
- `[[APPDATA_DIR]]/qui` contains the qui database, admin/session state, and qBittorrent credentials. It is provisioned as private appdata with mode `0700` and should be backed up; never recursively change ownership across the shared torrent tree during recovery.
- Require Cloudflare Access before reaching qui through `qui.atlas.vandaele.io`.

### Rclone

The `rclone` stack runs the official `rclone gui` web UI behind Caddy at:

```text
https://rclone.atlas.vandaele.io
```

Deploy order:

1. Deploy `rclone`.
2. Deploy or redeploy `caddy`.

Use the normal hostname below. Caddy redirects first-time GUI loads to the rclone launcher URL so the web UI knows how to reach the same-origin RC API:

```text
https://rclone.atlas.vandaele.io/
```

Operational notes:

- `rclone.atlas.vandaele.io` is a privileged management surface. Anyone who reaches either hostname can manage configured remotes and read or write the mounted local data path.
- The rclone RC API runs with `--no-auth` on a dedicated `rclone_network` that only Caddy and rclone join. `rclone.atlas.vandaele.io` is behind authentik forward auth for `admins`, with no bypass (see [Forward Auth](#forward-auth)); application-level authentication does not protect this endpoint.
- This stack mounts all of `[[DATA_DIR]]` at `/data`. That was chosen for flexibility, not least privilege.
- `rclone.conf` contains remote credentials and tokens. It is provisioned with `0600` permissions and should be backed up from `[[APPDATA_DIR]]/rclone`.
- `user-dirs.dirs` is repository-managed and triggers a redeploy so its read-only bind always references the current file.
- Do not use the UI self-update flow. Upgrade `rclone` by bumping the image tag in this repository.
- The upstream UI still shows `Mounts` and `Serves`. This stack does not provision FUSE mount support, and it does not publish or route `rclone serve` listeners beyond the main UI hostname.

### Speedtest Tracker

Speedtest Tracker runs behind Caddy at:

```text
https://speedtest.atlas.vandaele.io
```

Before deploying, create `SPEEDTEST_TRACKER_APP_KEY` in Komodo. This is mapped to the container's required `APP_KEY` environment variable; the shorter name is the upstream Speedtest Tracker/Laravel name, while the Komodo value is namespaced for this repo. Generate it with:

```sh
echo -n 'base64:'; openssl rand -base64 32
```

After first login, change Speedtest Tracker's default application credentials.

The stack uses SQLite under `[[APPDATA_DIR]]/speedtest-tracker`, runs a scheduled test every six hours by default with `SPEEDTEST_TRACKER_SCHEDULE=6 */6 * * *`, and prunes results older than 365 days by default. Set `SPEEDTEST_TRACKER_SERVERS` to a comma-separated list of Ookla server IDs if you want pinned test servers; otherwise Speedtest Tracker will choose automatically.

### Cloudflared

The `cloudflared` stack runs a remotely managed Cloudflare Tunnel connector for Atlas. It joins `proxy_network` and has no host ports; Cloudflare edge traffic is forwarded into Caddy over Docker networking.

Before deploying, create a remotely managed tunnel in Cloudflare Zero Trust and save the tunnel token in Komodo:

```text
CLOUDFLARE_TUNNEL_TOKEN
```

Deploy order:

1. Deploy or redeploy `caddy`.
2. Deploy `cloudflared`.

For each public hostname in the Cloudflare Tunnel dashboard, point the service at Caddy's tunnel listener:

```text
Service: http://caddy:8080
```

Port `8080` is reachable only on Docker networks, serves every public route over plain HTTP (Cloudflare terminates HTTPS), and takes the client address from `CF-Connecting-IP`. It never depends on Caddy's certificate, and LAN-only routes are not on it.

Define each public hostname exactly once, and give it a proxied DNS record (`CNAME <app>.atlas` to `<tunnel-id>.cfargotunnel.com`; the dashboard creates it with the route). Sending every public hostname to `http://caddy:8080` keeps routing declarative in Caddy and preserves the incoming `*.atlas.vandaele.io` host for matching. `probe_routes_public` checks every public route through Cloudflare, so a route or DNS record that stops reaching Caddy raises [`ProbeFailed`](#application-probes).

Caddy routes by HTTP host. The shared `atlas_reverse_proxy` snippet serves `<app>.atlas.vandaele.io` on `443` and on `8080`; the specialized rclone snippet does the same. For a custom route, use:

```caddyfile
speedtest.atlas.vandaele.io, http://speedtest.atlas.vandaele.io:8080 {
	reverse_proxy speedtest-tracker:80
}
```

Use Cloudflare Access policies on the public hostnames for admin-facing services. The tunnel removes inbound port exposure, but it does not replace application authentication.

### authentik

The `authentik` stack runs [authentik](https://goauthentik.io/) 2026.8, the login for Atlas applications, with per-user access for pjan and family, at:

```text
https://auth.atlas.vandaele.io
```

It is one HTTPS origin on every network, which OIDC callbacks, passkeys, and secure cookies need: Caddy serves it on `443` for the LAN and Tailscale, and Cloudflare terminates HTTPS for the internet. There is no Cloudflare Access in front: authentik itself is the gate, with a Cloudflare rate limit on its login API. Grafana is the first application behind it; the other applications follow app by app, after each gets its own HTTPS hostname.

Layout:

- `postgresql` (`postgres:16`, the version in authentik's reference compose file) runs as UID `70` with its data in `/volume2/appdata/authentik/postgres` (`0700`), only on the internal `authentik_network`, which has no route to the internet. Renovate keeps it on major 16; a major upgrade needs a dump and restore.
- `server` runs as UID `1000` with `/volume2/appdata/authentik/data` (`0700`, uploaded icons) at `/data`. It joins `proxy_network` for Caddy and `monitoring_network` for metrics (`:9300`) and the health probe.
- `worker` runs background tasks and applies the blueprints. It has no Docker socket (only outposts that authentik deploys itself need one; the embedded outpost runs inside the server) and is only on `authentik_network`, which is enough while authentik sends no email.
- Every container has a read-only root filesystem and no capabilities. authentik is not given `TZ`: it expects to run in UTC.

`stacks/caddy/conf/sites/auth.caddy` sends `X-Forwarded-Proto: https`, because authentik builds its OIDC URLs and secure cookies from the scheme, and replaces `X-Forwarded-For` with Cloudflare's `CF-Connecting-IP`, because authentik reads only `X-Forwarded-For` and Caddy would set it to the cloudflared container. authentik trusts `X-Forwarded-For` from private addresses (its default `listen.trusted_proxy_cidrs`); only containers can connect to it.

Komodo variables (all secret):

```text
AUTHENTIK_SECRET_KEY          openssl rand -base64 60 | tr -d '\n'
AUTHENTIK_POSTGRES_PASSWORD   openssl rand -hex 32
AUTHENTIK_BOOTSTRAP_EMAIL     pjan's email address
AUTHENTIK_BOOTSTRAP_PASSWORD  openssl rand -base64 32
GRAFANA_OIDC_CLIENT_SECRET    openssl rand -hex 32
```

Never change `AUTHENTIK_SECRET_KEY` after the first start: it signs sessions and tokens. `AUTHENTIK_POSTGRES_PASSWORD` only applies when the database is created. The bootstrap values are read only when the database is empty: they create `akadmin`, and a set password closes authentik's initial-setup flow, which would otherwise let anyone on the public hostname choose the admin password. Set them before the first deploy and empty them (keep the variables) once setup is done. `GRAFANA_OIDC_CLIENT_SECRET` goes to both the authentik worker (the Grafana blueprint) and Grafana.

#### Blueprints

`stacks/authentik/blueprints/` is mounted read-only at `/blueprints/custom` in the worker, which applies it when it starts; changing a file restarts the worker (`config_files`, `requires = "Restart"`). A blueprint resets the attributes it sets, so change these objects in the repository, not in the UI:

- `groups.yaml`: the groups `admins` (pjan; also authentik superusers) and `family`.
- `admins-mfa.yaml`: members of `admins` without TOTP or a passkey must set one up before they are logged in (stage `atlas-admins-mfa-setup` at order 35 of the default authentication flow). Everyone else is asked for TOTP or a passkey only once they have set one up in their user settings.
- `grafana.yaml`: the OAuth2/OIDC provider and application `grafana`, open to `admins` and `family` (Viewer).
- `forward-auth-<app>.yaml`: one proxy provider per app behind forward auth (see [Forward Auth](#forward-auth)), its application, and its group binding.
- `outpost.yaml`: the embedded outpost and the list of every forward-auth provider it serves.
- `reputation.yaml`: brute-force protection. An IP whose login reputation reaches `-5` (five failed logins more than successful ones, decaying after a day) cannot start the login flow. Usernames are not scored, so nobody can lock out a known user.

Changing `outpost.yaml` or a `forward-auth-*.yaml` restarts the server as well as the worker: the embedded outpost serves a new provider only after a restart. Logins pause for those seconds.

Users are created in the authentik UI, never in blueprints: they carry passwords. Without email (SMTP), pjan sets family passwords by hand.

#### Forward Auth

Apps without their own authentik login sit behind authentik forward auth in Caddy. Their site imports `atlas_protected_proxy` (or, for rclone, `atlas_rclone`), which runs `atlas_forward_auth` before anything else:

- An anonymous request is redirected to `https://auth.atlas.vandaele.io` and, after login, back to the app. The embedded outpost in `authentik-server` answers Caddy's checks; there is no separate outpost container.
- Each app has its own provider in single-application mode, so access is per app per group: an app bound to `admins` refuses a `family` user. Every forward-auth app is `admins` only.
- Caddy always sets `X-Forwarded-Host` to the request's own host. The outpost picks the provider (and its group policy) by that header, and on the tunnel listener Caddy would otherwise pass a client-supplied value through, letting a session for one app open another.
- Paths with encoded dots, slashes, or backslashes, or dot segments, get `400` before the check, so the outpost and the app always see the same path.
- A provider's `skip_path_regex` lets health probe paths through without a session; nothing else bypasses the check. Client-supplied `X-Authentik-*` headers are always stripped.
- When authentik is down, every forward-auth app answers `502`.

Gated today: rclone. `UNGATED_CADDY_ROUTES` in `scripts/validate-repository.py` lists the routes that stay outside forward auth (authentik itself, Caddy's health route, Grafana with its own authentik login, Plex and Seerr whose clients cannot follow a login redirect, and the LAN-only Backrest and Komodo); `NOT_YET_GATED_CADDY_ROUTES` lists the apps that still rely on their own login. For every gated route the validator requires its `forward-auth-<app>.yaml`, its place in `outpost.yaml`, the server restart in `config_files`, its `probe_gate` targets, and its place in the authentik inhibition in `alertmanager.yml`.

To put an app behind forward auth: add `forward-auth-<app>.yaml` (copy `forward-auth-rclone.yaml`; add a `skip_path_regex` for its probe path only), list it in `outpost.yaml`, register it in the authentik `config_files` with `services = ["worker", "server"]`, switch its site to `import atlas_protected_proxy <app> <upstream>`, move it from `NOT_YET_GATED_CADDY_ROUTES`, and add its `probe_gate` targets and inhibition entry. Only after its gate probes are green, relax the app's own login if wanted; to roll back, restore the app's own login first.

#### Break-Glass

- authentik down: on the LAN or Tailscale, open `https://komodo.atlas.vandaele.io` or `http://192.168.2.200:9120` (never behind authentik) and redeploy `authentik`. If Komodo is down too, SSH to the NAS and run `docker start authentik-postgresql authentik-server authentik-worker`.
- Locked out of authentik (a lost password or MFA device, or an IP blocked by `reputation.yaml`): log in as `akadmin` with the break-glass password from the password manager, or create a one-time recovery link over SSH with `docker exec authentik-worker ak create_recovery_key 1 pjan`.
- Grafana: its local `admin` login (`GRAFANA_ADMIN_PASSWORD`).

#### First Setup

1. Create the five Komodo variables above before running the Resource Sync: the sync deploys `authentik` and redeploys `monitoring`, and both fail without them. Wait until the three `authentik` containers are healthy, then deploy `caddy` by hand. Until step 2, the `authentik-public` probe fails.
2. In the Cloudflare Tunnel dashboard, add the public hostname `auth.atlas.vandaele.io` with service `http://caddy:8080`, and no Cloudflare Access application. In the Cloudflare dashboard for `vandaele.io`, turn on **SSL/TLS → Edge Certificates → Always Use HTTPS** and add a rate-limiting rule: URI path starts with `/api/v3/flows/executor/`, counted per IP, for example 20 requests per 10 seconds, action Block. A normal login takes about 5 requests there.
3. Open `https://auth.atlas.vandaele.io` and log in as `akadmin` with the bootstrap password. Set up TOTP and a passkey under **Settings → MFA Devices**.
4. Create the user `pjan` in **Directory → Users**, add it to `admins`, set its password, log in as `pjan` (authentik makes it set up TOTP or a passkey), and set up the other one too. Then deactivate `akadmin`, or give it a long random password kept in the password manager for break-glass.
5. Empty `AUTHENTIK_BOOTSTRAP_EMAIL` and `AUTHENTIK_BOOTSTRAP_PASSWORD` in Komodo.
6. Create the family users and add them to `family`.
7. Delete Grafana's local user `pjan` in **Administration → Users and access → Users** (log in as `admin`), then test the Grafana login below as `pjan` (Admin) and as a family member (authentik denies access).

#### Grafana Login

Grafana's login page has **Sign in with authentik** (`GF_AUTH_GENERIC_OAUTH_*` in `stacks/monitoring/compose.yaml`). Members of `admins` get Grafana's Admin role and everyone else Viewer, from the `groups` claim; authentik lets in `admins` and `family`. Grafana matches authentik users by username, never by email, because users can change their email in authentik. It therefore cannot take over an existing local Grafana user with the same username: that login fails with `unable to create user` until the local user is deleted. Dashboards live in Git Sync, so a deleted local user loses only its preferences and stars.

Grafana's own login form (the `admin` user from `GRAFANA_ADMIN_PASSWORD`) stays on as break-glass until every application uses authentik. Grafana's token and userinfo calls go to `https://auth.atlas.vandaele.io`, which Atlas DNS sends to Caddy's `443`, so they depend on Caddy's certificate on every network: when it is invalid ([`CaddyDown`](#caddy)), use the local `admin` login.

#### Backups And Restore

The nightly `appdata-backup` Action stops `authentik` (it is not in `NEVER_STOP`), so `/volume2/appdata/authentik` is copied with Postgres stopped and consistent. Nobody can log in for those minutes. To restore, stop the `authentik` stack and restore `authentik` as in [Restoring From The Local Snapshot](#restoring-from-the-local-snapshot) (the database and the data directory together), then start the stack: Postgres starts first, and the server and worker wait until it is healthy. `AUTHENTIK_SECRET_KEY` must be the one the snapshot was taken with.

#### Monitoring

Prometheus scrapes the server's metrics (job `authentik`). `probe_health` checks `http://authentik-server:9000/-/health/ready/` directly (service `authentik`) and `https://auth.atlas.vandaele.io/-/health/live/` through Cloudflare (service `authentik-public`, from `blackbox-public`, which resolves through public DNS), so [`ProbeFailed`](#application-probes) is critical when either fails, gated during the backup: every app behind forward auth is locked while authentik is down. Both appear as tiles in the Application health panel on Atlas Health. The `authentik` job is not in `MonitoringTargetDown`: that alert is not gated, so it would fire during every nightly backup, and the probe already covers a down server.

## Monitoring

The `monitoring` stack runs Prometheus, Alertmanager (see [Alerts](#alerts)), node-exporter, blackbox-exporter and blackbox-public (the same probes, resolved through public DNS for the probes of the Cloudflare path), smartctl-exporter, cAdvisor, the application exporters, and Grafana on the private `monitoring_network`. Only Grafana also joins `proxy_network`, and it is reachable at `https://grafana.atlas.vandaele.io` and at `https://grafana.atlas.vandaele.io`, which must be protected by Cloudflare Access; Grafana also requires its own login. Prometheus and Alertmanager have no host port and no web route; query Prometheus through Grafana.

The nightly `appdata-backup` Action never stops the `monitoring` stack, and its data is not backed up: `/volume2/appdata/prometheus` (90 days, at most 20 GB), `/volume2/appdata/alertmanager` (silences and the notification log), and `/volume2/appdata/grafana` (Grafana's SQLite database) are excluded. Only configuration is kept, in git: Prometheus, its rules, Alertmanager, blackbox, and Grafana provisioning in this repository, and dashboards in `pjan/atlas-dashboards`. After losing Volume 2, Grafana starts with an empty database: the admin login comes from `GRAFANA_ADMIN_PASSWORD`, the datasource (and alerting) from provisioning, and the dashboards return once Git Sync is reconnected with the token from the password manager. Extra users, service accounts, and alert history are lost. Scrapes run every 30 seconds and probes every 60 seconds.

Resource Sync only runs `compose up -d` when a tracked config file changes, which does not recreate an unchanged container. Prometheus and blackbox therefore reload `stacks/monitoring/prometheus/prometheus.yml` (with the rule files in `stacks/monitoring/prometheus/rules/`) and `stacks/monitoring/blackbox/blackbox.yml` automatically, and the stack restarts Grafana and sends Alertmanager `SIGHUP` in `post_deploy` so provisioning and alerting changes apply. `scripts/validate.sh` checks these configurations with the pinned images (`promtool check config`, `promtool check rules` and `test rules`, `amtool check-config`, `blackbox_exporter --config.check`).

Current signals:

| Job | What it checks |
|---|---|
| `node` | CPU, memory, filesystems, md RAID, btrfs, and the backup textfile metrics in `/volume1/backups/.metrics` |
| `cadvisor` | Per-container CPU (usage, the `cpus` limit, and throttling at it), memory (working set, RSS, limit), block I/O, pressure (PSI: CPU, memory, and I/O waiting), threads and the PIDs limit, start time, and OOM events, keyed by `container_id` |
| `smartctl` | SMART health, NVMe wear, spare, critical warnings, media errors, and temperatures for `sda` (Seagate 12 TB, Volume 1), `nvme0` (Lexar 512 GB, Volume 2), and `nvme1` (TWSC 128 GB, UGOS system disk) |
| `probe_routes` | Every Caddy route on `https://<app>.atlas.vandaele.io` from the LAN (UniFi DNS, Caddy and its certificate, and the application; 401 and 403 count as healthy) |
| `probe_gate` | Every route behind authentik forward auth sends an anonymous request to the authentik login (module `http_gate`: exactly `302` to `https://auth.atlas.vandaele.io/`), from the LAN and through Cloudflare; services `<app>-gate` and `<app>-gate-public` |
| `probe_routes_public` | Every public route through Cloudflare and the tunnel (from `blackbox-public`, through public DNS; services `<app>-public`) |
| `probe_tcp` | AdGuard DNS `:53`, Caddy `:80`, Komodo `:9120`, Plex `:32400`, and Roon Server `:9330` on `192.168.2.200` |
| `probe_dns_split` | UniFi and AdGuard resolve `sonarr.atlas.vandaele.io` to `192.168.2.200` |
| `probe_dns_atlas_local` | UniFi resolves `sonarr.atlas.local` to `192.168.2.200` (old hostnames, redirected) |
| `probe_dns_external` | AdGuard resolves an external name |
| `probe_tls_caddy` | Caddy's HTTPS listener `192.168.2.200:443` completes a TLS handshake for `caddy.atlas.vandaele.io` with a valid certificate, and its expiry |
| `probe_internet` | Outbound HTTPS from the NAS |
| `probe_health` | Application health, through Caddy unless noted: Servarr `/ping` must report `OK` (fails when the app cannot reach its database), Plex `/identity` must contain a `machineIdentifier` (through Caddy and directly on `:32400`), Grafana `/api/health` must report the database `ok`, SABnzbd must report its version, Caddy must answer `ok`, Komodo, Seerr, Autobrr, Houndarr, qui, and Spottarr health endpoints must return 200, and authentik's ready endpoint (directly, `authentik`) and live endpoint (through Cloudflare, `authentik-public`) must return 200 |
| `caddy` | Caddy's own metrics per hostname (requests, errors, latency) on the internal listener `:2020` |
| `cloudflared` | Tunnel metrics, including `cloudflared_tunnel_ha_connections`, on `:2000` |
| `unpackerr` | Extraction metrics on `:5656` |
| `authentik` | authentik's server metrics (requests, flows, tasks, outposts) on `:9300` |
| `exportarr`, `exportarr_slow` | Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, and SABnzbd through exportarr: the applications' own health issues (`<app>_system_health_issues`, for example unavailable indexers or download clients), status, and queues. Sonarr and Bazarr are scraped every 5 minutes because they are slow to query |
| `json_apis` | Gluetun VPN status, public IP and country, and forwarded port; qBittorrent connection status (`qbittorrent_transfer_status_info{connection_status}`: connected, firewalled, or disconnected), DHT nodes, transfer rates, and `listen_port` (must equal the Gluetun forwarded port); slskd connected and logged in to Soulseek; the state of every Komodo stack (`komodo_stack_info`); every stack container with its name, stack, service, image, state, Docker health, and exit code (`komodo_container_info`); the Komodo server (Periphery, `komodo_server_info`), Actions and Procedures with their last and next runs, and the Resource Sync with its last sync (`komodo_action_*`, `komodo_procedure_*`, `komodo_sync_*`); every container on the server, including those outside stacks (`komodo_server_container_info`); and Komodo's newest 100 updates and alerts (`komodo_update_start_timestamp_ms`, `komodo_alert_timestamp_ms`, one series per item) |

smartctl-exporter addresses disks by their stable `/dev/disk/by-id` names (`wwn-*` and `nvme-eui.*`, which avoid publishing serial numbers). Docker resolves those names when the container is created, so recreate the `monitoring` stack after adding or replacing a disk and update the device list in `stacks/monitoring/compose.yaml`. It runs as root with only those devices and the `SYS_RAWIO` (SATA) and `SYS_ADMIN` (NVMe) capabilities. smartctl cannot infer the device type from those names, so every device is listed with its type (`;sat` or `;nvme`).

cAdvisor has no Docker socket and no access to the Docker root (`/volume2/@docker`), because both expose every container's environment. It reads only `/sys/fs/cgroup`, so its series carry just the cgroup path (`/system.slice/docker-<id>.scope`, systemd driver on UGOS). Prometheus keeps the metrics the dashboards use, derives `container_id` from that path, and drops everything else. cAdvisor timestamps its samples, so the job sets `track_timestamps_staleness`; otherwise a removed container's series would linger for 5 minutes. Block I/O is reported at every layer (`dm-0`, `md1`, and `sda` carry the same bytes), so only the top layer counts: `dm-0` is Volume 1, `dm-1` Volume 2, `nvme1n1` the UGOS system disk, and `zram*` the compressed swap; never sum across layers. Names, stacks, Compose services, and health come from Komodo (`ListAllStackServices`) as `komodo_container_info{container, stack, compose_service, stack_id, image, state, health, exit_code}`. The recording rules in `rules/containers.yml` join them once: `atlas:container_names` has one series per container ID (Komodo stack services, then other containers Komodo lists as stack `unmanaged` or `appdata-backup`, then `id-<first 12 characters>`, and it keeps names through a Komodo outage of up to an hour), and every `atlas:container_*` series already carries `container`, `stack`, `compose_service`, and `stack_id`. cAdvisor runs as root with only `CAP_SYSLOG` and read access to `/dev/kmsg`, which it needs for OOM events (`kernel.dmesg_restrict=1`). There is no per-container network I/O. Restarts are derived from `container_start_time_seconds` (`atlas:container_started`), and `atlas:container_restarted_outside_backup` leaves out the nightly backup, which stops and starts most stacks; a recreated container starts a new series and is not a restart.

Every service sets `cpus` next to `mem_limit` and `pids_limit` (`scripts/validate.sh` requires all three). The `cpus` values of 2026-10-02 are first estimates without usage history: 4 for transcoding, unpacking, and torrent hashing, 2 for the applications, Prometheus, Grafana, and Gluetun, 1 for light services, 0.5 for exporters. A limit throttles a container instead of killing it, so tune them with the CPU of limit column on Atlas Containers and `atlas:container_cpu_throttled_ratio` (the share of CFS periods throttled at the limit). A changed limit applies when the stack is deployed again.

Volume 1 is a single 12 TB disk (`md1` is RAID 1 with one member), so it has no redundancy: media and the local backups share one disk. The off-site Backrest copy protects `/volume1/backups`; media are not protected.

Caddy, cloudflared, and Unpackerr join `monitoring_network` for scraping; their metrics ports are not published on the host. Public `*.atlas.vandaele.io` hostnames answer `404` for `/metrics` and `/prometheus`, so application metrics endpoints (for example slskd and Speedtest Tracker) are never exposed through Cloudflare.

Grafana provisions the Prometheus datasource (uid `prometheus`) from `stacks/monitoring/grafana/provisioning/`. Grafana runs with a read-only root filesystem, so plugin preinstallation and automatic plugin updates are disabled (`GF_PLUGINS_PREINSTALL_DISABLED`, `GF_PLUGINS_PREINSTALL_AUTO_UPDATE`): plugin versions come only from the pinned image. The app plugins Grafana installed on its first start (Advisor, Explore Traces, Logs Drilldown, Metrics Drilldown, Pyroscope) remain in `/volume2/appdata/grafana/plugins`, are no longer updated, and do not return after a Volume 2 loss. Grafana 13 ships Prometheus as a bundled plugin, and a failed startup update would otherwise leave it unregistered. Dashboards are kept in the private `pjan/atlas-dashboards` repository with Grafana Git Sync, using a fine-grained token scoped to that repository only (Contents read and write, Metadata read, Administration read; Webhooks read and write only while running the setup wizard, which registers a webhook before its "Disable webhook integration" option applies). Git Sync reads only `dashboards/`, targets the folder "Atlas dashboards", polls every 60 seconds with webhooks disabled (Grafana is behind Cloudflare Access), and commits UI saves directly to `main`; the exact wizard settings are in that repository's README. Do not create dashboards outside synced folders: anything else exists only in `grafana.db`. Never edit the vendored community dashboards in the UI; `scripts/vendor.sh` in that repository regenerates them. The Git Sync connection itself lives in `grafana.db`, so after a Volume 2 loss reconnect it in **Administration → General → Provisioning** with the same settings and the token from the password manager.

The Atlas theme is the app plugin `atlas-theme-app` in `stacks/monitoring/grafana/plugins/atlas-theme-app/` (hand-written, no build step), bind-mounted read-only at `/var/lib/grafana/plugins/atlas-theme-app`. It only changes Grafana's theme: `atlas-theme.json` defines it, and `module.js` applies it ([its README](stacks/monitoring/grafana/plugins/atlas-theme-app/README.md)). The file holds the Atlas palette, the themes Atlas Light and Atlas Dark in Grafana's theme-definition format (backgrounds, text, buttons, accent, status colours, Grafana's named colours, the series palette), and colour names Grafana has no slot for (`gray`, `teal`, …), which it also adds to Grafana's colour picker as hues. Styling beyond the theme belongs in panel options, for example the State timeline plus panel plugin's looks.

The rules are in `pjan/atlas-dashboards` `CONVENTIONS.md`. `scripts/validate.sh` checks `atlas-theme.json` against Grafana's theme schema (`stacks/monitoring/grafana-tests/grafana-theme.schema.json`, copied from `packages/grafana-data/src/themes/schema.generated.json` at the Grafana tag in use; copy it again when Grafana is upgraded), every palette reference, and that dark steps mirror light ones (1000 minus the step). Bump `info.version` in `plugin.json` with every change: browsers cache the files by that version. The plugin is unsigned, and `GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=atlas-theme-app` allows only it. It lives in git, not in `/volume2/appdata/grafana`, so it survives a Volume 2 loss; changes apply when `post_deploy` restarts Grafana and the browser reloads. Without the plugin (it also does not load for viewers without an org role, such as public dashboards), the dashboards work with Grafana's stock colours, except the plugin's extra colour names: `super-light-gray` timeline segments render black.

To tune the theme, open any Grafana page with `?atlasEditor=1` added to the URL (for example `https://grafana.atlas.vandaele.io/d/atlas-containers?atlasEditor=1`). A drawer shows `atlas-theme.json`; every edit applies at once, without a reload, and the palette swatches insert `atlas.<key>` references. Edits are kept in that browser only (localStorage), shown by an "Atlas theme: local override" badge, until **Reset to file**. **Copy** copies the file so it can be committed to this repository; the file in the repository stays the source for everyone else.

The plugin relies on undocumented Grafana behaviour (it replaces the theme at runtime and clears panel caches after a theme switch). After a Grafana upgrade, run the theme probe: it renders a dashboard in both themes and after a live switch, lists the colours the browser draws per element, checks Grafana's colour picker (the extra hues listed, and their rows scrolling inside the picker; on a temporary dashboard it creates and deletes), and ends with `FAIL` lines for what the theme no longer reaches. It takes a few minutes and pulls the Playwright image (about 2 GB), so it runs only on request, never from `validate.sh`:

```sh
GRAFANA_URL=https://grafana.atlas.vandaele.io GRAFANA_USER=pjan sh scripts/theme-probe.sh
```

It asks for the Grafana password (or takes `GRAFANA_PASSWORD`), switches that user's theme during the run, and restores the preference at the end. `DASHBOARD=/d/<uid>` probes another dashboard.

State timeline plus (`pjan-statetimeline-panel`) is pjan's drop-in for Grafana's state timeline, with opt-in per-row annotations and styling, released from the public [pjan/grafana-plugins](https://github.com/pjan/grafana-plugins) repository (AGPL-3.0, as it derives from Grafana's core panel). `stacks/monitoring/grafana/plugins/pjan-statetimeline-panel/` holds a release, bind-mounted read-only at `/var/lib/grafana/plugins/pjan-statetimeline-panel` and allowed as unsigned. `stacks/monitoring/grafana/plugin-releases.json` records its tag, commit, and a SHA-256 per file, and `scripts/validate.sh` fails if the directory differs from it. Never edit the directory by hand; to update, release the plugin in that repository, then run `python3 scripts/update-grafana-plugin.py pjan-statetimeline-panel <version>` (it also registers the files as config_files in `stacks.toml`; behind TLS inspection set `SSL_CERT_FILE` to a PEM bundle with the proxy's CA) and commit. Panels that use it show "Panel plugin not found" if it is missing; changing their `type` back to `state-timeline` restores the core panel (without the plugin's field options).

Secrets never go into Prometheus, Alertmanager, blackbox, or exporter configuration files. Exporters that accept an API key in their environment (exportarr) receive it from the existing Komodo variables. qBittorrent is read through `json-exporter` with its API key rather than a dedicated exporter: the released prometheus-qbittorrent-exporter `1.7.0` ignores the API key and logs in with an empty password, which makes qBittorrent ban the exporter's address. `json-exporter` reads its keys from Compose secrets fed by Komodo variables (`secrets.<name>.environment` in `stacks/monitoring/compose.yaml`), mounted under `/run/secrets`, and uses them only through `*_file` or header `files` settings in `stacks/monitoring/json/json.yml`; because of those secrets it runs without a read-only root filesystem. The validator counts secret environment variables as Compose inputs.

`KOMODO_MONITORING_API_KEY` and `KOMODO_MONITORING_API_SECRET` belong to a dedicated Komodo service user (User level, not admin) with Read on stacks, the server `atlas`, all Actions, all Procedures, and the Resource Sync `pjan/atlas`; they let `json-exporter` report every stack's and container's state, the control plane, and Komodo's updates and alerts without the Docker socket. Read returns a resource's configuration unredacted (for example webhook secrets and Action scripts); pjan accepts that on this personal server. Read on a stack includes its deployed `docker compose config`, in which Komodo redacts only values from variables marked secret, so every secret-bearing variable must be marked secret (see Required Non-Default Variables). Never grant this user Inspect, Logs, Processes, or Terminal: container inspect returns the environment. The Gluetun control key used for the VPN metrics is the shared `GLUETUN_CONTROL_API_KEY`, whose default role can also change the VPN state; a GET-only role for monitoring is optional hardening. Exporters that accept environment variables receive keys from Komodo variables; services that read secret files use `/run/secrets`.

`GRAFANA_SECRET_KEY` (`[security] secret_key`) encrypts Grafana's legacy secrets, such as contact point settings. `GRAFANA_SECRETS_MANAGER_KEY` (`[secrets_manager.encryption.secret_key.v1]`) encrypts secrets stored through Grafana's secrets manager, including the Git Sync token; its built-in default is public. Set both before storing any secret, keep them in the password manager, and never change them afterwards. `GRAFANA_ADMIN_PASSWORD` only applies on first start; change the password in Grafana later.

## Alerts

Prometheus evaluates the alert rules in `stacks/monitoring/prometheus/rules/`, and Alertmanager (`prom/alertmanager`, in the `monitoring` stack) sends them to the Discord channel `#atlas-alerts` as rich embeds. A Watchdog heartbeat to Healthchecks.io proves that the whole path works. Every check also has a red, amber, or green tile on the Grafana dashboard **Atlas Critical Health** (`pjan/atlas-dashboards`).

### How Alerting Works

```text
exporters, textfiles ─► Prometheus ─► rules (label check=…) ─► Alertmanager ─► templated webhook ─► Discord #atlas-alerts
                              │                                      └──────► Watchdog webhook ─► Healthchecks.io ─► Discord + email
                              └─► recording rules: atlas:check_status, atlas:maintenance ─► Grafana "Atlas Critical Health"
```

| Failure | Detected by |
|---|---|
| A check turns bad | its rule, then a Discord message and a red or amber tile |
| Prometheus, Alertmanager, the NAS, or the internet down | the Watchdog stops, then Healthchecks.io sends Discord and email |
| Discord delivery failing (bad webhook URL, rejected message, rate limit) | `AlertDeliveryFailing` (red tile), and the Watchdog stops, so Healthchecks.io sends email |

- Prometheus reloads the rule files together with `prometheus.yml`. Alertmanager's `stacks/monitoring/alertmanager/alertmanager.yml` and `atlas.tmpl` apply on the next `monitoring` deploy, whose `post_deploy` sends `SIGHUP`. An invalid file keeps the previous configuration and raises `ConfigReloadFailed`.
- Alerts are grouped by `alertname`: a group is sent 30 seconds after its first alert and at most every 5 minutes after that. Resolutions are sent too. Warnings repeat every 12 hours and criticals every 4 hours. Both go to the same channel, without mentions.
- The Discord webhook URL (`DISCORD_ALERTS_WEBHOOK_URL`) and the Healthchecks.io ping URL (`HEALTHCHECKS_WATCHDOG_PING_URL`) reach Alertmanager as Compose secrets (`url_file`), so Alertmanager runs without a read-only root filesystem, like `json-exporter`. Alertmanager has no host port and no route; its API is unauthenticated inside `monitoring_network`. Silences and the notification log live in `/volume2/appdata/alertmanager`, which is not backed up.
- A root cause suppresses the Discord messages of the alerts it causes (`inhibit_rules` in `alertmanager.yml`): `CaddyDown` suppresses `ProbeFailed` (except `plex-direct`, which does not go through Caddy); `VpnDown` suppresses `ProbeFailed` for the applications in Gluetun's network namespace and `PortForwardMismatch`; `VolumeSpaceCritical` suppresses `VolumeSpaceLow` for the same volume. The suppressed alerts' tiles still turn red or amber.
- Silence an alert from the NAS (the Atlas Critical Health header counts active silences):

  ```sh
  docker exec alertmanager amtool --alertmanager.url=http://127.0.0.1:9093 \
    silence add alertname=MonitoringTargetDown --duration=2h --comment="Grafana upgrade"
  docker exec alertmanager amtool --alertmanager.url=http://127.0.0.1:9093 silence query
  docker exec alertmanager amtool --alertmanager.url=http://127.0.0.1:9093 silence expire <id>
  ```

### Discord Messages

Every alert is one embed: the title `“<title>” is FIRING.` (red for critical, orange for warning, like the dashboard's CRIT and WARN) or `… is RESOLVED.` (green) links to its dashboard, followed by the description, the fields Severity, Since, Source, and Target (and Resolved and Duration when resolved), Details as a code block, Links, and the footer `Atlas · <source> · alert i/N`. The webhook's own name and avatar are used, and `allowed_mentions` is empty, so `@everyone` in alert text never pings.

Discord rejects a message over 6,000 characters, and Alertmanager does not retry a rejected (400) or rate-limited (429) notification, so it would be lost. `atlas.tmpl` therefore sends at most 4 embeds per message (the footer's `N` shows any others) and caps every value: title 100 characters, description 250, severity and source 20, target 80, details 350 plus the code fence; a capped value ends in `…`. Links are added in the order Open, Dashboard, Runbook while they fit in 300 characters, so a link is left out whole rather than cut. The validator renders every fixture in `stacks/monitoring/alertmanager-tests/` (firing, resolved, 7 grouped alerts, maximum length, hostile text) with the pinned `amtool` and checks Discord's limits and this budget.

### Alert Contract

Every alert rule carries these labels and annotations; `scripts/validate-repository.py` enforces them.

| Key | Kind | Content |
|---|---|---|
| `alertname` | name | CamelCase |
| `check` | label | the RAG unit, `<area>.<name>`, for example `meta.test` |
| `severity` | label | `critical` (data at risk, or a core service down) or `warning` (degraded) |
| `source` | label | `prometheus`, `backrest`, or `komodo` |
| `title` | annotation | short name, for example `Monitoring target down · grafana` (at most 85 characters) |
| `description` | annotation | what is wrong and the first action (at most 250 characters) |
| `target` | annotation | optional: what is affected (at most 80 characters; falls back to `instance`) |
| `details` | annotation | optional: a value, error text, or labels, shown as a code block (at most 350 characters) |
| `link`, `dashboard`, `runbook` | annotations | optional: the application (LAN); Grafana on `https://grafana.atlas.vandaele.io/` (also the title link); a heading of this README on `https://github.com/pjan/atlas#…` |

The Watchdog is the only alert without `check` and `severity`. Rules must not produce series labels named `check`, `severity`, `source`, or `title`; rename them in the expression first, for example `label_replace(..., "issue_source", "$1", "source", "(.*)")`.

Each check has at most one warning rule and at most one critical rule (the validator counts rules), so a tile maps to one cause per severity. To add an alert: add the rule, add its check to the `atlas:check_catalogue` list in `rules/rag.yml` (the validator requires the catalogue to equal the set of checks), add promtool cases in `stacks/monitoring/prometheus-tests/` in which it fires and in which it stays quiet, including one where `atlas:check_status{check="…"}` turns 1 or 2, and add or extend its runbook below. Rules affected by stopped stacks (probes, stack health, the port forward, qBittorrent) are gated: append `unless on () atlas:maintenance == 1` to the expression.

### Atlas Critical Health

`atlas:check_status` is `0` (green), `1` (amber: a warning fires), or `2` (red: a critical alert fires) per check, derived from Prometheus' `ALERTS` series; `atlas:check_catalogue` keeps healthy checks at `0`. The dashboard shows a status grid with one tile per check (no data is grey UNKNOWN), a RAG timeline over the selected time range, the firing alerts, and a header with "Backup running", active silences, the delivery status, and the number of firing alerts. The appdata backup appears as a region, and firing alerts as annotations.

- A tile is the Prometheus alert state. Pending alerts (still within their `for`) do not count, so a tile and a Discord message agree.
- Inhibited alerts still show red, because their root cause is red too.
- Silenced alerts still show red; the header counts active silences.
- During the appdata backup the maintenance gate keeps both the gated tiles and Discord quiet, and the header shows "Backup running".

### Maintenance Gate

The nightly appdata backup stops most stacks, which would otherwise fire every probe. `atlas:maintenance` in `rules/rag.yml` is `1` while that happens, derived from the backup's own metrics: `backup.sh check` runs before any stack is stopped and writes `atlas_backup_last_run_timestamp_seconds{set="appdata", mode="check"}`, and `backup.sh run` writes the same metric with `mode="run"` after the snapshot; only the latest mode is in the file.

- The gate is on from `check` until `run`, for at most 60 minutes, and for 15 minutes after `run` while the stacks start again.
- A backup that fails after `check` is gated for at most 60 minutes. The backup's own alerts are never gated, so the failure still alerts.
- The gate follows the real backup, including one run by hand, so it cannot drift from the Action's schedule or `TZ`.

### Healthchecks Watchdog

The `Watchdog` alert always fires while Prometheus and Alertmanager work, and Alertmanager sends it to Healthchecks.io every 5 minutes (never its resolution). It stops while Discord delivery fails. Healthchecks.io then alerts when Atlas, its internet connection, Prometheus, Alertmanager, or Discord delivery is broken, which no local rule can report.

Set it up once in Healthchecks.io:

1. Create the check "Atlas alerting" with period 5 minutes and grace 10 minutes, so 15 minutes without a ping raises it, the same window as `atlas:delivery_failing`.
2. Description: "Watchdog from Atlas Alertmanager. Down means Atlas, its internet connection, Prometheus, Alertmanager, or Discord delivery is broken."
3. Enable the Discord integration **and** email for this check: email still arrives when Discord is the problem.
4. Store the check's ping URL in the secret Komodo variable `HEALTHCHECKS_WATCHDOG_PING_URL`, then deploy `monitoring` (a changed variable value alone does not redeploy the stack).

To test it, stop the `alertmanager` container for 20 minutes: Healthchecks.io sends Discord and email after about 15 minutes, and starting it again recovers the check.

The Healthchecks.io checks for the appdata and off-site backups, and Backrest's Discord hook, stay until the local backup alerts have proven themselves over two green nights (the Atlas Critical Health tiles `backup.*` stayed green and the metrics files were updated). Then retire them:

1. In Backrest, delete the Healthchecks hooks of the plan `atlas-volume1-backups` and the Discord hook of the repository `gdrive-atlas-backups`; keep the pre-check and the metrics hook.
2. Remove the Healthchecks ping (`HEALTHCHECK_URL`) from the `appdata-backup` Action in `stacks.toml`, and the variable `HEALTHCHECKS_APPDATA_PING_URL` from `stacks.toml`, the validator's inventory, and this README; then run Resource Sync and delete the variable in Komodo.
3. Delete the appdata and off-site checks in Healthchecks.io. Only "Atlas alerting" remains.

### Runbooks

#### Alert Delivery

`AlertDeliveryFailing` (`meta.delivery`, critical): Alertmanager could not deliver at least one Discord notification in the last 15 minutes (`atlas:delivery_failing`, from `alertmanager_notifications_failed_total{receiver_name="discord"}`). A notification rejected with 400 or 429 is not retried, so that message is lost; check Atlas Critical Health for what fired.

1. Read the reason in `docker logs alertmanager` (status code and response).
2. 401 or 404: the webhook was deleted or `DISCORD_ALERTS_WEBHOOK_URL` is wrong. Create a new webhook in `#atlas-alerts`, update the variable, and deploy `monitoring`.
3. 400: Discord rejected the message; render the fixtures with `./scripts/validate.sh` and check the template or the alert text that broke it.
4. 429: rate limited; it clears by itself.

The alert clears 15 minutes after the last failure. To test it, set `DISCORD_ALERTS_WEBHOOK_URL` to a wrong webhook URL, deploy `monitoring`, and raise the [test alert](#test-alert): `meta.delivery` turns red within a few minutes, the Watchdog stops, and Healthchecks.io emails about 15 minutes after the last ping. Restore the variable and deploy again.

#### Monitoring Targets

`MonitoringTargetDown` (`meta.targets`, warning): Prometheus has not scraped a monitoring target (`node`, `smartctl`, `blackbox`, `json_exporter`, `cadvisor`, `alertmanager`, or `grafana`) for 10 minutes, so the alerts built on it cannot fire. Check the container in the `monitoring` stack in Komodo and its logs, and redeploy the stack if it does not recover.

#### Config Reloads

`ConfigReloadFailed` (`meta.reloads`, warning): Prometheus, Alertmanager, blackbox-exporter, or Caddy rejected a new configuration for 5 minutes and still runs the previous one. Find the error in the container's logs, fix the file in this repository (`./scripts/validate.sh` checks all of them), push, and deploy; the next successful reload clears the alert.

#### Test Alert

`AtlasTestAlert` (`meta.test`, warning) fires while `/volume1/backups/.metrics/atlas_test.prom` contains `atlas_test_alert 1`. Use it to test alerting end to end. Raise it as root on the NAS (write a temporary file, make it readable for node-exporter, which runs as `65534`, and rename it, so node-exporter never reads a partial file):

```sh
printf '%s\n' '# HELP atlas_test_alert Set to 1 by hand to test alerting.' '# TYPE atlas_test_alert gauge' 'atlas_test_alert 1' > /volume1/backups/.metrics/atlas_test.prom.tmp
chmod 0644 /volume1/backups/.metrics/atlas_test.prom.tmp
mv /volume1/backups/.metrics/atlas_test.prom.tmp /volume1/backups/.metrics/atlas_test.prom
```

Within about 2 minutes `meta.test` turns amber and a FIRING message arrives in `#atlas-alerts`. Clear it, also as root:

```sh
rm /volume1/backups/.metrics/atlas_test.prom
```

The tile turns green within 2 minutes, and the RESOLVED message follows within 5 more minutes. The RAG timeline on Atlas Critical Health shows the episode.

#### Appdata Backup

`AppdataBackupFailed` (`backup.appdata`, critical): the last `backup.sh` run exited non-zero (`atlas_backup_last_exit_code{set="appdata"}`), in `check` (the source looked incomplete; nothing was stopped) or in `run` (the snapshot failed). It stays until the next successful run. `AppdataBackupStale` (`backup.appdata-age`, critical): no snapshot has succeeded for 26 hours, or `atlas_backups.prom` is missing, for example because the Action no longer runs or failed before `backup.sh`. Failure and staleness are separate checks, so each tile has one critical cause.

1. Read the last `appdata-backup` run in Komodo (Actions) and the `appdata-backup:` lines in its log.
2. Make sure every stack it stopped runs again; `APPDATA_BACKUP_STOPPED_STACKS` lists the ones an interrupted run left stopped.
3. Fix the cause, then run `appdata-backup` in Komodo. The alerts resolve when `atlas_backups.prom` shows exit code 0 and a new success time.

Neither alert is gated. To test `AppdataBackupStale` without touching the backup (the off-site pre-check reads `.last-success`), give the metrics file an old success time as root on the NAS, and restore it afterwards (the next backup rewrites it anyway):

```sh
cd /volume1/backups/.metrics
cp atlas_backups.prom /tmp/atlas_backups.prom.saved
sed 's/^\(atlas_backup_last_success_timestamp_seconds{set="appdata"}\) .*/\1 1/' atlas_backups.prom > atlas_backups.prom.tmp
chmod 0644 atlas_backups.prom.tmp && mv atlas_backups.prom.tmp atlas_backups.prom
# About 16 minutes later: backup.appdata-age is red and a FIRING message arrived.
cp /tmp/atlas_backups.prom.saved atlas_backups.prom.tmp && mv atlas_backups.prom.tmp atlas_backups.prom
```

#### Off-Site Backup

`OffsiteBackupFailed` (`backup.offsite`, critical): the last snapshot of the Backrest plan `atlas-volume1-backups` failed (exit code 1), including a failed pre-check; Details show Backrest's error text. `OffsiteBackupPartial` (`backup.offsite`, warning): the snapshot was written, but restic could not read some files (exit code 3). `OffsiteBackupStale` (`backup.offsite-age`, critical): no snapshot has succeeded for 30 hours (the plan runs daily at 06:00), or `atlas_offsite.prom` is missing (the [metrics hook](#off-site-backup-metrics) was removed or never ran). The values come from the plan's metrics hook.

1. Open the plan's last operation in Backrest (`https://backrest.atlas.vandaele.io`) and read its log.
2. A pre-check failure means the appdata snapshot was not complete and recent: fix the [appdata backup](#appdata-backup) first.
3. For unreadable files (partial), fix their permissions or exclude them in the plan.
4. Run the plan with **Backup now**. The alerts resolve with the next successful snapshot.

#### Disk Health

`DiskFailing` (`disk.health`, critical), one alert per disk and reason: SMART health failed, an NVMe critical warning, NVMe spare at or below its threshold, new NVMe media errors (within a day), or new btrfs device errors (within an hour). Both data volumes are single-member RAID 1, so there is no redundancy. The disks are named as on Atlas Health; a btrfs device keeps its kernel name. `SmartDataMissing` (`disk.health`, warning): smartctl-exporter has reported fewer than 3 disks for 30 minutes, so a failing disk would go unnoticed.

1. Check the Disks and Storage rows on Atlas Health and `smartctl -a` for the disk.
2. Make sure the appdata and off-site backups are current, and plan the replacement.
3. btrfs error counters persist on the device; after dealing with the cause, reset them with `btrfs device stats -z /volume1`. The alert resolves by itself after an hour (a day for media errors), so the dashboards keep the totals.

#### Volume Space

`VolumeSpaceLow` (`storage.space`, warning): `/volume1` or `/volume2` has had less than 10 % free space for 30 minutes. `VolumeSpaceCritical` (`storage.space`, critical): less than 5 % for 5 minutes; it suppresses the warning for the same volume. Find what grew on Atlas Health (Storage row: growth over 7 days, days to full) and clean up: downloads, old snapshots, the Docker build cache (`/volume2`).

#### Caddy

`CaddyDown` (`services.caddy`, critical): for 3 minutes, Caddy's metrics endpoint (`caddy:2020`) or its LAN port (`192.168.2.200:80`) has not answered, or its HTTPS listener (`192.168.2.200:443`, job `probe_tls_caddy`) has not completed a TLS handshake with a valid certificate. All are checked without DNS. Every `https://<app>.atlas.vandaele.io` route, the tunnel's public routes (unless only the certificate failed), and every probe except `plex-direct` and `authentik` depend on it, so it suppresses `ProbeFailed`. A certificate failure also breaks Grafana's authentik login (see [Grafana Login](#grafana-login)); see `CaddyCertificateExpiring` below for the cause. Check the `caddy` stack and its logs in Komodo, validate the configuration with `./scripts/validate.sh`, and redeploy it. Gated during the appdata backup.

`CaddyCertificateExpiring` (`services.caddy`, warning): for 30 minutes, the `*.atlas.vandaele.io` certificate on `192.168.2.200:443` has had less than 10 days left. Caddy renews with a third of the lifetime left, so renewals through the Cloudflare DNS challenge have been failing for days. Check the `caddy` logs for `tls.obtain` errors and `CLOUDFLARE_DNS_API_TOKEN` in Komodo (see [Caddy Configuration](#caddy-configuration)), then redeploy `caddy`. The tunnel on `:8080` does not use the certificate. Gated during the appdata backup.

#### Application Probes

`ProbeFailed` (`services.apps`): for 5 minutes, an application's health endpoint (job `probe_health`, through Caddy on the LAN), its public route through Cloudflare and the tunnel (job `probe_routes_public`, service `<app>-public`), or its authentik gate (job `probe_gate`, services `<app>-gate` and `<app>-gate-public`) has failed. Warning for every application; critical for Plex (`plex` through Caddy, `plex-direct` on port 32400) and authentik (`authentik`, `authentik-public`), which locks every app behind forward auth; `ProbeFailed` for `authentik` suppresses the alerts of those apps. A failing `<app>-gate` means the app answers without the authentik login: check its Caddy site and provider at once (see [Forward Auth](#forward-auth)). Caddy's own probe is covered by [`CaddyDown`](#caddy). `authentik` probes its server directly. [`TunnelDown`](#cloudflare-tunnel) suppresses every `<app>-public` alert, and [`VpnDown`](#vpn) those of the VPN-bound applications. A failing `<app>-public` alone means its tunnel route or its Cloudflare DNS record no longer reaches Caddy (see [Cloudflared](#cloudflared)). The link opens the application.

1. Check the stack and its logs in Komodo, and redeploy it if it does not recover.
2. If many probes fail at once, check Caddy, Atlas DNS (`*.atlas.vandaele.io` from UniFi, `probe_dns_split`), and, for the VPN-bound applications, [the VPN](#vpn).

Gated during the appdata backup, which stops these stacks. To test it, stop `sonarr` in Komodo outside the backup: one FIRING message after about 5 minutes and `services.apps` amber, then RESOLVED after starting it again.

#### Cloudflare Tunnel

`TunnelDown` (`services.tunnel`, critical): cloudflared has had no connection to Cloudflare (`cloudflared_tunnel_ha_connections`) for 5 minutes, or its metrics are missing, so the public `*.atlas.vandaele.io` hostnames are down. The LAN is not affected. Check the `cloudflared` stack and its logs in Komodo (token, outbound internet) and redeploy it. Not gated: cloudflared is never stopped.

#### VPN

`VpnDown` (`downloads.vpn`, critical): Gluetun has not reported its VPN as `running` for 5 minutes. It also fires when the Gluetun control server or json-exporter cannot be read, which leaves the VPN state unknown; Details say which. The applications in Gluetun's network namespace (autobrr, bazarr, flaresolverr, lidarr, prowlarr, qbittorrent, radarr, sabnzbd, slskd, sonarr, spottarr) are offline, so it suppresses their `ProbeFailed` and `PortForwardMismatch`. Check the `gluetun` logs in Komodo (WireGuard key, server selection); after restarting gluetun, redeploy the VPN-bound stacks so they join its new network namespace. Not gated: gluetun is never stopped.

#### Port Forward

`PortForwardMismatch` (`downloads.port-forward`, warning): for 15 minutes, qBittorrent has not listened on the port Gluetun forwards, or Gluetun has no forwarded port; Details show both. Torrents are then firewalled. Check the port forwarding lines in the `gluetun` logs and `docker exec gluetun cat /tmp/gluetun/forwarded_port`; set that port in qBittorrent (Settings, Connection) or reconnect the VPN. Gated during the appdata backup, which stops qBittorrent.

#### Stack Health

`StackUnhealthy` (`stacks.health`, warning): Komodo has reported a stack in a state other than `running` or `down` (not deployed, for example `appdata-backup`) for 15 minutes, for example `unhealthy` (mixed container states), `stopped`, `restarting`, `paused`, or `unknown` (Komodo cannot reach Periphery; then every stack fires at once). Open the stack in Komodo, check its containers and logs, and deploy it again. Gated during the appdata backup, which stops most stacks.

#### Container Health

`ContainerUnhealthy` (`containers.health`, warning): Docker has reported a running container as `unhealthy` (its healthcheck fails) for 10 minutes. Komodo's stack state ignores Docker health, so `StackUnhealthy` does not cover this, and Docker never restarts an unhealthy container itself. Read the container's logs and its healthcheck in Komodo, fix the cause, and restart or redeploy the stack. Gated during the appdata backup.

#### Container Crash Loop

`ContainerCrashLooping` (`containers.crashloop`, warning): for 5 minutes, a container was in Docker's `restarting` state at some point in the last 10 minutes, or restarted unexpectedly 3 or more times in 15 minutes (`atlas:container_restarted_unexpectedly`: not within 10 minutes after a Komodo operation on its stack, not during the backup, not after a NAS boot). It inhibits `StackUnhealthy` for the same stack. Read the container's logs in Komodo (the last lines before each exit), fix the cause, and deploy the stack again. Gated during the appdata backup.

#### Container OOM Kill

`ContainerOOMKilled` (`containers.oom`, warning): the kernel killed a process for lack of memory in the last 15 minutes (node-exporter `node_vmstat_oom_kill`, which also counts kills at a container's `mem_limit`). It counts kills on the whole NAS and cannot name the container; the OOM column of the Containers table on Atlas Containers does, from cAdvisor, unless the container was removed. Raise the container's `mem_limit` in its `compose.yaml` or find its leak. It resolves 15 minutes after the last kill. Not gated.

## Caddy Configuration

Caddy config is stored declaratively in the repository:

```text
stacks/caddy/Dockerfile
stacks/caddy/conf/Caddyfile
stacks/caddy/conf/sites/*.caddy
```

Caddy listens on three ports:

- `80` (LAN): redirects only, `http://<app>.atlas.local` and `http://<app>.atlas.vandaele.io` to `https://<app>.atlas.vandaele.io`.
- `443` (LAN and Tailscale): `https://*.atlas.vandaele.io`, with one Let's Encrypt wildcard certificate. HTTP/1.1 and HTTP/2 only; UDP `443` is not published.
- `8080` (Docker networks only): the Cloudflare Tunnel's origin (see [Cloudflared](#cloudflared)).

The image is `atlas-caddy:local`, built from `stacks/caddy/Dockerfile` (the official image plus the [caddy-dns/cloudflare](https://github.com/caddy-dns/cloudflare) module) by the `caddy` stack's `pre_deploy`; Komodo never pulls it. A change to the Dockerfile redeploys the stack. Renovate updates both base images and the module, and never automerges them.

The wildcard site `*.atlas.vandaele.io` in the `Caddyfile` owns the certificate; every site on `443` uses it, and Caddy obtains no per-hostname certificates. Caddy obtains and renews it with a DNS challenge through the Cloudflare API, checking the challenge record against public resolvers (`1.1.1.1`), so Atlas' own DNS for `*.atlas.vandaele.io` cannot hide it. Renewal is automatic; [`CaddyCertificateExpiring`](#caddy) warns when it fails. Certificates live in the `caddy-data` Docker volume; losing it only means a new certificate.

Komodo variable (secret):

```text
CLOUDFLARE_DNS_API_TOKEN   Cloudflare API token: Zone > Zone > Read and Zone > DNS > Edit, zone vandaele.io only, no expiry
```

The token can edit every DNS record in `vandaele.io`; Cloudflare cannot scope it to one subdomain. The `pre_deploy` checks its format in the `.env` file Komodo writes, without printing it, and stops before Caddy is recreated if it is missing or malformed: Caddy would otherwise load no site at all and log the token. The build and `caddy validate` use a well-formed dummy token. To check a new token without leaving it in the shell history:

```sh
read -rs CF && curl -s -H "Authorization: Bearer $CF" \
  https://api.cloudflare.com/client/v4/user/tokens/verify | jq '.success'; unset CF
```

The root `Caddyfile` imports all site files:

```caddyfile
import sites/*.caddy
```

`caddy.atlas.vandaele.io` (on `443` and `8080`) returns a static `200 ok` health response. They do not proxy or expose Caddy's admin API.

To add a new app route:

1. Add a new file under `stacks/caddy/conf/sites/`.
2. Add the file to the Caddy stack `config_files` list in `stacks.toml`.
3. Ensure the app container joins `proxy_network`, or proxy to `host.docker.internal` for host services.
4. Push to `main`, execute Resource Sync, then explicitly deploy or redeploy `caddy` so the `post_deploy` reload hook applies the live config.

Most application UIs are exposed only through Caddy, at `https://<app>.atlas.vandaele.io`. The validator requires every route to be served on `443` and, except LAN-only routes, on the tunnel listener `8080`, and rejects `*.atlas.local` and port-80 addresses in site files. Public hostnames must be protected by appropriate Cloudflare Access policies. Every route is either behind authentik forward auth or listed as ungated (see [Forward Auth](#forward-auth)). Routes listed in `LOCAL_ONLY_CADDY_ROUTES` in `scripts/validate-repository.py` (currently `backrest` and `komodo`) are LAN-only: they use the `atlas_lan_proxy` snippet, are not on `8080`, and must not get a tunnel route or a public DNS record. Plex is the direct-port exception and still publishes `192.168.2.200:32400/tcp` for native client discovery and direct access.

Validation note:

- Caddy imports all site files on every validation run.

Example app route:

```caddyfile
import atlas_reverse_proxy example example:1234
```

Example host-service route:

```caddyfile
import atlas_reverse_proxy hostapp host.docker.internal:1234
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

The suite renders every managed stack and the manual Komodo bootstrap with deterministic validation values, validates Caddy with the pinned image, exercises the host-filesystem and network helpers, and checks repository policy. Policy checks cover stack/run-directory consistency, declared files, Caddy site registration, relative bind configuration, fail-closed bind mounts, pinned image tags, security/resource/logging controls, shell syntax, Komodo interpolation tags, tracked runtime secrets or OS metadata, and the alerting rules: the alert contract, the check catalogue, promtool coverage of every check, runbook anchors, and the Discord message fixtures rendered with the pinned `amtool` (see [Alerts](#alerts)). The alerting YAML files are read with the pinned `mikefarah/yq` image (`YQ_IMAGE` in the validator).

GitHub Actions runs the same command for pull requests and pushes to `main`. Workflow actions are pinned by commit SHA, and CI receives read-only repository permissions.
