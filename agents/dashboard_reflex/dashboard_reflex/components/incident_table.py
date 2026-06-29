"""
Table principale : liste des incidents tries par severite.

Chaque ligne est clickable et ouvre le drawer de detail.
Style : entete gris leger, lignes au hover, typographie serree.
"""

from __future__ import annotations

import reflex as rx

from ..state import DashboardState
from .tier_badge import tier_badge
from .sortable_header import sortable_header


def _filter_select(
    label: str,
    value: rx.Var[str],
    options: rx.Var[list[str]],
    on_change,
) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="1", color="#6b7280", weight="medium"),
        rx.select(
            options,
            value=value,
            on_change=on_change,
            size="2",
            width="180px",
        ),
        spacing="1",
        align="start",
    )


def _search_field(
    label: str,
    value: rx.Var[str],
    on_change,
    placeholder: str,
    width: str = "220px",
) -> rx.Component:
    """Champ de recherche texte avec debounce (evite un refetch par frappe)."""
    return rx.vstack(
        rx.text(label, size="1", color="#6b7280", weight="medium"),
        rx.debounce_input(
            rx.input(
                value=value,
                on_change=on_change,
                placeholder=placeholder,
                size="2",
                width=width,
            ),
            debounce_timeout=300,
        ),
        spacing="1",
        align="start",
    )


def _date_field(label: str, value: rx.Var[str], on_change) -> rx.Component:
    """Champ date (type=date) pour borner une plage."""
    return rx.vstack(
        rx.text(label, size="1", color="#6b7280", weight="medium"),
        rx.input(
            value=value,
            on_change=on_change,
            type="date",
            size="2",
            width="150px",
        ),
        spacing="1",
        align="start",
    )


def _filters_row() -> rx.Component:
    return rx.box(
        _search_field(
            "Recherche",
            DashboardState.incident_search,
            DashboardState.set_incident_search,
            "Marque ou motif...",
        ),
        _filter_select(
            "Severite",
            DashboardState.tier_filter,
            DashboardState.tier_options,
            DashboardState.set_tier_filter,
        ),
        _filter_select(
            "Sous-categorie",
            DashboardState.sous_cat_filter,
            DashboardState.sous_cat_options,
            DashboardState.set_sous_cat_filter,
        ),
        _date_field("Du", DashboardState.incident_date_from, DashboardState.set_incident_date_from),
        _date_field("Au", DashboardState.incident_date_to, DashboardState.set_incident_date_to),
        rx.vstack(
            rx.text("Limite", size="1", color="#6b7280", weight="medium"),
            rx.input(
                value=DashboardState.limit.to_string(),
                on_change=DashboardState.set_limit,
                type="number",
                size="2",
                width="100px",
            ),
            spacing="1",
            align="start",
        ),
        rx.vstack(
            rx.text(" ", size="1"),
            rx.button(
                rx.icon("x", size=14),
                "Reinitialiser",
                on_click=DashboardState.reset_incident_filters,
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
                DashboardState.row_count.to_string() + " resultats",
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


def _incident_sortable(label: str, column_key: str, width: str | None = None) -> rx.Component:
    """Header cliquable pour trier la grille Radar incidents."""
    return sortable_header(
        label=label,
        column_key=column_key,
        sort_column_var=DashboardState.incident_sort_column,
        sort_direction_var=DashboardState.incident_sort_direction,
        on_click=DashboardState.set_incident_sort,
        width=width,
    )


def _header_cell(label: str, width: str | None = None) -> rx.Component:
    return rx.table.column_header_cell(
        rx.text(
            label,
            size="1",
            color="#6b7280",
            weight="bold",
            letter_spacing="0.04em",
        ),
        width=width,
    )


def _row(row: rx.Var[dict]) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.hstack(
                rx.box(
                    rx.text(
                        row["score"].to_string(),
                        size="2",
                        weight="bold",
                        color="#111827",
                    ),
                    min_width="32px",
                ),
                tier_badge(row["tier"]),
                spacing="2",
                align="center",
            ),
        ),
        rx.table.cell(
            rx.text(
                row["date"],
                size="2",
                color="#374151",
            ),
        ),
        rx.table.cell(
            rx.text(
                row["marque"],
                size="2",
                weight="medium",
                color="#111827",
            ),
        ),
        rx.table.cell(
            rx.text(
                row["sous_categorie"],
                size="2",
                color="#6b7280",
            ),
        ),
        rx.table.cell(
            rx.text(
                row["motif_rappel"],
                size="2",
                color="#374151",
                style={
                    "display": "-webkit-box",
                    "-webkit-line-clamp": "2",
                    "-webkit-box-orient": "vertical",
                    "overflow": "hidden",
                    "max_width": "420px",
                },
            ),
        ),
        rx.table.cell(
            rx.icon("chevron_right", size=14, color="#9ca3af"),
            text_align="right",
        ),
        on_click=DashboardState.open_incident(
            row["source"],
            row["source_id"],
        ),
        cursor="pointer",
        _hover={"background": "#f9fafb"},
    )


def _empty_state() -> rx.Component:
    return rx.vstack(
        rx.icon("inbox", size=32, color="#d1d5db"),
        rx.text("Aucun incident", size="3", weight="medium", color="#374151"),
        rx.text(
            "Declenche une veille ou ajuste tes filtres.",
            size="2",
            color="#6b7280",
        ),
        spacing="2",
        align="center",
        padding="48px 24px",
        width="100%",
    )


def incident_table() -> rx.Component:
    return rx.box(
        _filters_row(),
        rx.box(
            rx.cond(
                DashboardState.row_count > 0,
                rx.box(
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                _incident_sortable("Score", "score", width="180px"),
                                _incident_sortable("Date", "date", width="110px"),
                                _incident_sortable("Marque", "marque"),
                                _incident_sortable("Sous-categorie", "sous_categorie"),
                                _incident_sortable("Motif", "motif_rappel"),
                                _header_cell("", width="40px"),
                            ),
                        ),
                        rx.table.body(
                            rx.foreach(DashboardState.rows, _row),
                        ),
                        variant="surface",
                        size="2",
                        min_width="640px",
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
    )
