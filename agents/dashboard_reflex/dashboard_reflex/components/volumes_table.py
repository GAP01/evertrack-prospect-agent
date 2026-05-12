"""
Table des signaux volumes (bucket signalconso_volume).

Calque le pattern de signaux_table.py : KPI cards + filtres + table sortable.
Spécificités : pas de marque (pas de cellule marque), 1 cellule "Catégorie / Dept",
1 cellule "Pic vs baseline" (count actuel + médiane historique), score basé sur z_mod.
"""

from __future__ import annotations

import reflex as rx

from ..state import DashboardState
from .sortable_header import sortable_header


# ── Badges ────────────────────────────────────────────────────────────────────

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
        rx.text(label, size="1", weight="medium", color=color),
        background=bg,
        padding="2px 8px",
        border_radius="9999px",
        display="inline-block",
    )


def _score_bar(score: rx.Var[int]) -> rx.Component:
    pct = score.to_string()
    color = rx.cond(
        score >= 80,
        "linear-gradient(90deg, #f87171 0%, #dc2626 100%)",
        rx.cond(
            score >= 60,
            "linear-gradient(90deg, #fbbf24 0%, #d97706 100%)",
            rx.cond(
                score >= 40,
                "linear-gradient(90deg, #fde047 0%, #ca8a04 100%)",
                "linear-gradient(90deg, #d1d5db 0%, #9ca3af 100%)",
            ),
        ),
    )
    return rx.hstack(
        rx.box(
            rx.box(width=pct + "%", height="6px", background=color, border_radius="9999px"),
            width="90px", height="6px", background="#f3f4f6",
            border_radius="9999px", overflow="hidden",
        ),
        rx.text(pct, size="1", weight="bold", color="#111827", min_width="26px"),
        spacing="2",
        align="center",
    )


def _z_pill(z: rx.Var[float]) -> rx.Component:
    """Badge z-score modifié. >= 5 = rouge intense, sinon dégradé."""
    is_red = z >= 5.0
    bg = rx.cond(is_red, "#fee2e2", "#fef3c7")
    color = rx.cond(is_red, "#991b1b", "#854d0e")
    return rx.box(
        rx.hstack(
            rx.icon("trending_up", size=10, color=color),
            rx.text("z=" + z.to_string(), size="1", weight="bold", color=color),
            spacing="1",
            align="center",
        ),
        background=bg,
        padding="2px 8px",
        border_radius="9999px",
        display="inline-block",
        border="1px solid " + rx.cond(is_red, "#fecaca", "#fde68a").to(str),
    )


def _pic_vs_baseline(actual: rx.Var[int], median: rx.Var[float]) -> rx.Component:
    """Affichage compact : '<actual> vs ~<median>'."""
    return rx.hstack(
        rx.text(
            actual.to_string(),
            size="3", weight="bold", color="#111827",
        ),
        rx.text("vs", size="1", color="#9ca3af"),
        rx.text(
            "~" + median.to_string(),
            size="2", color="#6b7280",
        ),
        spacing="1",
        align="baseline",
    )


# ── KPI cards ─────────────────────────────────────────────────────────────────

def _kpi_card(label: str, value: rx.Var, icon: str, color: str, tooltip: str = "") -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.icon(icon, size=16, color=color),
                rx.text(label, size="1", color="#6b7280", weight="medium"),
                rx.spacer(),
                rx.cond(
                    tooltip != "",
                    rx.tooltip(rx.icon("circle_help", size=12, color="#9ca3af"), content=tooltip),
                ),
                spacing="2", align="center", width="100%",
            ),
            rx.text(value, size="6", weight="bold", color="#111827"),
            spacing="1", align="start",
        ),
        padding="20px",
        border_radius="12px",
        background="white",
        border="1px solid #e5e7eb",
        box_shadow="0 1px 2px rgba(0,0,0,0.04)",
        flex="1 1 140px",
    )


