"""
Header superieur : titre de page + bouton refresh + toast.
"""

from __future__ import annotations

import reflex as rx

from ..state import DashboardState


def _toast() -> rx.Component:
    """Mini banniere qui s'affiche quand last_message est non vide."""
    # Couleurs selon le kind
    color_map = rx.match(
        DashboardState.last_message_kind,
        ("success", "#059669"),
        ("warning", "#b45309"),
        ("error", "#b91c1c"),
        "#2563eb",
    )
    bg_map = rx.match(
        DashboardState.last_message_kind,
        ("success", "#ecfdf5"),
        ("warning", "#fffbeb"),
        ("error", "#fef2f2"),
        "#eff6ff",
    )
    icon_map = rx.match(
        DashboardState.last_message_kind,
        ("success", "circle_check"),
        ("warning", "triangle_alert"),
        ("error", "circle_x"),
        "info",
    )

    return rx.cond(
        DashboardState.last_message != "",
        rx.hstack(
            rx.icon(icon_map, size=14),
            rx.text(DashboardState.last_message, size="2"),
            spacing="2",
            align="center",
            padding="6px 12px",
            border_radius="8px",
            background=bg_map,
            color=color_map,
            border="1px solid rgba(0,0,0,0.05)",
        ),
    )


def header() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.hstack(
                rx.text("Radar", size="1", color="#9ca3af"),
                rx.icon("chevron_right", size=12, color="#9ca3af"),
                rx.text("Incidents", size="1", color="#6b7280", weight="medium"),
                spacing="1",
                align="center",
            ),
            rx.heading("Incidents prioritaires", size="6", weight="bold", color="#111827"),
            rx.text(
                "Classement par severite pour cibler les prospects",
                size="2",
                color="#6b7280",
            ),
            spacing="1",
            align="start",
        ),
        rx.spacer(),
        _toast(),
        rx.cond(
            DashboardState.loading,
            rx.hstack(
                rx.spinner(size="2"),
                rx.text("Traitement...", size="2", color="#6b7280"),
                spacing="2",
                align="center",
            ),
        ),
        rx.button(
            rx.hstack(rx.icon("refresh_cw", size=14), rx.text("Rafraichir"), spacing="2"),
            on_click=DashboardState.refresh,
            variant="soft",
            color_scheme="gray",
            size="2",
        ),
        width="100%",
        align="center",
        padding_bottom="24px",
    )
