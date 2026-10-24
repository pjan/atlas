# The Jupyter egress proxy (README "Jupyter"): Squid from Alpine, running as
# its own user. The jupyterhub pre_deploy builds it; a rebuild picks up
# Alpine's current squid package. Renovate updates the base image.
FROM alpine:3.24@sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a

RUN apk add --no-cache squid

USER squid
ENTRYPOINT ["squid", "-N", "-f", "/etc/squid/squid.conf"]
