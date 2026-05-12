"""
Modèle de données normalisé pour un incident produit.

On garde une structure simple et stable, indépendante du schéma exact de
RappelConso (qui peut évoluer). Les champs qu'on n'arrive pas à mapper
atterrissent dans `raw` pour inspection ultérieure.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any, Optional


@dataclass
class Incident:
    # Identité
    source: str                          # "rappelconso" (pour l'instant)
    source_id: str                       # référence unique côté source
    source_url: Optional[str] = None     # lien vers la fiche publique

    # Produit
    categorie: Optional[str] = None      # ex. "Alimentation"
    sous_categorie: Optional[str] = None
    marque: Optional[str] = None
    modeles: Optional[str] = None        # noms/références concaténés
    nature_juridique: Optional[str] = None  # Rappel / Retrait

    # Incident
    motif: Optional[str] = None
    risques: Optional[str] = None
    zone_geographique: Optional[str] = None
    date_publication: Optional[date] = None

    # Acteurs
    distributeurs: Optional[str] = None  # liste concaténée
    # Numéro d'agrément sanitaire DGAL (CE 853/2004) — identifie l'établissement
    # de production réel. Format : "FR XX.XXX.XXX.CE" (souvent en minuscules en
    # provenance de l'API). Permet le lookup direct vers SIRET via la liste
    # publique des établissements agréés.
    marque_salubrite: Optional[str] = None
    # fabricant n'est pas toujours explicite dans RappelConso — à inférer plus tard

    # Traçabilité & debug
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.date_publication is not None:
            d["date_publication"] = self.date_publication.isoformat()
        return d
