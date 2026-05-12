"""
Client pour l'API recherche-entreprises (data.gouv.fr / INSEE).

Endpoint : https://recherche-entreprises.api.gouv.fr/search
- Gratuit, sans authentification
- Retourne SIREN, raison sociale, NAF, adresse, dirigeants, effectif
- Documentation : https://recherche-entreprises.api.gouv.fr/docs
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://recherche-entreprises.api.gouv.fr"
_TIMEOUT = 10  # secondes


class SireneAPIError(Exception):
    pass


class SireneClient:
    def __init__(self, timeout: int = _TIMEOUT):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "EverTrack/1.0 (enrichisseur-prospects)"
        self.timeout = timeout

    def search(self, query: str, nombre: int = 5) -> list[dict[str, Any]]:
        """
        Recherche des entreprises par texte libre.

        Retourne une liste de résultats bruts (dict) tels que renvoyés par l'API.
        Lève SireneAPIError en cas d'échec réseau ou HTTP.
        """
        try:
            resp = self.session.get(
                f"{_BASE_URL}/search",
                params={"q": query, "nombre": nombre},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise SireneAPIError(f"Timeout SIRENE pour query={query!r}")
        except requests.exceptions.RequestException as exc:
            raise SireneAPIError(f"Erreur réseau SIRENE : {exc}") from exc

        data = resp.json()
        return data.get("results", [])

    def get_by_siren(self, siren: str) -> Optional[dict[str, Any]]:
        """Lookup direct par SIREN (pour vérification ou enrichissement futur)."""
        try:
            resp = self.session.get(
                f"{_BASE_URL}/search",
                params={"q": siren, "nombre": 1},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise SireneAPIError(f"Erreur réseau SIRENE (siren={siren}) : {exc}") from exc

        results = resp.json().get("results", [])
        if results and results[0].get("siren") == siren:
            return results[0]
        return None


def extract_company_fields(result: dict[str, Any]) -> dict[str, Any]:
    """
    Extrait les champs utiles d'un résultat brut de l'API.

    Retourne un dict plat prêt à alimenter EnrichissementResult.

    Note : SIRENE ne retourne que des représentants légaux (gérants, PDG…).
    Le contact_type est donc toujours 'fallback_dirigeant' ici — Pappers peut
    l'améliorer en 'cible' si des profils qualité/supply/conformité sont trouvés.
    """
    from .models import TRANCHE_EFFECTIF
    from .contact_profiles import select_best_contact

    siege = result.get("siege") or {}
    dirigeants = result.get("dirigeants") or []

    contact_nom: Optional[str] = None
    contact_titre: Optional[str] = None
    contact_type: Optional[str] = None

    if dirigeants:
        chosen, contact_type = select_best_contact(dirigeants)
        if chosen:
            prenom = (chosen.get("prenoms") or "").strip()
            nom = (chosen.get("nom") or "").strip()
            contact_nom = f"{prenom} {nom}".strip() if prenom or nom else None
            contact_titre = (chosen.get("qualite") or "").strip() or None

    tranche_code = result.get("tranche_effectif_salarie")
    effectif_tranche = TRANCHE_EFFECTIF.get(tranche_code) if tranche_code else None

    adresse_parts = [
        siege.get("numero_voie"),
        siege.get("type_voie"),
        siege.get("libelle_voie"),
        siege.get("code_postal"),
        siege.get("libelle_commune"),
    ]
    adresse = " ".join(p for p in adresse_parts if p) or siege.get("adresse") or None

    return {
        "siren": result.get("siren"),
        "siret_siege": siege.get("siret"),
        "raison_sociale": result.get("nom_complet") or result.get("nom_raison_sociale"),
        "forme_juridique": result.get("libelle_nature_juridique"),
        "code_naf": result.get("activite_principale"),
        "libelle_naf": result.get("libelle_activite_principale"),
        "adresse": adresse,
        "effectif_tranche": effectif_tranche,
        "categorie_entreprise": result.get("categorie_entreprise"),
        "contact_nom": contact_nom,
        "contact_titre": contact_titre,
        "contact_source": "sirene" if contact_nom else None,
        "contact_type": contact_type,
    }
