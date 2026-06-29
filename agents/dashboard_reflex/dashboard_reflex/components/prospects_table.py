"""
Table des prospects enrichis — vue Agents 3.

Affiche les résultats d'enrichissement : entreprise trouvée, contact,
contact_type (cible vs fallback_dirigeant), confidence, match_status.
"""

from __future__ import annotations

import reflex as rx

from ..state import DashboardState
from .sortable_header import sortable_header


# ── Badges ───────────────────────────────────────────────────────────────────

def _match_status_badge(status: rx.Var[str]) -> rx.Component:
    """Badge coloré selon le match_status."""
    bg = rx.match(
        status,
        ("found",     "#dcfce7"),
        ("ambiguous", "#fef9c3"),
        ("not_found", "#fee2e2"),
        ("skipped",   "#f3f4f6"),
        "#f3f4f6",
    )
    color = rx.match(
        status,
        ("found",     "#166534"),
        ("ambiguous", "#854d0e"),
        ("not_found", "#991b1b"),
        ("skipped",   "#6b7280"),
        "#6b7280",
    )
    label = rx.match(
        status,
        ("found",     "Trouve"),
        ("ambiguous", "Ambigu"),
        ("not_found", "Non trouve"),
        ("skipped",   "Ignore"),
        status,
    )
    return rx.box(
        rx.text(label, size="1", weight="medium", color=color),
        background=bg,
        padding="2px 8px",
        border_radius="9999px",
        display="inline-block",
    )


def _contact_type_badge(ctype: rx.Var[str]) -> rx.Component:
    """Badge cible (vert) ou fallback_dirigeant (orange)."""
    return rx.cond(
        ctype == "cible",
        rx.box(
            rx.text("Cible", size="1", weight="medium", color="#166534"),
            background="#dcfce7",
            padding="2px 8px",
            border_radius="9999px",
            display="inline-block",
        ),
        rx.cond(
            ctype == "fallback_dirigeant",
            rx.box(
                rx.text("Dirigeant", size="1", weight="medium", color="#92400e"),
                background="#fef3c7",
                padding="2px 8px",
                border_radius="9999px",
                display="inline-block",
            ),
            rx.box(
                rx.text("-", size="1", color="#9ca3af"),
                display="inline-block",
            ),
        ),
    )


def _confidence_bar(confidence: rx.Var[float]) -> rx.Component:
    pct = (confidence * 100).to_string()
    color = rx.cond(
        confidence >= 0.72,
        "linear-gradient(90deg, #4ade80 0%, #16a34a 100%)",
        rx.cond(
            confidence >= 0.40,
            "linear-gradient(90deg, #fbbf24 0%, #d97706 100%)",
            "linear-gradient(90deg, #f87171 0%, #dc2626 100%)",
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
            width="80px",
            height="6px",
            background="#f3f4f6",
            border_radius="9999px",
            overflow="hidden",
        ),
        rx.text(
            (confidence * 100).to_string() + "%",
            size="1",
            color="#6b7280",
            min_width="36px",
        ),
        spacing="2",
        align="center",
    )


# ── Filtres ───────────────────────────────────────────────────────────────────

