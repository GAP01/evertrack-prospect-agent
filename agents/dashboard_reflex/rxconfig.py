"""Config Reflex EverTrack."""

import os

import reflex as rx
from reflex.plugins import SitemapPlugin

# En prod (Railway), API_URL = URL publique HTTPS du service ; le frontend
# parle au backend via cette origine (Caddy reverse-proxy le WebSocket).
# En local, None => Reflex utilise http://localhost:8000 par défaut.
_api_url = os.environ.get("API_URL") or None

config = rx.Config(
    app_name="dashboard_reflex",
    tailwind=None,
    disable_plugins=[SitemapPlugin],
    api_url=_api_url,
)
