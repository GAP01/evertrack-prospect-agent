"""
Client Pappers API — enrichissement contact dirigeant.

Activé quand PAPPERS_API_KEY est définie (dans .env ou variable d'env).
Documentation : https://www.pappers.fr/api/documentation

Usage : lookup par SIREN après identification SIRENE, pour récupérer
le dirigeant principal et ses coordonnées.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.pappers.fr/v2"
_TIMEOUT = 10


class PappersNotConfiguredError(Exception):
    pass


class PappersAPIError(Exception):
    pass


class PappersClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("PAPPERS_API_KEY")
        if not self.api_key:
            raise PappersNotConfiguredError(
                "Variable d'environnement PAPPERS_API_KEY non définie."
            )
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "EverTrack/1.0 (enrichisseur-prospects)"

    def get_by_siren(self, siren: str) -> Optional[dict[str, Any]]:
        """
        Récupère les données complètes d'une entreprise par son SIREN.

        Retourne le dict brut Pappers, ou None si non trouvé.
        """
        try:
            resp = self.session.get(
                f"{_BASE_URL}/entreprise",
                params={"siren": siren, "api_token": self.api_key},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise PappersAPIError(f"Timeout Pappers pour siren={siren}")
        except requests.exceptions.RequestException as exc:
            raise PappersAPIError(f"Erreur réseau Pappers : {exc}") from exc

        return resp.json()

    def extract_contact(self, data: dict[str, Any]) -> dict[str, Optional[str]]:
        """
        Extrait le contact le plus pertinent depuis une réponse Pappers.

        Priorité :
        1. Profil qualité / supply chain / conformité (contact_type='cible')
        2. Dirigeant exécutif en fallback (contact_type='fallback_dirigeant')

        Retourne un dict avec contact_nom, contact_titre, contact_type.
        """
        from .contact_profiles import select_best_contact

        dirigeants = data.get("dirigeants") or []
        if not dirigeants:
            return {"contact_nom": None, "contact_titre": None, "contact_type": None}

        chosen, contact_type = select_best_contact(dirigeants)
        if chosen is None:
            return {"contact_nom": None, "contact_titre": None, "contact_type": None}

        prenom = (chosen.get("prenom") or chosen.get("prenoms") or "").strip()
        nom = (chosen.get("nom") or "").strip().upper()
        contact_nom = f"{prenom} {nom}".strip() if prenom or nom else None
        contact_titre = (chosen.get("qualite") or "").strip() or None

        return {
            "contact_nom": contact_nom,
            "contact_titre": contact_titre,
            "contact_type": contact_type,
        }