def _prospects_filters() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text("Recherche", size="1", color="#6b7280", weight="medium"),
            rx.debounce_input(
                rx.input(
                    value=DashboardState.enrich_search,
                    on_change=DashboardState.set_enrich_search,
                    placeholder="Marque, entreprise ou contact...",
                    size="2",
                    width="240px",
                ),
                debounce_timeout=300,
            ),
            spacing="1",
            align="start",
        ),
        rx.vstack(
            rx.text("Statut match", size="1", color="#6b7280", weight="medium"),
            rx.select(
                DashboardState.enrich_match_options,
                value=DashboardState.enrich_match_filter,
                on_change=DashboardState.set_enrich_match_filter,
                size="2",
                width="100%",
            ),
            spacing="1",
            align="start",
        ),
        rx.vstack(
            rx.text("Limite", size="1", color="#6b7280", weight="medium"),
            rx.input(
                value=DashboardState.enrich_limit.to_string(),
                on_change=DashboardState.set_enrich_limit,
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
                on_click=DashboardState.reset_enrich_filters,
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
                DashboardState.enrich_row_count.to_string() + " prospects",
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


# ── KPI cards Prospects ───────────────────────────────────────────────────────

def _enrich_kpi_card(
    label: str,
    value: rx.Var,
    icon: str,
    color: str,
    tooltip: str = "",
) -> rx.Component:
    return rx.box(
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


def _enrich_kpi_row() -> rx.Component:
    return rx.box(
        _enrich_kpi_card(
            "Total enrichis",
            DashboardState.enrich_total.to_string(),
            "database",
            "#4f46e5",
            tooltip=(
                "Nombre total d'incidents dont la marque a été passée au matching "
                "SIRENE (Agent 3). Inclut les matchs réussis, ambigus et échoués."
            ),
        ),
        _enrich_kpi_card(
            "Match trouve",
            DashboardState.enrich_found.to_string(),
            "check_check",
            "#16a34a",
            tooltip=(
                "Incidents avec une entreprise identifiée de manière fiable "
                "(confidence ≥ 72%). La raison sociale SIRENE correspond bien "
                "à la marque de l'incident."
            ),
        ),
        _enrich_kpi_card(
            "Avec contact",
            DashboardState.enrich_with_contact.to_string(),
            "user",
            "#0891b2",
            tooltip=(
                "Incidents pour lesquels un contact a été identifié (via SIRENE "
                "dirigeants légaux ou via Pappers). C'est le point de départ "
                "pour l'outreach commercial."
            ),
        ),
        _enrich_kpi_card(
            "Profil cible",
            DashboardState.enrich_with_cible.to_string(),
            "target",
            "#dc2626",
            tooltip=(
                "Contacts identifiés comme 'profil cible' : responsables qualité, "
                "supply chain, conformité ou traçabilité. À l'inverse du "
                "'fallback_dirigeant' (gérant/PDG), ces profils sont directement "
                "en charge des problématiques de rappel."
            ),
        ),
        display="flex",
        flex_wrap="wrap",
        gap="16px",
        width="100%",
        padding_bottom="24px",
    )


# ── Table ─────────────────────────────────────────────────────────────────────

def _prospect_sortable(label: str, column_key: str, width: str | None = None) -> rx.Component:
    """Header cliquable pour trier la grille Prospects."""
    return sortable_header(
        label=label,
        column_key=column_key,
        sort_column_var=DashboardState.prospect_sort_column,
        sort_direction_var=DashboardState.prospect_sort_direction,
        on_click=DashboardState.set_prospect_sort,
        width=width,
    )


def _header_cell(label: str, width: str | None = None) -> rx.Component:
    return rx.table.column_header_cell(
        rx.text(label, size="1", color="#6b7280", weight="bold", letter_spacing="0.04em"),
        width=width,
    )


def _prospect_row(row: rx.Var[dict]) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            _match_status_badge(row["match_status"].to(str)),
        ),
        rx.table.cell(
            rx.text(row["marque_input"].to(str), size="2", weight="medium", color="#111827"),
        ),
        rx.table.cell(
            rx.vstack(
                rx.text(row["raison_sociale"].to(str), size="2", weight="medium", color="#111827"),
                rx.text(row["siren"].to(str), size="1", color="#9ca3af"),
                spacing="0",
                align="start",
            ),
        ),
        rx.table.cell(
            _confidence_bar(row["confidence"].to(float)),
        ),
        rx.table.cell(
            rx.cond(
                row["contact_nom"].to(str) != "",
                rx.vstack(
                    rx.hstack(
                        rx.text(
                            row["contact_nom"].to(str),
                            size="2",
                            color="#111827",
                            style={
                                "display": "-webkit-box",
                                "-webkit-line-clamp": "1",
                                "-webkit-box-orient": "vertical",
                                "overflow": "hidden",
                                "max_width": "160px",
                            },
                        ),
                        _contact_type_badge(row["contact_type"].to(str)),
                        spacing="2",
                        align="center",
                    ),
                    rx.text(
                        row["contact_titre"].to(str),
                        size="1",
                        color="#6b7280",
                        style={
                            "display": "-webkit-box",
                            "-webkit-line-clamp": "1",
                            "-webkit-box-orient": "vertical",
                            "overflow": "hidden",
                            "max_width": "200px",
                        },
                    ),
                    spacing="0",
                    align="start",
                ),
                rx.text("-", size="2", color="#9ca3af"),
            ),
        ),
        rx.table.cell(
            rx.text(
                row["adresse"].to(str),
                size="1",
                color="#6b7280",
                style={
                    "display": "-webkit-box",
                    "-webkit-line-clamp": "2",
                    "-webkit-box-orient": "vertical",
                    "overflow": "hidden",
                    "max_width": "200px",
                },
            ),
        ),
        rx.table.cell(
            rx.icon("chevron_right", size=14, color="#9ca3af"),
            text_align="right",
        ),
        on_click=DashboardState.open_prospect(
            row["source"],
            row["source_id"],
        ),
        cursor="pointer",
        _hover={"background": "#f9fafb"},
    )


def _empty_state() -> rx.Component:
    return rx.vstack(
        rx.icon("building_2", size=32, color="#d1d5db"),
        rx.text("Aucun prospect enrichi", size="3", weight="medium", color="#374151"),
        rx.text(
            "Lance l'enrichisseur depuis le terminal : python -m enrichisseur_prospects.cli enrich",
            size="2",
            color="#6b7280",
        ),
        spacing="2",
        align="center",
        padding="48px 24px",
        width="100%",
    )


def prospects_table() -> rx.Component:
    return rx.vstack(
        _enrich_kpi_row(),
        rx.box(
            _prospects_filters(),
            rx.box(
                rx.cond(
                    DashboardState.enrich_row_count > 0,
                    rx.box(
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    _prospect_sortable("Statut", "match_status", width="110px"),
                                    _prospect_sortable("Marque", "marque_input"),
                                    _prospect_sortable("Entreprise SIRENE", "raison_sociale"),
                                    _prospect_sortable("Confiance", "confidence", width="130px"),
                                    _prospect_sortable("Contact", "contact_nom"),
                                    _prospect_sortable("Adresse", "adresse"),
                                    _header_cell("", width="40px"),
                                ),
                            ),
                            rx.table.body(
                                rx.foreach(DashboardState.enrich_rows, _prospect_row),
                            ),
                            variant="surface",
                            size="2",
                            min_width="700px",
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
