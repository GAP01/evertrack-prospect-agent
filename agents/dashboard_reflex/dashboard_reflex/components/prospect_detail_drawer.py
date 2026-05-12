"""
Drawer latéral droit — détail d'un prospect enrichi.

Affiche : identifiant, données entreprise SIRENE, contact (avec type badge),
et les méta-données de l'enrichissement (confidence, api_used).
"""

from __future__ import annotations

import reflex as rx

from ..state import DashboardState


def _meta_row(label: str, value) -> rx.Component:
    return rx.hstack(
        rx.text(
            label,
            size="1",
            color="#6b7280",
            weight="medium",
            letter_spacing="0.04em",
            min_width="150px",
        ),
        rx.text(value, size="2", color="#111827"),
        spacing="3",
        align="start",
        width="100%",
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


def _confidence_display(confidence: rx.Var[float]) -> rx.Component:
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
                height="8px",
                background=color,
                border_radius="9999px",
            ),
            width="160px",
            height="8px",
            background="#f3f4f6",
            border_radius="9999px",
            overflow="hidden",
        ),
        rx.text(pct + "%", size="2", weight="bold", color="#111827"),
        spacing="3",
        align="center",
    )


def _contact_type_pill(ctype: rx.Var[str]) -> rx.Component:
    return rx.cond(
        ctype == "cible",
        rx.hstack(
            rx.icon("target", size=12, color="#166534"),
            rx.text("Profil cible", size="1", weight="medium", color="#166534"),
            spacing="1",
            align="center",
            background="#dcfce7",
            padding="4px 10px",
            border_radius="9999px",
        ),
        rx.cond(
            ctype == "fallback_dirigeant",
            rx.hstack(
                rx.icon("user", size=12, color="#92400e"),
                rx.text("Dirigeant (fallback)", size="1", weight="medium", color="#92400e"),
                spacing="1",
                align="center",
                background="#fef3c7",
                padding="4px 10px",
                border_radius="9999px",
            ),
            rx.box(),
        ),
    )


def prospect_detail_drawer() -> rx.Component:
    e = DashboardState.selected_enrich
    return rx.drawer.root(
        rx.drawer.overlay(z_index="10"),
        rx.drawer.portal(
            rx.drawer.content(
                rx.box(
                    # En-tête
                    rx.hstack(
                        rx.vstack(
                            rx.heading(
                                DashboardState.selected_enrich_title,
                                size="5",
                                weight="bold",
                                color="#111827",
                            ),
                            rx.hstack(
                                rx.text("Confiance", size="1", color="#6b7280"),
                                _confidence_display(DashboardState.selected_enrich_confidence),
                                spacing="3",
                                align="center",
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
                                on_click=DashboardState.close_prospect_drawer,
                            ),
                        ),
                        width="100%",
                        padding_bottom="16px",
                        border_bottom="1px solid #e5e7eb",
                    ),

                    # Identifiant
                    _section_title("IDENTIFIANT"),
                    _meta_row("Marque input", e["marque_input"].to(str)),
                    _meta_row("Source ID", e["source_id"].to(str)),
                    _meta_row("Requete SIRENE", e["query_used"].to(str)),

                    # Entreprise
                    _section_title("ENTREPRISE"),
                    _meta_row("Raison sociale", e["raison_sociale"].to(str)),
                    _meta_row("SIREN", e["siren"].to(str)),
                    _meta_row("SIRET siege", e["siret_siege"].to(str)),
                    _meta_row("Forme juridique", e["forme_juridique"].to(str)),
                    _meta_row("Code NAF", e["code_naf"].to(str)),
                    _meta_row("Activite", e["libelle_naf"].to(str)),
                    _meta_row("Adresse", e["adresse"].to(str)),
                    _meta_row("Effectif", e["effectif_tranche"].to(str)),
                    _meta_row("Categorie", e["categorie_entreprise"].to(str)),

                    # Contact
                    _section_title("CONTACT"),
                    rx.cond(
                        e["contact_nom"].to(str) != "",
                        rx.vstack(
                            rx.hstack(
                                rx.icon("user", size=14, color="#6b7280"),
                                rx.text(
                                    e["contact_nom"].to(str),
                                    size="3",
                                    weight="bold",
                                    color="#111827",
                                ),
                                spacing="2",
                                align="center",
                            ),
                            rx.text(
                                e["contact_titre"].to(str),
                                size="2",
                                color="#374151",
                                font_style="italic",
                            ),
                            _contact_type_pill(e["contact_type"].to(str)),
                            rx.text(
                                "Source : " + e["contact_source"].to(str),
                                size="1",
                                color="#9ca3af",
                            ),
                            spacing="2",
                            align="start",
                            padding="12px 14px",
                            border_radius="8px",
                            background="#f9fafb",
                            border="1px solid #f3f4f6",
                            width="100%",
                        ),
                        rx.box(
                            rx.hstack(
                                rx.icon("user_x", size=14, color="#9ca3af"),
                                rx.text("Aucun contact trouve", size="2", color="#9ca3af"),
                                spacing="2",
                                align="center",
                            ),
                            padding="12px 14px",
                            border_radius="8px",
                            background="#f9fafb",
                            width="100%",
                        ),
                    ),

                    # Enrichissement
                    _section_title("ENRICHISSEMENT"),
                    rx.cond(
                        e["api_used"].to(str).contains("agrement"),
                        rx.box(
                            rx.hstack(
                                rx.icon("badge_check", size=14, color="#15803d"),
                                rx.vstack(
                                    rx.text(
                                        "Match via agrement sanitaire DGAL",
                                        size="2",
                                        weight="bold",
                                        color="#15803d",
                                    ),
                                    rx.text(
                                        "Identification nominative officielle de "
                                        "l'etablissement de production. Confiance maximale.",
                                        size="1",
                                        color="#166534",
                                    ),
                                    spacing="0",
                                    align="start",
                                ),
                                spacing="2",
                                align="start",
                            ),
                            background="#dcfce7",
                            padding="10px 14px",
                            border_radius="8px",
                            border="1px solid #bbf7d0",
                            margin_bottom="8px",
                            width="100%",
                        ),
                    ),
                    _meta_row("Statut match", e["match_status"].to(str)),
                    _meta_row("API utilisee", e["api_used"].to(str)),
                    _meta_row("Requete", e["query_used"].to(str)),
                    _meta_row("Enrichi le", e["enriched_at"].to(str)),

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
        open=DashboardState.prospect_drawer_open,
        on_open_change=DashboardState.set_prospect_drawer_open,
        direction="right",
    )
