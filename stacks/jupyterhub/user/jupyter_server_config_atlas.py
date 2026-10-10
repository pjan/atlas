
# Atlas (README "Jupyter"), appended to the image's jupyter_server_config.py.
# No extension installs from the UI: the image is read-only and pinned.
c.LabApp.extension_manager = "readonly"
# The status bar shows this container's memory and CPU, not the NAS'.
c.ResourceUseDisplay.show_host_usage = False
c.ResourceUseDisplay.track_cpu_percent = True
# Keep kernel WebSockets busy, so Cloudflare does not close idle ones.
c.ServerApp.websocket_ping_interval = 30
