"""
Reecriture de l'email outreach via Claude Haiku pour ameliorer le style.

Strategie a deux niveaux calquee sur evaluateur_severite.llm_scorer :
- Si ANTHROPIC_API_KEY presente et SDK installe -> 2 appels Claude Haiku.
- Sinon -> retour transparent du body_fallback fourni par template_renderer.

Deux appels LLM :
  Call 1 : reformulation du corps email (220 mots max, ASCII only, sans
            inventer de chiffres absents du contexte).
  Call 2 : generation d'un objet email (70 chars max, ASCII only, sans
            ponctuation commerciale).

Garde-fous :
  - hallucination : chiffres inventes par le LLM detectes par comparaison
    avec le set de tokens numeriques RESTREINT (sous-set documenté du contexte
    + pitch + body_fallback -- exclut siren, siret, telephone, email, uuid).
  - link_injection : URLs, emails, numeros de telephone non autorises detectes
    dans la sortie LLM mais absents du pitch/fallback. Vise specifiquement la
    fuite de coordonnees depuis l'exemple stylistique.
  - ascii : presence de caracteres non-ASCII => fallback immediat (cp1252).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None  # type: ignore[misc,assignment]

from redacteur_outreach.style_loader import load_style_example

logger = logging.getLogger(__name__)

# Longueur maximale de l'objet. Si le LLM depasse, on tronque au dernier espace.
_OBJET_MAX_CHARS = 70

_SYSTEM_BODY = (
    "Tu es un assistant de redaction commerciale B2B en francais. "
    "Tu reformules un email d accroche pour ameliorer son ton et sa fluidite. "
    "Regles strictes :\n"
    "- ASCII uniquement (pas d accents).\n"
    "- Pas d emojis, pas de markdown.\n"
    "- Tu n inventes AUCUN chiffre, AUCUNE date, AUCUN fait qui n est pas deja dans\n"
    "  le brouillon ou le contexte fourni.\n"
    "- Ton sobre, factuel, courtois. Pas de superlatifs commerciaux.\n"
    "- Maximum 220 mots.\n"
    "- Conserve la structure : salutation, contexte, valeur, CTA, signature.\n"
    "- Reponds UNIQUEMENT avec le texte du nouvel email, rien d autre.\n"
    "Si un exemple de style est fourni ci-dessous :\n"
    "- Imite UNIQUEMENT le ton, la structure narrative et les tournures de l exemple.\n"
    "- N utilise AUCUN chiffre, AUCUN nom propre, AUCUNE URL, AUCUN email,\n"
    "  AUCUN numero de telephone presents dans cet exemple.\n"
    "- N invente aucun fait, nom, date ou reference de l exemple.\n"
    "- Utilise exclusivement les chiffres et faits du brouillon et du contexte fournis."
)

def _build_user_body(
    body_fallback: str,
    context_summary: str,
    style_example: str | None,
) -> str:
    """
    Construit le message user pour Call 1 (reformulation du corps).

    Le bloc STYLE_EXAMPLE est injecte uniquement si style_example est non-vide.
    L'exemple n'est jamais ajoute au set de tokens autorises — s'il fuit un
    chiffre dans la sortie LLM, le garde-fou hallucination doit se declencher.
    """
    parts = [
        "Voici le brouillon a reformuler :\n"
        "<<<\n"
        f"{body_fallback}\n"
        ">>>\n\n"
        "Contexte factuel (ne pas inventer hors de ces faits) :\n"
        f"{context_summary}",
    ]
    if style_example:
        parts.append(
            "\n\nEXEMPLE DE STYLE (inspire-toi du ton, de la structure narrative,"
            " des transitions — N'UTILISE PAS les chiffres ni les noms de"
            " personnes/entreprises de cet exemple) :\n"
            "---\n"
            "<STYLE_EXAMPLE>\n"
            f"{style_example}\n"
            "</STYLE_EXAMPLE>\n"
            "---\n"
            "Instruction : inspire-toi du ton et de la structure narrative."
            " Ne reprends AUCUN chiffre, nom propre, URL, email, telephone de l exemple."
        )
    return "".join(parts)


_SYSTEM_OBJET = (
    "Tu produis l objet d un email d accroche B2B en francais. Regles :\n"
    "- ASCII uniquement.\n"
    "- Maximum 70 caracteres.\n"
    "- Pas de point d exclamation.\n"
    "- Pas d emojis.\n"
    "- Sobre, factuel. Pas de \"URGENT\", \"DECOUVREZ\", etc.\n"
    "- Reponds UNIQUEMENT avec la ligne d objet, rien d autre."
)

_USER_OBJET_TMPL = (
    "Email :\n"
    "<<<\n"
    "{body_reecrit}\n"
    ">>>\n\n"
    "Marque concernee : {marque}\n"
    "Sujet de l incident : {motif_court}"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarize_context(context: dict[str, Any]) -> str:
    """
    Produit un bloc factuel court a partir du contexte cross-base.

    Utilise les cles connues du dict retourne par context_builder.build_context().
    Chaque cle manquante est silencieusement ignoree.
    """
    incident = context.get("incident") or {}
    enrichissement = context.get("enrichissement") or {}
    signaux_summary = context.get("signaux_summary") or []

    lines: list[str] = []

    marque = (incident.get("marque") or "").strip()
    if marque:
        lines.append(f"- Marque : {marque}")

    produit = (incident.get("modeles") or "").strip()
    if produit:
        lines.append(f"- Produit : {produit}")

    categorie = (incident.get("categorie") or "").strip()
    if categorie:
        lines.append(f"- Categorie : {categorie}")

    motif = (incident.get("motif") or "").strip()
    if motif:
        # Limite le motif a 150 chars pour eviter un prompt trop long
        lines.append(f"- Motif : {motif[:150]}")

    date_pub = (incident.get("date_publication") or "").strip()
    if date_pub:
        lines.append(f"- Date rappel : {date_pub[:10]}")

    contact_nom = (enrichissement.get("contact_nom") or "").strip()
    contact_titre = (enrichissement.get("contact_titre") or "").strip()
    if contact_nom:
        if contact_titre:
            lines.append(f"- Contact : {contact_nom} ({contact_titre})")
        else:
            lines.append(f"- Contact : {contact_nom}")

    score_row = context.get("score") or {}
    score_total = score_row.get("score_total")
    if score_total is not None:
        lines.append(f"- Score priorite : {score_total}")

    if signaux_summary:
        sources = [s.get("source_name") or "" for s in signaux_summary if s.get("source_name")]
        sources_str = ", ".join(sources) if sources else str(len(signaux_summary))
        lines.append(
            f"- Couverture mediatique : {len(signaux_summary)} article(s) recent(s) ({sources_str})"
        )

    return "\n".join(lines) if lines else "(contexte non disponible)"


def _extract_numeric_tokens(text: str) -> set[str]:
    """Extrait tous les tokens numeriques (suites de chiffres) d'un texte."""
    return set(re.findall(r"\b\d+\b", text))


