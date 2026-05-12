"""
Orchestrateur principal du Veilleur d'incidents.

Enchaîne : fetch API -> normalisation -> persistance SQLite -> export JSON.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from .api_client import RappelConsoClient
from .models import Incident
from .normalize import normalize_record
from .storage import Storage

logger = logging.getLogger(__name__)


# Filtre par defaut : alimentation (pilote agroalimentaire).
# IMPORTANT : RappelConso V2 normalise toutes les valeurs en minuscule
# (categorie, sous_categorie, marque...). Donc "alimentation" et pas "Alimentation".
DEFAULT_CATEGORIE = "alimentation"


def _build_where(since: Optional[date]) -> Optional[str]:
    """Construit une clause ODSQL pour filtrer a partir d'une date.

    Le champ `date_publication` est typé `datetime` dans le dataset V2,
    mais ODSQL accepte `date'YYYY-MM-DD'` en comparaison.
    """
    if since is None:
        return None
    return f"date_publication >= date'{since.isoformat()}'"


def _build_refine(categorie: Optional[str]) -> Optional[list[str]]:
    if not categorie:
        return None
    # `refine` filtre sur valeur exacte d'une facette.
    return [f"categorie_produit:{categorie}"]


def run_fetch(
    db_path: Path,
    export_json_path: Optional[Path] = None,
    since_days: int = 7,
    categorie: Optional[str] = DEFAULT_CATEGORIE,
    max_records: Optional[int] = None,
) -> dict:
    """Pipeline de base : récupérer, normaliser, stocker, exporter.

    Retourne un petit rapport exploitable (nb récupérés, nouveaux, MAJ)."""
    since = date.today() - timedelta(days=since_days) if since_days else None
    where = _build_where(since)
    refine = _build_refine(categorie)

    logger.info(
        "Fetch RappelConso — since=%s categorie=%s max=%s",
        since, categorie, max_records,
    )

    client = RappelConsoClient()
    incidents: list[Incident] = []
    for record in client.iter_records(
        where=where, refine=refine, max_records=max_records
    ):
        try:
            incidents.append(normalize_record(record))
        except Exception:
            logger.exception("Échec de normalisation sur un record")

    storage = Storage(db_path)
    new_count, updated_count = storage.upsert_many(incidents)

    report = {
        "fetched": len(incidents),
        "new": new_count,
        "updated": updated_count,
        "since": since.isoformat() if since else None,
        "categorie": categorie,
        "total_in_db": storage.count(),
    }

    if export_json_path:
        export_json_path.parent.mkdir(parents=True, exist_ok=True)
        export_json_path.write_text(
            json.dumps([i.to_dict() for i in incidents], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report["export_path"] = str(export_json_path)

    return report
