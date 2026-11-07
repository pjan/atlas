# The Jupyter egress proxy (README "Jupyter"): Squid from Alpine, running as
# its own user. The jupyterhub pre_deploy builds it; a rebuild picks up
# Alpine's current squid package. Renovate updates the base image.
FROM alpine:3.24@sha256:3f4d6b32e26703c6082839234f43769d5046b3ac7c910033911d1e71d8cd630a

RUN apk add --no-cache squid

USER squid
ENTRYPOINT ["squid", "-N", "-f", "/etc/squid/squid.conf"]
