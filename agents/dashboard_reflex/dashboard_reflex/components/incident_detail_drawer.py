"""
Drawer lateral droit avec le detail complet d'un incident + breakdown du score.

NB sur les Vars de dict :
- `.to(str)` est un cast de type (sortie brute, sans quotes).
- `.to_string()` fait JSON.stringify (ajoute des guillemets autour des
  strings). A reserver aux besoins de debug / injection JS.
"""

from __future__ import annotations

import reflex as rx

from ..state import DashboardState
from .tier_badge import tier_badge


def _meta_row(label: str, value) -> rx.Component:
    return rx.hstack(
        rx.text(
            label,
            size="1",
            color="#6b7280",
            weight="medium",
            letter_spacing="0.04em",
            min_width="140px",
        ),
        rx.text(value, size="2", color="#111827"),
        spacing="3",
        align="start",
        width="100%",
    )


def _dimension_bar(dim: rx.Var[dict]) -> rx.Component:
    score = dim["score"].to(float)
    weight = dim["weight"].to(float)
    return rx.vstack(
        rx.hstack(
            rx.text(
                dim["name"].to(str),
                size="2",
                weight="medium",
                color="#111827",
            ),
            rx.spacer(),
            rx.text(
                "pond. " + (weight * 100).to_string() + "%",
                size="1",
                color="#9ca3af",
            ),
            rx.text(
                score.to_string() + "/100",
                size="2",
                weight="bold",
                color="#4f46e5",
                min_width="60px",
                text_align="right",
            ),
            width="100%",
            align="center",
        ),
        rx.box(
            rx.box(
                width=score.to_string() + "%",
                height="6px",
                background="linear-gradient(90deg, #818cf8 0%, #4f46e5 100%)",
                border_radius="9999px",
            ),
            width="100%",
            height="6px",
            background="#f3f4f6",
            border_radius="9999px",
            overflow="hidden",
        ),
        rx.cond(
            dim["reason"].to(str) != "",
            rx.text(
                dim["reason"].to(str),
                size="1",
                color="#6b7280",
                font_style="italic",
            ),
        ),
        spacing="2",
        width="100%",
        padding_bottom="12px",
    )


def _section_title(text: str) -> rx.Component:
    return rx.text(
        text,
        size="1",
        color="#9ca3af",
        weight="bold",
        letter_spacing="0.08em",
        padding_top="16px",
        padding_bottom="8px",
    )


def _match_score_pill(score: rx.Var[float]) -> rx.Component:
    """Pastille colorée selon force du match (strong >= 0.7 vert, sinon jaune)."""
    is_strong = score >= 0.70
    bg = rx.cond(is_strong, "#dcfce7", "#fef9c3")
    color = rx.cond(is_strong, "#166534", "#854d0e")
    label = rx.cond(is_strong, "Fort", "Possible")
    pct = (score * 100).to(int).to_string() + "%"
    return rx.hstack(
        rx.text(label, size="1", weight="bold", color=color),
        rx.text(pct, size="1", color=color),
        spacing="1",
        align="center",
        background=bg,
        padding="2px 8px",
        border_radius="9999px",
        display="inline-flex",
    )


def _lead_time_badge(lead: rx.Var[int]) -> rx.Component:
    """Lead time : positif = signal AVANT le rappel officiel (early warning)."""
    is_ahead = lead > 0
    is_after = lead < 0
    bg = rx.cond(is_ahead, "#dbeafe", rx.cond(is_after, "#fef3c7", "#f3f4f6"))
    color = rx.cond(is_ahead, "#1e40af", rx.cond(is_after, "#92400e", "#6b7280"))
    icon = rx.cond(is_ahead, "zap", rx.cond(is_after, "clock", "dot"))
    prefix = rx.cond(is_ahead, "+", "")
    return rx.hstack(
        rx.icon(icon, size=10, color=color),
        rx.text(
            prefix + lead.to_string() + " j",
            size="1",
            weight="medium",
            color=color,
        ),
        spacing="1",
        align="center",
        background=bg,
        padding="2px 8px",
        border_radius="9999px",
        display="inline-flex",
    )


