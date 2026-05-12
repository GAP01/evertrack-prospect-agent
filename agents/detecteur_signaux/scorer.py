"""
Scoring de crédibilité d'un signal (0-100).

Composition :
    source_weight (0-35)  : qualité de la source
    recurrence    (0-30)  : nombre de sources distinctes
    recency       (0-15)  : fraîcheur du signal
    brand_known   (0-10)  : marque déjà dans incidents.sqlite (EverTrack)
    sentiment     (0-10)  : négatif fort = bonus (MVP : heuristique)

Seuil d'alerte : 60 → passe en `a_valider`.
"""

from __future__ import annotations

import logging
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .keywords import DEFAULT_SOURCE_WEIGHT, SOURCE_WEIGHTS
from .models import SCORE_SEUIL_ALERTE, STATUS_A_VALIDER, STATUS_FAIBLE

logger = logging.getLogger(__name__)


MAX_SOURCE_WEIGHT = 35
MAX_RECURRENCE = 30
MAX_RECENCY = 15
MAX_BRAND_KNOWN = 10
MAX_SENTIMENT = 10


# --- Composants individuels ---------------------------------------------

def score_source_weight(source_name: str) -> int:
    """Poids de la source [0-35]. Case-insensitive, match par substring."""
    if not source_name:
        return DEFAULT_SOURCE_WEIGHT
    low = source_name.lower()
    # Match exact > match substring
    if low in SOURCE_WEIGHTS:
        return min(SOURCE_WEIGHTS[low], MAX_SOURCE_WEIGHT)
    # Substring match (ex: "Le Monde.fr" contient "le monde")
    for pattern, weight in SOURCE_WEIGHTS.items():
        if pattern in low:
            return min(weight, MAX_SOURCE_WEIGHT)
    return DEFAULT_SOURCE_WEIGHT


def score_recurrence(n_sources: int) -> int:
    """10 points par source distincte, cappé à 30."""
    return min(n_sources * 10, MAX_RECURRENCE)


def score_recency(detected_at: datetime, now: Optional[datetime] = None) -> int:
    """Plus c'est récent, plus c'est fort (max 15)."""
    now = now or datetime.utcnow()
    delta_h = max(0.0, (now - detected_at).total_seconds() / 3600.0)
    if delta_h < 24:
        return 15
    if delta_h < 72:
        return 10
    if delta_h < 24 * 7:
        return 5
    return 0


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def score_brand_known(
    marque: Optional[str],
    incidents_db: Optional[Path],
) -> int:
    """+10 si la marque apparait déjà dans incidents.sqlite (même normalisée)."""
    if not marque or not incidents_db:
        return 0
    db = Path(incidents_db)
    if not db.exists():
        return 0

    needle = _strip_accents(marque.lower()).strip()
    if not needle or len(needle) < 2:
        return 0

    try:
        with sqlite3.connect(db) as conn:
            # Requête tolérante sur la casse, enlève les accents côté python
            rows = conn.execute(
                "SELECT DISTINCT marque FROM incidents WHERE marque IS NOT NULL"
            ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("incidents.sqlite lecture échouée : %s", exc)
        return 0

    for (existing,) in rows:
        if not existing:
            continue
        if needle in _strip_accents(existing.lower()):
            return MAX_BRAND_KNOWN
    return 0


# Mots négatifs forts en FR (heuristique simple, sans lib externe)
_NEGATIVE_WORDS = {
    "danger", "dangereux", "grave", "mort", "décès", "deces", "hospitalisation",
    "intoxiqué", "intoxique", "alerte", "scandale", "catastrophe", "urgent",
    "urgence", "risque vital", "empoisonné", "empoisonne", "malade", "malades",
    "hospitalise", "hospitalisé", "hospitalises", "hospitalisés",
}


def score_sentiment(titre: str, contenu: str = "") -> int:
    """Heuristique : +10 si >=2 mots négatifs, +5 si 1, sinon 0."""
    blob = _strip_accents(f"{titre} {contenu}".lower())
    hits = sum(1 for w in _NEGATIVE_WORDS if w in blob)
    if hits >= 2:
        return MAX_SENTIMENT
    if hits == 1:
        return 5
    return 0


# --- Agrégation ----------------------------------------------------------

def compute_score(
    source_name: str,
    n_sources: int,
    detected_at: datetime,
    marque: Optional[str],
    titre: str,
    contenu: str = "",
    incidents_db: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> tuple[int, dict[str, int]]:
    """
    Retourne (score_total, breakdown).

    breakdown = {"source_weight": int, "recurrence": int, ...}
    """
    breakdown = {
        "source_weight": score_source_weight(source_name),
        "recurrence": score_recurrence(n_sources),
        "recency": score_recency(detected_at, now=now),
        "brand_known": score_brand_known(marque, incidents_db),
        "sentiment": score_sentiment(titre, contenu),
    }
    total = sum(breakdown.values())
    return total, breakdown


def status_for_score(score: int) -> str:
    """Retourne `a_valider` si score >= seuil, sinon `faible`."""
    return STATUS_A_VALIDER if score >= SCORE_SEUIL_ALERTE else STATUS_FAIBLE