def _extract_urls(text: str) -> set[str]:
    """
    Extrait les URLs (http://, https://, www.X.Y) d'un texte.
    Normalise en minuscules pour comparaison case-insensitive.
    """
    # URLs explicites avec schema
    schema_urls = re.findall(r"https?://[^\s,;\"'<>]+", text, re.IGNORECASE)
    # URLs type www.domaine.tld sans schema (au moins 2 segments)
    www_urls = re.findall(r"\bwww\.[a-z0-9][\w.-]+\.[a-z]{2,}", text, re.IGNORECASE)
    return {u.lower().rstrip(".,;:)") for u in schema_urls + www_urls}


def _extract_emails(text: str) -> set[str]:
    """Extrait les adresses email d'un texte (normalise en minuscules)."""
    found = re.findall(r"\b[\w.+\-]+@[\w.\-]+\.[a-z]{2,}\b", text, re.IGNORECASE)
    return {e.lower() for e in found}


def _extract_phone_tokens(text: str) -> set[str]:
    """
    Extrait les indicateurs de numero de telephone d'un texte.

    Deux motifs :
    - Prefixe international : +suivi directement de chiffres (ex. +33, +1)
    - Groupes repetitifs : au moins 3 occurrences de 2 chiffres separes par
      espace ou point (ex. 06 26 64 98 41), detectes via le groupe r"\\d{2}[\\s.]".
      On retourne le motif brut pour comparaison set (suffisant pour detecter
      la fuite du numero).

    Ne retourne pas les numeros normalises -- retourne des tokens textuels
    distincts afin de permettre une comparaison exacte avec le set autorise.
    """
    tokens: set[str] = set()
    # Prefixe international (ex. "+33")
    intl = re.findall(r"\+\d{1,3}", text)
    tokens.update(intl)
    # Numeros en groupes de 2 chiffres : detecte "XX XX XX XX XX" ou "XX.XX.XX"
    # On cherche au moins 4 groupes consecutifs pour eviter les faux positifs
    groups = re.findall(r"(?:\d{2}[\s.]){3,}\d{2}", text)
    tokens.update(g.strip() for g in groups)
    return tokens


