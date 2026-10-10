# The Jupyter egress proxy (README "Jupyter"): Squid from Alpine, running as
# its own user. The jupyterhub pre_deploy builds it; a rebuild picks up
# Alpine's current squid package. Renovate updates the base image.
FROM alpine:3.23@sha256:85fe1e81d6758c208f3e1eed4338a1997e19d4be002d4dd32d3100c9a8c010a0

RUN apk add --no-cache squid

USER squid
ENTRYPOINT ["squid", "-N", "-f", "/etc/squid/squid.conf"]
