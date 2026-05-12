"""
Extraction structurée (marque, produit, symptôme) depuis un titre + contenu.

Stratégie à deux niveaux, calquée sur evaluateur_severite.llm_scorer :
- Si ANTHROPIC_API_KEY présente et SDK installé → appel Claude Haiku.
- Sinon → fallback regex + keyword matching.

Le LLM doit retourner un JSON strict :
    {"marque": str|null, "produit": str|null, "symptome": str|null,
     "is_alim": bool, "resume": str}

`is_alim=false` signale un faux positif (ex: rappel véhicule) → le signal
sera rejeté en amont.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from .keywords import NEGATIVE_FILTERS, SYMPTOM_KEYWORDS

logger = logging.getLogger(__name__)


@dataclass
class Extraction:
    marque: Optional[str]
    produit: Optional[str]
    symptome: Optional[str]
    resume: Optional[str]
    is_alim: bool = True
    source: str = "regex"  # 'llm' | 'regex'


SYSTEM_PROMPT = """Tu es un expert en veille agroalimentaire et signaux faibles sanitaires.

Ta tache : extraire depuis un titre + extrait de presse (ou post social) FRANCAIS les informations structurees d'un incident ou rappel produit ALIMENTAIRE.

Pertinence : tu dois identifier UNIQUEMENT les incidents liés à l'alimentation (produits consommables : aliments, boissons, compléments). Si le texte concerne un rappel automobile, jouet, médicament, cosmétique, outil, etc. → is_alim=false.

Extrais strictement :
- marque       : nom commercial de la marque (ex: "Nestlé", "Leclerc", "Lustucru"), ou null si absent
- produit      : type de produit (ex: "saucisson", "pizza surgelée", "eau de source"), ou null
- symptome     : danger identifié (ex: "listeria", "corps étranger", "allergène non déclaré", "salmonelle"), ou null
- is_alim      : true si c'est un incident alimentaire, false sinon
- resume       : phrase de 1 ligne resumant l'incident en francais (max 180 chars)

Reponds STRICTEMENT en JSON valide, sans texte autour, exactement ce schema :
{"marque": "<str|null>", "produit": "<str|null>", "symptome": "<str|null>", "is_alim": <bool>, "resume": "<str>"}

Pas de markdown, pas de bloc de code, juste le JSON."""


USER_TEMPLATE = """Titre : {titre}

Contenu :
{contenu}

Source : {source}

