"""
Persistance SQLite pour les incidents.

Une seule table `incidents`, indexée sur (source, source_id) pour détecter
les doublons lors des refresh successifs. Le record brut est sérialisé en JSON
dans la colonne `raw_json` pour permettre des inspections a posteriori.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from .models import Incident

logger = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    source            TEXT NOT NULL,
    source_id         TEXT NOT NULL,
    source_url        TEXT,
    categorie         TEXT,
    sous_categorie    TEXT,
    marque            TEXT,
    modeles           TEXT,
    nature_juridique  TEXT,
    motif             TEXT,
    risques           TEXT,
    zone_geographique TEXT,
    distributeurs     TEXT,
    marque_salubrite  TEXT,
    date_publication  TEXT,
    raw_json          TEXT,
    first_seen_at     TEXT DEFAULT (datetime('now')),
    last_seen_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_incidents_date
    ON incidents (date_publication DESC);

CREATE INDEX IF NOT EXISTS idx_incidents_categorie
    ON incidents (categorie);
"""


class Storage:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            # Migration idempotente : les bases pré-existantes n'ont pas la colonne marque_salubrite.
            try:
                conn.execute("ALTER TABLE incidents ADD COLUMN marque_salubrite TEXT")
            except sqlite3.OperationalError:
                pass  # colonne déjà présente

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_many(self, incidents: Iterable[Incident]) -> tuple[int, int]:
        """Insère ou met à jour les incidents. Retourne (nb_nouveaux, nb_maj)."""
        new_count = 0
        updated_count = 0
        with self._connect() as conn:
            for inc in incidents:
                existing = conn.execute(
                    "SELECT 1 FROM incidents WHERE source=? AND source_id=?",
                    (inc.source, inc.source_id),
                ).fetchone()

                d = inc.to_dict()
                raw_json = json.dumps(d.pop("raw"), ensure_ascii=False)

                if existing:
                    conn.execute(
                        """
                        UPDATE incidents SET
                            source_url=?, categorie=?, sous_categorie=?,
                            marque=?, modeles=?, nature_juridique=?, motif=?,
                            risques=?, zone_geographique=?, distributeurs=?,
                            marque_salubrite=?,
                            date_publication=?, raw_json=?,
                            last_seen_at=datetime('now')
                        WHERE source=? AND source_id=?
                        """,
                        (
                            d["source_url"], d["categorie"], d["sous_categorie"],
                            d["marque"], d["modeles"], d["nature_juridique"], d["motif"],
                            d["risques"], d["zone_geographique"], d["distributeurs"],
                            d.get("marque_salubrite"),
                            d["date_publication"], raw_json,
                            inc.source, inc.source_id,
                        ),
                    )
                    updated_count += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO incidents (
                            source, source_id, source_url, categorie, sous_categorie,
                            marque, modeles, nature_juridique, motif, risques,
                            zone_geographique, distributeurs, marque_salubrite,
                            date_publication, raw_json
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            inc.source, inc.source_id, d["source_url"], d["categorie"],
                            d["sous_categorie"], d["marque"], d["modeles"],
                            d["nature_juridique"], d["motif"], d["risques"],
                            d["zone_geographique"], d["distributeurs"],
                            d.get("marque_salubrite"),
                            d["date_publication"], raw_json,
                        ),
                    )
                    new_count += 1
        return new_count, updated_count

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

    def list_recent(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source, source_id, source_url, categorie, sous_categorie,
                       marque, nature_juridique, motif, date_publication,
                       zone_geographique, distributeurs
                FROM incidents
                ORDER BY date_publication DESC, source_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
