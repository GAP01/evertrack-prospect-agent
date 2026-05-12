"""
Orchestrateur de l'agent 2 : evaluateur de severite.

Lit les incidents depuis la base du Veilleur (agent 1), score chaque incident
sur 4 dimensions, ecrit le resultat dans la base scores.

Pondaration :
    risque_sanitaire     50%   (LLM ou fallback table)
    ampleur_geo          25%   (regles)
    population_vulnerable 15%  (regles)
    volume_distributeurs 10%   (regles)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .llm_scorer import score_risque_sanitaire
from .models import IncidentScore
from .rules import score_structured_dimensions
from .storage import ScoreStorage

logger = logging.getLogger(__name__)

SCORER_VERSION = "v0.1"


def _load_incidents(incidents_db: Path) -> list[dict[str, Any]]:
    """Lit tous les incidents de la base du veilleur."""
    if not incidents_db.exists():
        raise FileNotFoundError(
            f"Base d'incidents introuvable : {incidents_db}. "
            "Lance d'abord `python -m veilleur_incidents.cli fetch`."
        )
    conn = sqlite3.connect(incidents_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM incidents").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def score_incident(
    incident: dict[str, Any],
    use_llm: bool = True,
) -> IncidentScore:
    """Score un incident sur les 4 dimensions et renvoie le score agrege."""
    structured = score_structured_dimensions(incident)
    sanitaire, llm_used = score_risque_sanitaire(incident, use_llm=use_llm)
    return IncidentScore.from_dimensions(
        source=incident["source"],
        source_id=incident["source_id"],
        dimensions=[sanitaire] + structured,
        llm_used=llm_used,
        scorer_version=SCORER_VERSION,
    )


def run_score(
    incidents_db: Path,
    scores_db: Path,
    use_llm: bool = True,
    only_new: bool = True,
    max_incidents: Optional[int] = None,
) -> dict[str, Any]:
    """
    Pipeline : charger incidents -> scorer -> persister.

    Si `only_new`, on saute les incidents deja scores avec la meme version.
    """
    incidents = _load_incidents(incidents_db)
    storage = ScoreStorage(scores_db)

    skipped_ids: set[str] = set()
    if only_new:
        skipped_ids = storage.already_scored_ids("rappelconso", SCORER_VERSION)

    to_score = [
        i for i in incidents
        if i["source_id"] not in skipped_ids
    ]
    if max_incidents is not None:
        to_score = to_score[:max_incidents]

    logger.info(
        "Scoring %d incidents (sur %d en base, %d deja scores)",
        len(to_score), len(incidents), len(skipped_ids),
    )

    new_scores: list[IncidentScore] = []
    for inc in to_score:
        try:
            new_scores.append(score_incident(inc, use_llm=use_llm))
        except Exception:
            logger.exception("Echec scoring sur incident %s", inc.get("source_id"))

    storage.upsert_many(new_scores)

    return {
        "incidents_total": len(incidents),
        "skipped_already_scored": len(skipped_ids),
        "scored_now": len(new_scores),
        "llm_used_count": sum(1 for s in new_scores if s.llm_used),
        "by_tier": _tier_breakdown(new_scores),
        "scorer_version": SCORER_VERSION,
    }


def _tier_breakdown(scores: list[IncidentScore]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in scores:
        out[s.tier] = out.get(s.tier, 0) + 1
    return out