def _build_allowed_link_tokens(
    body_fallback: str,
    pitch: dict[str, Any],
) -> tuple[set[str], set[str], set[str]]:
    """
    Construit les sets de liens/contacts autorises depuis le pitch et le
    body_fallback uniquement.

    L'exemple stylistique est EXCLU : s'il fuit une URL ou un email dans la
    sortie LLM, le garde-fou link_injection doit se declencher.

    Les champs siren, siret, telephone, email du contexte enrichissement sont
    aussi exclus : ils ne doivent pas apparaitre litteralement dans l'email
    sortant (ils sont dans le contexte pour reference interne uniquement).

    Note d'implementation : on itere sur les valeurs string du pitch directement
    plutot que de passer par json.dumps(), car json.dumps echappe les sauts de
    ligne en "\\n" litteraux, ce qui brise le \b de la regex devant "www.".

    Returns:
        (allowed_urls, allowed_emails, allowed_phone_tokens)
    """
    # Collecte les valeurs textuelles brutes du pitch (pas de serialisation JSON)
    pitch_text_parts: list[str] = []
    for v in pitch.values():
        if isinstance(v, str):
            pitch_text_parts.append(v)

    blob = body_fallback + " " + " ".join(pitch_text_parts)
    return _extract_urls(blob), _extract_emails(blob), _extract_phone_tokens(blob)


