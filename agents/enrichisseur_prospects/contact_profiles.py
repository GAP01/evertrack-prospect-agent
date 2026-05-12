"""
Classification des contacts selon leur pertinence pour EverTrack.

Les profils cibles sont les opérationnels qualité/conformité/supply chain,
pas les dirigeants. Les dirigeants sont conservés en fallback.
"""

from __future__ import annotations

from typing import Any, Optional
from .normalizer import _strip_accents


# Mots-clés qui signalent un profil CIBLE (responsable opérationnel)
_TARGET_KEYWORDS = [
    "qualit",           # responsable qualité, directeur qualité, QHSE
    "qhse",
    "hse",
    "supply chain",
    "supply-chain",
    "chaine d appro",
    "chaine d'appro",
    "approvisionnement",
    "logistique",
    "conformit",        # responsable conformité, conformité réglementaire
    "reglementaire",
    "regulatory",
    "compliance",
    "securite alimentaire",
    "food safety",
    "sécurité des produits",
    "securite des produits",
    "rappel",           # responsable procédures de rappel
    "traçabilit",
    "tracabilit",
]

# Mots-clés qui signalent un DIRIGEANT (fallback si aucun profil cible trouvé)
_EXECUTIVE_KEYWORDS = [
    "president", "directeur general", "dg ", "pdg", "gerant",
    "ceo", "coo", "cfo", "chief", "associe", "administrateur",
]


def _normalize_titre(titre: str) -> str:
    return _strip_accents(titre.lower().strip())


def classify_contact_type(titre: Optional[str]) -> str:
    """
    Retourne 'cible' si le titre correspond à un profil qualité/supply/conformité,
    'fallback_dirigeant' sinon.
    """
    if not titre:
        return "fallback_dirigeant"
    n = _normalize_titre(titre)
    for kw in _TARGET_KEYWORDS:
        if kw in n:
            return "cible"
    return "fallback_dirigeant"


def select_best_contact(
    dirigeants: list[dict[str, Any]],
) -> tuple[Optional[dict[str, Any]], str]:
    """
    Sélectionne le meilleur contact dans une liste de dirigeants/contacts.

    Stratégie :
    1. Premier profil avec titre correspondant aux cibles EverTrack
    2. Sinon, premier profil identifié comme dirigeant exécutif
    3. Sinon, premier de la liste

    Retourne (personne_dict, contact_type).
    Le contact_type est 'cible' ou 'fallback_dirigeant'.
    """
    if not dirigeants:
        return None, "fallback_dirigeant"

    # Passe 1 : chercher un profil cible
    for d in dirigeants:
        titre = d.get("qualite") or d.get("titre") or ""
        if classify_contact_type(titre) == "cible":
            return d, "cible"

    # Passe 2 : priorité entre dirigeants (PDG > DG > Gérant > premier)
    priority_order = [
        "directeur general", "president", "pdg", "gerant", "dg ",
    ]
    for kw in priority_order:
        for d in dirigeants:
            titre = _normalize_titre(d.get("qualite") or d.get("titre") or "")
            if kw in titre:
                return d, "fallback_dirigeant"

    # Passe 3 : premier de la liste
    return dirigeants[0], "fallback_dirigeant"
