"""
Orchestrateur de l'agent 3 : enrichisseur de prospects.

Lit les incidents depuis incidents.sqlite (agent 1), tente de matcher chaque
incident avec une entreprise via l'API SIRENE, et stocke les résultats dans
enrichissements.sqlite.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # python-dotenv optionnel

from .api_sirene import SireneClient
from .api_pappers import PappersClient, PappersNotConfiguredError
from .matcher import match_incident, ENRICHER_VERSION, _get_pappers_client
from .models import EnrichissementResult
from .storage import EnrichissementStorage

logger = logging.getLogger(__name__)


def _load_incidents(incidents_db: Path) -> list[dict[str, Any]]:
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


def run_enrich(
    incidents_db: Path,
    enrichissements_db: Path,
    only_new: bool = True,
    max_incidents: Optional[int] = None,
) -> dict[str, Any]:
    """
    Pipeline : charger incidents → matcher → persister.

    Si `only_new`, saute les incidents déjà enrichis avec la même version.
    Retourne un rapport exploitable (nb traités, statuts, couverture).
    """
    incidents = _load_incidents(incidents_db)
    storage = EnrichissementStorage(enrichissements_db)
    client = SireneClient()
    pappers = _get_pappers_client()
    if pappers:
        logger.info("Pappers activé — enrichissement contact dirigeant après SIRENE")
    else:
        logger.info("Pappers non configuré — contact SIRENE uniquement (si disponible)")

    skipped_ids: set[str] = set()
    if only_new:
        skipped_ids = storage.already_enriched_ids("rappelconso", ENRICHER_VERSION)

    to_enrich = [i for i in incidents if i["source_id"] not in skipped_ids]
    if max_incidents is not None:
        to_enrich = to_enrich[:max_incidents]

    logger.info(
        "Enrichissement de %d incidents (sur %d en base, %d déjà traités)",
        len(to_enrich), len(incidents), len(skipped_ids),
    )

    results: list[EnrichissementResult] = []
    for inc in to_enrich:
        try:
            result = match_incident(inc, client, pappers=pappers)
            results.append(result)
        except Exception:
            logger.exception(
                "Échec enrichissement incident %s", inc.get("source_id")
            )

    storage.upsert_many(results)

    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r.match_status] = status_counts.get(r.match_status, 0) + 1

    return {
        "incidents_total": len(incidents),
        "skipped_already_enriched": len(skipped_ids),
        "enriched_now": len(results),
        "by_status": status_counts,
        "with_contact": sum(1 for r in results if r.contact_nom),
        "enricher_version": ENRICHER_VERSION,
    }