def _build_allowed_tokens(
    body_fallback: str,
    context: dict[str, Any],
    pitch: dict[str, Any],
) -> set[str]:
    """
    Construit le set de tokens numeriques autorises depuis un sous-set
    documente du contexte + pitch + body_fallback.

    Sous-set explicite du contexte autorise (champs metier non-sensibles) :
    - incident : marque, date_publication, motif (200 premiers chars)
    - score : score_total
    - signaux_summary : total, source_name
    - enrichissement : raison_sociale, contact_nom (pas de chiffres en pratique)

    EXCLU intentionnellement : siren, siret (9-14 chiffres), telephone, email,
    uuid, identifiants internes. Ces donnees ne doivent pas apparaitre
    litteralement dans le corps de l'email genere.
    """
    parts: list[str] = [body_fallback]

    # Sous-set incident
    incident = context.get("incident") or {}
    if isinstance(incident, dict):
        for key in ("marque", "date_publication", "categorie"):
            v = incident.get(key) or ""
            if v:
                parts.append(str(v))
        motif = (incident.get("motif") or "")[:200]
        if motif:
            parts.append(motif)

    # Score total uniquement (pas les dimensions detaillees)
    score_block = context.get("score") or {}
    if isinstance(score_block, dict):
        v = score_block.get("score_total")
        if v is not None:
            parts.append(str(v))

    # Signaux : nombre total + noms de sources (pas de score individuel)
    signaux = context.get("signaux_summary") or []
    if isinstance(signaux, list):
        parts.append(str(len(signaux)))
        for sig in signaux:
            if isinstance(sig, dict):
                src = sig.get("source_name") or ""
                if src:
                    parts.append(src)

    # Enrichissement : raison sociale + nom contact (pas siren/siret/tel)
    enrich = context.get("enrichissement") or {}
    if isinstance(enrich, dict):
        for key in ("raison_sociale", "contact_nom", "contact_titre"):
            v = enrich.get(key) or ""
            if v:
                parts.append(str(v))

    # Pitch complet
    try:
        parts.append(json.dumps(pitch, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        pass

    return _extract_numeric_tokens(" ".join(parts))


def _truncate_objet(objet: str, max_chars: int = _OBJET_MAX_CHARS) -> str:
    """
    Tronque l'objet a max_chars en coupant au dernier espace.
    Strategy : degradation gracieuse plutot que rejet — un objet tronque
    reste utilisable, un objet vide ne l'est pas.
    """
    objet = objet.strip()
    if len(objet) <= max_chars:
        return objet
    cut = objet.rfind(" ", 0, max_chars)
    if cut > 0:
        return objet[:cut]
    return objet[:max_chars]


# ---------------------------------------------------------------------------
# Appels Claude
# ---------------------------------------------------------------------------

def _call_rewrite_body(
    client: Any,
    body_fallback: str,
    context_summary: str,
    model: str,
    style_example: str | None = None,
) -> str | None:
    """
    Call 1 : reformulation du corps.
    Retourne le texte reformule ou None si l'appel echoue.

    style_example est injecte dans le user prompt via _build_user_body.
    Il n'est PAS utilise pour elargir le set de tokens autorises.
    """
    user_msg = _build_user_body(body_fallback, context_summary, style_example)
    msg = client.messages.create(
        model=model,
        max_tokens=600,
        system=_SYSTEM_BODY,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content).strip()
    return text if text else None


def _call_rewrite_objet(
    client: Any,
    body_reecrit: str,
    context: dict[str, Any],
    model: str,
) -> str | None:
    """
    Call 2 : generation de l'objet email.
    Retourne la ligne d'objet ou None si l'appel echoue.
    """
    incident = context.get("incident") or {}
    marque = (incident.get("marque") or "la marque").strip()
    motif = (incident.get("motif") or "incident produit").strip()
    motif_court = motif[:80]

    user_msg = _USER_OBJET_TMPL.format(
        body_reecrit=body_reecrit,
        marque=marque,
        motif_court=motif_court,
    )
    msg = client.messages.create(
        model=model,
        max_tokens=100,
        system=_SYSTEM_OBJET,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content).strip()
    return text if text else None


# ---------------------------------------------------------------------------
# Interface publique
# ---------------------------------------------------------------------------

def rewrite(
    body_fallback: str,
    context: dict[str, Any],
    pitch: dict[str, Any],
    *,
    model: str = "claude-haiku-4-5-20251001",
) -> dict[str, Any]:
    """
    Reecrit le body de l email via Claude Haiku pour ameliorer le style.
    Genere aussi un objet plus naturel.

    Fallback transparent vers body_fallback si :
    - ANTHROPIC_API_KEY absente.
    - Exception API.
    - Garde-fou hallucination declenche.

    Returns:
        {"body_md": str, "objet": str, "llm_used": bool, "reason": str|None}
        Si llm_used=False, reason explique pourquoi (e.g. "no_api_key",
        "api_error", "hallucination_detected").
    """
    # Objet par defaut base sur la marque (utilise si LLM non disponible ou en erreur)
    incident = context.get("incident") or {}
    marque = (incident.get("marque") or "").strip()
    default_objet = (
        f"Suite au rappel {marque} - tracabilite produit"
        if marque
        else "Tracabilite produit - suite a votre actualite recente"
    )

    def _fallback(reason: str) -> dict[str, Any]:
        return {
            "body_md": body_fallback,
            "objet": default_objet,
            "llm_used": False,
            "reason": reason,
        }

    # --- Verifications pre-appel ---

    if Anthropic is None:
        logger.warning("SDK anthropic non installe. Fallback body_fallback.")
        return _fallback("anthropic_not_installed")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.debug("ANTHROPIC_API_KEY absente. Fallback body_fallback.")
        return _fallback("no_api_key")

    # Sets de tokens autorises (sous-set explicite du contexte + pitch + brouillon).
    # L'exemple stylistique est intentionnellement exclu de tous ces sets :
    # s'il fuit un chiffre, une URL ou un email dans la sortie LLM, les
    # garde-fous hallucination / link_injection doivent se declencher.
    allowed_tokens = _build_allowed_tokens(body_fallback, context, pitch)
    allowed_urls, allowed_emails, allowed_phone_tokens = _build_allowed_link_tokens(
        body_fallback, pitch
    )

    context_summary = _summarize_context(context)

    # Charge l'exemple une fois par appel rewrite() pour permettre le mock dans
    # les tests. Le cache module-level de style_loader evite les I/O repetitives.
    style_example = load_style_example()

    # --- Appels Claude ---

    try:
        client = Anthropic(api_key=api_key)

        body_reecrit = _call_rewrite_body(
            client, body_fallback, context_summary, model, style_example
        )
        if not body_reecrit:
            logger.warning("Reponse vide pour Call 1. Fallback body_fallback.")
            return _fallback("api_error")

        objet_llm = _call_rewrite_objet(client, body_reecrit, context, model)
        # Call 2 est best-effort : si l'objet est vide, on garde le body reecrit
        # et on degrade vers l'objet par defaut (pas de fallback complet).
        if not objet_llm or not objet_llm.strip():
            logger.warning("Reponse vide pour Call 2 (objet). Utilisation de l'objet par defaut.")
            objet_llm = default_objet

    except Exception as exc:
        logger.warning("Appel Claude echoue : %s. Fallback body_fallback.", exc)
        return _fallback("api_error")

    # --- Garde-fou ASCII ---
    # Windows cp1252 : tout caractere non-ASCII provoquerait une erreur a l'affichage
    # ou au stockage. On prefere fallback plutot que corruption silencieuse.
    if not body_reecrit.isascii():
        logger.warning("Body LLM contient des caracteres non-ASCII. Fallback.")
        return _fallback("non_ascii_detected")

    # --- Garde-fou hallucination ---
    # Un token numerique present dans le body reecrit mais absent du set autorise
    # et ayant au moins 2 chiffres (evite de rejeter des "1er", "2e", etc.) est
    # considere comme une hallucination probable.
    body_tokens = _extract_numeric_tokens(body_reecrit)
    invented = {t for t in body_tokens - allowed_tokens if len(t) >= 2}
    if invented:
        logger.warning(
            "Tokens numeriques inventes detectes : %s. Fallback body_fallback.", invented
        )
        return _fallback("hallucination_detected")

    # --- Garde-fou link_injection ---
    # Detecte les URLs, emails et numeros de telephone presents dans le body LLM
    # mais absents du set autorise (pitch + body_fallback uniquement).
    # Vise specifiquement la fuite de coordonnees depuis l'exemple stylistique.
    body_urls = _extract_urls(body_reecrit)
    injected_urls = body_urls - allowed_urls
    if injected_urls:
        logger.warning(
            "URLs non autorisees detectees dans le body LLM : %s. Fallback.", injected_urls
        )
        return _fallback("link_injection")

    body_emails = _extract_emails(body_reecrit)
    injected_emails = body_emails - allowed_emails
    if injected_emails:
        logger.warning(
            "Emails non autorises detectes dans le body LLM : %s. Fallback.", injected_emails
        )
        return _fallback("link_injection")

    body_phone_tokens = _extract_phone_tokens(body_reecrit)
    injected_phones = body_phone_tokens - allowed_phone_tokens
    if injected_phones:
        logger.warning(
            "Tokens telephone non autorises detectes dans le body LLM : %s. Fallback.",
            injected_phones,
        )
        return _fallback("link_injection")

    # --- Nettoyage de l'objet ---
    objet_final = _truncate_objet(objet_llm.strip())
    # Fallback objet si LLM retourne une chaine vide apres nettoyage
    if not objet_final:
        objet_final = default_objet

    return {
        "body_md": body_reecrit,
        "objet": objet_final,
        "llm_used": True,
        "reason": None,
    }
