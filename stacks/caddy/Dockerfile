# Caddy with the Cloudflare DNS module, which obtains and renews the
# *.atlas.vandaele.io wildcard certificate through a DNS challenge (README
# "Caddy"). The caddy pre_deploy builds this image on the NAS; Renovate keeps
# both base images and the module current, and never automerges them.
FROM caddy:2.11.9-builder@sha256:345264d8c6b50f44f4a4d507d4e6b6bcae40eef2f210d70f76e717fd8cc31baf AS builder

ARG CADDY_DNS_CLOUDFLARE_VERSION=v0.2.4
RUN xcaddy build --with github.com/caddy-dns/cloudflare@${CADDY_DNS_CLOUDFLARE_VERSION}

FROM caddy:2.11.9@sha256:4e2425f6009577e7c651010f16679c28f7d12df3e7b1914f941a7a3370746b3c

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
