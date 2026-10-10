# The JupyterHub hub (README "Jupyter"): the official image plus the Docker
# spawner, the generic OAuth authenticator, and the idle culler. The
# jupyterhub pre_deploy builds it. Keep the JupyterHub version equal to the
# one in user/Dockerfile's base image (its hub-<version> tag); Renovate
# groups both.
FROM quay.io/jupyterhub/jupyterhub:6.0.1@sha256:b148e8513aceb98f59bfffea51f245e9c45d99e3e504a4a92e9f3bf73589fd42

RUN python3 -m pip install --no-cache-dir \
      dockerspawner==14.0.0 \
      oauthenticator==17.4.0 \
      jupyterhub-idle-culler==2.0.0
