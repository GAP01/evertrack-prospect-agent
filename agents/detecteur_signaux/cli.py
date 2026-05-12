"""
CLI du détecteur de signaux faibles.

Usage :
    python -m detecteur_signaux.cli fetch [--max N] [--no-llm] [--sources google_news,reddit,tiktok]
    python -m detecteur_signaux.cli show <signal_id>
    python -m detecteur_signaux.cli list [--status a_valider] [--min-score 60]
    python -m detecteur_signaux.cli stats
    python -m detecteur_signaux.cli validate <signal_id> --accept
    python -m detecteur_signaux.cli validate <signal_id> --reject
    python -m detecteur_signaux.cli promote <signal_id>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .cross_reference import recompute_all_matches
from .detecteur import promote_signal, run_detect, validate_signal
from .merger import merge_duplicates
from .storage import SignalStorage


DEFAULT_SIGNAUX_DB = Path("data/signaux.sqlite")
DEFAULT_INCIDENTS_DB = Path("data/incidents.sqlite")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def cmd_fetch(args: argparse.Namespace) -> int:
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    report = run_detect(
        signaux_db=args.signaux_db,
        incidents_db=args.incidents_db,
        sources=sources,
        use_llm=not args.no_llm,
        max_items=args.max,
        scrape_articles=not args.no_scrape,
    )
    # Recalcule les correspondances signaux ↔ incidents après chaque fetch,
    # sauf si --no-crossref passé pour raisons de debug.
    if not args.no_crossref:
        xref = recompute_all_matches(
            signaux_db=args.signaux_db,
            incidents_db=args.incidents_db,
            window_days=args.window_days,
        )
        report["crossref"] = xref
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Merge signaux redondants (via URL RappelConso + recalcul clé)."""
    result = merge_duplicates(
        signaux_db=args.signaux_db,
        incidents_db=args.incidents_db,
        rescore=not args.no_rescore,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_crossref(args: argparse.Namespace) -> int:
    """Recalcule les correspondances signaux ↔ incidents sans refetch."""
    result = recompute_all_matches(
        signaux_db=args.signaux_db,
        incidents_db=args.incidents_db,
        min_score=args.min_score,
        window_days=args.window_days,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_scrape_links(args: argparse.Namespace) -> int:
    """
    Parcourt les signaux_sources et tente d'extraire les URLs RappelConso
    depuis le HTML des articles. Ne re-crawle pas les RSS, juste enrichit.
    """
    import sqlite3
    import time
    import requests as _req
    from .rappelconso_link import fetch_article_html, extract_rappelconso_urls

    conn = sqlite3.connect(args.signaux_db)
    conn.row_factory = sqlite3.Row
    where = ""
    if not args.all:
        where = "WHERE rappelconso_url IS NULL OR rappelconso_url = ''"
    rows = conn.execute(
        f"SELECT signal_id, source_url FROM signaux_sources {where}"
    ).fetchall()
    print(f"{len(rows)} sources à traiter...")

    session = _req.Session()
    n_found = 0
    for i, row in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {row['source_url'][:80]}")
        html = fetch_article_html(row["source_url"], session=session)
        rc_urls = extract_rappelconso_urls(html) if html else []
        if rc_urls:
            conn.execute(
                """
                UPDATE signaux_sources SET rappelconso_url = ?
                WHERE signal_id = ? AND source_url = ?
                """,
                (rc_urls[0], row["signal_id"], row["source_url"]),
            )
            conn.commit()
            n_found += 1
            print(f"  → {rc_urls[0]}")
        time.sleep(args.sleep)

    conn.close()
    print(f"Done. {n_found}/{len(rows)} URLs RappelConso trouvées.")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    storage = SignalStorage(args.signaux_db)
    sig = storage.get(args.signal_id)
    if sig is None:
        print(f"Aucun signal trouvé pour id={args.signal_id!r}")
        return 1

    if args.format == "json":
        sig["sources"] = storage.list_sources(args.signal_id)
        print(json.dumps(sig, ensure_ascii=False, indent=2, default=str))
        return 0

    sources = storage.list_sources(args.signal_id)
    breakdown = {}
    try:
        breakdown = json.loads(sig.get("score_breakdown") or "{}")
    except json.JSONDecodeError:
        pass

    print(f"\n=== Signal {sig['signal_id']} ===")
    print(f"  Marque    : {sig.get('marque') or '-'}")
    print(f"  Produit   : {sig.get('produit') or '-'}")
    print(f"  Symptome  : {sig.get('symptome') or '-'}")
    print(f"  Resume    : {sig.get('resume') or '-'}")
    print(f"  Score     : {sig.get('score')} / 100")
    for k, v in breakdown.items():
        print(f"    - {k}: {v}")
    print(f"  Status    : {sig.get('status')}")
    print(f"  Sources   : {len(sources)}")
    for s in sources:
        print(f"    [{s['source_type']}] {s['source_name']} — {s['titre'][:70]}")
        print(f"      {s['source_url']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    storage = SignalStorage(args.signaux_db)
    rows = storage.list_signals(
        status=args.status,
        min_score=args.min_score,
        limit=args.limit,
    )
    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return 0

    if not rows:
        print("Aucun signal.")
        return 0

    print(f"\n{len(rows)} signaux :")
    print(f"{'ID':18} {'Score':6} {'Status':12} {'Marque':20} {'Titre':60}")
    print("-" * 120)
    for r in rows:
        marque = (r.get("marque") or "-")[:20]
        titre = (r.get("titre") or "")[:60]
        print(
            f"{r['signal_id']:18} {r.get('score',0):6d} "
            f"{r.get('status','')[:12]:12} {marque:20} {titre:60}"
        )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    storage = SignalStorage(args.signaux_db)
    s = storage.stats()
    if args.format == "json":
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0

    print("\n=== Stats détecteur de signaux ===")
    print(f"  Total signaux : {s['total']}")
    by_status = s.get("by_status") or {}
    print(f"  [?]    A valider : {by_status.get('a_valider', 0)}")
    print(f"  [ok]   Valide    : {by_status.get('valide', 0)}")
    print(f"  [x]    Rejete    : {by_status.get('rejete', 0)}")
    print(f"  [>]    Promu     : {by_status.get('promu', 0)}")
    print(f"  [-]    Faible    : {by_status.get('faible', 0)}")
    print(f"  Dernier fetch    : {s.get('last_seen_at') or 'jamais'}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    accept = args.accept and not args.reject
    if args.accept == args.reject:
        print("Erreur : spécifie --accept OU --reject (pas les deux ni aucun)")
        return 2

    result = validate_signal(
        signaux_db=args.signaux_db,
        signal_id=args.signal_id,
        accept=accept,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_promote(args: argparse.Namespace) -> int:
    result = promote_signal(
        signaux_db=args.signaux_db,
        incidents_db=args.incidents_db,
        signal_id=args.signal_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--signaux-db", type=Path, default=DEFAULT_SIGNAUX_DB,
        help="Base SQLite des signaux (sortie de cet agent)",
    )
    parser.add_argument(
        "--incidents-db", type=Path, default=DEFAULT_INCIDENTS_DB,
        help="Base SQLite des incidents (pour bonus brand_known + promotion)",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="detecteur_signaux",
        description="Détecteur de signaux faibles EverTrack",
    )
    _add_common_flags(p)
    sub = p.add_subparsers(dest="cmd", required=True)

    # fetch
    f = sub.add_parser("fetch", help="Lance un cycle de détection")
    _add_common_flags(f)
    f.add_argument("--max", type=int, default=None, help="Limite dure items traités")
    f.add_argument("--no-llm", action="store_true", help="Fallback regex (sans Claude)")
    f.add_argument(
        "--sources", default="google_news,reddit",
        help="Liste CSV des sources a interroger (ex: google_news, reddit, tiktok, signalconso)",
    )
    f.add_argument(
        "--no-crossref", action="store_true",
        help="Ne pas recalculer les correspondances signaux ↔ incidents après fetch",
    )
    f.add_argument(
        "--no-scrape", action="store_true",
        help="Ne pas scraper le HTML des articles pour détecter les liens RappelConso",
    )
    f.add_argument(
        "--window-days", type=int, default=30,
        help="Fenêtre temporelle pour les matches signal ↔ incident",
    )
    f.set_defaults(func=cmd_fetch)

    # crossref
    xr = sub.add_parser("crossref", help="Recalcule les correspondances signaux ↔ incidents")
    _add_common_flags(xr)
    xr.add_argument(
        "--min-score", type=float, default=0.5,
        help="Score minimal pour stocker un match (0.0-1.0)",
    )
    xr.add_argument(
        "--window-days", type=int, default=30,
        help="Fenêtre temporelle (± jours) autour de chaque signal",
    )
    xr.set_defaults(func=cmd_crossref)

    # merge-duplicates
    mg = sub.add_parser(
        "merge-duplicates",
        help="Fusionne les signaux redondants (même URL RappelConso + même clé)",
    )
    _add_common_flags(mg)
    mg.add_argument(
        "--no-rescore", action="store_true",
        help="Ne pas recalculer les scores des signaux survivants après merge",
    )
    mg.set_defaults(func=cmd_merge)

    # scrape-links
    sl = sub.add_parser(
        "scrape-links",
        help="Parcourt les articles existants pour détecter des liens RappelConso",
    )
    _add_common_flags(sl)
    sl.add_argument(
        "--all", action="store_true",
        help="Re-scraper aussi les sources qui ont déjà une URL RC",
    )
    sl.add_argument(
        "--sleep", type=float, default=0.5,
        help="Délai entre requêtes HTTP (secondes)",
    )
    sl.set_defaults(func=cmd_scrape_links)

    # show
    sh = sub.add_parser("show", help="Détail d'un signal")
    _add_common_flags(sh)
    sh.add_argument("signal_id")
    sh.add_argument("--format", choices=["text", "json"], default="text")
    sh.set_defaults(func=cmd_show)

    # list
    ls = sub.add_parser("list", help="Liste les signaux")
    _add_common_flags(ls)
    ls.add_argument("--status", default=None, help="Filtre (a_valider, valide, rejete, promu, faible)")
    ls.add_argument("--min-score", type=int, default=None)
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--format", choices=["text", "json"], default="text")
    ls.set_defaults(func=cmd_list)

    # stats
    st = sub.add_parser("stats", help="Statistiques globales")
    _add_common_flags(st)
    st.add_argument("--format", choices=["text", "json"], default="text")
    st.set_defaults(func=cmd_stats)

    # validate
    v = sub.add_parser("validate", help="Valider/rejeter un signal")
    _add_common_flags(v)
    v.add_argument("signal_id")
    v.add_argument("--accept", action="store_true")
    v.add_argument("--reject", action="store_true")
    v.set_defaults(func=cmd_validate)

    # promote
    pr = sub.add_parser("promote", help="Promouvoir un signal validé en incident")
    _add_common_flags(pr)
    pr.add_argument("signal_id")
    pr.set_defaults(func=cmd_promote)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
