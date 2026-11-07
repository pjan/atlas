# The JupyterHub hub (README "Jupyter"): the official image plus the Docker
# spawner, the generic OAuth authenticator, and the idle culler. The
# jupyterhub pre_deploy builds it. Keep the JupyterHub version equal to the
# one in user/Dockerfile's base image (its hub-<version> tag); Renovate
# groups both.
FROM quay.io/jupyterhub/jupyterhub:6.1.1@sha256:48973496688583afca1c29571c7e69849ed9b9ffb74874af29b2c87e787aa8c6

RUN python3 -m pip install --no-cache-dir \
      dockerspawner==14.0.0 \
      oauthenticator==17.4.0 \
      jupyterhub-idle-culler==2.0.0
