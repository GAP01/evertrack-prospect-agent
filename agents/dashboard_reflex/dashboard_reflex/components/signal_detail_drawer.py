"""
Drawer latéral droit — détail d'un signal faible.

Affiche : identité, score breakdown, sources multiples, actions de validation.
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
            min_width="120px",
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


def _score_circle(score: rx.Var[int]) -> rx.Component:
    """Gros badge circulaire affichant le score."""
    color = rx.cond(
        score >= 80, "#dc2626",
        rx.cond(score >= 60, "#d97706",
                rx.cond(score >= 40, "#ca8a04", "#6b7280")),
    )
    bg = rx.cond(
        score >= 80, "#fee2e2",
        rx.cond(score >= 60, "#fef3c7",
                rx.cond(score >= 40, "#fef9c3", "#f3f4f6")),
    )
    return rx.vstack(
        rx.text(score.to_string(), size="7", weight="bold", color=color),
        rx.text("/ 100", size="1", color="#9ca3af"),
        spacing="0",
        align="center",
        justify="center",
        width="80px",
        height="80px",
        border_radius="9999px",
        background=bg,
        border="3px solid " + color,
    )


def _breakdown_bar(item: rx.Var[dict]) -> rx.Component:
    """Barre d'une dimension du score (label + valeur + barre)."""
    return rx.vstack(
        rx.hstack(
            rx.text(item["label"], size="1", color="#374151", weight="medium"),
            rx.spacer(),
            rx.text(item["value"].to_string(), size="1", weight="bold", color="#111827"),
            width="100%",
        ),
        rx.box(
            rx.box(
                width=(item["value"].to(int) * 3).to_string() + "px",
                max_width="100%",
                height="4px",
                background="#4f46e5",
                border_radius="9999px",
            ),
            width="100%",
            height="4px",
            background="#f3f4f6",
            border_radius="9999px",
            overflow="hidden",
        ),
        spacing="1",
        align="start",
        width="100%",
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
    """Lead time en jours : + = signal avant incident, - = après."""
    is_ahead = lead > 0
    is_after = lead < 0
    bg = rx.cond(is_ahead, "#dbeafe", rx.cond(is_after, "#fef3c7", "#f3f4f6"))
    color = rx.cond(is_ahead, "#1e40af", rx.cond(is_after, "#92400e", "#6b7280"))
    prefix = rx.cond(is_ahead, "+", rx.cond(is_after, "", ""))
    return rx.box(
        rx.text(
            prefix + lead.to_string() + " j",
            size="1",
            weight="medium",
            color=color,
        ),
        background=bg,
        padding="2px 8px",
        border_radius="9999px",
        display="inline-block",
    )


def _match_item(match: rx.Var[dict]) -> rx.Component:
    """Carte d'un rappel officiel matché avec le signal courant."""
    is_confirmed = match["user_confirmed"].to(int) == 1
    signal_id = DashboardState.selected_signal["signal_id"].to(str)
    inc_source = match["inc_source"].to(str)
    inc_source_id = match["inc_source_id"].to(str)

    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.hstack(
                        rx.icon("shield_check", size=14, color=rx.cond(is_confirmed, "#16a34a", "#166534")),
                        rx.text(
                            match["inc_marque"],
                            size="2",
                            weight="bold",
                            color="#111827",
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
                        spacing="2",
                        align="center",
                    ),
                    rx.text(match["inc_categorie"], size="1", color="#6b7280"),
                    rx.text(
                        match["inc_motif"],
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
                        rx.text("Publié le", size="1", color="#9ca3af"),
                        rx.text(
                            match["inc_date"],
                            size="1",
                            color="#9ca3af",
                            weight="medium",
                        ),
                        _lead_time_badge(match["lead_time_days"].to(int)),
                        spacing="2",
                        align="center",
                    ),
                    spacing="1",
                    align="start",
                    flex="1",
                ),
                rx.vstack(
                    _match_score_pill(match["score"].to(float)),
                    rx.cond(
                        match["inc_url"] != "",
                        rx.link(
                            rx.hstack(
                                rx.icon("external_link", size=11, color="#4f46e5"),
                                rx.text("RappelConso", size="1", color="#4f46e5"),
                                spacing="1",
                                align="center",
                            ),
                            href=match["inc_url"],
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
            # Bouton validation humaine (confirme/déconfirme le lien)
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


def _source_item(src: rx.Var[dict]) -> rx.Component:
    """Carte entièrement cliquable d'une source d'article."""
    icon = rx.cond(src["source_type"] == "google_news", "newspaper", "message_square")
    return rx.link(
        rx.box(
            rx.hstack(
                rx.icon(icon, size=16, color="#4f46e5"),
                rx.vstack(
                    rx.hstack(
                        rx.text(
                            src["source_name"],
                            size="2",
                            weight="bold",
                            color="#4338ca",
                        ),
                        rx.spacer(),
                        rx.text(
                            src["detected_at"],
                            size="1",
                            color="#6366f1",
                        ),
                        width="100%",
                        align="center",
                    ),
                    rx.text(
                        src["titre"],
                        size="1",
                        color="#374151",
                        style={
                            "display": "-webkit-box",
                            "-webkit-line-clamp": "2",
                            "-webkit-box-orient": "vertical",
                            "overflow": "hidden",
                        },
                    ),
                    spacing="1",
                    align="start",
                    flex="1",
                ),
                rx.icon("external_link", size=14, color="#6366f1"),
                spacing="3",
                align="start",
                width="100%",
            ),
            padding="12px 14px",
            border_radius="8px",
            background="#eef2ff",
            border="1px solid #c7d2fe",
            _hover={"background": "#e0e7ff", "border_color": "#a5b4fc"},
            transition="background 120ms ease, border-color 120ms ease",
            width="100%",
        ),
        href=src["source_url"],
        is_external=True,
        text_decoration="none",
        width="100%",
    )


def _actions_row() -> rx.Component:
    """Boutons Valider / Rejeter (seulement si status=a_valider)."""
    sig_id = DashboardState.selected_signal["signal_id"].to(str)
    status = DashboardState.selected_signal["status"].to(str)

    return rx.cond(
        (status == "a_valider") | (status == "faible"),
        rx.hstack(
            rx.button(
                rx.hstack(
                    rx.icon("check", size=14),
                    rx.text("Valider"),
                    spacing="2",
                    align="center",
                ),
                on_click=DashboardState.validate_signal(sig_id),
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
                on_click=DashboardState.reject_signal(sig_id),
                color_scheme="red",
                variant="soft",
                size="2",
            ),
            spacing="2",
            width="100%",
            padding_top="12px",
        ),
        rx.box(),
    )


def signal_detail_drawer() -> rx.Component:
    s = DashboardState.selected_signal
    return rx.drawer.root(
        rx.drawer.overlay(z_index="10"),
        rx.drawer.portal(
            rx.drawer.content(
                rx.box(
                    # En-tête
                    rx.hstack(
                        rx.vstack(
                            rx.heading(
                                DashboardState.selected_signal_title,
                                size="5",
                                weight="bold",
                                color="#111827",
                            ),
                            rx.text(
                                s["titre"].to(str),
                                size="2",
                                color="#374151",
                                style={
                                    "display": "-webkit-box",
                                    "-webkit-line-clamp": "2",
                                    "-webkit-box-orient": "vertical",
                                    "overflow": "hidden",
                                },
                            ),
                            # Badge pression médiatique (si ≥ 2 signaux sur la marque)
                            rx.cond(
                                DashboardState.selected_signal_media_pressure > 1,
                                rx.hstack(
                                    rx.icon("flame", size=12, color="#ea580c"),
                                    rx.text(
                                        "Pression médiatique :",
                                        size="1",
                                        color="#9a3412",
                                        weight="medium",
                                    ),
                                    rx.text(
                                        DashboardState.selected_signal_pressure_label,
                                        size="1",
                                        color="#9a3412",
                                        weight="bold",
                                    ),
                                    spacing="1",
                                    align="center",
                                    background="#ffedd5",
                                    padding="4px 10px",
                                    border_radius="9999px",
                                    border="1px solid #fdba74",
                                ),
                            ),
                            spacing="2",
                            align="start",
                            flex="1",
                        ),
                        _score_circle(DashboardState.selected_signal_score),
                        rx.drawer.close(
                            rx.icon_button(
                                rx.icon("x", size=16),
                                variant="ghost",
                                color_scheme="gray",
                                on_click=DashboardState.close_signal_drawer,
                            ),
                        ),
                        width="100%",
                        padding_bottom="16px",
                        border_bottom="1px solid #e5e7eb",
                        align="start",
                        spacing="3",
                    ),

                    # Actions de validation
                    _actions_row(),

                    # Métadonnées
                    _section_title("SIGNAL"),
                    _meta_row("ID", s["signal_id"].to(str)),
                    _meta_row("Marque", s["marque"].to(str)),
                    _meta_row("Produit", s["produit"].to(str)),
                    _meta_row("Symptôme", s["symptome"].to(str)),
                    _meta_row("Résumé", s["resume"].to(str)),
                    _meta_row("Publié le", s["detected_at"].to(str)),
                    _meta_row("Dernier scan", s["last_seen_at"].to(str)),

                    # Sources (toutes les sources cliquables, juste sous les metadata)
                    rx.hstack(
                        rx.text(
                            "SOURCES",
                            size="1",
                            color="#9ca3af",
                            weight="bold",
                            letter_spacing="0.08em",
                        ),
                        rx.spacer(),
                        rx.box(
                            rx.text(
                                DashboardState.selected_signal_sources.length().to_string(),
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
                        rx.foreach(DashboardState.selected_signal_sources, _source_item),
                        spacing="2",
                        width="100%",
                    ),

                    # Breakdown score
                    _section_title("DÉTAIL DU SCORE"),
                    rx.vstack(
                        rx.foreach(DashboardState.selected_signal_breakdown, _breakdown_bar),
                        spacing="2",
                        width="100%",
                    ),

                    # Rappels officiels associés (cross-référence)
                    rx.cond(
                        DashboardState.selected_signal_match_count > 0,
                        rx.fragment(
                            rx.hstack(
                                rx.text(
                                    "RAPPELS OFFICIELS ASSOCIÉS",
                                    size="1",
                                    color="#9ca3af",
                                    weight="bold",
                                    letter_spacing="0.08em",
                                ),
                                rx.spacer(),
                                rx.box(
                                    rx.text(
                                        DashboardState.selected_signal_match_count.to_string(),
                                        size="1",
                                        weight="bold",
                                        color="#166534",
                                    ),
                                    background="#dcfce7",
                                    padding="2px 8px",
                                    border_radius="9999px",
                                ),
                                width="100%",
                                padding_top="16px",
                                padding_bottom="8px",
                            ),
                            rx.vstack(
                                rx.foreach(
                                    DashboardState.selected_signal_matches,
                                    _match_item,
                                ),
                                spacing="2",
                                width="100%",
                            ),
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
                width="560px",
                max_width="95vw",
                background="white",
                border_left="1px solid #e5e7eb",
                box_shadow="-12px 0 24px rgba(0,0,0,0.08)",
                z_index="50",
            ),
        ),
        open=DashboardState.signal_drawer_open,
        on_open_change=DashboardState.set_signal_drawer_open,
        direction="right",
    )
