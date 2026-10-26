# The JupyterHub hub (README "Jupyter"): the official image plus the Docker
# spawner, the generic OAuth authenticator, and the idle culler. The
# jupyterhub pre_deploy builds it. Keep the JupyterHub version equal to the
# one in user/Dockerfile's base image (its hub-<version> tag); Renovate
# groups both.
FROM quay.io/jupyterhub/jupyterhub:6.1.1@sha256:25fdffa6fae74bd2c2fe353e432ffbbbdf10f9f071515580d4e1fefd6f066b04

RUN python3 -m pip install --no-cache-dir \
      dockerspawner==14.0.0 \
      oauthenticator==17.4.0 \
      jupyterhub-idle-culler==2.0.0
