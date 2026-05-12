"""
Persistance SQLite des signaux faibles détectés.

Deux tables :
- `signaux`         : un row par signal (dédupliqué sur signal_id)
- `signaux_sources` : N sources par signal (historique multi-sources)

La fonction `upsert_with_source` gère les deux tables en une transaction :
si le signal existe déjà, on ajoute uniquement la source et on met à jour
last_seen_at + raw count pour permettre le re-scoring.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import (
    SignalAlerte,
    SignalSource,
    STATUS_FAIBLE,
    STATUS_PROMU,
    STATUS_REJETE,
    STATUS_VALIDE,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS signaux (
    signal_id            TEXT PRIMARY KEY,
    detector_version     TEXT NOT NULL,
    marque               TEXT,
    produit              TEXT,
    symptome             TEXT,
    titre                TEXT,
    resume               TEXT,
    source_type          TEXT,
    source_name          TEXT,
    source_url           TEXT,
    score                INTEGER,
    score_breakdown      TEXT,
    status               TEXT NOT NULL,
    promu_vers_source    TEXT,
    promu_vers_source_id TEXT,
    detected_at          TEXT NOT NULL,
    last_seen_at         TEXT NOT NULL,
    raw_json             TEXT
);
CREATE INDEX IF NOT EXISTS idx_signaux_status ON signaux (status);
CREATE INDEX IF NOT EXISTS idx_signaux_score  ON signaux (score);
CREATE INDEX IF NOT EXISTS idx_signaux_marque ON signaux (marque);

CREATE TABLE IF NOT EXISTS signaux_sources (
    signal_id        TEXT NOT NULL,
    source_type      TEXT NOT NULL,
    source_name      TEXT NOT NULL,
    source_url       TEXT NOT NULL,
    titre            TEXT,
    contenu          TEXT,
    detected_at      TEXT NOT NULL,
    rappelconso_url  TEXT,
    PRIMARY KEY (signal_id, source_url)
);
CREATE INDEX IF NOT EXISTS idx_sources_signal ON signaux_sources (signal_id);
-- NB : idx_sources_rc_url créé dans _MIGRATIONS (après ALTER TABLE)

CREATE TABLE IF NOT EXISTS signal_incident_matches (
    signal_id          TEXT NOT NULL,
    incident_source    TEXT NOT NULL,
    incident_source_id TEXT NOT NULL,
    score              REAL NOT NULL,
    brand_match        REAL,
    symptom_match      REAL,
    product_match      REAL,
    date_proximity     REAL,
    lead_time_days     INTEGER,
    computed_at        TEXT NOT NULL,
    user_confirmed     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (signal_id, incident_source, incident_source_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_signal   ON signal_incident_matches (signal_id);
CREATE INDEX IF NOT EXISTS idx_matches_incident ON signal_incident_matches (incident_source, incident_source_id);
CREATE INDEX IF NOT EXISTS idx_matches_score    ON signal_incident_matches (score);

-- Trace du dernier run de chaque collector source.
-- Permet au dashboard d'afficher "Dernier scan" basé sur l'exécution du
-- collector (et pas sur la dernière émission d'un signal — qui peut être
-- antérieure si aucune nouvelle anomalie n'a été détectée depuis).
CREATE TABLE IF NOT EXISTS source_runs (
    source_type   TEXT PRIMARY KEY,        -- nom du collector (google_news, reddit, signalconso_volume…)
    last_run_at   TEXT NOT NULL,            -- ISO datetime de fin du run
    last_emitted  INTEGER NOT NULL DEFAULT 0,  -- nb d'items SignalSource sortis du collector
    last_started_at TEXT
);
"""

_MIGRATIONS: list[str] = [
    # user_confirmed ajouté pour permettre la validation humaine d'un match
    "ALTER TABLE signal_incident_matches ADD COLUMN user_confirmed INTEGER NOT NULL DEFAULT 0",
    # rappelconso_url : si un article contient un lien direct vers une fiche
    # rappel.conso.gouv.fr, on le stocke ici pour auto-confirmer le match.
    "ALTER TABLE signaux_sources ADD COLUMN rappelconso_url TEXT",
    "CREATE INDEX IF NOT EXISTS idx_sources_rc_url ON signaux_sources (rappelconso_url)",
]


