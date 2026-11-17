# Caddy with the Cloudflare DNS module, which obtains and renews the
# *.atlas.vandaele.io wildcard certificate through a DNS challenge (README
# "Caddy"). The caddy pre_deploy builds this image on the NAS; Renovate keeps
# both base images and the module current, and never automerges them.
FROM caddy:2.11.9-builder@sha256:f9beaa5ddbe7df6f26ebbcf9cbf44e05a1917b9bba464f0c3229038d7e2e6e13 AS builder

ARG CADDY_DNS_CLOUDFLARE_VERSION=v0.2.4
RUN xcaddy build --with github.com/caddy-dns/cloudflare@${CADDY_DNS_CLOUDFLARE_VERSION}

FROM caddy:2.11.9@sha256:4851e54a46b206517c574821bb5cc67f170d2156041e9fbc4c9193b45e84a75b

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
