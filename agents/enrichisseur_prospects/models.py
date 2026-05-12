"""Modèles de données de l'enrichisseur de prospects."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


MATCH_STATUSES = ("found", "ambiguous", "not_found", "skipped")

# Seuils de confiance pour le match nom de marque / raison sociale
CONFIDENCE_FOUND = 0.72      # au-dessus : found
CONFIDENCE_AMBIGUOUS = 0.40  # entre les deux : ambiguous


TRANCHE_EFFECTIF = {
    "00": "0 salarié",
    "01": "1-2",
    "02": "3-5",
    "03": "6-9",
    "11": "10-19",
    "12": "20-49",
    "21": "50-99",
    "22": "100-199",
    "31": "200-249",
    "32": "250-499",
    "41": "500-999",
    "42": "1 000-1 999",
    "51": "2 000-4 999",
    "52": "5 000-9 999",
    "53": "10 000+",
}


@dataclass
class EnrichissementResult:
    """Résultat d'enrichissement pour un incident."""

    # Clé
    source: str
    source_id: str
    enricher_version: str

    # Input
    marque_input: Optional[str]
    query_used: Optional[str]          # terme normalisé envoyé à l'API

    # Matching
    match_status: str                  # found | ambiguous | not_found | skipped
    confidence: float                  # 0.0–1.0

    # Identification SIRENE
    siren: Optional[str] = None
    siret_siege: Optional[str] = None
    raison_sociale: Optional[str] = None
    forme_juridique: Optional[str] = None
    code_naf: Optional[str] = None
    libelle_naf: Optional[str] = None
    adresse: Optional[str] = None
    effectif_tranche: Optional[str] = None  # libellé lisible
    categorie_entreprise: Optional[str] = None  # PME / ETI / GE

    # Contact (issu de SIRENE ou Pappers)
    contact_nom: Optional[str] = None
    contact_titre: Optional[str] = None
    contact_source: Optional[str] = None   # 'sirene' | 'societecom' | 'pappers'
    contact_type: Optional[str] = None     # 'cible' | 'fallback_dirigeant'

    # Réservé pour enrichissement futur (societe.com / Pappers)
    ca_annuel: Optional[str] = None

    # Meta
    api_used: str = "sirene"
    enriched_at: datetime = field(default_factory=datetime.utcnow)
    raw_json: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["enriched_at"] = self.enriched_at.isoformat()
        return d