def _volume_kpi_row() -> rx.Component:
    return rx.box(
        _kpi_card(
            "Total anomalies",
            DashboardState.volume_total.to_string(),
            "activity",
            "#4f46e5",
            tooltip=(
                "Total de signaux 'volume' détectés via SignalConso. "
                "Un signal = un pic anormal sur un couple (catégorie, département, semaine ISO). "
                "Pas de marque associée — c'est un indicateur de zone géographique à investiguer."
            ),
        ),
        _kpi_card(
            "En alerte",
            DashboardState.volume_en_alerte.to_string(),
            "triangle_alert",
            "#dc2626",
            tooltip=(
                "Signaux au statut 'à valider' ou 'validé'. "
                "Statistiquement significatifs (z-score modifié ≥ 3.5). "
                "À examiner pour rapprocher avec un incident RappelConso."
            ),
        ),
        _kpi_card(
            "Top catégorie",
            DashboardState.volume_top_category,
            "list",
            "#7c3aed",
            tooltip=(
                "Catégorie SignalConso la plus représentée parmi les anomalies "
                "actuelles. Indique où la pression est la plus forte."
            ),
        ),
        _kpi_card(
            "Top département",
            DashboardState.volume_top_dep,
            "map_pin",
            "#0891b2",
            tooltip=(
                "Département concerné par le plus d'anomalies actuellement. "
                "Localisation à surveiller en priorité."
            ),
        ),
        _kpi_card(
            "Z-score max",
            DashboardState.volume_max_z,
            "trending_up",
            "#ea580c",
            tooltip=(
                "Z-score modifié (Iglewicz-Hoaglin) le plus élevé observé. "
                "Plus c'est haut, plus l'anomalie est statistiquement significative. "
                "Seuil de détection : 3.5."
            ),
        ),
        display="flex",
        flex_wrap="wrap",
        gap="16px",
        width="100%",
        padding_bottom="24px",
    )


# ── Filtres ───────────────────────────────────────────────────────────────────

def _volume_filters() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text("Statut", size="1", color="#6b7280", weight="medium"),
            rx.select(
                DashboardState.volume_status_options,
                value=DashboardState.volume_status_filter,
                on_change=DashboardState.set_volume_status_filter,
                size="2", width="140px",
            ),
            spacing="1", align="start",
        ),
        rx.vstack(
            rx.text("Catégorie", size="1", color="#6b7280", weight="medium"),
            rx.select(
                DashboardState.volume_categories_distinct,
                value=DashboardState.volume_category_filter,
                on_change=DashboardState.set_volume_category_filter,
                size="2", width="200px",
            ),
            spacing="1", align="start",
        ),
        rx.vstack(
            rx.text("Département", size="1", color="#6b7280", weight="medium"),
            rx.input(
                placeholder="Code (ex: 17)",
                value=DashboardState.volume_dep_filter,
                on_change=DashboardState.set_volume_dep_filter,
                size="2", width="120px",
            ),
            spacing="1", align="start",
        ),
        rx.vstack(
            rx.text("Score min", size="1", color="#6b7280", weight="medium"),
            rx.input(
                value=DashboardState.volume_min_score.to_string(),
                on_change=DashboardState.set_volume_min_score,
                type="number", size="2", width="90px",
            ),
            spacing="1", align="start",
        ),
        rx.vstack(
            rx.text("Limite", size="1", color="#6b7280", weight="medium"),
            rx.input(
                value=DashboardState.volume_limit.to_string(),
                on_change=DashboardState.set_volume_limit,
                type="number", size="2", width="100px",
            ),
            spacing="1", align="start",
        ),
        rx.hstack(
            rx.icon("filter", size=12, color="#6b7280"),
            rx.text(
                DashboardState.volume_row_count.to_string() + " anomalies",
                size="1", color="#6b7280",
            ),
            spacing="1", align="center",
        ),
        style={
            "display": "flex",
            "flex-wrap": "wrap",
            "gap": "12px",
            "align-items": "flex-end",
            "width": "100%",
            "padding-bottom": "16px",
            "@media (max-width: 640px)": {
                "flex-direction": "column",
                "align-items": "stretch",
            },
        },
    )


