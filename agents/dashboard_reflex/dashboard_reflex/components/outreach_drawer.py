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


# ---------------------------------------------------------------------------
# Section INSIGHTS : 3 KPI visuels
# ---------------------------------------------------------------------------

def _kpi_score_gauge() -> rx.Component:
    """
    KPI 1 — Score sanitaire.

    Utilise rx.recharts.radial_bar_chart avec une seule barre 0-100.
    La couleur de la barre reflete le tier via outreach_kpi_score_color.
    Hauteur fixe 160px — recharts calcule mal les hauteurs % dans un drawer vaul.
    """
    score_val = DashboardState.outreach_kpi_score_value
    score_label = DashboardState.outreach_kpi_score_label
    score_color = DashboardState.outreach_kpi_score_color

    # Couleur Radix token -> hex approximatif pour recharts (qui accepte du CSS)
    bar_color = rx.match(
        score_color,
        ("red", "#dc2626"),
        ("orange", "#ea580c"),
        ("amber", "#d97706"),
        ("green", "#16a34a"),
        "#9ca3af",
    )

    # Données du gauge : une seule entrée, "value" est le score, "fill" est
    # injecte via la prop fill du composant radial_bar
    gauge_data = [{"name": "score", "value": score_val}]

    return rx.vstack(
        rx.text(
            "Score sanitaire",
            size="1",
            color="#6b7280",
            weight="medium",
            letter_spacing="0.04em",
        ),
        rx.box(
            rx.recharts.radial_bar_chart(
                rx.recharts.radial_bar(
                    data_key="value",
                    fill=bar_color,
                    background=True,
                    label={"position": "insideStart", "fill": "#fff", "fontSize": 11},
                ),
                data=gauge_data,
                inner_radius="40%",
                outer_radius="80%",
                start_angle=180,
                end_angle=0,
                min_angle=15,
                width=160,
                height=100,
                margin={"top": 0, "right": 0, "bottom": 0, "left": 0},
            ),
            width="160px",
            height="100px",
            flex_shrink="0",
        ),
        rx.hstack(
            rx.text(
                score_val.to_string(),
                size="5",
                weight="bold",
                color="#111827",
            ),
            rx.text(
                "/ 100",
                size="2",
                color="#9ca3af",
            ),
            spacing="1",
            align="baseline",
        ),
        rx.cond(
            score_label != "",
            rx.badge(
                score_label,
                color_scheme=score_color,
                variant="soft",
                size="1",
            ),
        ),
        spacing="2",
        align="center",
        width="100%",
    )


def _kpi_sources_bar() -> rx.Component:
    """
    KPI 2 — Couverture mediatique.

    Bar chart horizontal : axe Y = source name, axe X = nb occurrences.
    Affiche un placeholder si aucune source n'est disponible.
    """
    sources_data = DashboardState.outreach_kpi_sources_data
    total = DashboardState.outreach_kpi_sources_total

    chart_block = rx.box(
        rx.recharts.bar_chart(
            rx.recharts.bar(
                data_key="count",
                fill="#6366f1",
                radius=2,
            ),
            rx.recharts.x_axis(
                type_="number",
                tick={"fontSize": 10},
                allow_decimals=False,
            ),
            rx.recharts.y_axis(
                data_key="source",
                type_="category",
                width=90,
                tick={"fontSize": 9},
            ),
            rx.recharts.tooltip(),
            data=sources_data,
            layout="vertical",
            width=210,
            height=120,
            margin={"top": 4, "right": 8, "bottom": 4, "left": 0},
        ),
        width="210px",
        height="120px",
        flex_shrink="0",
    )

    placeholder = rx.box(
        rx.text(
            "(aucun signal croise)",
            size="2",
            color="#9ca3af",
            font_style="italic",
        ),
        display="flex",
        align_items="center",
        justify_content="center",
        width="100%",
        height="80px",
        background="#f9fafb",
        border_radius="6px",
        border="1px dashed #e5e7eb",
    )

    return rx.vstack(
        rx.text(
            "Couverture mediatique",
            size="1",
            color="#6b7280",
            weight="medium",
            letter_spacing="0.04em",
        ),
        rx.cond(
            total > 0,
            chart_block,
            placeholder,
        ),
        rx.hstack(
            rx.text(
                total.to_string(),
                size="4",
                weight="bold",
                color="#111827",
            ),
            rx.text(
                "source(s)",
                size="2",
                color="#9ca3af",
            ),
            spacing="1",
            align="baseline",
        ),
        spacing="2",
        align="center",
        width="100%",
    )


