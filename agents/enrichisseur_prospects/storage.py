"""
Persistance SQLite des enrichissements de prospects.

Table `enrichissements` liée à `incidents` (clé composite source + source_id).
Même pattern que ScoreStorage : PRIMARY KEY inclut enricher_version pour
permettre la recalibration sans perte historique.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import EnrichissementResult


SCHEMA = """
CREATE TABLE IF NOT EXISTS enrichissements (
    source               TEXT NOT NULL,
    source_id            TEXT NOT NULL,
    enricher_version     TEXT NOT NULL,
    marque_input         TEXT,
    query_used           TEXT,
    match_status         TEXT NOT NULL,
    confidence           REAL,
    siren                TEXT,
    siret_siege          TEXT,
    raison_sociale       TEXT,
    forme_juridique      TEXT,
    code_naf             TEXT,
    libelle_naf          TEXT,
    adresse              TEXT,
    effectif_tranche     TEXT,
    categorie_entreprise TEXT,
    contact_nom          TEXT,
    contact_titre        TEXT,
    contact_source       TEXT,
    contact_type         TEXT,
    ca_annuel            TEXT,
    api_used             TEXT,
    enriched_at          TEXT NOT NULL,
    raw_json             TEXT,
    PRIMARY KEY (source, source_id, enricher_version)
);
CREATE INDEX IF NOT EXISTS idx_enrich_siren   ON enrichissements (siren);
CREATE INDEX IF NOT EXISTS idx_enrich_status  ON enrichissements (match_status);
"""

# Migrations appliquées après CREATE TABLE IF NOT EXISTS (ordre important)
_MIGRATIONS = [
    "ALTER TABLE enrichissements ADD COLUMN contact_type TEXT",
    "CREATE INDEX IF NOT EXISTS idx_enrich_contact_type ON enrichissements (contact_type)",
]


class EnrichissementStorage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Applique les migrations de schéma sans perte de données."""
        for stmt in _MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # colonne déjà présente

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(self, result: EnrichissementResult) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO enrichissements
                (source, source_id, enricher_version, marque_input, query_used,
                 match_status, confidence, siren, siret_siege, raison_sociale,
                 forme_juridique, code_naf, libelle_naf, adresse, effectif_tranche,
                 categorie_entreprise, contact_nom, contact_titre, contact_source,
                 contact_type, ca_annuel, api_used, enriched_at, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.source,
                    result.source_id,
                    result.enricher_version,
                    result.marque_input,
                    result.query_used,
                    result.match_status,
                    result.confidence,
                    result.siren,
                    result.siret_siege,
                    result.raison_sociale,
                    result.forme_juridique,
                    result.code_naf,
                    result.libelle_naf,
                    result.adresse,
                    result.effectif_tranche,
                    result.categorie_entreprise,
                    result.contact_nom,
                    result.contact_titre,
                    result.contact_source,
                    result.contact_type,
                    result.ca_annuel,
                    result.api_used,
                    result.enriched_at.isoformat(),
                    result.raw_json,
                ),
            )

    def upsert_many(self, results: Iterable[EnrichissementResult]) -> int:
        n = 0
        for r in results:
            self.upsert(r)
            n += 1
        return n

    def already_enriched_ids(
        self, source: str, enricher_version: str
    ) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT source_id FROM enrichissements
                WHERE source = ? AND enricher_version = ?
                """,
                (source, enricher_version),
            ).fetchall()
        return {r["source_id"] for r in rows}

    def get(self, source: str, source_id: str) -> Optional[dict[str, Any]]:
        """Retourne l'enrichissement le plus récent pour un incident."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM enrichissements
                WHERE source = ? AND source_id = ?
                ORDER BY enricher_version DESC, enriched_at DESC LIMIT 1
                """,
                (source, source_id),
            ).fetchone()
        return dict(row) if row else None

    def stats(self) -> dict[str, Any]:
        """Stats de couverture : total, par match_status, SIREN trouvés."""
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(DISTINCT source||source_id) FROM enrichissements"
            ).fetchone()[0]

            by_status = {}
            for row in conn.execute(
                """
                SELECT match_status, COUNT(*) as n FROM enrichissements
                GROUP BY match_status
                """
            ).fetchall():
                by_status[row["match_status"]] = row["n"]

            with_contact = conn.execute(
                "SELECT COUNT(*) FROM enrichissements WHERE contact_nom IS NOT NULL"
            ).fetchone()[0]

        return {
            "total_enrichis": total,
            "by_status": by_status,
            "with_contact": with_contact,
        }

    def list_found(self, limit: int = 50) -> list[dict[str, Any]]:
        """Liste les enrichissements réussis (found), triés par confidence desc."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM enrichissements
                WHERE match_status = 'found'
                ORDER BY confidence DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