# ── Table ─────────────────────────────────────────────────────────────────────

def _header_cell(label: str, width: str | None = None) -> rx.Component:
    return rx.table.column_header_cell(
        rx.text(label, size="1", color="#6b7280", weight="bold", letter_spacing="0.04em"),
        width=width,
    )


def _vol_sortable(label: str, column_key: str, width: str | None = None) -> rx.Component:
    return sortable_header(
        label=label,
        column_key=column_key,
        sort_column_var=DashboardState.volume_sort_column,
        sort_direction_var=DashboardState.volume_sort_direction,
        on_click=DashboardState.set_volume_sort,
        width=width,
    )


def _volume_row(row: rx.Var[dict]) -> rx.Component:
    return rx.table.row(
        rx.table.cell(_status_badge(row["status"].to(str))),
        rx.table.cell(_score_bar(row["score"].to(int))),
        rx.table.cell(_z_pill(row["z_mod"].to(float))),
        rx.table.cell(_pic_vs_baseline(row["count_actuel"].to(int), row["baseline_median"].to(float))),
        rx.table.cell(
            rx.vstack(
                rx.text(row["category"].to(str), size="2", weight="medium", color="#111827"),
                rx.text(
                    row["dep_name"].to(str) + " (" + row["dep_code"].to(str) + ")",
                    size="1", color="#6b7280",
                ),
                spacing="0", align="start",
            ),
        ),
        rx.table.cell(
            rx.text(row["iso_week"].to(str), size="2", color="#374151", weight="medium"),
        ),
        rx.table.cell(
            rx.text(row["detected_at"].to(str), size="1", color="#6b7280"),
        ),
        rx.table.cell(
            rx.icon("chevron_right", size=14, color="#9ca3af"),
            text_align="right",
        ),
        on_click=DashboardState.open_volume(row["signal_id"]),
        cursor="pointer",
        _hover={"background": "#f9fafb"},
    )


def _empty_state() -> rx.Component:
    return rx.vstack(
        rx.icon("activity", size=32, color="#d1d5db"),
        rx.text("Aucune anomalie de volume détectée", size="3", weight="medium", color="#374151"),
        rx.text(
            "Lance le détecteur : python -m detecteur_signaux.cli fetch --sources signalconso_volume",
            size="2", color="#6b7280",
        ),
        spacing="2",
        align="center",
        padding="48px 24px",
        width="100%",
    )


def volumes_table() -> rx.Component:
    return rx.vstack(
        _volume_kpi_row(),
        rx.box(
            _volume_filters(),
            rx.box(
                rx.cond(
                    DashboardState.volume_row_count > 0,
                    rx.box(
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    _vol_sortable("Statut", "status", width="110px"),
                                    _vol_sortable("Score", "score", width="140px"),
                                    _vol_sortable("Z-mod", "z_mod", width="100px"),
                                    _vol_sortable("Pic vs baseline", "count_actuel", width="160px"),
                                    _vol_sortable("Catégorie / Dept", "category"),
                                    _vol_sortable("Semaine ISO", "iso_week", width="120px"),
                                    _vol_sortable("Détecté", "detected_at", width="110px"),
                                    _header_cell("", width="40px"),
                                ),
                            ),
                            rx.table.body(
                                rx.foreach(DashboardState.volume_rows, _volume_row),
                            ),
                            variant="surface",
                            size="2",
                            min_width="900px",
                        ),
                        overflow_x="auto",
                        width="100%",
                    ),
                    _empty_state(),
                ),
                width="100%",
                border_radius="12px",
                border="1px solid #e5e7eb",
                background="white",
                overflow="hidden",
                box_shadow="0 1px 2px rgba(0,0,0,0.04)",
            ),
            width="100%",
        ),
        width="100%",
        spacing="0",
    )
