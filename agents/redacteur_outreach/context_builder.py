"""
Assemblage du contexte multi-base pour un incident donne.

Lit en lecture seule les 4 bases SQLite du pipeline :
  - incidents.sqlite    (Agent 1)
  - scores.sqlite       (Agent 2)
  - enrichissements.sqlite (Agent 3)
  - signaux.sqlite      (Agent 4 : signaux + signal_incident_matches)

Retourne un dict JSON-serialisable pret a etre passe au template/LLM.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Optional


class IncidentNotFoundError(Exception):
    """Raised when build_context cannot find the incident in incidents.sqlite."""


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _open(db_path: str) -> Optional[sqlite3.Connection]:
    """Ouvre la connexion si le fichier existe, None sinon."""
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# Colonnes souhaitees pour chaque table.
# Si une colonne est absente (schema en evolution), on la skip sans erreur.
_INCIDENT_COLS = (
    "source",
    "source_id",
    "marque",
    "modeles",          # nom_produit dans la spec — colonne reelle = modeles
    "categorie",        # categorie_produit dans la spec — colonne reelle = categorie
    "sous_categorie",
    "motif",
    "risques",
    "distributeurs",
    "date_publication",
    "source_url",
    "zone_geographique",
)

_SCORE_COLS = (
    "source",
    "source_id",
    "score",            # score_total dans la spec
    "tier",
    "dimensions_json",  # sous-scores serialises — desserialise ci-dessous
    "scored_at",
    "scorer_version",
    "llm_used",
)

_ENRICH_COLS = (
    "source",
    "source_id",
    "siren",
    "siret_siege",      # siret dans la spec
    "raison_sociale",   # denomination dans la spec
    "adresse",
    "contact_nom",
    "contact_titre",    # contact_fonction dans la spec
    "contact_source",
    "contact_type",
    "confidence",
    "match_status",
    "enricher_version",
)

_SIGNAL_COLS = (
    "signal_id",
    "marque",
    "symptome",
    "score",            # score_credibilite dans la spec — colonne reelle = score
    "detected_at",
    "source_name",      # source_name dans la table signaux
    "titre",
)


def _select_available(
    conn: sqlite3.Connection,
    table: str,
    desired_cols: tuple[str, ...],
    where: str,
    params: tuple,
    order: str = "",
    limit: int = 0,
) -> Optional[dict[str, Any]]:
    """
    Recupere une seule ligne en ne selectionnant que les colonnes existantes.
    Retourne None si aucune ligne, ou si une OperationalError inattendue survient.
    """
    try:
        pragma = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {r["name"] for r in pragma}
        cols = [c for c in desired_cols if c in existing]
        if not cols:
            return None
        sql = f"SELECT {', '.join(cols)} FROM {table} WHERE {where}"
        if order:
            sql += f" ORDER BY {order}"
        if limit:
            sql += f" LIMIT {limit}"
        row = conn.execute(sql, params).fetchone()
        return _row_to_dict(row) if row else None
    except sqlite3.OperationalError:
        return None


def _select_many_available(
    conn: sqlite3.Connection,
    table: str,
    desired_cols: tuple[str, ...],
    where: str,
    params: tuple,
    order: str = "",
    limit: int = 0,
) -> list[dict[str, Any]]:
    """Version multi-lignes de _select_available."""
    try:
        pragma = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {r["name"] for r in pragma}
        cols = [c for c in desired_cols if c in existing]
        if not cols:
            return []
        sql = f"SELECT {', '.join(cols)} FROM {table} WHERE {where}"
        if order:
            sql += f" ORDER BY {order}"
        if limit:
            sql += f" LIMIT {limit}"
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def _fetch_incident(db_path: str, source: str, source_id: str) -> dict[str, Any]:
    """
    Charge l'incident depuis incidents.sqlite.
    Leve IncidentNotFoundError si absent ou si le fichier n'existe pas.
    """
    conn = _open(db_path)
    if conn is None:
        raise IncidentNotFoundError(
            f"incidents.sqlite introuvable : {db_path}"
        )
    try:
        row = _select_available(
            conn, "incidents", _INCIDENT_COLS,
            "source = ? AND source_id = ?",
            (source, source_id),
        )
    finally:
        conn.close()
    if row is None:
        raise IncidentNotFoundError(
            f"Incident inconnu : source={source!r} source_id={source_id!r}"
        )
    return row


def _fetch_score(db_path: str, source: str, source_id: str) -> Optional[dict[str, Any]]:
    """
    Charge le score le plus recent pour l'incident.
    Retourne None si le fichier ou la ligne est absent.
    Desserialise dimensions_json pour exposer les sous-scores nommement.
    """
    conn = _open(db_path)
    if conn is None:
        return None
    try:
        row = _select_available(
            conn, "scores", _SCORE_COLS,
            "source = ? AND source_id = ?",
            (source, source_id),
            order="scored_at DESC",
            limit=1,
        )
    finally:
        conn.close()
    if row is None:
        return None

    # Desserialiser dimensions_json pour en extraire les sous-scores individuels.
    # Format : [{"name": "risque_sanitaire", "raw": 80, "weight": 0.5, "rationale": "..."},...]
    dims_raw = row.pop("dimensions_json", None)
    dims: list[dict[str, Any]] = []
    if dims_raw:
        try:
            dims = json.loads(dims_raw)
        except (json.JSONDecodeError, TypeError):
            pass

    # Expose les sous-scores sous des cles explicites attendues par le template
    dim_map: dict[str, float] = {}
    justifications: list[str] = []
    for d in dims:
        name = d.get("name", "")
        raw = d.get("raw")
        if name and raw is not None:
            dim_map[name] = raw
        rationale = d.get("rationale", "")
        if rationale:
            justifications.append(f"{name}: {rationale}")

    row["score_total"] = row.pop("score", None)
    row["score_risque"] = dim_map.get("risque_sanitaire")
    row["score_ampleur"] = dim_map.get("ampleur_geo")
    row["score_vulnerabilite"] = dim_map.get("population_vulnerable")
    row["score_volume"] = dim_map.get("volume_distributeurs")
    row["justification"] = " | ".join(justifications) if justifications else None
    row["dimensions"] = dims  # conserve l'integralite pour usage avance

    return row


def _fetch_enrichissement(
    db_path: str, source: str, source_id: str
) -> Optional[dict[str, Any]]:
    """
    Charge l'enrichissement le plus recent (enricher_version DESC).
    Retourne None si le fichier ou la ligne est absent.
    Renomme les colonnes vers les noms attendus par le template.
    """
    conn = _open(db_path)
    if conn is None:
        return None
    try:
        row = _select_available(
            conn, "enrichissements", _ENRICH_COLS,
            "source = ? AND source_id = ?",
            (source, source_id),
            order="enricher_version DESC, rowid DESC",
            limit=1,
        )
    finally:
        conn.close()
    if row is None:
        return None

    # Alias pour compatibilite avec la spec T3 et le template T5
    row.setdefault("siret", row.get("siret_siege"))
    row.setdefault("denomination", row.get("raison_sociale"))
    row.setdefault("contact_fonction", row.get("contact_titre"))
    # Champs absents de la DB (hors scope V1) — fournis comme None
    row.setdefault("contact_prenom", None)
    row.setdefault("contact_email", None)
    row.setdefault("contact_phone", None)

    return row


def _fetch_signaux_summary(
    db_path: str, source: str, source_id: str
) -> list[dict[str, Any]]:
    """
    Retourne jusqu'a 3 signaux lies a l'incident via signal_incident_matches.
    Tries par score decroissant (crédibilite).
    Si signaux.sqlite ou la table signal_incident_matches n'existe pas, retourne [].
    """
    conn = _open(db_path)
    if conn is None:
        return []
    try:
        # Verifier que signal_incident_matches existe avant d'aller plus loin.
        tables_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_incident_matches'"
        ).fetchone()
        if tables_rows is None:
            return []

        # JOIN signal_incident_matches x signaux
        try:
            rows = conn.execute(
                """
                SELECT
                    s.signal_id,
                    s.marque,
                    s.symptome,
                    s.score        AS score_credibilite,
                    s.detected_at,
                    s.source_name,
                    s.titre
                FROM signal_incident_matches m
                INNER JOIN signaux s ON s.signal_id = m.signal_id
                WHERE m.incident_source = ?
                  AND m.incident_source_id = ?
                ORDER BY s.score DESC
                LIMIT 3
                """,
                (source, source_id),
            ).fetchall()
        except sqlite3.OperationalError:
            # Colonnes manquantes dans l'une ou l'autre table
            return []

        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def build_context(
    source: str,
    source_id: str,
    data_dir: str = "data",
) -> dict[str, Any]:
    """
    Assemble le contexte complet pour un incident donne depuis les 4 bases SQLite.

    Parametres
    ----------
    source :
        Origine de l'incident, ex. "rappelconso".
    source_id :
        Identifiant unique de l'incident dans sa source.
    data_dir :
        Repertoire contenant les fichiers *.sqlite.
        Par defaut "data" (relatif depuis agents/).

    Retour
    ------
    dict avec les cles :
        "incident"       - dict des champs incident, jamais None (leve IncidentNotFoundError)
        "score"          - dict du score le plus recent, ou None
        "enrichissement" - dict de l'enrichissement le plus recent, ou None
        "signaux_summary"- liste de 0-3 dicts de signaux croises

    Leve
    ----
    IncidentNotFoundError si l'incident est absent de incidents.sqlite.
    """
    incidents_db = os.path.join(data_dir, "incidents.sqlite")
    scores_db = os.path.join(data_dir, "scores.sqlite")
    enrichissements_db = os.path.join(data_dir, "enrichissements.sqlite")
    signaux_db = os.path.join(data_dir, "signaux.sqlite")

    incident = _fetch_incident(incidents_db, source, source_id)
    score = _fetch_score(scores_db, source, source_id)
    enrichissement = _fetch_enrichissement(enrichissements_db, source, source_id)
    signaux_summary = _fetch_signaux_summary(signaux_db, source, source_id)

    return {
        "incident": incident,
        "score": score,
        "enrichissement": enrichissement,
        "signaux_summary": signaux_summary,
    }
