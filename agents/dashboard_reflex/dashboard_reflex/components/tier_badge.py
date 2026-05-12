"""
Pastille de tier (critique / eleve / modere / faible).

On utilise un match sur le tier pour piloter le background / foreground, dans
l'esprit Linear (pill serrée, teinte saturée mais pas criarde).
"""

from __future__ import annotations

import reflex as rx


# Palette : bg soft + texte sombre, dans la gamme indigo/rouge/orange/jaune.
_TIER_STYLES: dict[str, dict[str, str]] = {
    "critique": {
        "background": "#fee2e2",
        "color": "#991b1b",
        "border": "1px solid #fecaca",
    },
    "eleve": {
        "background": "#ffedd5",
        "color": "#9a3412",
        "border": "1px solid #fed7aa",
    },
    "modere": {
        "background": "#fef9c3",
        "color": "#854d0e",
        "border": "1px solid #fde68a",
    },
    "faible": {
        "background": "#e5e7eb",
        "color": "#374151",
        "border": "1px solid #d1d5db",
    },
}

_DEFAULT_STYLE = _TIER_STYLES["faible"]


def tier_badge(tier: rx.Var[str] | str, size: str = "1") -> rx.Component:
    """Badge de tier avec couleur dependante.

    On construit 4 badges et on les affiche conditionnellement (Reflex ne
    permet pas d'indexer un dict Python par une Var cote client).
    """

    def pill(label: str) -> rx.Component:
        style = _TIER_STYLES.get(label, _DEFAULT_STYLE)
        return rx.box(
            label.upper(),
            style={
                "display": "inline-flex",
                "align_items": "center",
                "padding": "2px 8px",
                "border_radius": "9999px",
                "font_size": "11px",
                "font_weight": "600",
                "letter_spacing": "0.02em",
                "background": style["background"],
                "color": style["color"],
                "border": style["border"],
                "white_space": "nowrap",
            },
        )

    return rx.match(
        tier,
        ("critique", pill("critique")),
        ("eleve", pill("eleve")),
        ("modere", pill("modere")),
        ("faible", pill("faible")),
        pill("faible"),
    )
