# The Jupyter user server (README "Jupyter"): Jupyter's scipy-notebook plus
# Atlas' extensions and packages, every version pinned. The jupyterhub
# pre_deploy builds it as atlas-jupyter-user:local. jupyterhub-singleuser must
# equal the hub's JupyterHub version (hub/Dockerfile); Renovate groups both
# base images. The pinned packages are updated by hand.
FROM quay.io/jupyter/scipy-notebook:2026-10-05@sha256:2479174ae36ec84373f3c352cb6d5801382c0aa6642e739f04bea409f6cedae1

RUN mamba install --yes --quiet \
      jupyterhub-singleuser=6.0.1 \
      jupyterlab-lsp=5.3.0 python-lsp-server=1.15.0 python-lsp-ruff=2.3.4 \
      jupyterlab_code_formatter=3.1.0 ruff=0.17.0 \
      jupyterlab_execute_time=3.2.0 jupyter-resource-usage=1.3.0 jupyter-archive=3.5.1 \
      jupyterlab-spellchecker=0.9.0 jupyterlab-search-replace=1.1.3 jupyterlab-quickopen=2.3.0 \
      uv=0.12.24 polars=2.0.0 duckdb=1.5.6 pyarrow=25.0.0 plotly=7.1.0 httpx=0.28.1 itables=2.9.1 \
 && pip install --no-cache-dir jupyterlab-vim==4.1.4 \
 && mamba clean --all -f -y \
 && fix-permissions "${CONDA_DIR}" \
 && fix-permissions "/home/${NB_USER}"

# Admin defaults for JupyterLab; users can change them in their settings.
COPY overrides.json /opt/conda/share/jupyter/lab/settings/overrides.json

# Server settings. JupyterLab reads LabApp settings from this file, not from
# jupyter_server_config.d/*.json.
COPY --chown=1000:100 jupyter_server_config_atlas.py /tmp/jupyter_server_config_atlas.py
RUN cat /tmp/jupyter_server_config_atlas.py >> /etc/jupyter/jupyter_server_config.py \
 && rm /tmp/jupyter_server_config_atlas.py