class SignalStorage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        for stmt in _MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- Écriture --------------------------------------------------------

    def upsert_signal(self, signal: SignalAlerte) -> None:
        """Insert ou remplace le signal. Utilisé après (re)scoring."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO signaux
                (signal_id, detector_version, marque, produit, symptome,
                 titre, resume, source_type, source_name, source_url,
                 score, score_breakdown, status,
                 promu_vers_source, promu_vers_source_id,
                 detected_at, last_seen_at, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.signal_id,
                    signal.detector_version,
                    signal.marque,
                    signal.produit,
                    signal.symptome,
                    signal.titre,
                    signal.resume,
                    signal.source_type,
                    signal.source_name,
                    signal.source_url,
                    signal.score,
                    json.dumps(signal.score_breakdown, ensure_ascii=False),
                    signal.status,
                    signal.promu_vers_source,
                    signal.promu_vers_source_id,
                    signal.detected_at.isoformat(),
                    signal.last_seen_at.isoformat(),
                    signal.raw_json,
                ),
            )

    def attach_source(
        self, signal_id: str, src: SignalSource,
        rappelconso_url: Optional[str] = None,
    ) -> bool:
        """Ajoute une source à un signal. Retourne True si c'est une nouvelle source."""
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO signaux_sources
                    (signal_id, source_type, source_name, source_url, titre,
                     contenu, detected_at, rappelconso_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal_id,
                        src.source_type,
                        src.source_name,
                        src.source_url,
                        src.titre,
                        src.contenu,
                        src.detected_at.isoformat(),
                        rappelconso_url,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                # Doublon (signal_id, source_url). Si on a découvert un nouveau
                # rappelconso_url, on le patche (on ne peut le trouver qu'à la
                # fin du scrapping, pas à l'insertion initiale).
                if rappelconso_url:
                    conn.execute(
                        """
                        UPDATE signaux_sources
                        SET rappelconso_url = ?
                        WHERE signal_id = ? AND source_url = ?
                          AND (rappelconso_url IS NULL OR rappelconso_url = '')
                        """,
                        (rappelconso_url, signal_id, src.source_url),
                    )
                return False

    def update_last_seen(self, signal_id: str, ts: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE signaux SET last_seen_at = ? WHERE signal_id = ?",
                (ts.isoformat(), signal_id),
            )

    def set_status(self, signal_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE signaux SET status = ? WHERE signal_id = ?",
                (status, signal_id),
            )

    def mark_promoted(
        self, signal_id: str, source: str, source_id: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE signaux
                SET status = ?, promu_vers_source = ?, promu_vers_source_id = ?
                WHERE signal_id = ?
                """,
                (STATUS_PROMU, source, source_id, signal_id),
            )

    # --- Lecture ---------------------------------------------------------

    def get(self, signal_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM signaux WHERE signal_id = ?", (signal_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_sources(self, signal_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signaux_sources
                WHERE signal_id = ?
                ORDER BY detected_at DESC
                """,
                (signal_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_sources(self, signal_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM signaux_sources WHERE signal_id = ?",
                (signal_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def rappelconso_urls_for_signal(self, signal_id: str) -> list[str]:
        """Liste les URLs RappelConso détectées dans les sources de ce signal."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT rappelconso_url FROM signaux_sources
                WHERE signal_id = ? AND rappelconso_url IS NOT NULL
                  AND rappelconso_url != ''
                """,
                (signal_id,),
            ).fetchall()
        return [r["rappelconso_url"] for r in rows]

    def all_signals_with_rappelconso_urls(self) -> list[tuple[str, str]]:
        """Retourne [(signal_id, rappelconso_url), ...] pour tous les signaux
        ayant au moins une source avec un lien direct RappelConso."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT signal_id, rappelconso_url FROM signaux_sources
                WHERE rappelconso_url IS NOT NULL AND rappelconso_url != ''
                """
            ).fetchall()
        return [(r["signal_id"], r["rappelconso_url"]) for r in rows]

    # --- Source runs (tracking dernier scan par collector) -----------

    def record_source_run(
        self,
        source_type: str,
        last_emitted: int,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
    ) -> None:
        """
        Enregistre/met à jour le dernier run d'un collector source.

        Appelé après chaque exécution d'un collector dans run_detect, même
        si emitted=0. Permet au dashboard de distinguer "collector pas
        exécuté depuis X" de "exécuté mais rien trouvé".
        """
        end_iso = (ended_at or datetime.utcnow()).isoformat()
        start_iso = started_at.isoformat() if started_at else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO source_runs
                (source_type, last_run_at, last_emitted, last_started_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_type) DO UPDATE SET
                    last_run_at = excluded.last_run_at,
                    last_emitted = excluded.last_emitted,
                    last_started_at = excluded.last_started_at
                """,
                (source_type, end_iso, last_emitted, start_iso),
            )

    def get_source_run(self, source_type: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM source_runs WHERE source_type = ?",
                (source_type,),
            ).fetchone()
        return dict(row) if row else None

    def get_all_source_runs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM source_runs ORDER BY last_run_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def merge_signal_into(
        self,
        deprecated_signal_id: str,
        survivor_signal_id: str,
    ) -> dict[str, int]:
        """
        Fusionne `deprecated_signal_id` dans `survivor_signal_id`.

        Réassigne toutes les sources du signal déprécié vers le survivant,
        supprime le signal déprécié de la table `signaux`, et supprime les
        matches cross-ref obsolètes (qui seront recalculés au prochain crossref).

        Gestion des conflits d'URL : si une source (signal_id, source_url)
        existe déjà pour le survivant, on skip (UPDATE échouerait sur la PK).

        Retourne un rapport {sources_moved, sources_duplicates, matches_removed}.
        """
        if deprecated_signal_id == survivor_signal_id:
            return {"sources_moved": 0, "sources_duplicates": 0, "matches_removed": 0}

        with self._connect() as conn:
            # 1. Identifier les sources à déplacer qui n'existent PAS déjà
            #    pour le survivor (éviter PK collision)
            sources_to_move = conn.execute(
                """
                SELECT source_url FROM signaux_sources
                WHERE signal_id = ?
                  AND source_url NOT IN (
                    SELECT source_url FROM signaux_sources WHERE signal_id = ?
                  )
                """,
                (deprecated_signal_id, survivor_signal_id),
            ).fetchall()

            # 2. Déplacer ces sources vers le survivor
            n_moved = 0
            for (url,) in sources_to_move:
                conn.execute(
                    """
                    UPDATE signaux_sources
                    SET signal_id = ?
                    WHERE signal_id = ? AND source_url = ?
                    """,
                    (survivor_signal_id, deprecated_signal_id, url),
                )
                n_moved += 1

            # 3. Supprimer les sources dupliquées résiduelles (celles
            #    qui existaient déjà pour le survivor avec la même URL)
            cur = conn.execute(
                "DELETE FROM signaux_sources WHERE signal_id = ?",
                (deprecated_signal_id,),
            )
            n_duplicates = cur.rowcount

            # 4. Supprimer les matches cross-ref du signal déprécié
            #    (ils seront recalculés via crossref après)
            cur = conn.execute(
                "DELETE FROM signal_incident_matches WHERE signal_id = ?",
                (deprecated_signal_id,),
            )
            n_matches_removed = cur.rowcount

            # 5. Supprimer le signal déprécié lui-même
            conn.execute(
                "DELETE FROM signaux WHERE signal_id = ?",
                (deprecated_signal_id,),
            )

        return {
            "sources_moved": n_moved,
            "sources_duplicates": n_duplicates,
            "matches_removed": n_matches_removed,
        }

    def earliest_source_date(self, signal_id: str) -> Optional[datetime]:
        """
        Date de publication du plus ancien article/post lié à ce signal.
        Reflète "quand l'information est apparue pour la 1re fois" — c'est la
        date à utiliser pour le scoring recency et pour le dashboard.
        """
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT MIN(detected_at) AS dt FROM signaux_sources
                WHERE signal_id = ?
                """,
                (signal_id,),
            ).fetchone()
        if row is None or row["dt"] is None:
            return None
        try:
            return datetime.fromisoformat(row["dt"])
        except (ValueError, TypeError):
            return None

    def list_signals(
        self,
        status: Optional[str] = None,
        min_score: Optional[int] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM signaux WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if min_score is not None:
            sql += " AND score >= ?"
            params.append(min_score)
        sql += " ORDER BY score DESC, last_seen_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM signaux").fetchone()[0]
            by_status: dict[str, int] = {}
            for row in conn.execute(
                "SELECT status, COUNT(*) n FROM signaux GROUP BY status"
            ).fetchall():
                by_status[row["status"]] = row["n"]
            alerts = conn.execute(
                "SELECT COUNT(*) FROM signaux WHERE status IN (?, ?)",
                ("a_valider", "valide"),
            ).fetchone()[0]
            last = conn.execute(
                "SELECT MAX(last_seen_at) as ts FROM signaux"
            ).fetchone()
            last_seen = last["ts"] if last and last["ts"] else None
        return {
            "total": total,
            "by_status": by_status,
            "en_alerte": alerts,
            "last_seen_at": last_seen,
        }

    # --- Matches signaux ↔ incidents ---------------------------------

    def upsert_match(
        self,
        signal_id: str,
        incident_source: str,
        incident_source_id: str,
        score: float,
        brand_match: float,
        symptom_match: float,
        product_match: float,
        date_proximity: float,
        lead_time_days: Optional[int],
        computed_at: str,
    ) -> None:
        """
        Upsert un match (algorithmique). Préserve le flag user_confirmed
        si le match existait déjà.
        """
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT user_confirmed FROM signal_incident_matches
                WHERE signal_id = ? AND incident_source = ? AND incident_source_id = ?
                """,
                (signal_id, incident_source, incident_source_id),
            ).fetchone()
            user_confirmed = int(existing["user_confirmed"]) if existing else 0
            conn.execute(
                """
                INSERT OR REPLACE INTO signal_incident_matches
                (signal_id, incident_source, incident_source_id, score,
                 brand_match, symptom_match, product_match, date_proximity,
                 lead_time_days, computed_at, user_confirmed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id, incident_source, incident_source_id, score,
                    brand_match, symptom_match, product_match, date_proximity,
                    lead_time_days, computed_at, user_confirmed,
                ),
            )

    def clear_matches(self, keep_confirmed: bool = True) -> None:
        """Vide la table. Par défaut, préserve les matches validés humainement."""
        with self._connect() as conn:
            if keep_confirmed:
                conn.execute(
                    "DELETE FROM signal_incident_matches WHERE user_confirmed = 0"
                )
            else:
                conn.execute("DELETE FROM signal_incident_matches")

    def confirm_match(
        self, signal_id: str, incident_source: str, incident_source_id: str,
    ) -> bool:
        """
        Marque un match comme validé humainement. Si la ligne n'existe pas
        (score < seuil), on la crée à score=0 pour la matérialiser.
        Retourne True si la ligne a été mise à jour / créée.
        """
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT 1 FROM signal_incident_matches
                WHERE signal_id = ? AND incident_source = ? AND incident_source_id = ?
                """,
                (signal_id, incident_source, incident_source_id),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE signal_incident_matches
                    SET user_confirmed = 1
                    WHERE signal_id = ? AND incident_source = ? AND incident_source_id = ?
                    """,
                    (signal_id, incident_source, incident_source_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO signal_incident_matches
                    (signal_id, incident_source, incident_source_id, score,
                     brand_match, symptom_match, product_match, date_proximity,
                     lead_time_days, computed_at, user_confirmed)
                    VALUES (?, ?, ?, 0, 0, 0, 0, 0, NULL, ?, 1)
                    """,
                    (
                        signal_id, incident_source, incident_source_id,
                        datetime.utcnow().isoformat(),
                    ),
                )
        return True

    def unconfirm_match(
        self, signal_id: str, incident_source: str, incident_source_id: str,
    ) -> bool:
        """Retire la validation humaine."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE signal_incident_matches SET user_confirmed = 0
                WHERE signal_id = ? AND incident_source = ? AND incident_source_id = ?
                """,
                (signal_id, incident_source, incident_source_id),
            )
        return True

    def get_matches_for_signal(
        self, signal_id: str, min_score: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Matches validés humainement d'abord, puis par score décroissant."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signal_incident_matches
                WHERE signal_id = ? AND (score >= ? OR user_confirmed = 1)
                ORDER BY user_confirmed DESC, score DESC
                """,
                (signal_id, min_score),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_matches_for_incident(
        self, source: str, source_id: str, min_score: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Matches validés humainement d'abord, puis par score décroissant."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM signal_incident_matches
                WHERE incident_source = ? AND incident_source_id = ?
                  AND (score >= ? OR user_confirmed = 1)
                ORDER BY user_confirmed DESC, score DESC
                """,
                (source, source_id, min_score),
            ).fetchall()
        return [dict(r) for r in rows]

    def match_stats(self) -> dict[str, Any]:
        """Stats globales des matches : total, strong, lead_time moyen."""
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM signal_incident_matches"
            ).fetchone()[0]
            strong = conn.execute(
                "SELECT COUNT(*) FROM signal_incident_matches WHERE score >= 0.70"
            ).fetchone()[0]
            # Lead time moyen sur les matches strong avec signal en amont
            row = conn.execute(
                """
                SELECT AVG(lead_time_days) avg_lead,
                       COUNT(*) n_lead
                FROM signal_incident_matches
                WHERE score >= 0.70 AND lead_time_days IS NOT NULL AND lead_time_days > 0
                """
            ).fetchone()
            avg_lead = float(row["avg_lead"]) if row and row["avg_lead"] is not None else None
            n_lead = int(row["n_lead"] or 0) if row else 0
        return {
            "total_matches": total,
            "strong_matches": strong,
            "avg_lead_time_days": avg_lead,
            "signals_ahead_count": n_lead,
        }
