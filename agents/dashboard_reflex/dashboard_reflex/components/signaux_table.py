"""
Table des signaux faibles — vue Agent détecteur.

Affiche marque + symptôme + score (barre colorée) + status + source primaire.
Clic sur une ligne ouvre le drawer détail.
"""

from __future__ import annotations

import reflex as rx

from ..state import DashboardState
from .sortable_header import sortable_header


# ── Badges ────────────────────────────────────────────────────────────────────

def _status_badge(status: rx.Var[str]) -> rx.Component:
    """Badge coloré selon le status du signal."""
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
            rx.box(
                width=pct + "%",
                height="6px",
                background=color,
                border_radius="9999px",
            ),
            width="90px",
            height="6px",
            background="#f3f4f6",
            border_radius="9999px",
            overflow="hidden",
        ),
        rx.text(
            pct,
            size="1",
            weight="bold",
            color="#111827",
            min_width="26px",
        ),
        spacing="2",
        align="center",
    )


def _recurrence_badge(n: rx.Var[int]) -> rx.Component:
    """Badge récurrence avec picto. Couleur graduée selon intensité.

    - n >= 3 : orange vif (signal très relayé)
    - n = 2  : orange clair
    - n = 1  : gris discret (signal isolé)
    - n = 0  : vide
    """
    is_hot = n >= 3
    is_warm = n == 2
    bg = rx.cond(
        is_hot, "#fed7aa",           # orange-200
        rx.cond(is_warm, "#fef3c7",  # amber-100
                "#f3f4f6"),           # gray-100
    )
    color = rx.cond(
        is_hot, "#9a3412",            # orange-800
        rx.cond(is_warm, "#854d0e",   # amber-800
                "#6b7280"),            # gray-500
    )
    border = rx.cond(
        is_hot, "1px solid #fb923c",
        rx.cond(is_warm, "1px solid #fcd34d",
                "1px solid #e5e7eb"),
    )
    return rx.hstack(
        rx.icon("layers", size=12, color=color),
        rx.text(
            n.to_string(),
            size="2",
            weight="bold",
            color=color,
            min_width="14px",
        ),
        spacing="1",
        align="center",
        background=bg,
        padding="3px 8px",
        border_radius="9999px",
        border=border,
        display="inline-flex",
    )


def _source_type_pill(stype: rx.Var[str]) -> rx.Component:
    icon = rx.cond(stype == "google_news", "newspaper", "message_square")
    bg = rx.cond(stype == "google_news", "#eef2ff", "#fef3c7")
    color = rx.cond(stype == "google_news", "#4338ca", "#92400e")
    label = rx.cond(stype == "google_news", "News", "Reddit")
    return rx.hstack(
        rx.icon(icon, size=10, color=color),
        rx.text(label, size="1", weight="medium", color=color),
        spacing="1",
        align="center",
        background=bg,
        padding="2px 6px",
        border_radius="9999px",
        display="inline-flex",
    )


# ── KPI cards ─────────────────────────────────────────────────────────────────

