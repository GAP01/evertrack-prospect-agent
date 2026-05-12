"""
Sidebar fixe a gauche. Style SaaS B2B (Linear / Stripe) :
- fond blanc, bord droit gris tres clair
- logo en haut
- stats snapshot compactes
- boutons d'action (fetch / score), desactives si demo_mode
"""

from __future__ import annotations

import reflex as rx

from ..state import DashboardState


def _nav_item(icon: str, label: str, page: str) -> rx.Component:
    is_active = DashboardState.current_page == page
    return rx.hstack(
        rx.icon(icon, size=16),
        rx.text(label, size="2", weight="medium"),
        spacing="3",
        align="center",
        padding="8px 12px",
        border_radius="6px",
        background=rx.cond(is_active, "#eef2ff", "transparent"),
        color=rx.cond(is_active, "#4338ca", "#374151"),
        cursor="pointer",
        _hover={"background": "#f9fafb"},
        width="100%",
        on_click=(
            DashboardState.nav_radar if page == "radar"
            else DashboardState.nav_signaux if page == "signaux"
            else DashboardState.nav_volumes if page == "volumes"
            else DashboardState.nav_prospects
        ),
    )


def _stat_row(label: str, value: rx.Var | str) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="1", color="#6b7280"),
        rx.spacer(),
        rx.text(value, size="2", weight="medium", color="#111827"),
        width="100%",
    )


def _action_button(
    label: str,
    icon: str,
    on_click,
    disabled: rx.Var,
    variant: str = "solid",
) -> rx.Component:
    return rx.button(
        rx.hstack(rx.icon(icon, size=14), rx.text(label, size="2"), spacing="2", align="center"),
        on_click=on_click,
        disabled=disabled,
        variant=variant,
        color_scheme="indigo",
        width="100%",
        size="2",
    )


def sidebar() -> rx.Component:
    return rx.vstack(
        # Logo / marque
        rx.hstack(
            rx.box(
                rx.icon("shield_check", size=18, color="white"),
                width="32px",
                height="32px",
                border_radius="8px",
                background="linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)",
                display="flex",
                align_items="center",
                justify_content="center",
            ),
            rx.vstack(
                rx.text("EverTrack", size="3", weight="bold", color="#111827"),
                rx.text("Radar incidents", size="1", color="#6b7280"),
                spacing="0",
                align="start",
            ),
            spacing="3",
            align="center",
            width="100%",
            padding_bottom="24px",
        ),

        # Navigation
        rx.vstack(
            rx.text("NAVIGATION", size="1", color="#9ca3af", weight="bold", letter_spacing="0.08em"),
            _nav_item("layout_dashboard", "Radar incidents", "radar"),
            _nav_item("radio_tower", "Signaux faibles", "signaux"),
            _nav_item("activity", "Volumes SignalConso", "volumes"),
            _nav_item("building_2", "Prospects", "prospects"),
            spacing="1",
            width="100%",
            align="start",
        ),

        rx.divider(margin_y="16px"),

        # Stats snapshot
        rx.vstack(
            rx.text("APERCU", size="1", color="#9ca3af", weight="bold", letter_spacing="0.08em"),
            _stat_row("Incidents", DashboardState.incidents_total),
            _stat_row("Scores", DashboardState.scores_total),
            _stat_row("Derniere eval.", DashboardState.last_score_at),
            spacing="2",
            width="100%",
            align="start",
        ),

        rx.divider(margin_y="16px"),

        # Actions
        rx.vstack(
            rx.text("ACTIONS", size="1", color="#9ca3af", weight="bold", letter_spacing="0.08em"),
            _action_button(
                "Rafraichir la veille",
                "cloud_download",
                DashboardState.action_fetch,
                disabled=DashboardState.demo_mode | DashboardState.loading,
            ),
            _action_button(
                "Scorer les incidents",
                "gauge",
                DashboardState.action_score,
                disabled=DashboardState.demo_mode | DashboardState.loading,
                variant="outline",
            ),
            rx.cond(
                DashboardState.demo_mode,
                rx.box(
                    rx.hstack(
                        rx.icon("lock", size=12),
                        rx.text("Mode demo", size="1"),
                        spacing="2",
                        align="center",
                    ),
                    padding="6px 10px",
                    border_radius="6px",
                    background="#fffbeb",
                    color="#92400e",
                    border="1px solid #fef3c7",
                    width="100%",
                ),
            ),
            spacing="2",
            width="100%",
            align="start",
        ),

        rx.spacer(),

        # Footer
        rx.hstack(
            rx.box(
                rx.text("GP", size="1", weight="bold", color="white"),
                width="28px",
                height="28px",
                border_radius="9999px",
                background="#4f46e5",
                display="flex",
                align_items="center",
                justify_content="center",
            ),
            rx.vstack(
                rx.text("Gautier", size="2", weight="medium", color="#111827"),
                rx.text("admin", size="1", color="#6b7280"),
                spacing="0",
                align="start",
            ),
            spacing="2",
            align="center",
            width="100%",
        ),

        width="260px",
        height="100vh",
        padding="20px",
        background="white",
        border_right="1px solid #e5e7eb",
        position="fixed",
        left="0",
        top="0",
        align="start",
        spacing="2",
        style={
            "@media (max-width: 640px)": {"display": "none"},
        },
    )
