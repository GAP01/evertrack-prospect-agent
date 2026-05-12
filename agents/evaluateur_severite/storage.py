"""
Persistance SQLite des scores de severite.

Table `scores` liee a `incidents` (cle composite source + source_id).
On garde l'historique : chaque scoring est un nouveau row (UNIQUE par version).
Pour le ranking, on prend la version la plus recente.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import IncidentScore, DimensionScore


SCHEMA = """
CREATE TABLE IF NOT EXISTS scores (
    source           TEXT NOT NULL,
    source_id        TEXT NOT NULL,
    score            REAL NOT NULL,
    tier             TEXT NOT NULL,
    dimensions_json  TEXT NOT NULL,
    scored_at        TEXT NOT NULL,
    scorer_version   TEXT NOT NULL,
    llm_used         INTEGER NOT NULL,
    PRIMARY KEY (source, source_id, scorer_version, scored_at)
);
CREATE INDEX IF NOT EXISTS idx_scores_score ON scores (score DESC);
CREATE INDEX IF NOT EXISTS idx_scores_incident ON scores (source, source_id);
"""


class ScoreStorage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(self, score: IncidentScore) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO scores
                (source, source_id, score, tier, dimensions_json,
                 scored_at, scorer_version, llm_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    score.source,
                    score.source_id,
                    score.score,
                    score.tier,
                    json.dumps([d.__dict__ for d in score.dimensions], ensure_ascii=False),
                    score.scored_at.isoformat(),
                    score.scorer_version,
                    1 if score.llm_used else 0,
                ),
            )

    def upsert_many(self, scores: Iterable[IncidentScore]) -> int:
        n = 0
        for s in scores:
            self.upsert(s)
            n += 1
        return n

    def latest_score(self, source: str, source_id: str) -> Optional[dict[str, Any]]:
        """Retourne le score le plus recent pour un incident donne."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM scores
                WHERE source = ? AND source_id = ?
                ORDER BY scored_at DESC LIMIT 1
                """,
                (source, source_id),
            ).fetchone()
        return dict(row) if row else None

    def top(self, limit: int = 10, tier: Optional[str] = None) -> list[dict[str, Any]]:
        """
        Retourne le top N par score (version la plus recente uniquement par incident).
        Optionnellement filtre par tier.
        """
        # On selectionne le score le plus recent par incident, puis on classe.
        sql = """
        WITH latest AS (
            SELECT source, source_id, MAX(scored_at) AS scored_at
            FROM scores
            GROUP BY source, source_id
        )
        SELECT s.* FROM scores s
        INNER JOIN latest l
          ON s.source = l.source AND s.source_id = l.source_id
         AND s.scored_at = l.scored_at
        """
        params: list = []
        if tier:
            sql += " WHERE s.tier = ?"
            params.append(tier)
        sql += " ORDER BY s.score DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def already_scored_ids(
        self, source: str, scorer_version: str
    ) -> set[str]:
        """Liste des source_id deja scores avec cette version (pour eviter de rescorer)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT source_id FROM scores
                WHERE source = ? AND scorer_version = ?
                """,
                (source, scorer_version),
            ).fetchall()
        return {r["source_id"] for r in rows}

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(DISTINCT source||source_id) FROM scores").fetchone()[0]
