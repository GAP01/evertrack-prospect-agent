"""
Fusion de signaux redondants.

Deux stratégies complémentaires :

1. **Merge par clé de dédup** : recalcule le `signal_id` de chaque signal
   existant avec la version courante de `compute_signal_id`. Si plusieurs
   signaux existants partagent la nouvelle clé, on les fusionne.
   Utile après un bump de version du déduplicateur (ex: passage jour→semaine).

2. **Merge par URL RappelConso** : règle dure. Si N signaux ont, dans leurs
   sources, la même URL `rappel.conso.gouv.fr/fiche-rappel/NNN`, ce sont
   forcément le même événement officiel → fusion inconditionnelle.

Le signal survivant est toujours le plus ancien (par `detected_at` initial),
celui qui a le plus de sources en cas d'égalité.

Le re-scoring des signaux survivants est nécessaire après merge : `n_sources`
change → `recurrence` change. Fait par le caller (généralement juste avant
`recompute_all_matches`).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .deduplicator import compute_signal_id
from .rappelconso_link import extract_fiche_number
from .storage import SignalStorage

logger = logging.getLogger(__name__)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _pick_survivor(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Parmi N candidats, choisit le signal qui "absorbe" les autres.

    Règle :
    1. Celui avec le plus de sources (le plus "mature")
    2. En cas d'égalité : le plus ancien detected_at (signal historique)
    """
    def key(sig: dict[str, Any]) -> tuple[int, datetime]:
        n_sources = int(sig.get("_n_sources", 0))
        dt = _parse_iso(sig.get("detected_at")) or datetime.max
        # On veut tri DESC sur n_sources puis ASC sur detected_at
        return (-n_sources, dt)
    return min(candidates, key=key)


def _load_signals_with_source_counts(db: Path) -> list[dict[str, Any]]:
    """Charge tous les signaux + leur nombre de sources."""
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT s.*, COUNT(src.signal_id) AS _n_sources
            FROM signaux s
            LEFT JOIN signaux_sources src ON src.signal_id = s.signal_id
            GROUP BY s.signal_id
        """).fetchall()
    return [dict(r) for r in rows]


# --- Stratégie 1 : merge via recalcul de signal_id -----------------------

def merge_by_recomputed_key(signaux_db: Path) -> dict[str, Any]:
    """
    Recalcule le signal_id théorique de chaque signal avec la logique actuelle.
    Si plusieurs signaux existants se retrouveraient avec la même clé, fusion.

    Utile après un changement de version du déduplicateur (nouvelles familles
    pathogènes, fenêtre temporelle élargie, etc.).

    Ne modifie PAS le signal_id (reste sur l'ancien hash pour préserver les
    URLs déjà vues et les validations humaines). On fusionne juste les doublons.
    """
    storage = SignalStorage(signaux_db)
    signaux = _load_signals_with_source_counts(signaux_db)

    # Group by new computed key
    groups: dict[str, list[dict[str, Any]]] = {}
    for sig in signaux:
        dt = _parse_iso(sig.get("detected_at"))
        new_key = compute_signal_id(
            marque=sig.get("marque"),
            symptome=sig.get("symptome"),
            titre=sig.get("titre") or "",
            detected_at=dt or datetime.utcnow(),
            produit=sig.get("produit"),
        )
        groups.setdefault(new_key, []).append(sig)

    merged = 0
    collisions = []
    for new_key, members in groups.items():
        if len(members) < 2:
            continue
        survivor = _pick_survivor(members)
        survivor_id = survivor["signal_id"]
        to_merge = [m for m in members if m["signal_id"] != survivor_id]
        collisions.append({
            "survivor": survivor_id,
            "merged_into": [m["signal_id"] for m in to_merge],
            "new_key": new_key,
        })
        for m in to_merge:
            rpt = storage.merge_signal_into(m["signal_id"], survivor_id)
            logger.info(
                "Merge (key) %s → %s : %d sources moved, %d dups, %d matches removed",
                m["signal_id"], survivor_id,
                rpt["sources_moved"], rpt["sources_duplicates"], rpt["matches_removed"],
            )
            merged += 1

    return {
        "strategy": "recomputed_key",
        "signaux_before": len(signaux),
        "groups_total": len(groups),
        "collisions": len(collisions),
        "signaux_merged": merged,
        "details": collisions,
    }


# --- Stratégie 2 : merge via URL RappelConso ------------------------------

def merge_by_rappelconso_url(signaux_db: Path) -> dict[str, Any]:
    """
    Regroupe les signaux qui partagent une même fiche RappelConso (via leurs
    sources). Chaque groupe est fusionné en un signal unique.

    Règle dure : une URL RappelConso pointe vers un rappel officiel unique.
    Deux signaux liés à la même fiche sont forcément le même événement.
    """
    storage = SignalStorage(signaux_db)

    # Charge (fiche_num, signal_id) via les sources
    with sqlite3.connect(signaux_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT DISTINCT signal_id, rappelconso_url
            FROM signaux_sources
            WHERE rappelconso_url IS NOT NULL AND rappelconso_url != ''
        """).fetchall()

    # Group by fiche number (plus stable que l'URL entière qui peut varier sur /interne vs /externe)
    groups: dict[str, list[str]] = {}
    for r in rows:
        fiche = extract_fiche_number(r["rappelconso_url"])
        if not fiche:
            continue
        groups.setdefault(fiche, []).append(r["signal_id"])

    # Dédup des signal_ids dans chaque groupe
    for fiche, ids in groups.items():
        groups[fiche] = list(dict.fromkeys(ids))  # préserve ordre, dédup

    signaux_all = {s["signal_id"]: s for s in _load_signals_with_source_counts(signaux_db)}

    merged = 0
    collisions = []
    for fiche, signal_ids in groups.items():
        if len(signal_ids) < 2:
            continue
        members = [signaux_all[sid] for sid in signal_ids if sid in signaux_all]
        if len(members) < 2:
            continue
        survivor = _pick_survivor(members)
        survivor_id = survivor["signal_id"]
        to_merge = [m for m in members if m["signal_id"] != survivor_id]
        collisions.append({
            "survivor": survivor_id,
            "merged_into": [m["signal_id"] for m in to_merge],
            "fiche_rappelconso": fiche,
        })
        for m in to_merge:
            rpt = storage.merge_signal_into(m["signal_id"], survivor_id)
            logger.info(
                "Merge (URL %s) %s → %s : %d sources moved, %d dups, %d matches removed",
                fiche, m["signal_id"], survivor_id,
                rpt["sources_moved"], rpt["sources_duplicates"], rpt["matches_removed"],
            )
            merged += 1

    return {
        "strategy": "rappelconso_url",
        "fiches_with_multiple_signaux": len(collisions),
        "signaux_merged": merged,
        "details": collisions,
    }


