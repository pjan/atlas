# JupyterHub for Atlas (README "Jupyter"). Logins through authentik with
# OpenID Connect (oidc-jupyterhub.yaml) behind forward auth
# (forward-auth-jupyter.yaml); one container per user through the socket
# proxy, on jupyter_users only, reaching the internet through the egress
# proxy. Secrets come from the environment (Komodo variables).
import os
import sys
from pathlib import Path

c = get_config()  # noqa: F821

DATA = "/srv/jupyterhub/data"
HOMES = Path("/srv/jupyterhub/home")
PUBLIC_URL = "https://jupyter.atlas.vandaele.io"
AUTH_URL = "https://auth.atlas.vandaele.io"
EGRESS_PROXY = "http://egress-proxy:3128"
NO_PROXY = "jupyterhub,localhost,127.0.0.1"

# Hub: the proxy on :8000 for Caddy, the hub API on :8081 for user servers.
c.JupyterHub.bind_url = "http://:8000"
c.JupyterHub.hub_bind_url = "http://0.0.0.0:8081"
c.JupyterHub.hub_connect_url = "http://jupyterhub:8081"
c.JupyterHub.db_url = f"sqlite:///{DATA}/jupyterhub.sqlite"
c.JupyterHub.cookie_secret_file = f"{DATA}/jupyterhub_cookie_secret"
c.ConfigurableHTTPProxy.pid_file = f"{DATA}/jupyterhub-proxy.pid"
# Stopping the hub (deploys, the nightly backup) stops every user server.
c.JupyterHub.cleanup_servers = True
# Admins cannot open other users' servers.
c.JupyterHub.admin_access = False
# The NAS has little free memory (README "Jupyter").
c.JupyterHub.active_server_limit = 2

# Login: authentik OIDC. Its endpoints are written out instead of discovered.
# Server-side calls go to the public hostname, which Atlas DNS sends to Caddy.
c.JupyterHub.authenticator_class = "generic-oauth"
c.GenericOAuthenticator.client_id = "jupyterhub"
c.GenericOAuthenticator.client_secret = os.environ["JUPYTERHUB_OIDC_CLIENT_SECRET"]
c.GenericOAuthenticator.oauth_callback_url = f"{PUBLIC_URL}/hub/oauth_callback"
c.GenericOAuthenticator.authorize_url = f"{AUTH_URL}/application/o/authorize/"
c.GenericOAuthenticator.token_url = f"{AUTH_URL}/application/o/token/"
c.GenericOAuthenticator.userdata_url = f"{AUTH_URL}/application/o/userinfo/"
c.GenericOAuthenticator.logout_redirect_url = f"{AUTH_URL}/application/o/jupyterhub/end-session/"
c.GenericOAuthenticator.scope = ["openid", "profile", "email"]
c.GenericOAuthenticator.username_claim = "preferred_username"
# authentik's groups claim decides access and the admin role.
c.GenericOAuthenticator.manage_groups = True
c.GenericOAuthenticator.auth_state_groups_key = "oauth_user.groups"
c.GenericOAuthenticator.allowed_groups = {"admins", "family"}
c.GenericOAuthenticator.admin_groups = {"admins"}
# Auth state is encrypted with JUPYTERHUB_CRYPT_KEY.
c.Authenticator.enable_auth_state = True
c.Authenticator.auto_login = True

# User servers: atlas-jupyter-user:local, built by the stack's pre_deploy.
c.JupyterHub.spawner_class = "docker"
c.DockerSpawner.client_kwargs = {"base_url": "tcp://socket-proxy:2375"}
c.DockerSpawner.image = "atlas-jupyter-user:local"
c.DockerSpawner.pull_policy = "never"
c.DockerSpawner.network_name = "jupyter_users"
c.DockerSpawner.use_internal_ip = True
c.DockerSpawner.remove = True
c.DockerSpawner.name_template = "jupyter-{username}"
c.DockerSpawner.notebook_dir = "/home/jovyan"
# {username} is DockerSpawner's escaped name, as in make_home below.
c.DockerSpawner.volumes = {
    f"{os.environ['JUPYTERHUB_HOMES_ON_HOST']}/{{username}}": "/home/jovyan",
}
c.DockerSpawner.mem_limit = "2G"
c.DockerSpawner.cpu_limit = 2.0
c.DockerSpawner.extra_host_config = {
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges:true"],
    "pids_limit": 512,
    # The image stays as built: users install into their home only.
    "read_only": True,
    "tmpfs": {"/tmp": "rw,nosuid,nodev,size=1g"},
    "log_config": {"type": "json-file", "config": {"max-size": "10m", "max-file": "3"}},
}
c.DockerSpawner.environment = {
    "HTTP_PROXY": EGRESS_PROXY,
    "HTTPS_PROXY": EGRESS_PROXY,
    "http_proxy": EGRESS_PROXY,
    "https_proxy": EGRESS_PROXY,
    "NO_PROXY": NO_PROXY,
    "no_proxy": NO_PROXY,
    # Server runtime files stay out of the persistent home: the image's
    # healthcheck would otherwise read a previous container's file.
    "JUPYTER_RUNTIME_DIR": "/tmp/jupyter-runtime",
    # conda and mamba cache packages in the home (/opt/conda is read-only).
    "CONDA_PKGS_DIRS": "/home/jovyan/.conda/pkgs",
}
c.Spawner.start_timeout = 180
c.Spawner.http_timeout = 120


def make_home(spawner):
    """Create the user's home before DockerSpawner binds it.

    The hub runs as 1000:100, so the directory belongs to the image's jovyan.
    A missing bind source would be created by Docker as root:root.
    """
    (HOMES / spawner.escaped_name).mkdir(mode=0o700, exist_ok=True)


c.Spawner.pre_spawn_hook = make_home

# Services: the idle culler, and a token for Prometheus to read /hub/metrics.
# A kernel busy without output and without a browser counts as idle.
c.JupyterHub.load_roles = [
    {
        "name": "idle-culler",
        "scopes": ["list:users", "read:users:activity", "read:servers", "delete:servers"],
        "services": ["idle-culler"],
    },
    {
        "name": "metrics",
        "scopes": ["read:metrics"],
        "services": ["prometheus"],
    },
]
c.JupyterHub.services = [
    {
        "name": "idle-culler",
        "command": [
            sys.executable, "-m", "jupyterhub_idle_culler",
            "--timeout=14400",
            "--cull-every=600",
        ],
    },
    {
        "name": "prometheus",
        "api_token": os.environ["JUPYTERHUB_METRICS_TOKEN"],
    },
]