Extrais le JSON."""


# --- Fallback regex -------------------------------------------------------

# Marques connues du corpus RappelConso (à enrichir — MVP minimal)
# En fallback sans LLM, on se contente de capturer des patterns "marque X"
# et on laisse marque=None si rien de fiable.
_MARQUE_PATTERNS = [
    re.compile(r"\bde la marque ([A-ZÉÈÊÀÂÎÔÛÇ][\wÀ-ÿ'’\-\s]{1,30}?)(?=[,\.\s]|$)", re.UNICODE),
    re.compile(r"\bmarque\s+([A-ZÉÈÊÀÂÎÔÛÇ][\wÀ-ÿ'’\-\s]{1,30}?)(?=[,\.\s]|$)", re.UNICODE),
    re.compile(r"\bchez\s+([A-ZÉÈÊÀÂÎÔÛÇ][\wÀ-ÿ'’\-]{1,20})", re.UNICODE),
]

_SYMPTOME_MAP = [
    ("listeria", "listeria"),
    ("listeriose", "listeria"),
    ("salmonel", "salmonelle"),
    ("e.coli", "e.coli"),
    ("escherichia coli", "e.coli"),
    ("botulisme", "botulisme"),
    ("norovirus", "norovirus"),
    ("allergene non declar", "allergène non déclaré"),
    ("allergene non mentionn", "allergène non déclaré"),
    ("corps etranger", "corps étranger"),
    ("morceau de verre", "corps étranger (verre)"),
    ("fragment de plastique", "corps étranger (plastique)"),
    ("fragment de metal", "corps étranger (métal)"),
    ("moisissure", "moisissure"),
    ("toxine", "toxine"),
    ("intoxication alimentaire", "intoxication alimentaire"),
]


def _strip_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def has_negative_filter(title: str) -> bool:
    """True si le titre contient un des faux-positifs connus."""
    low = title.lower()
    return any(neg in low for neg in NEGATIVE_FILTERS)


def has_symptom_keyword(text: str) -> bool:
    """True si au moins un mot-clé symptôme apparaît."""
    low = _strip_accents(text.lower())
    return any(_strip_accents(kw) in low for kw in SYMPTOM_KEYWORDS)


def _regex_extract_marque(text: str) -> Optional[str]:
    for pattern in _MARQUE_PATTERNS:
        m = pattern.search(text)
        if m:
            candidate = m.group(1).strip(" ,.'’-")
            if len(candidate) >= 2:
                return candidate
    return None


def _regex_extract_symptome(text: str) -> Optional[str]:
    low = _strip_accents(text.lower())
    for needle, label in _SYMPTOME_MAP:
        if _strip_accents(needle) in low:
            return label
    return None


def _fallback_extract(titre: str, contenu: str) -> Extraction:
    blob = f"{titre}\n{contenu}"
    # is_alim heuristique : si un symptome OU un mot-clé alim est présent
    is_alim = has_symptom_keyword(blob) and not has_negative_filter(titre)
    marque = _regex_extract_marque(blob)
    symptome = _regex_extract_symptome(blob)
    # Résumé = titre tronqué
    resume = titre[:180]
    return Extraction(
        marque=marque,
        produit=None,
        symptome=symptome,
        resume=resume,
        is_alim=is_alim,
        source="regex",
    )


# --- Appel Claude Haiku ---------------------------------------------------

def _call_claude(
    titre: str, contenu: str, source_name: str,
    model: str = "claude-haiku-4-5-20251001",
) -> Optional[Extraction]:
    try:
        import anthropic  # type: ignore
    except ImportError:
        logger.warning("SDK anthropic absent. Fallback regex.")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.debug("ANTHROPIC_API_KEY absente. Fallback regex.")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    user_msg = USER_TEMPLATE.format(
        titre=titre,
        contenu=(contenu or "(aucun contenu)")[:1500],
        source=source_name or "inconnue",
    )

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        logger.warning("Appel Claude échoué (%s). Fallback regex.", exc)
        return None

    text = "".join(getattr(b, "text", "") for b in msg.content).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        logger.warning("Réponse LLM sans JSON : %r", text[:200])
        return None

    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("JSON LLM invalide (%s) : %r", exc, text[:200])
        return None

    def _clean(v, maxlen: int = 100) -> Optional[str]:
        if v is None or v == "null" or v == "":
            return None
        return str(v).strip()[:maxlen]

    return Extraction(
        marque=_clean(data.get("marque"), 80),
        produit=_clean(data.get("produit"), 100),
        symptome=_clean(data.get("symptome"), 100),
        resume=_clean(data.get("resume"), 180) or titre[:180],
        is_alim=bool(data.get("is_alim", True)),
        source="llm",
    )


# --- Interface publique ---------------------------------------------------

def extract(
    titre: str,
    contenu: str,
    source_name: str,
    use_llm: bool = True,
) -> Extraction:
    """
    Extrait marque/produit/symptôme depuis titre + contenu.

    Priorité LLM si dispo, sinon regex. Toujours retourne une Extraction
    (éventuellement avec is_alim=False si faux positif détecté).
    """
    # Filtre négatif immédiat
    if has_negative_filter(titre):
        return Extraction(
            marque=None, produit=None, symptome=None,
            resume=titre[:180], is_alim=False, source="regex",
        )

    if use_llm:
        extracted = _call_claude(titre, contenu, source_name)
        if extracted is not None:
            return extracted

    return _fallback_extract(titre, contenu)
