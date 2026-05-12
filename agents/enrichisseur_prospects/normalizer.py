"""
Normalisation de la marque brute avant envoi à l'API SIRENE.

Problèmes à traiter :
- Formes juridiques parasites (SAS, SARL, SA, SASU...)
- Accents et caractères spéciaux
- Marques génériques invalides ("sans marque", "-", etc.)
- Casse
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional


# Formes juridiques à ignorer en fin ou début de nom
_FORMES_JURIDIQUES = {
    "sa", "sas", "sarl", "sasu", "snc", "sci", "scop", "se",
    "scs", "eurl", "ei", "auto-entrepreneur", "sca", "gie",
    "association", "assoc",
}

# Termes qui seuls ne constituent pas un nom de marque exploitable
_GENERIC_BRANDS = {
    "sans marque", "sans marques", "sans", "-", "", "n/a",
    "na", "?", "nc", "inconnu", "unknown", "divers", "various",
    "non renseigne", "non renseigné", "nr", "autres",
}

# Mots à retirer systématiquement du nom (trop génériques)
_STOP_WORDS = {"france", "groupe", "group", "international", "europe"}

_RE_PUNCT = re.compile(r"[^\w\s]")
_RE_SPACES = re.compile(r"\s+")


def _strip_accents(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def normalize_marque(marque: Optional[str]) -> Optional[str]:
    """Retourne une requête propre pour l'API, ou None si la marque est inutilisable."""
    if not marque:
        return None

    s = marque.strip().lower()
    s = _strip_accents(s)

    if s in _GENERIC_BRANDS:
        return None

    # Retire ponctuation (sauf tirets dans les noms composés — on garde les tirets)
    s = re.sub(r"[^\w\s\-]", " ", s)

    # Retire les formes juridiques isolées comme mots
    words = s.split()
    cleaned = [w for w in words if w not in _FORMES_JURIDIQUES]

    # Retire les stop words seulement si d'autres mots restent
    without_stop = [w for w in cleaned if w not in _STOP_WORDS]
    if without_stop:
        cleaned = without_stop

    s = " ".join(cleaned).strip()
    s = _RE_SPACES.sub(" ", s)

    # Nom trop court = inutilisable (ex: "-", "a")
    if len(s) < 2:
        return None

    return s


def normalize_distributeur(distributeurs: Optional[str]) -> Optional[str]:
    """
    Extrait le premier distributeur identifiable comme fallback quand la marque
    est invalide. Ignore les distributions géo-localisées trop spécifiques.
    """
    if not distributeurs:
        return None

    # Prend le premier token avant une virgule, "et", "uniquement"
    first = re.split(r"[,;]|\bet\b|\buniquement\b", distributeurs, maxsplit=1)[0]
    first = first.strip()

    # Si le distributeur ressemble à une adresse ou est trop long, on l'ignore
    if len(first) > 60 or len(first) < 2:
        return None

    return normalize_marque(first)
