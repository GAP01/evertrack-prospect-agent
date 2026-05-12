"""
Rendu deterministe de l'email outreach depuis le contexte cross-base et le pitch.

Utilise string.Template avec safe_substitute — les variables manquantes restent
litterales ($var) mais toutes les variables attendues sont pre-remplies avec
des valeurs de repli, donc aucun $xxx ne subsiste dans la sortie normale.
"""

from __future__ import annotations

import os
import string
from typing import Any

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "email_fr.txt")

# Mois courts FR, ASCII only (sans accents) — indice 0 = janvier
MOIS_COURTS = [
    "janv", "fevr", "mars", "avr", "mai", "juin",
    "juil", "aout", "sept", "oct", "nov", "dec",
]

# Titres de civilite connus — utilises pour deduire "Madame" / "Monsieur"
_TITRES_MASCULINS = {
    "m.", "mr", "mr.", "monsieur", "m",
    "directeur", "responsable", "gerant", "pdg", "dg", "president",
}
_TITRES_FEMININS = {
    "mme", "mme.", "madame", "ms", "ms.", "miss",
    "directrice", "responsable",
}


def _load_template() -> string.Template:
    with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return string.Template(f.read())


def _format_date_fr(iso_date: str | None) -> str:
    """
    Convertit une date ISO-8601 (YYYY-MM-DD ou YYYY-MM-DDTHH:MM:SS)
    en format lisible FR "DD MMM YYYY" (ex: "15 mars 2024").
    Retourne "recemment" si la chaine est vide, None, ou non parsable.
    """
    if not iso_date:
        return "recemment"
    try:
        # Coupe a 10 chars pour tolerrer les formats datetime complets
        parts = iso_date[:10].split("-")
        if len(parts) != 3:
            return iso_date
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        mois = MOIS_COURTS[month - 1]
        return f"{day} {mois} {year}"
    except (ValueError, IndexError):
        return iso_date if iso_date else "recemment"


def _truncate(text: str | None, max_chars: int, suffix: str = "...") -> str:
    """
    Tronque `text` a `max_chars` caracteres en coupant au dernier espace
    avant la limite pour eviter de couper un mot. Ajoute `suffix` si tronque.
    Retourne "" si text est None ou vide.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    # Cherche le dernier espace avant max_chars - len(suffix)
    cut = max_chars - len(suffix)
    space_idx = text.rfind(" ", 0, cut)
    if space_idx > 0:
        return text[:space_idx] + suffix
    return text[:cut] + suffix


def _build_subject(context: dict) -> str:
    """
    Construit l'objet email en ASCII only (sans accents).
    Si la marque est connue : "Suite au rappel {marque} - tracabilite produit"
    Sinon : "Tracabilite produit - suite a votre actualite recente"
    """
    incident = context.get("incident") or {}
    marque = incident.get("marque") or ""
    marque = marque.strip()
    if marque:
        return f"Suite au rappel {marque} - tracabilite produit"
    return "Tracabilite produit - suite a votre actualite recente"


def _build_bloc_signaux(signaux_summary: list) -> str:
    """
    Construit le paragraphe optionnel de couverture mediatique.
    Retourne une chaine vide si signaux_summary est vide.
    Affiche 1-3 titres tronques a 80 chars chacun.
    """
    if not signaux_summary:
        return ""
    n = len(signaux_summary)
    titres = []
    for sig in signaux_summary[:3]:
        titre = sig.get("titre") or ""
        if titre:
            titres.append(_truncate(titre, 80))
    if not titres:
        return ""
    titres_str = "; ".join(titres)
    return (
        f"\n\nNous avons egalement observe une couverture mediatique recente "
        f"({n} source(s) : {titres_str})."
    )


def _build_contact_civilite(enrichissement: dict | None) -> str:
    """
    Deduit la formule d'appel a partir des donnees d'enrichissement.

    - contact_type == "cible" avec contact_nom present :
        tente de deduire Madame/Monsieur depuis contact_titre,
        sinon utilise prenom + nom (contact_prenom peut etre None).
    - contact_type == "fallback_dirigeant" : "Madame, Monsieur" (formule formelle).
    - Absence d'enrichissement ou contact_nom vide : "Madame, Monsieur".
    """
    if not enrichissement:
        return "Madame, Monsieur"

    contact_nom = (enrichissement.get("contact_nom") or "").strip()
    contact_type = enrichissement.get("contact_type") or ""

    if not contact_nom:
        return "Madame, Monsieur"

    if contact_type == "cible":
        contact_titre = (enrichissement.get("contact_titre") or "").lower().strip()
        # Tente de detecter la civilite depuis le titre/fonction
        if contact_titre:
            for mot in contact_titre.split():
                if mot in _TITRES_FEMININS:
                    return f"Madame {contact_nom}"
                if mot in _TITRES_MASCULINS:
                    return f"Monsieur {contact_nom}"
        # Pas de civilite deductible : utilise prenom + nom si prenom present
        contact_prenom = (enrichissement.get("contact_prenom") or "").strip()
        if contact_prenom:
            return f"{contact_prenom} {contact_nom}".strip()
        # Nom seul sans civilite determinee — on reste generique avec le nom
        return contact_nom

    # fallback_dirigeant ou autre : formule formelle sans nom
    return "Madame, Monsieur"


def _build_marque_pretty(incident: dict | None) -> str:
    """
    Retourne la marque formatee.
    Si tout en majuscules et >= 2 chars, applique .title() pour lisibilite.
    Si absente, retourne "d'un de vos produits".
    """
    if not incident:
        return "d'un de vos produits"
    marque = (incident.get("marque") or "").strip()
    if not marque:
        return "d'un de vos produits"
    # .isupper() est vrai seulement si tous les caracteres cased sont maj
    if marque.isupper() and len(marque) >= 2:
        return marque.title()
    return marque


def render(context: dict, pitch: dict) -> dict:
    """
    Rend l'email a partir du contexte cross-base et de la config pitch.

    Args:
        context: dict retourne par context_builder.build_context().
        pitch:   dict retourne par pitch_loader.load_pitch().

    Returns:
        {"objet": str, "body": str}
    """
    template = _load_template()

    incident = context.get("incident") or {}
    enrichissement = context.get("enrichissement")
    signaux_summary = context.get("signaux_summary") or []

    # Motif raccourci a ~200 chars
    motif_resume = _truncate(incident.get("motif") or "", 200)

    # Categorie parenthesee si disponible
    categorie = (incident.get("categorie") or "").strip()
    categorie_suffix = f" ({categorie})" if categorie else ""

    mapping: dict[str, Any] = {
        "contact_civilite": _build_contact_civilite(enrichissement),
        "marque_pretty": _build_marque_pretty(incident),
        "date_publication_fr": _format_date_fr(incident.get("date_publication")),
        "produit_pretty": (incident.get("modeles") or "votre produit").strip(),
        "categorie_suffix": categorie_suffix,
        "motif_resume": motif_resume,
        "bloc_signaux_optionnel": _build_bloc_signaux(signaux_summary),
        "pitch_court": pitch.get("pitch_court") or "",
        "valeur_immediate": pitch.get("valeur_immediate") or "",
        "cta": pitch.get("cta") or "",
        "signature": pitch.get("signature") or "",
        "opt_out": pitch.get("opt_out_placeholder") or "",
    }

    body = template.safe_substitute(mapping)
    objet = _build_subject(context)

    return {"objet": objet, "body": body}
