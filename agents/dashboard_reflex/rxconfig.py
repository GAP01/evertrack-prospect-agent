"""Config Reflex EverTrack."""

import reflex as rx
from reflex.plugins import SitemapPlugin


config = rx.Config(
    app_name="dashboard_reflex",
    tailwind=None,
    disable_plugins=[SitemapPlugin],
)