def _kpi_contact_progress() -> rx.Component:
    """
    KPI 3 — Qualite du contact prospect.

    Barre de progression CSS + label couleur selon le tier de confidence.
    Pattern inspire de _confidence_display (prospect_detail_drawer.py).
    """
    conf_pct = DashboardState.outreach_kpi_confidence_percent
    conf_status = DashboardState.outreach_kpi_confidence_status
    conf_value = DashboardState.outreach_kpi_confidence_value

    bar_color = rx.cond(
        conf_value >= 0.72,
        "linear-gradient(90deg, #4ade80 0%, #16a34a 100%)",
        rx.cond(
            conf_value >= 0.40,
            "linear-gradient(90deg, #fbbf24 0%, #d97706 100%)",
            "linear-gradient(90deg, #f87171 0%, #dc2626 100%)",
        ),
    )

    status_color = rx.cond(
        conf_status == "cible",
        "#166534",
        rx.cond(
            conf_status == "fallback_dirigeant",
            "#92400e",
            "#6b7280",
        ),
    )

    status_label = rx.cond(
        conf_status == "cible",
        "Contact cible",
        rx.cond(
            conf_status == "fallback_dirigeant",
            "Fallback dirigeant",
            rx.cond(
                conf_status != "",
                conf_status,
                "Non trouve",
            ),
        ),
    )

    return rx.vstack(
        rx.text(
            "Qualite du contact",
            size="1",
            color="#6b7280",
            weight="medium",
            letter_spacing="0.04em",
        ),
        # Barre de progression
        rx.box(
            rx.box(
                width=conf_pct.to_string() + "%",
                height="8px",
                background=bar_color,
                border_radius="9999px",
            ),
            width="100%",
            max_width="180px",
            height="8px",
            background="#f3f4f6",
            border_radius="9999px",
            overflow="hidden",
        ),
        # Valeur numerique
        rx.hstack(
            rx.text(
                conf_pct.to_string(),
                size="5",
                weight="bold",
                color="#111827",
            ),
            rx.text(
                "%",
                size="2",
                color="#9ca3af",
            ),
            spacing="1",
            align="baseline",
        ),
        # Statut contact
        rx.text(
            status_label,
            size="2",
            color=status_color,
            weight="medium",
        ),
        spacing="2",
        align="center",
        width="100%",
    )


def _kpi_no_data_placeholder() -> rx.Component:
    """Box gris affiche a la place des KPI si context_json est absent ou vide."""
    return rx.box(
        rx.hstack(
            rx.icon("info", size=14, color="#9ca3af"),
            rx.text(
                "Donnees KPI insuffisantes pour ce message.",
                size="2",
                color="#6b7280",
            ),
            spacing="2",
            align="center",
        ),
        padding="12px 16px",
        border_radius="8px",
        background="#f9fafb",
        border="1px solid #e5e7eb",
        width="100%",
        margin_top="4px",
        margin_bottom="4px",
    )


def _insights_block() -> rx.Component:
    """
    Section INSIGHTS — 3 KPI en grille.

    Desktop (>= 768px) : 3 colonnes cote a cote.
    Mobile (< 768px)   : 1 colonne, blocs empiles.

    Affiche uniquement si DashboardState.outreach_kpi_has_data == True,
    sinon affiche un callout "Donnees KPI insuffisantes".
    """
    kpi_grid = rx.box(
        rx.grid(
            # Card score sanitaire
            rx.box(
                _kpi_score_gauge(),
                background="#f9fafb",
                border="1px solid #e5e7eb",
                border_radius="8px",
                padding="12px",
                min_height="200px",
                display="flex",
                flex_direction="column",
                align_items="center",
                justify_content="flex-start",
            ),
            # Card couverture mediatique
            rx.box(
                _kpi_sources_bar(),
                background="#f9fafb",
                border="1px solid #e5e7eb",
                border_radius="8px",
                padding="12px",
                min_height="200px",
                display="flex",
                flex_direction="column",
                align_items="center",
                justify_content="flex-start",
            ),
            # Card qualite contact
            rx.box(
                _kpi_contact_progress(),
                background="#f9fafb",
                border="1px solid #e5e7eb",
                border_radius="8px",
                padding="12px",
                min_height="200px",
                display="flex",
                flex_direction="column",
                align_items="center",
                justify_content="flex-start",
            ),
            style={
                "grid-template-columns": "1fr 1fr 1fr",
                "gap": "12px",
                "@media (max-width: 768px)": {
                    "grid-template-columns": "1fr",
                },
            },
            width="100%",
        ),
        padding_top="4px",
        padding_bottom="4px",
        width="100%",
    )

    return rx.vstack(
        _section_title("INSIGHTS"),
        rx.cond(
            DashboardState.outreach_kpi_has_data,
            kpi_grid,
            _kpi_no_data_placeholder(),
        ),
        width="100%",
        spacing="0",
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

                    # Section INSIGHTS (nouvelle — KPI visuels)
                    _insights_block(),

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
                width="720px",
                max_width="95vw",
                background="white",
                border_left="1px solid #e5e7eb",
                box_shadow="-12px 0 24px rgba(0,0,0,0.08)",
                z_index="50",
                style={
                    "@media (max-width: 768px)": {
                        "width": "100%",
                    },
                },
            ),
        ),
        open=DashboardState.outreach_drawer_open,
        on_open_change=DashboardState.set_outreach_drawer_open,
        direction="right",
    )
