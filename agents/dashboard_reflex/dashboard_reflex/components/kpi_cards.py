"""
Cartes KPI en haut du dashboard (4 cartes : incidents, scores, critiques, derniere eval).
"""

from __future__ import annotations

import reflex as rx

from ..state import DashboardState


def _card(
    label: str,
    value: rx.Var | str,
    icon: str,
    tint: str,
    icon_color: str,
    hint: rx.Var | str = "",
    tooltip: str = "",
) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.hstack(
                    rx.text(label, size="1", color="#6b7280", weight="medium", letter_spacing="0.04em"),
                    rx.cond(
                        tooltip != "",
                        rx.tooltip(
                            rx.icon("circle_help", size=12, color="#9ca3af"),
                            content=tooltip,
                        ),
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.heading(value, size="6", weight="bold", color="#111827"),
                rx.text(hint, size="1", color="#9ca3af"),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.box(
                rx.icon(icon, size=18, color=icon_color),
                width="40px",
                height="40px",
                border_radius="10px",
                background=tint,
                display="flex",
                align_items="center",
                justify_content="center",
            ),
            align="center",
            width="100%",
        ),
        padding="20px",
        border_radius="12px",
        background="white",
        border="1px solid #e5e7eb",
        box_shadow="0 1px 2px rgba(0,0,0,0.04)",
        width="100%",
        _hover={"border_color": "#d1d5db"},
        transition="border-color 120ms ease",
    )


def kpi_cards() -> rx.Component:
    return rx.grid(
        _card(
            "INCIDENTS TOTAUX",
            DashboardState.incidents_total.to_string(),
            "database",
            "#eef2ff",
            "#4f46e5",
            hint="en base",
            tooltip=(
                "Nombre total d'incidents (rappels + retraits) en base, issus "
                "de la veille RappelConso et des signaux faibles promus. "
                "Inclut toutes les périodes."
            ),
        ),
        _card(
            "INCIDENTS SCORES",
            DashboardState.scores_total.to_string(),
            "gauge",
            "#ecfdf5",
            "#059669",
            hint="via pipeline",
            tooltip=(
                "Nombre d'incidents qui ont été scorés par l'évaluateur de "
                "sévérité (Agent 2). Le score 0-100 combine risque sanitaire "
                "(via Claude Haiku), ampleur géographique, population vulnérable "
                "et volume de distributeurs."
            ),
        ),
        _card(
            "CRITIQUES AFFICHES",
            DashboardState.count_by_tier["critique"].to_string(),
            "triangle_alert",
            "#fef2f2",
            "#dc2626",
            hint=DashboardState.row_count.to_string() + " lignes visibles",
            tooltip=(
                "Nombre d'incidents classés 'critique' (score ≥ 80/100) "
                "parmi ceux actuellement affichés dans le tableau ci-dessous. "
                "Le hint indique le total de lignes visibles (tous tiers confondus)."
            ),
        ),
        _card(
            "DERNIERE EVALUATION",
            DashboardState.last_score_at,
            "clock",
            "#fffbeb",
            "#d97706",
            hint="",
            tooltip=(
                "Date de la dernière exécution de l'évaluateur de sévérité "
                "(Agent 2). À recalculer après chaque rafraîchissement de la veille "
                "pour scorer les nouveaux incidents."
            ),
        ),
        style={
            "display": "grid",
            "grid-template-columns": "repeat(4, 1fr)",
            "gap": "16px",
            "width": "100%",
            "padding-bottom": "24px",
            "@media (max-width: 640px)": {
                "grid-template-columns": "repeat(2, 1fr)",
            },
        },
    )
