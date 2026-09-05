# Atlas

Repository holding the configuration of all my Docker Compose stacks for my NAS, deployed with [Komodo](https://komo.do/), updated with [Renovate](https://docs.renovatebot.com/).

## Environment

This repository manages Docker Compose stacks for the `Atlas` NAS.

- NAS: UGREEN DXP4800 Pro
- NAS LAN IP: `192.168.2.200`
- NAS checkout/bootstrap directory: `/volume2/docker/komodo`
- Komodo Core URL: `http://192.168.2.200:9120`
- Caddy HTTP entrypoint: `http://192.168.2.200:80`
- Local DNS zone: `*.atlas.local`

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
ssh root@192.168.2.200
cd /volume2/docker/komodo
```

Copy the contents of this repository’s `komodo/` directory into `/volume2/docker/komodo`, then copy `.env.example` to `.env` and edit `/volume2/docker/komodo/.env`.

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
PERIPHERY_ROOT_DIRECTORY=/volume2/docker/komodo
```

`PERIPHERY_ROOT_DIRECTORY` must match the real checkout path on the NAS so Periphery can see the repo and stack files under the same path inside and outside the container.

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
- `COMPOSE_KOMODO_BACKUPS_PATH` should point at a persistent NAS path that already exists or can be created by Docker.

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

## Deploying Stack Changes

After pushing changes to `main`:

1. Open Komodo.
2. Wait for the `atlas` Resource Sync to show pending changes.
3. Review the diff.
4. Execute the sync.

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
PROTONVPN_WIREGUARD_PRIVATE_KEY
GLUETUN_CONTROL_API_KEY
SPEEDTEST_TRACKER_APP_KEY
CLOUDFLARED_TUNNEL_TOKEN
HOMEPAGE_ADGUARD_USERNAME
HOMEPAGE_ADGUARD_PASSWORD
HOMEPAGE_KOMODO_API_KEY
HOMEPAGE_KOMODO_API_SECRET
HOMEPAGE_LIDARR_API_KEY
HOMEPAGE_PLEX_TOKEN
HOMEPAGE_PROWLARR_API_KEY
HOMEPAGE_QBITTORRENT_API_KEY
HOMEPAGE_RADARR_API_KEY
HOMEPAGE_SEERR_API_KEY
HOMEPAGE_SONARR_API_KEY
HOMEPAGE_SPEEDTEST_TRACKER_API_KEY
RECYCLARR_SONARR_API_KEY
RECYCLARR_RADARR_API_KEY
SPOTTARR_USENET_HOSTNAME
SPOTTARR_USENET_USERNAME
SPOTTARR_USENET_PASSWORD
SPOTTARR_NEWZNAB_API_KEY
```

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
HOMEPAGE_PLEX_TOKEN
```

Then redeploy `homepage` so the updated environment variable is injected into the container.

Notes:

- This only works after Plex has been successfully claimed and signed in to your Plex account.
- If the command returns nothing, first confirm Plex is claimed and the server is visible in your Plex account.
- Plex documents a browser-based way to obtain an `X-Plex-Token` from the Plex Web App XML view. The `Preferences.xml` method above is the more direct Atlas-specific approach for the Homepage variable.
- If you reset your Plex password and sign out connected devices, Plex tokens can be invalidated. If the Homepage Plex widget stops working after an account security change, fetch the token again and update `HOMEPAGE_PLEX_TOKEN`.

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
- Seerr relies on its own auth plus Plex auth. There is no Caddy Basic Auth gate in the baseline LAN/Tailscale deployment.
- The container runs as UID/GID `1000:1000`. The pre-deploy step creates `[[APPDATA_DIR]]/seerr/logs` and recursively repairs ownership so `/app/config` stays writable after first deploys or migrations.
- `[[APPDATA_DIR]]/seerr` should be backed up with its ownership and permissions preserved.
- If Seerr is ever exposed beyond LAN/Tailscale, revisit TLS, SSO, and proxy-layer auth before doing so.

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
- Keep `/volume2/appdata/bazarr` private because it contains provider credentials and app tokens.

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
API key: SPOTTARR_NEWZNAB_API_KEY
```

Operational notes:

- This stack does not expose a direct host port. Access is Caddy-only through `http://spottarr.atlas.local`.
- Spottarr stores its SQLite data in `/volume2/appdata/spottarr`, mounted at `/data`.
- The container is not a LinuxServer image. It runs with Compose `user: "999:10"` rather than LSIO `PUID`/`PGID` environment variables.
- Keep `/volume2/appdata/spottarr` private because it contains index state and may reveal Usenet-backed search behavior.
- Coordinate `SPOTTARR_USENET_MAXCONNECTIONS` with SABnzbd and provider limits.
- Start with the default `SPOTTARR_SPOTNET_RETRIEVEAFTER=2026-01-01T00:00:00Z`; moving earlier increases first-import time, storage, memory pressure, and Usenet request volume.

### Recyclarr

The `recyclarr` stack runs Recyclarr as a background TRaSH Guides sync worker for Sonarr and Radarr. It has no web UI, no Caddy route, and no direct host ports.

Recyclarr reaches the VPN-bound Arr services through Gluetun's `downloaders-vpn` alias:

```text
Sonarr URL: http://downloaders-vpn:8989
Radarr URL: http://downloaders-vpn:7878
```

Before deploying, create these Komodo variables from the Sonarr and Radarr API keys:

```text
RECYCLARR_SONARR_API_KEY
RECYCLARR_RADARR_API_KEY
```

The repo-managed Recyclarr config lives at:

```text
stacks/recyclarr/config/configs/atlas.yml
```

Runtime state is stored in `/volume2/appdata/recyclarr`, and disposable logs/resources are stored in `/volume2/tmp/recyclarr`. Keep `/volume2/appdata/recyclarr` private because it contains sync state and may contain future local secrets if the stack is changed to use `secrets.yml`.

Deploy order:

1. Create `RECYCLARR_SONARR_API_KEY` and `RECYCLARR_RADARR_API_KEY`.
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
- If Recyclarr reports `Access to the path '/config/state' is denied`, redeploy the stack so the pre-deploy ownership repair runs. For immediate recovery on Atlas, run `chown -R 1000:1000 /volume2/appdata/recyclarr /volume2/tmp/recyclarr && chmod -R u+rwX,go-rwx /volume2/appdata/recyclarr /volume2/tmp/recyclarr && chmod 0755 /volume2/appdata/recyclarr/configs`, then recreate the Recyclarr container.
- There is no useful HTTP health endpoint. Monitor the container/process if useful, but treat preview output, sync logs, and last-success alerting as the real operational signals.

### Gluetun, qBittorrent, And SABnzbd

qBittorrent and SABnzbd are split from Gluetun so the VPN container can be reused by all VPN-bound media stacks. Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, FlareSolverr, and Spottarr now share that same Gluetun network namespace.

In Docker terms, qBittorrent, SABnzbd, Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, FlareSolverr, and Spottarr do not join `media_network` or `proxy_network` directly. They use `network_mode: "container:gluetun"`, and Caddy or other non-VPN containers reach the routed services through Gluetun's `downloaders-vpn` network alias.

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
3. Deploy or redeploy `sabnzbd`.
4. Deploy or redeploy `flaresolverr`.
5. Deploy or redeploy `sonarr`.
6. Deploy or redeploy `radarr`.
7. Deploy or redeploy `lidarr`.
8. Deploy or redeploy `prowlarr`.
9. Deploy or redeploy `bazarr`.
10. Deploy or redeploy `spottarr`.
11. Deploy or redeploy `homepage`.
12. Deploy or redeploy `recyclarr`.
13. Deploy or redeploy `caddy`.

If Gluetun is recreated, every container sharing its network namespace must be recreated, not merely restarted, so it reattaches to the current namespace. That includes qBittorrent, SABnzbd, Sonarr, Radarr, Lidarr, Prowlarr, Bazarr, FlareSolverr, and Spottarr. The repo encodes this with `after = ["gluetun"]`-style dependencies and `extra_args = ["--force-recreate"]` on each VPN-bound stack.

Komodo `after = ["gluetun"]` affects dependency ordering during Resource Sync deploys. If Gluetun is deployed manually outside a dependency-aware sync/procedure, explicitly redeploy all VPN-bound stacks afterwards; their `--force-recreate` deploy args handle the required namespace reattachment.

qBittorrent and SABnzbd are available at:

```text
http://qbittorrent.atlas.local
http://sabnzbd.atlas.local
```

There are no direct qBittorrent or SABnzbd host UI ports. Keep UI access Caddy-only unless an emergency LAN-bound port is deliberately added to the Gluetun stack.

On first startup, LinuxServer qBittorrent prints the temporary admin password in the container logs. Log in, change the password, then configure these paths:

```text
Incomplete torrents: /data/downloads/torrents/incomplete
Completed torrents: /data/downloads/torrents/completed
TV category: /data/downloads/torrents/completed/tv
Movies category: /data/downloads/torrents/completed/movies
Music category: /data/downloads/torrents/completed/music
```

Configure Sonarr, Radarr, and Lidarr download clients to use:

```text
Host: 127.0.0.1
Port: 8080
```

SABnzbd uses port `8085` inside Gluetun's shared network namespace because qBittorrent already uses `8080`. The repo-managed LinuxServer custom init script patches SABnzbd's service runner before startup so the web UI binds `0.0.0.0:8085`. Treat `SABNZBD_PORT=8085` and the custom init script as the source of truth for the internal listening port.

On first startup, configure SABnzbd through Caddy and keep `External internet access` disabled or limited. Configure these paths:

```text
Incomplete downloads: /data/downloads/usenet/incomplete
Completed downloads: /data/downloads/usenet/completed
TV category: /data/downloads/usenet/completed/tv
Movies category: /data/downloads/usenet/completed/movies
Music category: /data/downloads/usenet/completed/music
```

Configure Sonarr, Radarr, and Lidarr SABnzbd download clients to use:

```text
Host: 127.0.0.1
Port: 8085
```

Keep `/volume2/appdata/sabnzbd` private because it contains SABnzbd API keys and Usenet provider credentials. The stack provisions it as `0700`; download directories remain group-writable for media imports.

For Lidarr, use category `music`, completed downloads `/data/downloads/torrents/completed/music`, and root folder `/data/media/music`.

Configure Prowlarr's Lidarr app integration to use:

```text
URL: http://127.0.0.1:8686
API key: copied from Lidarr
```

Proton VPN provides Gluetun-managed VPN port forwarding on supported paid-plan servers. qBittorrent's listening port is updated through Gluetun's `VPN_PORT_FORWARDING_UP_COMMAND` and reset through `VPN_PORT_FORWARDING_DOWN_COMMAND` when forwarding is removed.

Homepage reads Gluetun through the internal control server at `http://downloaders-vpn:8000` using `GLUETUN_CONTROL_API_KEY`. The control server is exposed only on Docker networks, not through Caddy or a host port.

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
- `[[APPDATA_DIR]]/qui` contains the qui database, admin/session state, and qBittorrent credentials. It is provisioned as private appdata and should be backed up.
- If `*.atlas.vandaele.io` is exposed through Cloudflare Tunnel, require Cloudflare Access before reaching qui.

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

- `rclone.atlas.local` is a privileged management surface. Anyone who reaches it can manage configured remotes and read or write the mounted local data path.
- The rclone RC API runs with `--no-auth` on a dedicated `rclone_network` that only Caddy and rclone should join.
- This stack mounts all of `[[DATA_DIR]]` at `/data`. That was chosen for flexibility, not least privilege.
- `rclone.conf` contains remote credentials and tokens. It is provisioned with `0600` permissions and should be backed up from `[[APPDATA_DIR]]/rclone`.
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

On first login, create the Uptime Kuma admin user and enable two-factor authentication. There is no Caddy Basic Auth gate on `http://uptime.atlas.local`; traffic remains plaintext on the LAN or tailnet path.

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
CLOUDFLARED_TUNNEL_TOKEN
```

Deploy order:

1. Deploy or redeploy `caddy`.
2. Deploy `cloudflared`.

For each public hostname in the Cloudflare Tunnel dashboard, point the service at Caddy:

```text
Service: http://caddy:80
```

Caddy routes by HTTP host. The preferred pattern is to add each public hostname as an additional site address in the relevant Caddy route, for example:

```caddyfile
http://speedtest.atlas.local, http://speedtest.example.com {
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
- `HOMEPAGE_ALLOWED_HOSTS` is set to the exact canonical v1 host, `homepage.atlas.local`. If Atlas is later accessed through additional hostnames or direct IPs, append those exact values as a comma-separated list before redeploying `homepage`.
- Homepage widget credentials stay in Komodo variables. The stack maps them into Homepage's `HOMEPAGE_VAR_*` templating environment variables.
- `LOG_TARGETS=stdout` keeps Homepage from trying to create `/app/config/logs` inside the read-only config mount.
- Resource Sync updates `stacks/homepage/config/*` through `config_files` with `requires = "None"`, so normal YAML, CSS, and JS edits do not force a container restart.
- After Homepage config file changes land through Resource Sync, use Homepage's refresh icon to regenerate the static UI. A `homepage` redeploy is only needed for environment-variable changes or when adding new local static assets.
- Caddy route changes still require an explicit `caddy` deploy or redeploy after Resource Sync so the Caddy `post_deploy` reload hook updates the live config.

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

To add a new app route:

1. Add a new file under `stacks/caddy/conf/sites/`.
2. Add the file to the Caddy stack `config_files` list in `stacks.toml`.
3. Ensure the app container joins `proxy_network`, or proxy to `host.docker.internal` for host services.
4. Push to `main`, execute Resource Sync, then explicitly deploy or redeploy `caddy` so the `post_deploy` reload hook applies the live config.

Most media app UIs are exposed through Caddy-only local hostnames rather than direct host ports. Plex is the current exception and still publishes `192.168.2.200:32400/tcp` for native client discovery and direct access.

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

Renovate will open PRs for Docker image updates. Validation commands that run `docker run` during `pre_deploy` derive their image from the stack's own `compose.yaml`, so there is no separate pinned validation image to keep in sync. Komodo polling will detect merged changes to `main`; execute Resource Sync and deploy the affected stack.
