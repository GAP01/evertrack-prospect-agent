"""
CLI du Veilleur d'incidents.

Usage :
    python -m veilleur_incidents.cli fetch --since-days 7 --categorie Alimentation
    python -m veilleur_incidents.cli list --limit 10

Les flags -v/--verbose et --db sont acceptes avant OU apres la sous-commande :
    python -m veilleur_incidents.cli -v fetch --max-records 5
    python -m veilleur_incidents.cli fetch --max-records 5 -v
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .api_client import RappelConsoClient
from .storage import Storage
from .veilleur import DEFAULT_CATEGORIE, run_fetch


DEFAULT_DB = Path("data/incidents.sqlite")
DEFAULT_EXPORT = Path("data/incidents_last_fetch.json")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def cmd_fetch(args: argparse.Namespace) -> int:
    report = run_fetch(
        db_path=args.db,
        export_json_path=args.export,
        since_days=args.since_days,
        categorie=args.categorie,
        max_records=args.max_records,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    """Interroge le dataset RappelConso et imprime la liste de ses champs."""
    client = RappelConsoClient()
    fields = client.list_fields()
    if args.format == "json":
        print(json.dumps(fields, ensure_ascii=False, indent=2))
        return 0
    print(f"{len(fields)} champs dans le dataset {client.dataset_id} :\n")
    for f in fields:
        name = f.get("name") or "?"
        type_ = f.get("type") or "?"
        label = f.get("label") or ""
        print(f"  - {name:45s} [{type_:10s}] {label}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    storage = Storage(args.db)
    rows = storage.list_recent(limit=args.limit)
    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            date_pub = r.get("date_publication") or "(pas de date)"
            marque = r.get("marque") or "-"
            motif = r.get("motif") or "-"
            print(f"[{date_pub}] {marque} - {motif[:90]}")
    return 0


def _add_common_flags(parser):
    parser.add_argument("-v", "--verbose", action="store_true", help="Logging DEBUG")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="Chemin SQLite (defaut: data/incidents.sqlite)")


def build_parser():
    p = argparse.ArgumentParser(prog="veilleur", description="Veilleur d'incidents EverTrack")
    _add_common_flags(p)
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="Recuperer les nouveaux incidents")
    _add_common_flags(f)
    f.add_argument("--since-days", type=int, default=7,
                   help="Fenetre temporelle en jours (defaut: 7)")
    f.add_argument("--categorie", default=DEFAULT_CATEGORIE,
                   help="Categorie RappelConso (defaut: Alimentation). Utiliser '' pour desactiver.")
    f.add_argument("--max-records", type=int, default=None,
                   help="Limite dure du nombre d'incidents recuperes")
    f.add_argument("--export", type=Path, default=DEFAULT_EXPORT,
                   help="Chemin d'export JSON (defaut: data/incidents_last_fetch.json)")
    f.set_defaults(func=cmd_fetch)

    l = sub.add_parser("list", help="Lister les incidents en base")
    _add_common_flags(l)
    l.add_argument("--limit", type=int, default=10)
    l.add_argument("--format", choices=["text", "json"], default="text")
    l.set_defaults(func=cmd_list)

    s = sub.add_parser("schema", help="Inspecter les champs reels du dataset RappelConso")
    _add_common_flags(s)
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_schema)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    if hasattr(args, "categorie") and not args.categorie:
        args.categorie = None
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
