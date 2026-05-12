"""
Drawer lateral droit — message d'accroche outreach (Agent 5).

Ouvert depuis le drawer Prospect via le bouton "Message".
Permet de generer, valider, rejeter ou marquer comme envoye un message.
Le corps du message est en lecture seule (copier-coller dans Outlook/Sellsy).
"""

from __future__ import annotations

import reflex as rx

from ..state import DashboardState


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


def _meta_row(label: str, value) -> rx.Component:
    return rx.hstack(
        rx.text(
            label,
            size="1",
            color="#6b7280",
            weight="medium",
            letter_spacing="0.04em",
            min_width="130px",
        ),
        rx.text(value, size="2", color="#111827"),
        spacing="3",
        align="start",
        width="100%",
    )


def _status_badge(status: rx.Var[str]) -> rx.Component:
    """Badge couleur selon le statut du message outreach."""
    # Couleurs Radix : gray=absent/brouillon, amber=a_valider, green=valide,
    # blue=envoye, red=rejete
    color = rx.match(
        status,
        ("absent", "gray"),
        ("brouillon", "gray"),
        ("a_valider", "amber"),
        ("valide", "green"),
        ("envoye", "blue"),
        ("rejete", "red"),
        "gray",
    )
    label = rx.match(
        status,
        ("absent", "Pas encore genere"),
        ("brouillon", "Brouillon"),
        ("a_valider", "A valider"),
        ("valide", "Valide"),
        ("envoye", "Envoye"),
        ("rejete", "Rejete"),
        "Inconnu",
    )
    return rx.badge(label, color_scheme=color, variant="soft", size="2")


