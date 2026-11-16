# The Jupyter egress proxy (README "Jupyter"): Squid from Alpine, running as
# its own user. The jupyterhub pre_deploy builds it; a rebuild picks up
# Alpine's current squid package. Renovate updates the base image.
FROM alpine:3.24@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf

RUN apk add --no-cache squid

USER squid
ENTRYPOINT ["squid", "-N", "-f", "/etc/squid/squid.conf"]
