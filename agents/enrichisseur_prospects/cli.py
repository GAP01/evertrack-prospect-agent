"""
CLI de l'Enrichisseur de prospects.

Usage :
    python -m enrichisseur_prospects.cli enrich
    python -m enrichisseur_prospects.cli enrich --max 10
    python -m enrichisseur_prospects.cli enrich --reenrich
    python -m enrichisseur_prospects.cli show 2026-04-0196
    python -m enrichisseur_prospects.cli stats
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .enrichisseur import run_enrich, ENRICHER_VERSION
from .storage import EnrichissementStorage


DEFAULT_INCIDENTS_DB = Path("data/incidents.sqlite")
DEFAULT_ENRICHISSEMENTS_DB = Path("data/enrichissements.sqlite")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def cmd_enrich(args: argparse.Namespace) -> int:
    report = run_enrich(
        incidents_db=args.incidents_db,
        enrichissements_db=args.enrichissements_db,
        only_new=not args.reenrich,
        max_incidents=args.max,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    storage = EnrichissementStorage(args.enrichissements_db)
    result = storage.get("rappelconso", args.source_id)
    if result is None:
        print(f"Aucun enrichissement trouvé pour source_id={args.source_id!r}")
        print("Lance d'abord `enrich`.")
        return 1

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    # Format texte lisible
    status = result["match_status"]
    conf = result.get("confidence") or 0.0
    marque = result.get("marque_input") or "?"
    raison = result.get("raison_sociale") or "-"
    siren = result.get("siren") or "-"
    naf = result.get("libelle_naf") or "-"
    adresse = result.get("adresse") or "-"
    effectif = result.get("effectif_tranche") or "-"
    contact = result.get("contact_nom") or "-"
    titre = result.get("contact_titre") or ""
    ctype = result.get("contact_type") or "-"
    api = result.get("api_used") or "-"

    print(f"\n=== Enrichissement : {args.source_id} ===")
    print(f"  Marque input   : {marque}")
    print(f"  Match status   : {status}  (confidence={conf:.2f})")
    print(f"  Raison sociale : {raison}")
    print(f"  SIREN          : {siren}")
    print(f"  NAF            : {naf}")
    print(f"  Adresse        : {adresse}")
    print(f"  Effectif       : {effectif}")
    print(f"  Contact        : {contact}{' — ' + titre if titre else ''}")
    print(f"  Contact type   : {ctype}")
    print(f"  API utilisee   : {api}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    storage = EnrichissementStorage(args.enrichissements_db)
    stats = storage.stats()

    if args.format == "json":
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    total = stats["total_enrichis"]
    by_status = stats.get("by_status", {})
    with_contact = stats.get("with_contact", 0)
    found = by_status.get("found", 0)
    ambiguous = by_status.get("ambiguous", 0)
    not_found = by_status.get("not_found", 0)
    skipped = by_status.get("skipped", 0)

    print(f"\n=== Stats enrichissements (version {ENRICHER_VERSION}) ===")
    print(f"  Total enrichis    : {total}")
    print(f"  [ok]   Found      : {found}")
    print(f"  [~]    Ambiguous  : {ambiguous}")
    print(f"  [x]    Not found  : {not_found}")
    print(f"  [-]    Skipped    : {skipped}")
    print(f"  Avec contact      : {with_contact}")
    if total > 0:
        taux = round((found + ambiguous) / total * 100, 1)
        print(f"  Taux de couverture: {taux}%")
    return 0


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--incidents-db", type=Path, default=DEFAULT_INCIDENTS_DB,
        help="Base SQLite des incidents (du veilleur)",
    )
    parser.add_argument(
        "--enrichissements-db", type=Path, default=DEFAULT_ENRICHISSEMENTS_DB,
        help="Base SQLite des enrichissements (sortie de cet agent)",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="enrichisseur",
        description="Enrichisseur de prospects EverTrack — Agent 3",
    )
    _add_common_flags(p)
    sub = p.add_subparsers(dest="cmd", required=True)

    # enrich
    e = sub.add_parser("enrich", help="Enrichir les incidents via SIRENE")
    _add_common_flags(e)
    e.add_argument(
        "--reenrich", action="store_true",
        help="Force le ré-enrichissement des incidents déjà traités",
    )
    e.add_argument(
        "--max", type=int, default=None,
        help="Limite dure du nombre d'incidents traités",
    )
    e.set_defaults(func=cmd_enrich)

    # show
    s = sub.add_parser("show", help="Afficher l'enrichissement d'un incident")
    _add_common_flags(s)
    s.add_argument("source_id", help="source_id de l'incident (ex: 2026-04-0196)")
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_show)

    # stats
    st = sub.add_parser("stats", help="Statistiques de couverture")
    _add_common_flags(st)
    st.add_argument("--format", choices=["text", "json"], default="text")
    st.set_defaults(func=cmd_stats)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