def _signal_match_item(sig: rx.Var[dict]) -> rx.Component:
    """Carte d'un signal faible matché avec l'incident courant."""
    source_icon = rx.cond(
        sig["source_type"] == "google_news", "newspaper", "message_square"
    )
    is_confirmed = sig["user_confirmed"].to(int) == 1
    signal_id = sig["signal_id"].to(str)
    inc_source = DashboardState.selected_source
    inc_source_id = DashboardState.selected_source_id

    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.hstack(
                        rx.icon("radio_tower", size=14, color="#4f46e5"),
                        rx.text(
                            sig["marque"],
                            size="2",
                            weight="bold",
                            color="#111827",
                        ),
                        rx.text("—", size="2", color="#9ca3af"),
                        rx.text(
                            sig["symptome"],
                            size="2",
                            color="#dc2626",
                        ),
                        rx.cond(
                            is_confirmed,
                            rx.hstack(
                                rx.icon("badge_check", size=12, color="#16a34a"),
                                rx.text("Validé", size="1", weight="bold", color="#16a34a"),
                                spacing="1",
                                align="center",
                                background="#dcfce7",
                                padding="2px 6px",
                                border_radius="9999px",
                            ),
                        ),
                        spacing="1",
                        align="center",
                    ),
                    rx.text(
                        sig["titre"],
                        size="1",
                        color="#374151",
                        style={
                            "display": "-webkit-box",
                            "-webkit-line-clamp": "2",
                            "-webkit-box-orient": "vertical",
                            "overflow": "hidden",
                        },
                    ),
                    rx.hstack(
                        rx.icon(source_icon, size=10, color="#9ca3af"),
                        rx.text(sig["source_name"], size="1", color="#9ca3af"),
                        rx.text("·", size="1", color="#d1d5db"),
                        rx.text(sig["detected_at"], size="1", color="#9ca3af"),
                        _lead_time_badge(sig["lead_time_days"].to(int)),
                        spacing="2",
                        align="center",
                    ),
                    spacing="1",
                    align="start",
                    flex="1",
                ),
                rx.vstack(
                    _match_score_pill(sig["score"].to(float)),
                    rx.cond(
                        sig["source_url"] != "",
                        rx.link(
                            rx.hstack(
                                rx.icon("external_link", size=11, color="#4f46e5"),
                                rx.text("Source", size="1", color="#4f46e5"),
                                spacing="1",
                                align="center",
                            ),
                            href=sig["source_url"],
                            is_external=True,
                        ),
                        rx.box(),
                    ),
                    spacing="2",
                    align="end",
                ),
                spacing="3",
                align="start",
                width="100%",
            ),
            rx.cond(
                is_confirmed,
                rx.button(
                    rx.hstack(
                        rx.icon("x", size=12),
                        rx.text("Retirer la validation", size="1"),
                        spacing="1",
                        align="center",
                    ),
                    on_click=DashboardState.unconfirm_signal_match(
                        signal_id, inc_source, inc_source_id,
                    ),
                    variant="ghost",
                    color_scheme="gray",
                    size="1",
                ),
                rx.button(
                    rx.hstack(
                        rx.icon("check", size=12),
                        rx.text("Confirmer ce lien", size="1"),
                        spacing="1",
                        align="center",
                    ),
                    on_click=DashboardState.confirm_signal_match(
                        signal_id, inc_source, inc_source_id,
                    ),
                    variant="soft",
                    color_scheme="green",
                    size="1",
                ),
            ),
            spacing="2",
            align="start",
            width="100%",
        ),
        padding="12px 14px",
        border_radius="8px",
        background=rx.cond(is_confirmed, "#f0fdf4", "#f9fafb"),
        border=rx.cond(is_confirmed, "2px solid #86efac", "1px solid #e5e7eb"),
        width="100%",
    )


