"""
Drawer détail d'un signal volume (signalconso_volume).

Affiche : statut, score, métadonnées (catégorie, dépt, semaine ISO),
stats baseline (médiane, MAD, n samples, z-mod) et actions valider/rejeter.
"""

from __future__ import annotations

import reflex as rx

from ..state import DashboardState


def _score_circle(score: rx.Var[int]) -> rx.Component:
    """Cercle SVG avec score au centre, couleur dégradée selon score."""
    color = rx.cond(
        score >= 80, "#dc2626",
        rx.cond(score >= 60, "#d97706",
                rx.cond(score >= 40, "#ca8a04", "#9ca3af")),
    )
    return rx.box(
        rx.text(score.to_string(), size="6", weight="bold", color=color),
        width="64px",
        height="64px",
        border_radius="9999px",
        background="white",
        border="3px solid " + color.to(str),
        display="flex",
        align_items="center",
        justify_content="center",
    )


def _status_badge(status: rx.Var[str]) -> rx.Component:
    bg = rx.match(
        status,
        ("a_valider", "#fef9c3"),
        ("valide", "#dcfce7"),
        ("rejete", "#fee2e2"),
        ("promu", "#dbeafe"),
        ("faible", "#f3f4f6"),
        "#f3f4f6",
    )
    color = rx.match(
        status,
        ("a_valider", "#854d0e"),
        ("valide", "#166534"),
        ("rejete", "#991b1b"),
        ("promu", "#1e40af"),
        ("faible", "#6b7280"),
        "#6b7280",
    )
    label = rx.match(
        status,
        ("a_valider", "A valider"),
        ("valide", "Validé"),
        ("rejete", "Rejeté"),
        ("promu", "Promu"),
        ("faible", "Faible"),
        status,
    )
    return rx.box(
        rx.text(label, size="2", weight="medium", color=color),
        background=bg,
        padding="4px 12px",
        border_radius="9999px",
        display="inline-block",
    )


def _stat_row(label: str, value: rx.Var | str, color: str = "#111827") -> rx.Component:
    return rx.hstack(
        rx.text(label, size="2", color="#6b7280"),
        rx.spacer(),
        rx.text(value, size="2", weight="medium", color=color),
        width="100%",
    )


def _actions_row() -> rx.Component:
    s = DashboardState.selected_volume
    sid = s["signal_id"].to(str)
    is_pending = s["status"].to(str) == "a_valider"
    return rx.hstack(
        rx.button(
            rx.hstack(rx.icon("check", size=14), rx.text("Valider"), spacing="2"),
            on_click=DashboardState.validate_signal(sid),
            disabled=~is_pending,
            color_scheme="green",
            variant="solid",
            size="2",
        ),
        rx.button(
            rx.hstack(rx.icon("x", size=14), rx.text("Rejeter"), spacing="2"),
            on_click=DashboardState.reject_signal(sid),
            disabled=~is_pending,
            color_scheme="red",
            variant="soft",
            size="2",
        ),
        spacing="2",
        padding_top="16px",
        padding_bottom="16px",
    )


def volume_detail_drawer() -> rx.Component:
    s = DashboardState.selected_volume
    return rx.drawer.root(
        rx.drawer.overlay(z_index="10"),
        rx.drawer.portal(
            rx.drawer.content(
                rx.box(
                    # En-tête
                    rx.hstack(
                        rx.vstack(
                            rx.heading(
                                DashboardState.selected_volume_title,
                                size="5",
                                weight="bold",
                                color="#111827",
                            ),
                            rx.text(
                                "Semaine ISO " + s["iso_week"].to(str),
                                size="2",
                                color="#6b7280",
                            ),
                            _status_badge(s["status"].to(str)),
                            spacing="2",
                            align="start",
                            flex="1",
                        ),
                        _score_circle(s["score"].to(int)),
                        rx.drawer.close(
                            rx.icon_button(
                                rx.icon("x", size=16),
                                variant="ghost",
                                color_scheme="gray",
                                on_click=DashboardState.close_volume_drawer,
                            ),
                        ),
                        width="100%",
                        padding_bottom="16px",
                        border_bottom="1px solid #e5e7eb",
                        align="start",
                        spacing="3",
                    ),

                    _actions_row(),

                    # Bloc localisation
                    rx.text(
                        "LOCALISATION",
                        size="1",
                        color="#9ca3af",
                        weight="bold",
                        letter_spacing="0.08em",
                        padding_top="8px",
                        padding_bottom="8px",
                    ),
                    rx.box(
                        rx.vstack(
                            _stat_row("Catégorie", s["category"].to(str)),
                            _stat_row("Département", s["dep_name"].to(str) + " (" + s["dep_code"].to(str) + ")"),
                            _stat_row("Semaine", s["iso_week"].to(str)),
                            _stat_row("Détecté le", s["detected_at"].to(str)),
                            spacing="2",
                            width="100%",
                        ),
                        background="#f9fafb",
                        padding="12px 16px",
                        border_radius="8px",
                        border="1px solid #e5e7eb",
                    ),

                    # Bloc statistique
                    rx.text(
                        "ANALYSE STATISTIQUE",
                        size="1",
                        color="#9ca3af",
                        weight="bold",
                        letter_spacing="0.08em",
                        padding_top="16px",
                        padding_bottom="8px",
                    ),
                    rx.box(
                        rx.vstack(
                            _stat_row(
                                "Pic actuel",
                                s["count_actuel"].to(str) + " signalements",
                                color="#dc2626",
                            ),
                            _stat_row(
                                "Médiane baseline",
                                s["baseline_median"].to(str) + " signalements/semaine",
                            ),
                            _stat_row(
                                "MAD baseline",
                                s["baseline_mad"].to(str),
                            ),
                            _stat_row(
                                "Échantillons baseline",
                                s["baseline_n_samples"].to(str) + " semaines",
                            ),
                            _stat_row(
                                "Z-score modifié",
                                s["z_mod"].to(str),
                                color="#dc2626",
                            ),
                            _stat_row(
                                "Seuil",
                                s["z_mod_threshold"].to(str),
                            ),
                            _stat_row(
                                "Méthode",
                                s["method"].to(str),
                            ),
                            spacing="2",
                            width="100%",
                        ),
                        background="#f9fafb",
                        padding="12px 16px",
                        border_radius="8px",
                        border="1px solid #e5e7eb",
                    ),

                    # Note explicative — pas de cross-ref pour ce bucket
                    rx.box(
                        rx.hstack(
                            rx.icon("info", size=14, color="#0369a1"),
                            rx.text(
                                "Pas de cross-référence automatique avec les rappels RappelConso "
                                "pour ce bucket — vérifier manuellement les rappels du même département "
                                "et de la même catégorie sur la fenêtre temporelle.",
                                size="1",
                                color="#075985",
                            ),
                            spacing="2",
                            align="start",
                        ),
                        background="#e0f2fe",
                        padding="10px 14px",
                        border_radius="8px",
                        border="1px solid #bae6fd",
                        margin_top="16px",
                    ),

                    padding="24px",
                    overflow_y="auto",
                    height="100vh",
                ),
                position="fixed",
                top="0",
                right="0",
                bottom="0",
                left="auto",
                height="100vh",
                width="520px",
                max_width="95vw",
                background="white",
                border_left="1px solid #e5e7eb",
                box_shadow="-12px 0 24px rgba(0,0,0,0.08)",
                z_index="50",
            ),
        ),
        open=DashboardState.volume_drawer_open,
        on_open_change=DashboardState.set_volume_drawer_open,
        direction="right",
    )
