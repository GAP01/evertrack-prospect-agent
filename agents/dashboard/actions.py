"""
Wrappers pour declencher les pipelines des agents 1 (fetch) et 2 (score)
depuis le dashboard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from veilleur_incidents.veilleur import run_fetch, DEFAULT_CATEGORIE
from evaluateur_severite.evaluateur import run_score


def trigger_fetch(
    incidents_db: Path,
    since_days: int = 7,
    categorie: Optional[str] = DEFAULT_CATEGORIE,
    max_records: Optional[int] = None,
) -> dict[str, Any]:
    """Lance l'agent 1. Renvoie le rapport produit par run_fetch."""
    return run_fetch(
        db_path=incidents_db,
        export_json_path=None,  # pas besoin du JSON quand c'est l'UI qui consomme
        since_days=since_days,
        categorie=categorie,
        max_records=max_records,
    )


def trigger_score(
    incidents_db: Path,
    scores_db: Path,
    use_llm: bool = True,
    rescore: bool = False,
    max_incidents: Optional[int] = None,
) -> dict[str, Any]:
    """Lance l'agent 2. Renvoie le rapport produit par run_score."""
    return run_score(
        incidents_db=incidents_db,
        scores_db=scores_db,
        use_llm=use_llm,
        only_new=not rescore,
        max_incidents=max_incidents,
    )