def incident_detail_drawer() -> rx.Component:
    return rx.drawer.root(
        rx.drawer.overlay(z_index="10"),
        rx.drawer.portal(
            rx.drawer.content(
                rx.box(
                    rx.hstack(
                        rx.vstack(
                            rx.hstack(
                                rx.heading(
                                    DashboardState.selected_incident_title,
                                    size="5",
                                    weight="bold",
                                    color="#111827",
                                ),
                                tier_badge(DashboardState.selected_score_tier),
                                spacing="3",
                                align="center",
                            ),
                            rx.hstack(
                                rx.text("Score global", size="1", color="#6b7280"),
                                rx.text(
                                    DashboardState.selected_score_value.to_string(),
                                    size="3",
                                    weight="bold",
                                    color="#4f46e5",
                                ),
                                rx.text("/100", size="2", color="#9ca3af"),
                                spacing="2",
                                align="baseline",
                            ),
                            spacing="2",
                            align="start",
                        ),
                        rx.spacer(),
                        rx.drawer.close(
                            rx.icon_button(
                                rx.icon("x", size=16),
                                variant="ghost",
                                color_scheme="gray",
                                on_click=DashboardState.close_drawer,
                            ),
                        ),
                        width="100%",
                        padding_bottom="16px",
                        border_bottom="1px solid #e5e7eb",
                    ),
                    _section_title("IDENTIFIANT"),
                    _meta_row("Source", DashboardState.selected_source),
                    _meta_row("ID", DashboardState.selected_source_id),

                    # Lien prominent vers la fiche RappelConso (juste sous l'ID)
                    rx.cond(
                        DashboardState.selected_incident["source_url"].to(str) != "",
                        rx.box(
                            rx.link(
                                rx.box(
                                    rx.hstack(
                                        rx.icon("external_link", size=16, color="#4f46e5"),
                                        rx.vstack(
                                            rx.text(
                                                "Ouvrir la fiche RappelConso",
                                                size="2",
                                                weight="bold",
                                                color="#4338ca",
                                            ),
                                            rx.text(
                                                DashboardState.selected_incident["source_url"].to(str),
                                                size="1",
                                                color="#6366f1",
                                                style={
                                                    "display": "-webkit-box",
                                                    "-webkit-line-clamp": "1",
                                                    "-webkit-box-orient": "vertical",
                                                    "overflow": "hidden",
                                                    "word-break": "break-all",
                                                },
                                            ),
                                            spacing="0",
                                            align="start",
                                            flex="1",
                                        ),
                                        rx.spacer(),
                                        rx.icon("chevron_right", size=14, color="#6366f1"),
                                        spacing="3",
                                        align="center",
                                        width="100%",
                                    ),
                                    padding="12px 16px",
                                    border_radius="8px",
                                    background="#eef2ff",
                                    border="1px solid #c7d2fe",
                                    _hover={
                                        "background": "#e0e7ff",
                                        "border_color": "#a5b4fc",
                                    },
                                    transition="background 120ms ease, border-color 120ms ease",
                                    width="100%",
                                ),
                                href=DashboardState.selected_incident["source_url"].to(str),
                                is_external=True,
                                text_decoration="none",
                                width="100%",
                            ),
                            padding_top="8px",
                            width="100%",
                        ),
                    ),

                    _section_title("INCIDENT"),
                    _meta_row("Date", DashboardState.selected_incident["date_publication"].to(str)),
                    _meta_row("Sous-categorie", DashboardState.selected_incident["sous_categorie"].to(str)),
                    rx.cond(
                        DashboardState.selected_incident["marque_salubrite"].to(str) != "",
                        rx.hstack(
                            rx.text("Agrement sanitaire", size="2", color="#6b7280", weight="medium"),
                            rx.spacer(),
                            rx.box(
                                rx.hstack(
                                    rx.icon("badge_check", size=12, color="#15803d"),
                                    rx.text(
                                        DashboardState.selected_incident["marque_salubrite"].to(str),
                                        size="2",
                                        weight="bold",
                                        color="#15803d",
                                        font_family="ui-monospace, monospace",
                                    ),
                                    spacing="1",
                                    align="center",
                                ),
                                background="#dcfce7",
                                padding="2px 8px",
                                border_radius="6px",
                                border="1px solid #bbf7d0",
                                display="inline-block",
                            ),
                            width="100%",
                            padding="6px 0",
                            border_bottom="1px solid #f3f4f6",
                        ),
                    ),
                    _meta_row("Distributeurs", DashboardState.selected_incident["distributeurs"].to(str)),
                    _meta_row("Zone", DashboardState.selected_incident["zone_geographique"].to(str)),
                    _section_title("MOTIF"),
                    rx.box(
                        rx.text(
                            DashboardState.selected_incident["motif"].to(str),
                            size="2",
                            color="#374151",
                            line_height="1.6",
                        ),
                        padding="12px 14px",
                        border_radius="8px",
                        background="#f9fafb",
                        border="1px solid #f3f4f6",
                        width="100%",
                    ),
                    _section_title("RISQUE IDENTIFIE"),
                    rx.box(
                        rx.text(
                            DashboardState.selected_incident["risques"].to(str),
                            size="2",
                            color="#374151",
                            line_height="1.6",
                        ),
                        padding="12px 14px",
                        border_radius="8px",
                        background="#fef2f2",
                        border="1px solid #fee2e2",
                        width="100%",
                    ),
                    _section_title("BREAKDOWN DU SCORE"),
                    rx.vstack(
                        rx.foreach(DashboardState.selected_dimensions, _dimension_bar),
                        spacing="2",
                        width="100%",
                    ),

                    # Signaux faibles détectés pour cet incident (cross-référence)
                    rx.cond(
                        DashboardState.selected_incident_match_count > 0,
                        rx.fragment(
                            rx.hstack(
                                rx.text(
                                    "SIGNAUX FAIBLES DÉTECTÉS",
                                    size="1",
                                    color="#9ca3af",
                                    weight="bold",
                                    letter_spacing="0.08em",
                                ),
                                rx.spacer(),
                                rx.box(
                                    rx.text(
                                        DashboardState.selected_incident_match_count.to_string(),
                                        size="1",
                                        weight="bold",
                                        color="#4338ca",
                                    ),
                                    background="#eef2ff",
                                    padding="2px 8px",
                                    border_radius="9999px",
                                ),
                                width="100%",
                                padding_top="16px",
                                padding_bottom="8px",
                            ),
                            rx.vstack(
                                rx.foreach(
                                    DashboardState.selected_incident_matches,
                                    _signal_match_item,
                                ),
                                spacing="2",
                                width="100%",
                            ),
                        ),
                    ),

                    _section_title("LIEN SOURCE"),
                    rx.link(
                        rx.hstack(
                            rx.icon("external_link", size=14),
                            rx.text("Ouvrir la fiche RappelConso", size="2"),
                            spacing="2",
                            align="center",
                        ),
                        href=DashboardState.selected_incident["source_url"].to(str),
                        is_external=True,
                        color="#4f46e5",
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
                width="560px",
                max_width="95vw",
                background="white",
                border_left="1px solid #e5e7eb",
                box_shadow="-12px 0 24px rgba(0,0,0,0.08)",
                z_index="50",
            ),
        ),
        open=DashboardState.drawer_open,
        on_open_change=DashboardState.set_drawer_open,
        direction="right",
    )
