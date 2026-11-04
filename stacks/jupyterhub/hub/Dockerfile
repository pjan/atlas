# The JupyterHub hub (README "Jupyter"): the official image plus the Docker
# spawner, the generic OAuth authenticator, and the idle culler. The
# jupyterhub pre_deploy builds it. Keep the JupyterHub version equal to the
# one in user/Dockerfile's base image (its hub-<version> tag); Renovate
# groups both.
FROM quay.io/jupyterhub/jupyterhub:6.1.1@sha256:550d4334b83eb74e1959d1a2541838d2fcb7e8deac65f0efd68d85213150dbcf

RUN python3 -m pip install --no-cache-dir \
      dockerspawner==14.0.0 \
      oauthenticator==17.4.0 \
      jupyterhub-idle-culler==2.0.0
