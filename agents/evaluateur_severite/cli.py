"""
CLI de l'Evaluateur de severite.

Usage :
    python -m evaluateur_severite.cli score --no-llm
    python -m evaluateur_severite.cli score --max 5
    python -m evaluateur_severite.cli top --limit 10
    python -m evaluateur_severite.cli top --tier critique
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

from .evaluateur import run_score, SCORER_VERSION
from .storage import ScoreStorage


DEFAULT_INCIDENTS_DB = Path("data/incidents.sqlite")
DEFAULT_SCORES_DB = Path("data/scores.sqlite")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def cmd_score(args: argparse.Namespace) -> int:
    report = run_score(
        incidents_db=args.incidents_db,
        scores_db=args.scores_db,
        use_llm=not args.no_llm,
        only_new=not args.rescore,
        max_incidents=args.max,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _load_incident_meta(incidents_db: Path, source: str, source_id: str) -> dict:
    """Pour enrichir l'affichage du top : marque + motif depuis la base incidents."""
    if not incidents_db.exists():
        return {}
    conn = sqlite3.connect(incidents_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT marque, motif, sous_categorie, date_publication, source_url "
        "FROM incidents WHERE source = ? AND source_id = ?",
        (source, source_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def cmd_top(args: argparse.Namespace) -> int:
    storage = ScoreStorage(args.scores_db)
    rows = storage.top(limit=args.limit, tier=args.tier)
    if args.format == "json":
        # Enrichir avec les metadonnees incident
        enriched = []
        for r in rows:
            meta = _load_incident_meta(args.incidents_db, r["source"], r["source_id"])
            r["dimensions"] = json.loads(r.pop("dimensions_json"))
            r["incident"] = meta
            enriched.append(r)
        print(json.dumps(enriched, ensure_ascii=False, indent=2))
        return 0

    if not rows:
        print("(aucun score en base — lance d'abord `score`)")
        return 0

    print(f"\nTop {len(rows)} incidents par severite (scorer {SCORER_VERSION}) :\n")
    for i, r in enumerate(rows, 1):
        meta = _load_incident_meta(args.incidents_db, r["source"], r["source_id"])
        marque = (meta.get("marque") or "?")[:25]
        motif = (meta.get("motif") or "?")[:70]
        date_pub = meta.get("date_publication") or "?"
        print(f"{i:2d}. [{r['score']:5.1f} {r['tier']:>8s}] "
              f"{date_pub} | {marque:25s} | {motif}")
    return 0


def _add_common_flags(parser):
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--incidents-db", type=Path, default=DEFAULT_INCIDENTS_DB,
                        help="Base SQLite des incidents (du veilleur)")
    parser.add_argument("--scores-db", type=Path, default=DEFAULT_SCORES_DB,
                        help="Base SQLite des scores")


def build_parser():
    p = argparse.ArgumentParser(prog="evaluateur",
                                description="Evaluateur de severite EverTrack")
    _add_common_flags(p)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score", help="Scorer les incidents non encore scores")
    _add_common_flags(s)
    s.add_argument("--no-llm", action="store_true",
                   help="Desactive l'appel a l'API Claude (fallback table mots-cles)")
    s.add_argument("--rescore", action="store_true",
                   help="Force le scoring meme sur les incidents deja scores")
    s.add_argument("--max", type=int, default=None,
                   help="Limite dure du nombre d'incidents scores")
    s.set_defaults(func=cmd_score)

    t = sub.add_parser("top", help="Afficher le top N par severite")
    _add_common_flags(t)
    t.add_argument("--limit", type=int, default=10)
    t.add_argument("--tier", choices=["critique", "eleve", "modere", "faible"],
                   default=None)
    t.add_argument("--format", choices=["text", "json"], default="text")
    t.set_defaults(func=cmd_top)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
