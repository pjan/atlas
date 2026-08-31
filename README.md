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

### 1. Free Ports 80 And 443 In UGOS

UGOS can bind ports `80` and `443` with its built-in nginx service. Caddy needs port `80` for clean local hostnames such as `http://sonarr.atlas.local`.

In the UGOS dashboard:

1. Open `Control Panel`.
2. Open `Device Connection`.
3. Open `Portal Settings`.
4. Uncheck the options that redirect port `80` and port `443` to the HTTP/HTTPS portal ports.
5. Apply the change.

Verify over SSH:

```sh
sudo ss -ltnp | grep ':80' || echo "port 80 is free"
sudo ss -ltnp | grep ':443' || echo "port 443 is free"
```

Expected result: no UGOS/nginx listener on `0.0.0.0:80` or `0.0.0.0:443`.

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

Copy the contents of this repository’s komodo/ directory into /volume2/docker/komodo, then edit /volume2/docker/komodo/.env.

Generate separate values:

```sh
openssl rand -base64 32
openssl rand -base64 32
openssl rand -base64 32
openssl rand -base64 64
```

Use them for:

```env
KOMODO_DATABASE_PASSWORD=<32-byte random value>
KOMODO_INIT_ADMIN_PASSWORD=<32-byte random value>
KOMODO_WEBHOOK_SECRET=<32-byte random value>
KOMODO_JWT_SECRET=<64-byte random value>
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

### Plex Claim Token

When deploying Plex for the first time, `PLEX_CLAIM` needs to be set. It is a short-lived token from `https://plex.tv/claim` that attaches the new Plex server to your Plex account during first startup.

To claim a fresh Plex install:

1. Generate a claim token at `https://plex.tv/claim`.
2. Set `PLEX_CLAIM` on the Plex stack in Komodo.
3. Deploy Plex.
4. Confirm the server appears in your Plex account.
5. Clear `PLEX_CLAIM` and redeploy Plex so the expired token is not retained.

If restoring an existing Plex `/config` with a valid `Preferences.xml`, a claim token is usually not required.

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
4. Push to `main`, execute Resource Sync, and let Komodo restart Caddy.

Media app UIs are exposed through Caddy-only local hostnames rather than direct host ports.

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

Renovate will open PRs for Docker image updates. Komodo polling will detect merged changes to `main`; execute Resource Sync and deploy the affected stack.