# --- Re-scoring post-merge -----------------------------------------------

def recompute_scores_for_survivors(
    signaux_db: Path,
    incidents_db: Optional[Path] = None,
) -> int:
    """
    Après un merge, les signaux survivants ont potentiellement plus de sources
    → leur `recurrence` change → leur score aussi. Recalcule le score et
    update la table signaux.

    N'appelle pas le LLM (ne ré-extrait pas), juste recompute le scoring.
    """
    from .scorer import compute_score, status_for_score
    import json as _json

    with sqlite3.connect(signaux_db) as conn:
        conn.row_factory = sqlite3.Row
        signaux = [dict(r) for r in conn.execute("SELECT * FROM signaux").fetchall()]

    storage = SignalStorage(signaux_db)
    n_updated = 0

    for sig in signaux:
        signal_id = sig["signal_id"]
        n_sources = storage.count_sources(signal_id)
        pub_dt = storage.earliest_source_date(signal_id) or _parse_iso(sig.get("detected_at"))
        if not pub_dt:
            continue

        score, breakdown = compute_score(
            source_name=sig.get("source_name") or "",
            n_sources=n_sources,
            detected_at=pub_dt,
            marque=sig.get("marque"),
            titre=sig.get("titre") or "",
            contenu="",
            incidents_db=incidents_db,
        )

        # Préserve le statut humain sinon recalc
        current_status = sig.get("status") or "faible"
        if current_status not in ("valide", "rejete", "promu"):
            new_status = status_for_score(score)
        else:
            new_status = current_status

        with sqlite3.connect(signaux_db) as conn:
            conn.execute(
                """
                UPDATE signaux
                SET score = ?, score_breakdown = ?, status = ?
                WHERE signal_id = ?
                """,
                (
                    score,
                    _json.dumps(breakdown, ensure_ascii=False),
                    new_status,
                    signal_id,
                ),
            )
        n_updated += 1

    return n_updated


# --- Orchestrateur -------------------------------------------------------

def merge_duplicates(
    signaux_db: Path,
    incidents_db: Optional[Path] = None,
    rescore: bool = True,
) -> dict[str, Any]:
    """
    Applique les 2 stratégies de merge puis recalcule les scores.

    Ordre d'exécution :
    1. merge_by_rappelconso_url (règle dure, prioritaire)
    2. merge_by_recomputed_key (utilise la logique dédup actuelle)
    3. recompute_scores_for_survivors

    Retourne un rapport global.
    """
    report: dict[str, Any] = {}

    r1 = merge_by_rappelconso_url(signaux_db)
    report["merge_rappelconso_url"] = r1

    r2 = merge_by_recomputed_key(signaux_db)
    report["merge_recomputed_key"] = r2

    if rescore:
        n = recompute_scores_for_survivors(signaux_db, incidents_db=incidents_db)
        report["signaux_rescored"] = n

    return report
