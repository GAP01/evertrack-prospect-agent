"""
Acces aux bases SQLite des agents 1 (incidents) et 2 (scores).

Le dashboard ne fait QUE lire ici. Les ecritures passent par actions.py
qui invoque les pipelines des agents.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _connect_ro(db_path: Path) -> Optional[sqlite3.Connection]:
    """Ouvre une connexion lecture seule. Retourne None si la base n'existe pas encore."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def stats(incidents_db: Path, scores_db: Path) -> dict[str, Any]:
    """Statistiques d'entete : nb incidents, nb scores, dernieres dates."""
    out = {
        "incidents_total": 0,
        "scores_total": 0,
        "last_incident_seen": None,
        "last_score_at": None,
    }
    conn_inc = _connect_ro(incidents_db)
    if conn_inc is not None:
        row = conn_inc.execute(
            "SELECT COUNT(*) AS n, MAX(last_seen_at) AS last_seen FROM incidents"
        ).fetchone()
        out["incidents_total"] = row["n"] or 0
        out["last_incident_seen"] = row["last_seen"]
        conn_inc.close()
    conn_sc = _connect_ro(scores_db)
    if conn_sc is not None:
        row = conn_sc.execute(
            "SELECT COUNT(DISTINCT source||source_id) AS n, MAX(scored_at) AS last_at FROM scores"
        ).fetchone()
        out["scores_total"] = row["n"] or 0
        out["last_score_at"] = row["last_at"]
        conn_sc.close()
    return out


def top_incidents(
    incidents_db: Path,
    scores_db: Path,
    limit: int = 50,
    tier: Optional[str] = None,
    sous_categorie: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Renvoie le top N (incidents joints a leur score le plus recent),
    classe par score DESC.
    """
    conn_sc = _connect_ro(scores_db)
    if conn_sc is None:
        return []
    sql = """
    WITH latest AS (
        SELECT source, source_id, MAX(scored_at) AS scored_at
        FROM scores GROUP BY source, source_id
    )
    SELECT s.* FROM scores s
    INNER JOIN latest l
      ON s.source=l.source AND s.source_id=l.source_id AND s.scored_at=l.scored_at
    """
    params: list = []
    if tier:
        sql += " WHERE s.tier = ?"
        params.append(tier)
    sql += " ORDER BY s.score DESC LIMIT ?"
    params.append(limit * 2)  # marge pour filtrage sous_categorie cote python

    score_rows = [dict(r) for r in conn_sc.execute(sql, params).fetchall()]
    conn_sc.close()

    if not score_rows:
        return []

    # Joindre avec les metadonnees incident
    conn_inc = _connect_ro(incidents_db)
    if conn_inc is None:
        return []
    out = []
    for sr in score_rows:
        meta = conn_inc.execute(
            "SELECT * FROM incidents WHERE source=? AND source_id=?",
            (sr["source"], sr["source_id"]),
        ).fetchone()
        if meta is None:
            continue
        meta = dict(meta)
        if sous_categorie and sous_categorie.lower() not in (meta.get("sous_categorie") or "").lower():
            continue
        sr["incident"] = meta
        sr["dimensions"] = json.loads(sr.pop("dimensions_json"))
        out.append(sr)
        if len(out) >= limit:
            break
    conn_inc.close()
    return out


def get_incident_full(
    incidents_db: Path,
    scores_db: Path,
    source: str,
    source_id: str,
) -> Optional[dict[str, Any]]:
    """Vue detaillee : incident + score le plus recent + raw_json parse."""
    conn_inc = _connect_ro(incidents_db)
    if conn_inc is None:
        return None
    inc_row = conn_inc.execute(
        "SELECT * FROM incidents WHERE source=? AND source_id=?",
        (source, source_id),
    ).fetchone()
    conn_inc.close()
    if inc_row is None:
        return None
    incident = dict(inc_row)
    if incident.get("raw_json"):
        try:
            incident["raw"] = json.loads(incident["raw_json"])
        except json.JSONDecodeError:
            incident["raw"] = None

    score = None
    conn_sc = _connect_ro(scores_db)
    if conn_sc is not None:
        sc_row = conn_sc.execute(
            "SELECT * FROM scores WHERE source=? AND source_id=? ORDER BY scored_at DESC LIMIT 1",
            (source, source_id),
        ).fetchone()
        if sc_row:
            score = dict(sc_row)
            score["dimensions"] = json.loads(score.pop("dimensions_json"))
        conn_sc.close()

    return {"incident": incident, "score": score}


def list_sous_categories(incidents_db: Path) -> list[str]:
    """Pour alimenter le filtre 'sous-categorie'."""
    conn = _connect_ro(incidents_db)
    if conn is None:
        return []
    rows = conn.execute(
        "SELECT DISTINCT sous_categorie FROM incidents "
        "WHERE sous_categorie IS NOT NULL AND sous_categorie != '' "
        "ORDER BY sous_categorie"
    ).fetchall()
    conn.close()
    return [r["sous_categorie"] for r in rows]


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