def _signal_kpi_card(
    label: str,
    value: rx.Var,
    icon: str,
    color: str,
    tooltip: str = "",
) -> rx.Component:
    """Carte KPI avec icône d'info cliquable (tooltip explicatif)."""
    card = rx.box(
        rx.vstack(
            rx.hstack(
                rx.icon(icon, size=16, color=color),
                rx.text(label, size="1", color="#6b7280", weight="medium"),
                rx.spacer(),
                rx.cond(
                    tooltip != "",
                    rx.tooltip(
                        rx.icon("circle_help", size=12, color="#9ca3af"),
                        content=tooltip,
                    ),
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            rx.text(value, size="6", weight="bold", color="#111827"),
            spacing="1",
            align="start",
        ),
        padding="20px",
        border_radius="12px",
        background="white",
        border="1px solid #e5e7eb",
        box_shadow="0 1px 2px rgba(0,0,0,0.04)",
        flex="1 1 140px",
    )
    return card


def _signal_kpi_row() -> rx.Component:
    return rx.box(
        _signal_kpi_card(
            "Total signaux",
            DashboardState.signal_total.to_string(),
            "radio_tower",
            "#4f46e5",
            tooltip=(
                "Nombre total de signaux détectés via Google News et Reddit. "
                "Un signal = un événement (rappel potentiel, alerte, buzz) "
                "identifié par sa marque + symptôme + semaine."
            ),
        ),
        _signal_kpi_card(
            "En alerte",
            DashboardState.signal_en_alerte.to_string(),
            "triangle_alert",
            "#dc2626",
            tooltip=(
                "Signaux au statut 'à valider' ou 'validé' — c'est-à-dire "
                "dont le score de crédibilité dépasse le seuil (40/100) ou "
                "qui ont été validés manuellement. À examiner en priorité."
            ),
        ),
        _signal_kpi_card(
            "A valider",
            DashboardState.signal_a_valider.to_string(),
            "circle_help",
            "#d97706",
            tooltip=(
                "Signaux qui ont franchi automatiquement le seuil de "
                "crédibilité (score ≥ 40) et attendent ta décision "
                "humaine (Valider / Rejeter / Promouvoir en incident)."
            ),
        ),
        _signal_kpi_card(
            "Matchs rappels",
            DashboardState.strong_matches.to_string()
            + " / "
            + DashboardState.total_matches.to_string(),
            "link",
            "#0891b2",
            tooltip=(
                "Correspondances entre signaux et rappels officiels RappelConso. "
                "Format : 'matchs forts (≥70%) / total des matchs possibles (≥50%)'. "
                "Un match fort indique une forte probabilité que signal et rappel "
                "concernent le même événement."
            ),
        ),
        _signal_kpi_card(
            "Lead time moyen",
            DashboardState.avg_lead_time,
            "zap",
            "#16a34a",
            tooltip=(
                "Délai moyen (en jours) entre la détection d'un signal et la "
                "publication du rappel officiel correspondant — calculé sur "
                "les matchs forts (≥70%) où le signal précède le rappel. "
                "Positif = nous avons détecté en avance. Idéal : le plus élevé possible."
            ),
        ),
        _signal_kpi_card(
            "Marques sous pression",
            DashboardState.n_brands_under_pressure.to_string(),
            "flame",
            "#ea580c",
            tooltip=(
                "Nombre de marques mentionnées dans au moins 2 signaux "
                "distincts sur les 7 derniers jours. Indicateur de pression "
                "médiatique : une marque sous pression récurrente mérite "
                "une attention particulière, même si chaque signal isolé est faible."
            ),
        ),
        display="flex",
        flex_wrap="wrap",
        gap="16px",
        width="100%",
        padding_bottom="24px",
    )


# ── Filtres ───────────────────────────────────────────────────────────────────

def _signaux_filters() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text("Recherche", size="1", color="#6b7280", weight="medium"),
            rx.debounce_input(
                rx.input(
                    value=DashboardState.signal_search,
                    on_change=DashboardState.set_signal_search,
                    placeholder="Marque, symptome ou titre...",
                    size="2",
                    width="220px",
                ),
                debounce_timeout=300,
            ),
            spacing="1",
            align="start",
        ),
        rx.vstack(
            rx.text("Statut", size="1", color="#6b7280", weight="medium"),
            rx.select(
                DashboardState.signal_status_options,
                value=DashboardState.signal_status_filter,
                on_change=DashboardState.set_signal_status_filter,
                size="2",
                width="100%",
            ),
            spacing="1",
            align="start",
        ),
        rx.vstack(
            rx.text("Du", size="1", color="#6b7280", weight="medium"),
            rx.input(
                value=DashboardState.signal_date_from,
                on_change=DashboardState.set_signal_date_from,
                type="date",
                size="2",
                width="150px",
            ),
            spacing="1",
            align="start",
        ),
        rx.vstack(
            rx.text("Au", size="1", color="#6b7280", weight="medium"),
            rx.input(
                value=DashboardState.signal_date_to,
                on_change=DashboardState.set_signal_date_to,
                type="date",
                size="2",
                width="150px",
            ),
            spacing="1",
            align="start",
        ),
        rx.vstack(
            rx.text("Limite", size="1", color="#6b7280", weight="medium"),
            rx.input(
                value=DashboardState.signal_limit.to_string(),
                on_change=DashboardState.set_signal_limit,
                type="number",
                size="2",
                width="100px",
            ),
            spacing="1",
            align="start",
        ),
        rx.vstack(
            rx.text(" ", size="1"),
            rx.button(
                rx.icon("x", size=14),
                "Reinitialiser",
                on_click=DashboardState.reset_signal_filters,
                variant="soft",
                color_scheme="gray",
                size="2",
            ),
            spacing="1",
            align="start",
        ),
        rx.hstack(
            rx.icon("filter", size=12, color="#6b7280"),
            rx.text(
                DashboardState.signal_row_count.to_string() + " signaux",
                size="1",
                color="#6b7280",
            ),
            spacing="1",
            align="center",
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


def _signal_sortable(label: str, column_key: str, width: str | None = None) -> rx.Component:
    """Header cliquable pour trier la grille Signaux."""
    return sortable_header(
        label=label,
        column_key=column_key,
        sort_column_var=DashboardState.signal_sort_column,
        sort_direction_var=DashboardState.signal_sort_direction,
        on_click=DashboardState.set_signal_sort,
        width=width,
    )


def _signal_row(row: rx.Var[dict]) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            _status_badge(row["status"].to(str)),
        ),
        rx.table.cell(
            _recurrence_badge(row["n_sources"].to(int)),
        ),
        rx.table.cell(
            rx.text(
                row["detected_at"].to(str),
                size="2",
                color="#374151",
                weight="medium",
            ),
        ),
        rx.table.cell(
            _score_bar(row["score"].to(int)),
        ),
        rx.table.cell(
            rx.vstack(
                rx.text(
                    rx.cond(
                        row["marque"].to(str) != "",
                        row["marque"].to(str),
                        "(marque inconnue)",
                    ),
                    size="2",
                    weight="medium",
                    color="#111827",
                ),
                rx.text(row["symptome"].to(str), size="1", color="#dc2626"),
                spacing="0",
                align="start",
            ),
        ),
        rx.table.cell(
            rx.text(
                row["titre"].to(str),
                size="2",
                color="#374151",
                style={
                    "display": "-webkit-box",
                    "-webkit-line-clamp": "2",
                    "-webkit-box-orient": "vertical",
                    "overflow": "hidden",
                    "max_width": "360px",
                },
            ),
        ),
        rx.table.cell(
            rx.vstack(
                _source_type_pill(row["source_type"].to(str)),
                rx.text(row["source_name"].to(str), size="1", color="#6b7280"),
                spacing="1",
                align="start",
            ),
        ),
        rx.table.cell(
            rx.icon("chevron_right", size=14, color="#9ca3af"),
            text_align="right",
        ),
        on_click=DashboardState.open_signal(row["signal_id"]),
        cursor="pointer",
        _hover={"background": "#f9fafb"},
    )


