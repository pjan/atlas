# Caddy with the Cloudflare DNS module, which obtains and renews the
# *.atlas.vandaele.io wildcard certificate through a DNS challenge (README
# "Caddy"). The caddy pre_deploy builds this image on the NAS; Renovate keeps
# both base images and the module current, and never automerges them.
FROM caddy:2.11.7-builder@sha256:c4cd20eaa0b69112fd5d4f721ffc9671687e1d5d0b155c8620cf7546dbef94c0 AS builder

ARG CADDY_DNS_CLOUDFLARE_VERSION=v0.2.4
RUN xcaddy build --with github.com/caddy-dns/cloudflare@${CADDY_DNS_CLOUDFLARE_VERSION}

FROM caddy:2.11.7@sha256:36c24ad91a7ff7bc4c87fe22bfa8df3c4b18da0773d73fc12ee2c52b98c0bb7e

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
