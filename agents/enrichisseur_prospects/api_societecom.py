"""
Stub — client societe.com API Pro.

Activé quand la variable d'environnement SOCIETECOM_API_KEY est définie.
Documentation : https://api.societe.com/pro/

Implémentation prévue :
- Lookup par SIREN pour récupérer dirigeants + données financières
- Endpoint : GET https://api.societe.com/api/v2/entreprise/{siren}
"""

from __future__ import annotations

import os
from typing import Any, Optional


class SocieteComNotConfiguredError(Exception):
    pass


class SocieteComClient:
    def __init__(self):
        self.api_key = os.environ.get("SOCIETECOM_API_KEY")
        if not self.api_key:
            raise SocieteComNotConfiguredError(
                "Variable d'environnement SOCIETECOM_API_KEY non définie. "
                "Obtenez une clé sur https://api.societe.com/pro/"
            )

    def get_by_siren(self, siren: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError("societe.com API Pro — à implémenter (clé requise)")

    def extract_contact(self, result: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("societe.com API Pro — à implémenter")
