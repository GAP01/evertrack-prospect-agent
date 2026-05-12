"""Modèles de données du détecteur de signaux faibles."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


DETECTOR_VERSION = "v0.1"

# Statuts d'un signal
STATUS_FAIBLE = "faible"        # score < seuil alerte
STATUS_A_VALIDER = "a_valider"  # score >= seuil, en attente d'action humaine
STATUS_VALIDE = "valide"        # validé mais pas encore promu
STATUS_REJETE = "rejete"        # faux positif, ignoré
STATUS_PROMU = "promu"          # promu en incident dans incidents.sqlite

STATUSES = (STATUS_FAIBLE, STATUS_A_VALIDER, STATUS_VALIDE, STATUS_REJETE, STATUS_PROMU)

# Seuil de score pour passer en 'a_valider'
# (calibré à 40 après observation : les signaux crédibles plafonnent vers 40-50
#  car la dédup + poids sources permettent rarement d'atteindre 60+)
SCORE_SEUIL_ALERTE = 40


@dataclass
class SignalSource:
    """Une source qui a remonté ce signal (N sources possibles par signal)."""
    source_type: str          # 'google_news' | 'reddit'
    source_name: str          # 'LSA', 'Le Monde', 'r/france', ...
    source_url: str
    titre: str
    detected_at: datetime
    contenu: Optional[str] = None
    # Optionnel : permet à un collector d'imposer son propre signal_id
    # (ex: signalconso_volume qui inclut dep_code dans la dédup).
    # Si None, detecteur.run_detect calcule le signal_id par compute_signal_id.
    forced_signal_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["detected_at"] = self.detected_at.isoformat()
        return d


@dataclass
class SignalAlerte:
    """Un signal faible détecté — potentiellement fusion de plusieurs sources."""

    # Identité (hash sur titre+marque+jour pour dedup stable)
    signal_id: str
    detector_version: str = DETECTOR_VERSION

    # Contenu extrait
    marque: Optional[str] = None
    produit: Optional[str] = None
    symptome: Optional[str] = None       # listeria, corps étranger, allergène, ...
    titre: Optional[str] = None          # titre canonique (1re source)
    resume: Optional[str] = None         # résumé court (1-2 phrases)

    # Source primaire (pour affichage rapide)
    source_type: str = ""                # 'google_news' | 'reddit'
    source_name: str = ""
    source_url: str = ""

    # Scoring
    score: int = 0
    score_breakdown: dict[str, int] = field(default_factory=dict)
    status: str = STATUS_FAIBLE

    # Promotion
    promu_vers_source: Optional[str] = None   # "signal_detecteur"
    promu_vers_source_id: Optional[str] = None  # = signal_id si promu

    # Timestamps
    detected_at: datetime = field(default_factory=datetime.utcnow)
    last_seen_at: datetime = field(default_factory=datetime.utcnow)

    # Meta
    raw_json: Optional[str] = None            # payload 1re source

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["detected_at"] = self.detected_at.isoformat()
        d["last_seen_at"] = self.last_seen_at.isoformat()
        return d