def _empty_state() -> rx.Component:
    return rx.vstack(
        rx.icon("radio_tower", size=32, color="#d1d5db"),
        rx.text("Aucun signal détecté", size="3", weight="medium", color="#374151"),
        rx.text(
            "Lance le détecteur depuis le terminal : python -m detecteur_signaux.cli fetch",
            size="2",
            color="#6b7280",
        ),
        spacing="2",
        align="center",
        padding="48px 24px",
        width="100%",
    )


def signaux_table() -> rx.Component:
    return rx.vstack(
        _signal_kpi_row(),
        rx.box(
            _signaux_filters(),
            rx.box(
                rx.cond(
                    DashboardState.signal_row_count > 0,
                    rx.box(
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    _signal_sortable("Statut", "status", width="110px"),
                                    _signal_sortable("Récurrence", "n_sources", width="90px"),
                                    _signal_sortable("Publié le", "detected_at", width="110px"),
                                    _signal_sortable("Score", "score", width="140px"),
                                    _signal_sortable("Marque / Symptôme", "marque"),
                                    _signal_sortable("Titre", "titre"),
                                    _signal_sortable("Source", "source_name"),
                                    _header_cell("", width="40px"),
                                ),
                            ),
                            rx.table.body(
                                rx.foreach(DashboardState.signal_rows, _signal_row),
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
