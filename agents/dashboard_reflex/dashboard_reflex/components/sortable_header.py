"""
Cellule d'en-tête de table cliquable pour le tri.

Utilisable sur les 3 grilles (incidents, signaux, prospects) en passant
les vars et le handler correspondants.

Affiche :
- Label
- Icône discrète `chevrons_up_down` gris si la colonne n'est pas active
- Icône `arrow_up` ou `arrow_down` indigo si active dans la direction courante

Sans clic, garde le tri par défaut du data layer. Premier clic = DESC.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import reflex as rx


def sortable_header(
    label: str,
    column_key: str,
    sort_column_var: Any,
    sort_direction_var: Any,
    on_click: Callable[[str], Any],
    width: Optional[str] = None,
) -> rx.Component:
    """
    Retourne un `rx.table.column_header_cell` cliquable avec indicateur visuel.

    Args:
        label: texte affiché
        column_key: clé de la colonne (doit matcher un champ des rows normalisés)
        sort_column_var: Var d'état représentant la colonne actuellement triée
        sort_direction_var: Var d'état "asc" ou "desc"
        on_click: event handler (ex: DashboardState.set_signal_sort) qui
            reçoit le column_key en argument
        width: largeur CSS optionnelle de la colonne
    """
    is_active = sort_column_var == column_key
    is_asc = sort_direction_var == "asc"
    return rx.table.column_header_cell(
        rx.hstack(
            rx.text(
                label,
                size="1",
                color=rx.cond(is_active, "#4338ca", "#6b7280"),
                weight="bold",
                letter_spacing="0.04em",
            ),
            rx.cond(
                is_active,
                rx.cond(
                    is_asc,
                    rx.icon("arrow_up", size=12, color="#4338ca"),
                    rx.icon("arrow_down", size=12, color="#4338ca"),
                ),
                rx.icon("chevrons_up_down", size=10, color="#d1d5db"),
            ),
            spacing="1",
            align="center",
        ),
        on_click=on_click(column_key),
        cursor="pointer",
        _hover={"background": "#f3f4f6"},
        transition="background 100ms ease",
        width=width,
        user_select="none",
    )