def _actions_row() -> rx.Component:
    """Boutons d'action conditionnels selon le statut du message."""
    status = DashboardState.selected_outreach["status"].to(str)
    body_md = DashboardState.selected_outreach["body_md"].to(str)
    busy = DashboardState.outreach_busy

    return rx.vstack(
        # Cas 1 : pas encore genere
        rx.cond(
            status == "absent",
            rx.button(
                rx.cond(
                    busy,
                    rx.hstack(
                        rx.icon("loader", size=14),
                        rx.text("Generation..."),
                        spacing="2",
                        align="center",
                    ),
                    rx.hstack(
                        rx.icon("wand_2", size=14),
                        rx.text("Generer"),
                        spacing="2",
                        align="center",
                    ),
                ),
                on_click=DashboardState.generate_outreach,
                disabled=busy,
                color_scheme="indigo",
                variant="solid",
                size="2",
            ),
        ),
        # Cas 2 : brouillon ou a_valider
        rx.cond(
            (status == "brouillon") | (status == "a_valider"),
            rx.hstack(
                rx.button(
                    rx.hstack(
                        rx.icon("check", size=14),
                        rx.text("Valider"),
                        spacing="2",
                        align="center",
                    ),
                    on_click=DashboardState.validate_outreach,
                    color_scheme="green",
                    variant="solid",
                    size="2",
                ),
                rx.button(
                    rx.hstack(
                        rx.icon("x", size=14),
                        rx.text("Rejeter"),
                        spacing="2",
                        align="center",
                    ),
                    on_click=DashboardState.reject_outreach,
                    color_scheme="red",
                    variant="soft",
                    size="2",
                ),
                rx.button(
                    rx.cond(
                        busy,
                        rx.hstack(
                            rx.icon("loader", size=14),
                            rx.text("Generation..."),
                            spacing="2",
                            align="center",
                        ),
                        rx.hstack(
                            rx.icon("refresh_cw", size=14),
                            rx.text("Regenerer"),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    on_click=DashboardState.regenerate_outreach,
                    disabled=busy,
                    color_scheme="gray",
                    variant="soft",
                    size="2",
                ),
                spacing="2",
                flex_wrap="wrap",
            ),
        ),
        # Cas 3 : valide
        rx.cond(
            status == "valide",
            rx.hstack(
                rx.button(
                    rx.hstack(
                        rx.icon("send", size=14),
                        rx.text("Marquer envoye"),
                        spacing="2",
                        align="center",
                    ),
                    on_click=DashboardState.mark_outreach_sent,
                    color_scheme="blue",
                    variant="solid",
                    size="2",
                ),
                rx.button(
                    rx.cond(
                        busy,
                        rx.hstack(
                            rx.icon("loader", size=14),
                            rx.text("Generation..."),
                            spacing="2",
                            align="center",
                        ),
                        rx.hstack(
                            rx.icon("refresh_cw", size=14),
                            rx.text("Regenerer"),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    on_click=DashboardState.regenerate_outreach,
                    disabled=busy,
                    color_scheme="gray",
                    variant="soft",
                    size="2",
                ),
                spacing="2",
                flex_wrap="wrap",
            ),
        ),
        # Cas 4 : envoye ou rejete (uniquement regenerer)
        rx.cond(
            (status == "envoye") | (status == "rejete"),
            rx.button(
                rx.cond(
                    busy,
                    rx.hstack(
                        rx.icon("loader", size=14),
                        rx.text("Generation..."),
                        spacing="2",
                        align="center",
                    ),
                    rx.hstack(
                        rx.icon("refresh_cw", size=14),
                        rx.text("Regenerer"),
                        spacing="2",
                        align="center",
                    ),
                ),
                on_click=DashboardState.regenerate_outreach,
                disabled=busy,
                color_scheme="gray",
                variant="soft",
                size="2",
            ),
        ),
        # Bouton Copier — toujours visible si body non vide
        rx.cond(
            body_md != "",
            rx.button(
                rx.hstack(
                    rx.icon("clipboard_copy", size=14),
                    rx.text("Copier le corps"),
                    spacing="2",
                    align="center",
                ),
                on_click=rx.set_clipboard(body_md),
                color_scheme="gray",
                variant="ghost",
                size="2",
            ),
        ),
        spacing="2",
        align="start",
        padding_top="12px",
        width="100%",
    )


def outreach_drawer() -> rx.Component:
    o = DashboardState.selected_outreach
    return rx.drawer.root(
        rx.drawer.overlay(z_index="10"),
        rx.drawer.portal(
            rx.drawer.content(
                rx.box(
                    # En-tete
                    rx.hstack(
                        rx.vstack(
                            rx.heading(
                                "Message d'accroche",
                                size="5",
                                weight="bold",
                                color="#111827",
                            ),
                            _status_badge(o["status"].to(str)),
                            spacing="2",
                            align="start",
                        ),
                        rx.spacer(),
                        rx.drawer.close(
                            rx.icon_button(
                                rx.icon("x", size=16),
                                variant="ghost",
                                color_scheme="gray",
                                on_click=DashboardState.close_outreach_drawer,
                            ),
                        ),
                        width="100%",
                        padding_bottom="16px",
                        border_bottom="1px solid #e5e7eb",
                        align="start",
                    ),

                    # Actions
                    _actions_row(),

                    # Informations de tracabilite
                    _section_title("TRACABILITE"),
                    rx.hstack(
                        rx.text(
                            "LLM utilise :",
                            size="1",
                            color="#6b7280",
                            weight="medium",
                        ),
                        rx.cond(
                            o["llm_used"].to(bool),
                            rx.text("Oui", size="2", color="#059669", weight="bold"),
                            rx.text("Non (fallback regles)", size="2", color="#6b7280"),
                        ),
                        spacing="2",
                        align="center",
                        width="100%",
                    ),
                    _meta_row("Genere le", o["generated_at"].to(str)),
                    _meta_row("Valide le", o["validated_at"].to(str)),
                    _meta_row("Envoye le", o["sent_at"].to(str)),
                    rx.cond(
                        o["notes"].to(str) != "",
                        _meta_row("Notes", o["notes"].to(str)),
                    ),

                    # Objet
                    _section_title("OBJET"),
                    rx.cond(
                        o["objet"].to(str) != "",
                        rx.text(
                            o["objet"].to(str),
                            size="3",
                            weight="bold",
                            color="#111827",
                        ),
                        rx.text(
                            "(pas encore genere)",
                            size="2",
                            color="#9ca3af",
                            font_style="italic",
                        ),
                    ),

                    # Corps du message
                    _section_title("CORPS DU MESSAGE"),
                    rx.cond(
                        o["body_md"].to(str) != "",
                        rx.text_area(
                            value=o["body_md"].to(str),
                            read_only=True,
                            rows="20",
                            width="100%",
                            style={
                                "font-family": "monospace",
                                "font-size": "12px",
                                "resize": "none",
                                "background": "#f9fafb",
                                "border": "1px solid #e5e7eb",
                                "border-radius": "8px",
                                "padding": "12px",
                            },
                        ),
                        rx.box(
                            rx.text(
                                "Aucun corps genere.",
                                size="2",
                                color="#9ca3af",
                                font_style="italic",
                            ),
                            rx.text(
                                "Cliquez sur \"Generer\" pour produire le message.",
                                size="2",
                                color="#9ca3af",
                            ),
                            padding="16px",
                            border_radius="8px",
                            background="#f9fafb",
                            border="1px dashed #d1d5db",
                            width="100%",
                        ),
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
                width="480px",
                max_width="95vw",
                background="white",
                border_left="1px solid #e5e7eb",
                box_shadow="-12px 0 24px rgba(0,0,0,0.08)",
                z_index="50",
            ),
        ),
        open=DashboardState.outreach_drawer_open,
        on_open_change=DashboardState.set_outreach_drawer_open,
        direction="right",
    )
