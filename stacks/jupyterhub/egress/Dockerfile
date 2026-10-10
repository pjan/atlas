# The Jupyter egress proxy (README "Jupyter"): Squid from Alpine, running as
# its own user. The jupyterhub pre_deploy builds it; a rebuild picks up
# Alpine's current squid package. Renovate updates the base image.
FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6

RUN apk add --no-cache squid

USER squid
ENTRYPOINT ["squid", "-N", "-f", "/etc/squid/squid.conf"]
