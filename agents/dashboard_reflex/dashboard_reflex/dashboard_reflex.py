"""
Application Reflex EverTrack.

Point d'entrée : assemble sidebar + contenu principal et déclare la page.
Le contenu principal switche entre deux vues via DashboardState.current_page :
  - "radar"     → incidents scorés (Agent 1 + 2)
  - "prospects" → enrichissements SIRENE (Agent 3)
"""

from __future__ import annotations

import reflex as rx

from .state import DashboardState
from .components.sidebar import sidebar
from .components.header import header
from .components.kpi_cards import kpi_cards
from .components.incident_table import incident_table
from .components.incident_detail_drawer import incident_detail_drawer
from .components.prospects_table import prospects_table
from .components.prospect_detail_drawer import prospect_detail_drawer
from .components.signaux_table import signaux_table
from .components.signal_detail_drawer import signal_detail_drawer
from .components.volumes_table import volumes_table
from .components.volume_detail_drawer import volume_detail_drawer


def _prospects_header() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.vstack(
                rx.hstack(
                    rx.text("EverTrack", size="2", color="#6b7280"),
                    rx.icon("chevron_right", size=14, color="#9ca3af"),
                    rx.text("Prospects", size="2", color="#374151"),
                    spacing="2",
                    align="center",
                ),
                rx.heading(
                    "Prospects enrichis",
                    size="6",
                    weight="bold",
                    color="#111827",
                ),
                rx.text(
                    "Entreprises identifiees via SIRENE — contacts qualite / supply chain / conformite",
                    size="2",
                    color="#6b7280",
                ),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            spacing="4",
            align="start",
            width="100%",
        ),
        width="100%",
        padding_bottom="24px",
    )


def _signaux_header() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.vstack(
                rx.hstack(
                    rx.text("EverTrack", size="2", color="#6b7280"),
                    rx.icon("chevron_right", size=14, color="#9ca3af"),
                    rx.text("Signaux faibles", size="2", color="#374151"),
                    spacing="2",
                    align="center",
                ),
                rx.heading(
                    "Signaux faibles",
                    size="6",
                    weight="bold",
                    color="#111827",
                ),
                rx.text(
                    "Alertes précoces détectées via Google News + Reddit — à valider avant promotion en incident",
                    size="2",
                    color="#6b7280",
                ),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.cond(
                DashboardState.signal_last_seen != "jamais",
                rx.vstack(
                    rx.text("DERNIER SCAN", size="1", color="#9ca3af", weight="bold"),
                    rx.text(
                        DashboardState.signal_last_seen,
                        size="2",
                        color="#374151",
                    ),
                    spacing="0",
                    align="end",
                ),
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        width="100%",
        padding_bottom="24px",
    )


def _volumes_header() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.vstack(
                rx.hstack(
                    rx.text("EverTrack", size="2", color="#6b7280"),
                    rx.icon("chevron_right", size=14, color="#9ca3af"),
                    rx.text("Volumes SignalConso", size="2", color="#374151"),
                    spacing="2",
                    align="center",
                ),
                rx.heading(
                    "Anomalies de volume — SignalConso",
                    size="6",
                    weight="bold",
                    color="#111827",
                ),
                rx.text(
                    "Pics anormaux détectés sur les signalements DGCCRF "
                    "par catégorie et département (z-score modifié ≥ 3.5)",
                    size="2",
                    color="#6b7280",
                ),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.cond(
                DashboardState.volume_last_seen != "jamais",
                rx.vstack(
                    rx.text("DERNIER SCAN", size="1", color="#9ca3af", weight="bold"),
                    rx.text(
                        DashboardState.volume_last_seen,
                        size="2",
                        color="#374151",
                    ),
                    spacing="0",
                    align="end",
                ),
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        width="100%",
        padding_bottom="24px",
    )


def _mobile_bottom_nav() -> rx.Component:
    """Barre de navigation fixée en bas, visible uniquement sur mobile (≤640px)."""
    def _tab(icon: str, label: str, page: str) -> rx.Component:
        is_active = DashboardState.current_page == page
        return rx.vstack(
            rx.icon(
                icon,
                size=20,
                color=rx.cond(is_active, "#4338ca", "#9ca3af"),
            ),
            rx.text(
                label,
                size="1",
                weight=rx.cond(is_active, "bold", "regular"),
                color=rx.cond(is_active, "#4338ca", "#9ca3af"),
            ),
            spacing="1",
            align="center",
            flex="1",
            padding="6px 0",
            cursor="pointer",
            on_click=(
                DashboardState.nav_radar if page == "radar"
                else DashboardState.nav_signaux if page == "signaux"
                else DashboardState.nav_volumes if page == "volumes"
                else DashboardState.nav_prospects
            ),
        )

    return rx.box(
        rx.hstack(
            _tab("layout_dashboard", "Radar", "radar"),
            _tab("radio_tower", "Signaux", "signaux"),
            _tab("activity", "Volumes", "volumes"),
            _tab("building_2", "Prospects", "prospects"),
            width="100%",
            justify="between",
            spacing="0",
        ),
        style={
            "position": "fixed",
            "bottom": "0",
            "left": "0",
            "right": "0",
            "background": "white",
            "border-top": "1px solid #e5e7eb",
            "padding": "4px 0 env(safe-area-inset-bottom, 8px)",
            "z-index": "9999",
            "box-shadow": "0 -2px 8px rgba(0,0,0,0.06)",
            "transform": "translateZ(0)",
            "@media (min-width: 641px)": {"display": "none"},
        },
    )


def index() -> rx.Component:
    return rx.box(
        sidebar(),
        rx.box(
            rx.match(
                DashboardState.current_page,
                ("radar", rx.fragment(
                    header(),
                    kpi_cards(),
                    incident_table(),
                )),
                ("signaux", rx.fragment(
                    _signaux_header(),
                    signaux_table(),
                )),
                ("volumes", rx.fragment(
                    _volumes_header(),
                    volumes_table(),
                )),
                ("prospects", rx.fragment(
                    _prospects_header(),
                    prospects_table(),
                )),
                rx.fragment(
                    header(),
                    kpi_cards(),
                    incident_table(),
                ),
            ),
            style={
                "padding": "32px 40px",
                "margin-left": "260px",
                "min-height": "100vh",
                "background": "#f9fafb",
                "@media (max-width: 640px)": {
                    "margin-left": "0px",
                    "padding": "16px 12px 80px",
                },
            },
        ),
        _mobile_bottom_nav(),
        incident_detail_drawer(),
        prospect_detail_drawer(),
        signal_detail_drawer(),
        volume_detail_drawer(),
        width="100%",
        min_height="100vh",
        background="#f9fafb",
        font_family=(
            "'Inter', ui-sans-serif, system-ui, -apple-system, "
            "BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
        ),
    )


app = rx.App(
    theme=rx.theme(
        appearance="light",
        accent_color="indigo",
        gray_color="slate",
        radius="medium",
        scaling="100%",
    ),
    stylesheets=[
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap",
    ],
)

app.add_page(
    index,
    route="/",
    title="EverTrack | Radar incidents",
    on_load=DashboardState.load_initial,
)
