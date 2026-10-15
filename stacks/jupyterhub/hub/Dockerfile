# The JupyterHub hub (README "Jupyter"): the official image plus the Docker
# spawner, the generic OAuth authenticator, and the idle culler. The
# jupyterhub pre_deploy builds it. Keep the JupyterHub version equal to the
# one in user/Dockerfile's base image (its hub-<version> tag); Renovate
# groups both.
FROM quay.io/jupyterhub/jupyterhub:6.1.0@sha256:bfc876d8875368a60934200553569ca4d5087839f26e0710957d6006d40a38da

RUN python3 -m pip install --no-cache-dir \
      dockerspawner==14.0.0 \
      oauthenticator==17.4.0 \
      jupyterhub-idle-culler==2.0.0
