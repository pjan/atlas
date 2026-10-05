# Caddy with the Cloudflare DNS module, which obtains and renews the
# *.atlas.vandaele.io wildcard certificate through a DNS challenge (README
# "Caddy"). The caddy pre_deploy builds this image on the NAS; Renovate keeps
# both base images and the module current, and never automerges them.
FROM caddy:2.11.6-builder@sha256:f5b1a66449d305280e559dba0ab9f7ce9a2a14c527c79d7c6fb48abc8f895818 AS builder

ARG CADDY_DNS_CLOUDFLARE_VERSION=v0.2.4
RUN xcaddy build --with github.com/caddy-dns/cloudflare@${CADDY_DNS_CLOUDFLARE_VERSION}

FROM caddy:2.11.6@sha256:3422ce6de165df66534f9b9ba50efaf457114ec961763cc52f5dbdaac2972d73

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
