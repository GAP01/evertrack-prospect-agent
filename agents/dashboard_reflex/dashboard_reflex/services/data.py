"""
Bridge vers les modules existants :
- veilleur_incidents (agent 1)
- evaluateur_severite (agent 2)
- dashboard.data_access (lecteur SQLite)

On ajoute le parent de l'app `agents/` au PYTHONPATH si besoin, pour que
les imports vers les autres modules fonctionnent quand Reflex lance le backend.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

# agents/ est 2 niveaux au-dessus de ce fichier :
#   agents/dashboard_reflex/dashboard_reflex/services/data.py
#   agents/                                              <-- target
AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTS_ROOT))

import sqlite3

from dashboard import data_access  # noqa: E402
from dashboard import actions  # noqa: E402


DATA_DIR = Path(os.environ.get("EVERTRACK_DATA_DIR", AGENTS_ROOT / "data"))
INCIDENTS_DB = DATA_DIR / "incidents.sqlite"
SCORES_DB = DATA_DIR / "scores.sqlite"
ENRICHISSEMENTS_DB = DATA_DIR / "enrichissements.sqlite"
SIGNAUX_DB = DATA_DIR / "signaux.sqlite"
OUTREACH_DB = DATA_DIR / "outreach.sqlite"

DEMO_MODE = os.environ.get("EVERTRACK_DEMO_MODE", "").strip() in ("1", "true", "yes")


def get_stats() -> dict[str, Any]:
    return data_access.stats(INCIDENTS_DB, SCORES_DB)


def get_top(
    limit: int = 50,
    tier: Optional[str] = None,
    sous_categorie: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict[str, Any]]:
    return data_access.top_incidents(
        INCIDENTS_DB, SCORES_DB, limit=limit, tier=tier, sous_categorie=sous_categorie,
        search=search, date_from=date_from, date_to=date_to,
    )


def get_incident(source: str, source_id: str) -> Optional[dict[str, Any]]:
    return data_access.get_incident_full(INCIDENTS_DB, SCORES_DB, source, source_id)


def list_sous_categories() -> list[str]:
    return data_access.list_sous_categories(INCIDENTS_DB)


def trigger_fetch(since_days: int = 7, categorie: Optional[str] = "alimentation",
                  max_records: Optional[int] = None) -> dict[str, Any]:
    return actions.trigger_fetch(
        incidents_db=INCIDENTS_DB,
        since_days=since_days,
        categorie=categorie,
        max_records=max_records,
    )


def trigger_score(use_llm: bool = True, rescore: bool = False,
                  max_incidents: Optional[int] = None) -> dict[str, Any]:
    return actions.trigger_score(
        incidents_db=INCIDENTS_DB,
        scores_db=SCORES_DB,
        use_llm=use_llm,
        rescore=rescore,
        max_incidents=max_incidents,
    )


def _enrich_connect() -> Optional[sqlite3.Connection]:
    if not ENRICHISSEMENTS_DB.exists():
        return None
    conn = sqlite3.connect(ENRICHISSEMENTS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_enrichissements(
    limit: int = 100,
    match_status: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Lit les enrichissements depuis enrichissements.sqlite, triés par confidence desc.

    `search` filtre en sous-chaine case-insensitive sur marque_input OU
    raison_sociale OU contact_nom.
    """
    conn = _enrich_connect()
    if conn is None:
        return []
    sql = "SELECT * FROM enrichissements WHERE 1=1"
    params: list = []
    if match_status:
        sql += " AND match_status = ?"
        params.append(match_status)
    term = (search or "").strip().lower()
    if term:
        like = f"%{term}%"
        sql += (
            " AND (LOWER(marque_input) LIKE ? OR LOWER(raison_sociale) LIKE ?"
            " OR LOWER(contact_nom) LIKE ?)"
        )
        params.extend([like, like, like])
    sql += " ORDER BY confidence DESC, enriched_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_enrichissement(source: str, source_id: str) -> Optional[dict[str, Any]]:
    """Retourne l'enrichissement le plus récent pour un incident."""
    conn = _enrich_connect()
    if conn is None:
        return None
    row = conn.execute(
        "SELECT * FROM enrichissements WHERE source = ? AND source_id = ? "
        "ORDER BY enriched_at DESC LIMIT 1",
        (source, source_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_enrichissement_stats() -> dict[str, Any]:
    """Stats de couverture : total, by_status, with_contact, with_cible."""
    conn = _enrich_connect()
    if conn is None:
        return {"total": 0, "by_status": {}, "with_contact": 0, "with_cible": 0}
    total = conn.execute("SELECT COUNT(*) FROM enrichissements").fetchone()[0]
    by_status: dict[str, int] = {}
    for r in conn.execute(
        "SELECT match_status, COUNT(*) n FROM enrichissements GROUP BY match_status"
    ).fetchall():
        by_status[r["match_status"]] = r["n"]
    with_contact = conn.execute(
        "SELECT COUNT(*) FROM enrichissements WHERE contact_nom IS NOT NULL"
    ).fetchone()[0]
    with_cible = conn.execute(
        "SELECT COUNT(*) FROM enrichissements WHERE contact_type = 'cible'"
    ).fetchone()[0]
    conn.close()
    return {
        "total": total,
        "by_status": by_status,
        "with_contact": with_contact,
        "with_cible": with_cible,
    }


# --- Signaux faibles (Agent détecteur) -----------------------------------

def _signaux_connect() -> Optional[sqlite3.Connection]:
    if not SIGNAUX_DB.exists():
        return None
    conn = sqlite3.connect(SIGNAUX_DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_signaux(
    limit: int = 100,
    status: Optional[str] = None,
    min_score: Optional[int] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Lit les signaux depuis signaux.sqlite avec leur nombre de sources.

    Tri : récurrence desc (signaux relayés par plusieurs articles en 1er),
    puis date de publication desc, puis score desc en tie-breaker.

    `search` filtre en sous-chaine case-insensitive sur marque OU symptome
    OU titre. `date_from`/`date_to` bornent detected_at (ISO YYYY-MM-DD).
    """
    conn = _signaux_connect()
    if conn is None:
        return []
    # JOIN avec signaux_sources pour compter N sources par signal
    sql = """
        SELECT s.*, COALESCE(src_counts.n, 0) AS n_sources
        FROM signaux s
        LEFT JOIN (
            SELECT signal_id, COUNT(*) AS n
            FROM signaux_sources
            GROUP BY signal_id
        ) src_counts ON src_counts.signal_id = s.signal_id
        WHERE 1=1
    """
    params: list = []
    if status:
        sql += " AND s.status = ?"
        params.append(status)
    if min_score is not None:
        sql += " AND s.score >= ?"
        params.append(min_score)
    term = (search or "").strip().lower()
    if term:
        like = f"%{term}%"
        sql += (
            " AND (LOWER(s.marque) LIKE ? OR LOWER(s.symptome) LIKE ?"
            " OR LOWER(s.titre) LIKE ?)"
        )
        params.extend([like, like, like])
    if date_from:
        sql += " AND substr(s.detected_at, 1, 10) >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND substr(s.detected_at, 1, 10) <= ?"
        params.append(date_to)
    # Tri : récurrence desc en premier, puis fraîcheur, puis score
    sql += " ORDER BY n_sources DESC, s.detected_at DESC, s.score DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_signal(signal_id: str) -> Optional[dict[str, Any]]:
    """Détail d'un signal + liste de ses sources."""
    conn = _signaux_connect()
    if conn is None:
        return None
    sig = conn.execute(
        "SELECT * FROM signaux WHERE signal_id = ?", (signal_id,)
    ).fetchone()
    if sig is None:
        conn.close()
        return None
    result = dict(sig)
    sources = conn.execute(
        "SELECT * FROM signaux_sources WHERE signal_id = ? ORDER BY detected_at DESC",
        (signal_id,),
    ).fetchall()
    result["sources"] = [dict(s) for s in sources]
    conn.close()
    return result


def get_signal_stats() -> dict[str, Any]:
    """Stats : total, by_status, en_alerte, last_seen_at."""
    conn = _signaux_connect()
    if conn is None:
        return {"total": 0, "by_status": {}, "en_alerte": 0, "last_seen_at": None}
    total = conn.execute("SELECT COUNT(*) FROM signaux").fetchone()[0]
    by_status: dict[str, int] = {}
    for r in conn.execute(
        "SELECT status, COUNT(*) n FROM signaux GROUP BY status"
    ).fetchall():
        by_status[r["status"]] = r["n"]
    en_alerte = conn.execute(
        "SELECT COUNT(*) FROM signaux WHERE status IN ('a_valider', 'valide')"
    ).fetchone()[0]
    last = conn.execute("SELECT MAX(last_seen_at) AS ts FROM signaux").fetchone()
    last_seen = last["ts"] if last and last["ts"] else None
    conn.close()
    return {
        "total": total,
        "by_status": by_status,
        "en_alerte": en_alerte,
        "last_seen_at": last_seen,
    }


def set_signal_status(signal_id: str, status: str) -> bool:
    """Met à jour le statut d'un signal (valide/rejete depuis le dashboard)."""
    conn = _signaux_connect()
    if conn is None:
        return False
    conn.execute(
        "UPDATE signaux SET status = ? WHERE signal_id = ?",
        (status, signal_id),
    )
    conn.commit()
    conn.close()
    return True


# --- Cross-référence signaux ↔ incidents --------------------------------

def get_matches_for_signal(signal_id: str, min_score: float = 0.5) -> list[dict[str, Any]]:
    """Rappels officiels correspondant à un signal, enrichis du détail incident.

    Les matches validés humainement remontent en premier même si leur score
    algorithmique est en-dessous du seuil.
    """
    conn = _signaux_connect()
    if conn is None:
        return []
    if not INCIDENTS_DB.exists():
        conn.close()
        return []
    conn.execute("ATTACH DATABASE ? AS inc", (str(INCIDENTS_DB),))
    rows = conn.execute(
        """
        SELECT m.score, m.brand_match, m.symptom_match, m.product_match,
               m.date_proximity, m.lead_time_days, m.user_confirmed,
               i.source AS inc_source, i.source_id AS inc_source_id,
               i.source_url AS inc_url,
               i.marque AS inc_marque, i.sous_categorie AS inc_categorie,
               i.motif AS inc_motif, i.risques AS inc_risques,
               i.date_publication AS inc_date
        FROM signal_incident_matches m
        JOIN inc.incidents i
          ON i.source = m.incident_source AND i.source_id = m.incident_source_id
        WHERE m.signal_id = ? AND (m.score >= ? OR m.user_confirmed = 1)
        ORDER BY m.user_confirmed DESC, m.score DESC
        """,
        (signal_id, min_score),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_matches_for_incident(
    source: str, source_id: str, min_score: float = 0.5,
) -> list[dict[str, Any]]:
    """Signaux correspondant à un incident officiel, enrichis du détail signal."""
    conn = _signaux_connect()
    if conn is None:
        return []
    rows = conn.execute(
        """
        SELECT m.score, m.brand_match, m.symptom_match, m.product_match,
               m.date_proximity, m.lead_time_days, m.user_confirmed,
               s.signal_id, s.marque, s.symptome, s.produit, s.titre, s.resume,
               s.source_type, s.source_name, s.source_url, s.status,
               s.score AS signal_score, s.detected_at
        FROM signal_incident_matches m
        JOIN signaux s ON s.signal_id = m.signal_id
        WHERE m.incident_source = ? AND m.incident_source_id = ?
          AND (m.score >= ? OR m.user_confirmed = 1)
        ORDER BY m.user_confirmed DESC, m.score DESC
        """,
        (source, source_id, min_score),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def confirm_match(signal_id: str, inc_source: str, inc_source_id: str) -> bool:
    """Valide humainement un match (remontera en tête)."""
    conn = _signaux_connect()
    if conn is None:
        return False
    existing = conn.execute(
        """
        SELECT 1 FROM signal_incident_matches
        WHERE signal_id = ? AND incident_source = ? AND incident_source_id = ?
        """,
        (signal_id, inc_source, inc_source_id),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE signal_incident_matches SET user_confirmed = 1
            WHERE signal_id = ? AND incident_source = ? AND incident_source_id = ?
            """,
            (signal_id, inc_source, inc_source_id),
        )
    else:
        from datetime import datetime as _dt
        conn.execute(
            """
            INSERT INTO signal_incident_matches
            (signal_id, incident_source, incident_source_id, score,
             brand_match, symptom_match, product_match, date_proximity,
             lead_time_days, computed_at, user_confirmed)
            VALUES (?, ?, ?, 0, 0, 0, 0, 0, NULL, ?, 1)
            """,
            (signal_id, inc_source, inc_source_id, _dt.utcnow().isoformat()),
        )
    conn.commit()
    conn.close()
    return True


def unconfirm_match(signal_id: str, inc_source: str, inc_source_id: str) -> bool:
    """Retire la validation humaine."""
    conn = _signaux_connect()
    if conn is None:
        return False
    conn.execute(
        """
        UPDATE signal_incident_matches SET user_confirmed = 0
        WHERE signal_id = ? AND incident_source = ? AND incident_source_id = ?
        """,
        (signal_id, inc_source, inc_source_id),
    )
    conn.commit()
    conn.close()
    return True


def get_brand_media_pressure(
    marque: Optional[str],
    window_days: int = 7,
) -> int:
    """
    Nombre de signaux distincts mentionnant cette marque dans la fenêtre.

    Mesure la "pression médiatique" sur la marque — indicateur de notoriété
    négative récente indépendant du score individuel des signaux.
    """
    if not marque:
        return 0
    conn = _signaux_connect()
    if conn is None:
        return 0
    from datetime import datetime as _dt, timedelta as _td
    since = (_dt.utcnow() - _td(days=window_days)).isoformat()
    # Comparaison case-insensitive sur la marque
    row = conn.execute(
        """
        SELECT COUNT(*) FROM signaux
        WHERE LOWER(marque) = LOWER(?) AND detected_at >= ?
        """,
        (marque, since),
    ).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def get_top_brands_under_pressure(
    window_days: int = 7,
    min_count: int = 2,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Marques avec le plus de signaux distincts dans la fenêtre.
    Retourne [{"marque": str, "n_signaux": int, "avg_score": float}].
    """
    conn = _signaux_connect()
    if conn is None:
        return []
    from datetime import datetime as _dt, timedelta as _td
    since = (_dt.utcnow() - _td(days=window_days)).isoformat()
    rows = conn.execute(
        """
        SELECT marque, COUNT(*) AS n_signaux, AVG(score) AS avg_score
        FROM signaux
        WHERE marque IS NOT NULL AND marque != ''
          AND detected_at >= ?
        GROUP BY LOWER(marque)
        HAVING n_signaux >= ?
        ORDER BY n_signaux DESC, avg_score DESC
        LIMIT ?
        """,
        (since, min_count, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_media_pressure_summary(window_days: int = 7) -> dict[str, Any]:
    """Résumé global : nb marques sous pression, top 3."""
    top = get_top_brands_under_pressure(window_days=window_days, min_count=2, limit=3)
    conn = _signaux_connect()
    n_brands_under_pressure = 0
    if conn is not None:
        from datetime import datetime as _dt, timedelta as _td
        since = (_dt.utcnow() - _td(days=window_days)).isoformat()
        row = conn.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT LOWER(marque) FROM signaux
              WHERE marque IS NOT NULL AND marque != ''
                AND detected_at >= ?
              GROUP BY LOWER(marque) HAVING COUNT(*) >= 2
            )
            """,
            (since,),
        ).fetchone()
        n_brands_under_pressure = int(row[0]) if row else 0
        conn.close()
    return {
        "window_days": window_days,
        "n_brands_under_pressure": n_brands_under_pressure,
        "top": top,
    }


def get_match_stats() -> dict[str, Any]:
    """Stats globales des matches : total, strong, lead time moyen."""
    conn = _signaux_connect()
    if conn is None:
        return {
            "total_matches": 0, "strong_matches": 0,
            "avg_lead_time_days": None, "signals_ahead_count": 0,
        }
    total = conn.execute(
        "SELECT COUNT(*) FROM signal_incident_matches"
    ).fetchone()[0]
    strong = conn.execute(
        "SELECT COUNT(*) FROM signal_incident_matches WHERE score >= 0.70"
    ).fetchone()[0]
    row = conn.execute(
        """
        SELECT AVG(lead_time_days) avg_lead, COUNT(*) n_lead
        FROM signal_incident_matches
        WHERE score >= 0.70 AND lead_time_days IS NOT NULL AND lead_time_days > 0
        """
    ).fetchone()
    avg_lead = float(row[0]) if row and row[0] is not None else None
    n_lead = int(row[1] or 0) if row else 0
    conn.close()
    return {
        "total_matches": total,
        "strong_matches": strong,
        "avg_lead_time_days": avg_lead,
        "signals_ahead_count": n_lead,
    }


# ── Signaux volumes (bucket signalconso_volume) ─────────────────────────────

def get_volume_signaux(
    limit: int = 100,
    status: Optional[str] = None,
    category: Optional[str] = None,
    dep_code: Optional[str] = None,
    min_score: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Lit les signaux du bucket signalconso_volume avec le payload JSON parsé.

    Le contenu JSON contient : category, dep_code, dep_name, iso_week,
    count_actuel, baseline_median, baseline_mad, z_mod, etc.

    Filtre category/dep_code via comparaison sur le payload (LIKE) puisque
    ce sont des champs métier dans le JSON, pas des colonnes propres.
    """
    import json as _json

    conn = _signaux_connect()
    if conn is None:
        return []
    sql = "SELECT * FROM signaux WHERE source_type = 'signalconso_volume'"
    params: list = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if min_score is not None:
        sql += " AND score >= ?"
        params.append(min_score)
    sql += " ORDER BY score DESC, detected_at DESC LIMIT ?"
    params.append(limit * 5)  # over-fetch puis on filtre cat/dep côté Python
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()

    # Parse contenu JSON dans une clé `payload` exploitable côté state.
    out: list[dict[str, Any]] = []
    for r in rows:
        payload: dict[str, Any] = {}
        raw = r.get("raw_json") or ""
        if raw:
            try:
                src_dict = _json.loads(raw)
                inner = src_dict.get("contenu") or ""
                if inner:
                    payload = _json.loads(inner)
            except (ValueError, TypeError):
                pass
        # Fallback : tenter de parser le titre via la table signaux_sources
        if not payload:
            conn2 = _signaux_connect()
            if conn2 is not None:
                src_row = conn2.execute(
                    "SELECT contenu FROM signaux_sources WHERE signal_id = ? LIMIT 1",
                    (r["signal_id"],),
                ).fetchone()
                conn2.close()
                if src_row and src_row[0]:
                    try:
                        payload = _json.loads(src_row[0])
                    except (ValueError, TypeError):
                        pass

        r["payload"] = payload
        # Filtres post-fetch sur les champs JSON
        if category and payload.get("category") != category:
            continue
        if dep_code and str(payload.get("dep_code") or "") != dep_code:
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def get_volume_signal(signal_id: str) -> Optional[dict[str, Any]]:
    """Détail d'un signal volume avec son payload parsé."""
    import json as _json

    sig = get_signal(signal_id)
    if sig is None:
        return None
    payload: dict[str, Any] = {}
    # Tente de parser depuis la 1re source
    sources = sig.get("sources") or []
    if sources:
        contenu = sources[0].get("contenu") or ""
        if contenu:
            try:
                payload = _json.loads(contenu)
            except (ValueError, TypeError):
                pass
    sig["payload"] = payload
    return sig


def get_volume_stats() -> dict[str, Any]:
    """Stats du bucket volume : total, by_status, top_category, top_dep, max_z."""
    import json as _json

    conn = _signaux_connect()
    if conn is None:
        return {}
    rows = conn.execute(
        "SELECT * FROM signaux WHERE source_type = 'signalconso_volume'"
    ).fetchall()
    rows = [dict(r) for r in rows]
    total = len(rows)

    by_status: dict[str, int] = {}
    cat_counts: dict[str, int] = {}
    dep_counts: dict[str, int] = {}
    z_values: list[float] = []

    for r in rows:
        st = r.get("status") or ""
        by_status[st] = by_status.get(st, 0) + 1

        # Parse breakdown pour z_mod
        bd_raw = r.get("score_breakdown") or "{}"
        try:
            bd = _json.loads(bd_raw)
            z = bd.get("z_mod")
            if z is not None:
                z_values.append(float(z))
        except (ValueError, TypeError):
            pass

        # Source name format : "SignalConso/<Category>/<dep_name>"
        sn = r.get("source_name") or ""
        parts = sn.split("/")
        if len(parts) >= 2:
            cat = parts[1]
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        if len(parts) >= 3:
            dep = parts[2]
            dep_counts[dep] = dep_counts.get(dep, 0) + 1

    en_alerte = (by_status.get("a_valider") or 0) + (by_status.get("valide") or 0)
    top_category = max(cat_counts.items(), key=lambda kv: kv[1])[0] if cat_counts else "-"
    top_dep = max(dep_counts.items(), key=lambda kv: kv[1])[0] if dep_counts else "-"
    max_z = max(z_values) if z_values else 0.0

    # last_run_at : date du dernier run du collector signalconso_volume
    # (lu depuis source_runs, pas depuis MAX(signaux.last_seen_at) qui ne
    # change que si une nouvelle anomalie est émise).
    last_run = None
    last_emitted = 0
    try:
        row = conn.execute(
            "SELECT last_run_at, last_emitted FROM source_runs "
            "WHERE source_type = 'signalconso_volume'"
        ).fetchone()
        if row:
            last_run = row[0]
            last_emitted = int(row[1] or 0)
    except sqlite3.OperationalError:
        # Table source_runs pas encore créée (avant migration) → fallback
        pass

    # Fallback : si jamais source_runs vide, on revient sur l'ancien comportement
    if last_run is None:
        last_run = conn.execute(
            "SELECT MAX(last_seen_at) FROM signaux WHERE source_type = 'signalconso_volume'"
        ).fetchone()[0]

    conn.close()
    return {
        "total": total,
        "by_status": by_status,
        "en_alerte": en_alerte,
        "top_category": top_category,
        "top_dep": top_dep,
        "max_z": round(max_z, 2),
        "categories_distinct": sorted(cat_counts.keys()),
        "deps_distinct": sorted(dep_counts.keys()),
        "last_seen_at": last_run,             # rétrocompat avec le state
        "last_run_at": last_run,              # nouveau, sémantiquement clair
        "last_run_emitted": last_emitted,
    }


# ── Outreach messages (Agent 5 — redacteur_outreach) ────────────────────────

def _outreach_connect():
    """Ouvre une connexion vers outreach.sqlite (crée le fichier au besoin)."""
    from redacteur_outreach.storage import OutreachStorage
    return OutreachStorage(str(OUTREACH_DB))


def get_outreach_message(source: str, source_id: str) -> Optional[dict[str, Any]]:
    """Retourne le message outreach pour (source, source_id), ou None si absent."""
    import dataclasses
    try:
        storage = _outreach_connect()
        msg = storage.get_by_source(source, source_id)
        storage.close()
        return dataclasses.asdict(msg) if msg is not None else None
    except Exception:
        return None


def get_outreach_message_by_id(message_id: str) -> Optional[dict[str, Any]]:
    """Retourne le message outreach par son message_id, ou None si absent."""
    import dataclasses
    try:
        storage = _outreach_connect()
        msg = storage.get(message_id)
        storage.close()
        return dataclasses.asdict(msg) if msg is not None else None
    except Exception:
        return None


def set_outreach_status(
    message_id: str,
    status: str,
    *,
    validated_at: Optional[str] = None,
    sent_at: Optional[str] = None,
) -> None:
    """Met a jour le statut d'un message outreach."""
    try:
        storage = _outreach_connect()
        storage.set_status(message_id, status, validated_at=validated_at, sent_at=sent_at)
        storage.close()
    except Exception:
        pass


def count_outreach_a_valider() -> int:
    """Nombre de messages en statut 'a_valider'."""
    try:
        storage = _outreach_connect()
        counts = storage.count_by_status()
        storage.close()
        return counts.get("a_valider", 0)
    except Exception:
        return 0


def count_outreach_by_status() -> dict[str, int]:
    """Nombre de messages par statut."""
    try:
        storage = _outreach_connect()
        counts = storage.count_by_status()
        storage.close()
        return counts
    except Exception:
        return {}


# ── KPI payload outreach (pour le drawer INSIGHTS) ──────────────────────────

# Seuils de score sanitaire pour l'étiquetage (identiques à ceux d'evaluateur_severite)
_SCORE_TIERS: tuple[tuple[int, str, str], ...] = (
    (80, "Critique", "red"),
    (60, "Eleve",    "orange"),
    (40, "Modere",   "amber"),
    (0,  "Faible",   "green"),
)

_KPI_EMPTY: dict[str, Any] = {
    "score_sanitaire": {
        "value": 0,
        "label": "Faible",
        "color": "green",
    },
    "sources_media": {
        "total": 0,
        "by_source": [],
    },
    "confidence_prospect": {
        "value": 0.0,
        "percent": 0,
        "status": "",
    },
}


def _score_label_color(value: int) -> tuple[str, str]:
    """Retourne (label, color) pour un score sanitaire 0-100."""
    for threshold, label, color in _SCORE_TIERS:
        if value >= threshold:
            return label, color
    return "Faible", "green"


def build_outreach_kpi(context_json_str: Optional[str]) -> dict[str, Any]:
    """
    Parse le context_json d'un message outreach et retourne le payload KPI
    consommable par le drawer INSIGHTS.

    Le context_json est produit par redacteur_outreach.context_builder.build_context()
    et contient les clés : "incident", "score", "enrichissement", "signaux_summary".

    Retour garanti sans exception : si context_json est None, vide, malformé
    ou depasse 64 Ko, un payload "vide" cohérent est renvoyé.

    Cap 64 Ko : un context_json legitime ne depasse jamais quelques Ko. Une
    taille anormale signale soit une corruption soit une tentative d'injection
    de contenu volumineux. On retourne le payload vide plutot que de parser.
    """
    import json as _json

    if not context_json_str:
        import copy
        return copy.deepcopy(_KPI_EMPTY)

    if len(context_json_str) > 65536:  # 64 KB cap
        import copy
        return copy.deepcopy(_KPI_EMPTY)

    try:
        ctx = _json.loads(context_json_str)
    except (ValueError, TypeError):
        import copy
        return copy.deepcopy(_KPI_EMPTY)

    if not isinstance(ctx, dict):
        import copy
        return copy.deepcopy(_KPI_EMPTY)

    # --- score_sanitaire ---
    # context_builder._fetch_score renomme "score" → "score_total"
    score_block = ctx.get("score") or {}
    raw_score = score_block.get("score_total") if isinstance(score_block, dict) else None
    try:
        score_value = max(0, min(100, int(float(raw_score)))) if raw_score is not None else 0
    except (TypeError, ValueError):
        score_value = 0
    label, color = _score_label_color(score_value)

    # --- sources_media ---
    # signaux_summary est une liste de dicts avec "source_name"
    signaux_summary = ctx.get("signaux_summary") or []
    source_counts: dict[str, int] = {}
    if isinstance(signaux_summary, list):
        for sig in signaux_summary:
            if not isinstance(sig, dict):
                continue
            src = str(sig.get("source_name") or "").strip()
            if src:
                source_counts[src] = source_counts.get(src, 0) + 1
    by_source = sorted(
        [{"source": src, "count": cnt} for src, cnt in source_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )

    # --- confidence_prospect ---
    enrich = ctx.get("enrichissement") or {}
    if isinstance(enrich, dict):
        raw_conf = enrich.get("confidence")
        try:
            conf_value = max(0.0, min(1.0, float(raw_conf))) if raw_conf is not None else 0.0
        except (TypeError, ValueError):
            conf_value = 0.0
        contact_status = str(enrich.get("contact_type") or enrich.get("match_status") or "")
    else:
        conf_value = 0.0
        contact_status = ""

    return {
        "score_sanitaire": {
            "value": score_value,
            "label": label,
            "color": color,
        },
        "sources_media": {
            "total": sum(source_counts.values()),
            "by_source": by_source,
        },
        "confidence_prospect": {
            "value": conf_value,
            "percent": round(conf_value * 100),
            "status": contact_status,
        },
    }
