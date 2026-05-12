"""
CLI du redacteur outreach (Agent 5).

Usage :
    python -m redacteur_outreach.cli generate <source_id> [--source SOURCE]
    python -m redacteur_outreach.cli generate-batch [--min-score N] [--max N]
    python -m redacteur_outreach.cli list [--status STATUS] [--limit N]
    python -m redacteur_outreach.cli show <message_id> [--format md|json|eml]
    python -m redacteur_outreach.cli validate <message_id> --accept|--reject
    python -m redacteur_outreach.cli mark-sent <message_id>
    python -m redacteur_outreach.cli set-status <message_id> --status STATUS
    python -m redacteur_outreach.cli regenerate <message_id> [--no-llm]
    python -m redacteur_outreach.cli stats
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterator

from .context_builder import IncidentNotFoundError
from .models import STATUS_CHOICES, OutreachMessage
from .redacteur import Redacteur
from .storage import OutreachStorage


def _db_path(data_dir: str) -> str:
    return os.path.join(data_dir, "outreach.sqlite")


def _open_storage(data_dir: str) -> OutreachStorage | None:
    """
    Ouvre le storage SQLite en creant le repertoire si necessaire.

    Retourne None et affiche [x] si le chemin est inaccessible.
    Le repertoire est cree automatiquement pour eviter une erreur sqlite3
    si data_dir n'existe pas encore.
    """
    db = _db_path(data_dir)
    try:
        os.makedirs(data_dir, exist_ok=True)
        return OutreachStorage(db)
    except (sqlite3.OperationalError, OSError) as exc:
        print(f"[x] impossible d'ouvrir la base outreach: {exc}")
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _strip_crlf(value: str) -> str:
    """Retire CR/LF d'un header pour eviter CWE-93 header injection."""
    return value.replace("\r", "").replace("\n", "").strip()


def _iter_candidates(
    data_dir: str,
    min_score: int,
    limit: int | None,
) -> Iterator[tuple[str, str, float | None]]:
    """
    Retourne les (source, source_id, score_total) pour les incidents enrichis.

    Jointure :
      - incidents.sqlite (source de verite)
      - enrichissements.sqlite (filtre : doit exister)
      - scores.sqlite (filtre : score >= min_score si presente)

    Les incidents sans score sont exclus quand min_score > 0 et toujours exclus
    si scores.sqlite n'existe pas et min_score > 0 ; avec min_score=0 et sans
    scores.sqlite, on inclut tous les incidents enrichis (score=None).
    """
    incidents_db = os.path.join(data_dir, "incidents.sqlite")
    enrichissements_db = os.path.join(data_dir, "enrichissements.sqlite")
    scores_db = os.path.join(data_dir, "scores.sqlite")

    if not os.path.exists(incidents_db) or not os.path.exists(enrichissements_db):
        return

    # Attacher les bases supplementaires pour faire un JOIN cross-fichier.
    conn = sqlite3.connect(incidents_db)
    conn.row_factory = sqlite3.Row
    try:
        try:
            conn.execute(f"ATTACH DATABASE ? AS enrich", (enrichissements_db,))
        except sqlite3.OperationalError:
            return

        scores_available = os.path.exists(scores_db)
        if scores_available:
            try:
                conn.execute(f"ATTACH DATABASE ? AS scores_db", (scores_db,))
            except sqlite3.OperationalError:
                scores_available = False

        if scores_available:
            sql = """
                SELECT i.source, i.source_id, s.score AS score_total
                FROM incidents i
                INNER JOIN enrich.enrichissements e
                    ON e.source = i.source AND e.source_id = i.source_id
                INNER JOIN scores_db.scores s
                    ON s.source = i.source AND s.source_id = i.source_id
                WHERE s.score >= ?
                GROUP BY i.source, i.source_id
                ORDER BY s.score DESC
            """
            params: tuple = (min_score,)
        else:
            if min_score > 0:
                # Pas de scores disponibles et un filtre est demande : rien.
                return
            sql = """
                SELECT i.source, i.source_id, NULL AS score_total
                FROM incidents i
                INNER JOIN enrich.enrichissements e
                    ON e.source = i.source AND e.source_id = i.source_id
                GROUP BY i.source, i.source_id
                ORDER BY i.source_id
            """
            params = ()

        if limit is not None:
            sql += f" LIMIT {int(limit)}"

        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            yield row["source"], row["source_id"], row["score_total"]
    except sqlite3.OperationalError:
        return
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_generate(args: argparse.Namespace) -> int:
    storage = _open_storage(args.data_dir)
    if storage is None:
        return 1
    # Verifier l'idempotence avant d'appeler Redacteur pour distinguer [ok] vs [~].
    existing = storage.get_by_source(args.source, args.source_id)
    if existing is not None and not args.force:
        print(
            f"[~] message existant: message_id={existing.message_id}"
            f" status={existing.status}"
            f" (use --force pour regenerer)"
        )
        return 0

    redacteur = Redacteur(storage, data_dir=args.data_dir)
    try:
        msg = redacteur.generate(
            args.source,
            args.source_id,
            canal=args.canal,
            no_llm=args.no_llm,
            force=args.force,
        )
    except IncidentNotFoundError:
        print(f"[x] incident inconnu: source={args.source} source_id={args.source_id}")
        return 1

    print(
        f"[ok] message_id={msg.message_id}"
        f" status={msg.status}"
        f" llm_used={msg.llm_used}"
    )
    return 0


def cmd_generate_batch(args: argparse.Namespace) -> int:
    n_candidates = 0
    n_new = 0
    n_existing = 0
    n_errors = 0

    storage = _open_storage(args.data_dir)
    if storage is None:
        return 1
    redacteur = Redacteur(storage, data_dir=args.data_dir)

    for source, source_id, score_total in _iter_candidates(
        args.data_dir, args.min_score, args.max
    ):
        n_candidates += 1
        already = storage.get_by_source(source, source_id)
        if already is not None and not args.force:
            n_existing += 1
            continue
        try:
            redacteur.generate(
                source,
                source_id,
                no_llm=args.no_llm,
                force=args.force,
            )
            n_new += 1
        except IncidentNotFoundError:
            n_errors += 1
        except Exception:
            n_errors += 1

    print("[ok] batch termine")
    print(f"- candidats   : {n_candidates}")
    print(f"- generes neufs : {n_new}")
    print(f"- existants    : {n_existing} (idempotents)")
    print(f"- erreurs      : {n_errors}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    storage = _open_storage(args.data_dir)
    if storage is None:
        return 1

    if args.status:
        messages = storage.list_by_status(args.status)
    else:
        messages = storage.list_all(limit=args.limit)

    if not messages:
        print("[~] aucun message")
        return 0

    # Largeurs de colonnes fixes pour eviter les debordements courants.
    col_id = 18
    col_sid = 22
    col_status = 10
    col_date = 22
    col_llm = 5

    header = (
        f"{'message_id':{col_id}} | "
        f"{'source_id':{col_sid}} | "
        f"{'status':{col_status}} | "
        f"{'generated_at':{col_date}} | "
        f"{'llm':{col_llm}}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)
    for msg in messages:
        llm_str = "oui" if msg.llm_used else "non"
        date_str = (msg.generated_at or "")[:22]
        print(
            f"{msg.message_id:{col_id}} | "
            f"{(msg.source_id or ''):{col_sid}} | "
            f"{(msg.status or ''):{col_status}} | "
            f"{date_str:{col_date}} | "
            f"{llm_str:{col_llm}}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    storage = _open_storage(args.data_dir)
    if storage is None:
        return 1
    msg = storage.get(args.message_id)
    if msg is None:
        print(f"[x] message inconnu: {args.message_id}")
        return 1

    fmt = args.format

    if fmt == "json":
        print(json.dumps(asdict(msg), ensure_ascii=True, indent=2))
        return 0

    if fmt == "eml":
        # Recuperer contact_email depuis context_json si present.
        to_addr = "TBD@destinataire.invalid"
        if msg.context_json:
            try:
                ctx = json.loads(msg.context_json)
                enrich = ctx.get("enrichissement") or {}
                email = enrich.get("contact_email")
                if email and "@" in str(email):
                    to_addr = str(email)
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

        # Recuperer editeur_nom depuis context_json pitch si possible ; fallback fixe.
        from_addr = "EverTrack <outreach@evertrack.invalid>"

        date_str = _strip_crlf(msg.generated_at or _now_iso())
        subject = _strip_crlf(
            (msg.objet or "").encode("ascii", errors="replace").decode("ascii")
        )
        to_addr = _strip_crlf(to_addr)
        from_addr = _strip_crlf(from_addr)
        body = (msg.body_md or "").encode("ascii", errors="replace").decode("ascii")

        print(f"From: {from_addr}")
        print(f"To: {to_addr}")
        print(f"Subject: {subject}")
        print(f"Date: {date_str}")
        print("MIME-Version: 1.0")
        print("Content-Type: text/plain; charset=us-ascii")
        print("")
        print(body)
        return 0

    # Format md (defaut)
    print(f"=== Message {msg.message_id} ===")
    print(f"  source_id   : {msg.source_id}")
    print(f"  status      : {msg.status}")
    print(f"  llm_used    : {msg.llm_used}")
    print(f"  generated_at: {msg.generated_at or '-'}")
    print(f"  canal       : {msg.canal}")
    print("")
    print(f"Objet : {msg.objet or '-'}")
    print("")
    print("--- Corps ---")
    print(msg.body_md or "(vide)")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    if args.accept == args.reject:
        print("[x] specifier --accept OU --reject (pas les deux ni aucun)")
        return 1

    storage = _open_storage(args.data_dir)
    if storage is None:
        return 1
    msg = storage.get(args.message_id)
    if msg is None:
        print(f"[x] message inconnu: {args.message_id}")
        return 1

    new_status = "valide" if args.accept else "rejete"
    storage.set_status(args.message_id, new_status, validated_at=_now_iso())
    print(f"[ok] message {args.message_id} -> {new_status}")
    return 0


def cmd_mark_sent(args: argparse.Namespace) -> int:
    storage = _open_storage(args.data_dir)
    if storage is None:
        return 1
    msg = storage.get(args.message_id)
    if msg is None:
        print(f"[x] message inconnu: {args.message_id}")
        return 1

    storage.set_status(args.message_id, "envoye", sent_at=_now_iso())
    print(f"[ok] message {args.message_id} marque envoye")
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    if args.status not in STATUS_CHOICES:
        valid = ", ".join(STATUS_CHOICES)
        print(f"[x] statut invalide: {args.status!r}. Valeurs valides: {valid}")
        return 1

    storage = _open_storage(args.data_dir)
    if storage is None:
        return 1
    msg = storage.get(args.message_id)
    if msg is None:
        print(f"[x] message inconnu: {args.message_id}")
        return 1

    storage.set_status(args.message_id, args.status)
    print(f"[ok] message {args.message_id} -> {args.status}")
    return 0


def cmd_regenerate(args: argparse.Namespace) -> int:
    storage = _open_storage(args.data_dir)
    if storage is None:
        return 1
    existing = storage.get(args.message_id)
    if existing is None:
        print(f"[x] message inconnu: {args.message_id}")
        return 1

    # Utilise generate(force=True) plutot que regenerate() pour pouvoir passer no_llm.
    # regenerate() ne prend pas no_llm et appelerait le LLM sans controle.
    redacteur = Redacteur(storage, data_dir=args.data_dir)
    try:
        msg = redacteur.generate(
            existing.source,
            existing.source_id,
            canal=existing.canal,
            no_llm=args.no_llm,
            force=True,
        )
    except IncidentNotFoundError:
        print(
            f"[x] incident inconnu: source={existing.source}"
            f" source_id={existing.source_id}"
        )
        return 1

    print(f"[ok] message regenere id={msg.message_id} status={msg.status}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    storage = _open_storage(args.data_dir)
    if storage is None:
        return 1
    counts = storage.count_by_status()

    total = sum(counts.values())
    print("[ok] outreach stats")
    for status in STATUS_CHOICES:
        print(f"- {status:<12}: {counts.get(status, 0)}")
    print(f"- {'total':<12}: {total}")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _add_data_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Repertoire contenant les fichiers SQLite (defaut: data)",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="redacteur_outreach",
        description="Agent 5 EverTrack - Redacteur outreach",
    )
    sub = p.add_subparsers(dest="cmd")

    # generate
    gen = sub.add_parser("generate", help="Genere un message pour un incident")
    gen.add_argument("source_id", help="Identifiant source de l'incident")
    gen.add_argument(
        "--source", default="rappelconso",
        help="Source de l'incident (defaut: rappelconso)",
    )
    gen.add_argument(
        "--canal", default="email", choices=["email"],
        help="Canal de diffusion (defaut: email)",
    )
    gen.add_argument(
        "--no-llm", action="store_true",
        help="Utilise uniquement le template (sans Claude)",
    )
    gen.add_argument(
        "--force", action="store_true",
        help="Force la regeneration meme si un message existe deja",
    )
    _add_data_dir(gen)
    gen.set_defaults(func=cmd_generate)

    # generate-batch
    batch = sub.add_parser(
        "generate-batch",
        help="Genere des messages pour tous les incidents enrichis filtres par score",
    )
    batch.add_argument(
        "--min-score", type=int, default=0,
        help="Score minimal (jointure scores.sqlite, defaut: 0)",
    )
    batch.add_argument(
        "--max", type=int, default=None,
        help="Nombre maximum d'incidents traites",
    )
    batch.add_argument("--no-llm", action="store_true")
    batch.add_argument("--force", action="store_true")
    _add_data_dir(batch)
    batch.set_defaults(func=cmd_generate_batch)

    # list
    ls = sub.add_parser("list", help="Liste les messages outreach")
    ls.add_argument("--status", default=None, help="Filtre par statut")
    ls.add_argument("--limit", type=int, default=50, help="Nombre max de lignes")
    _add_data_dir(ls)
    ls.set_defaults(func=cmd_list)

    # show
    sh = sub.add_parser("show", help="Affiche le detail d'un message")
    sh.add_argument("message_id")
    sh.add_argument(
        "--format", choices=["md", "json", "eml"], default="md",
        help="Format de sortie (md, json, eml)",
    )
    _add_data_dir(sh)
    sh.set_defaults(func=cmd_show)

    # validate
    val = sub.add_parser("validate", help="Valide ou rejette un message")
    val.add_argument("message_id")
    val.add_argument("--accept", action="store_true", help="Marquer comme valide")
    val.add_argument("--reject", action="store_true", help="Marquer comme rejete")
    _add_data_dir(val)
    val.set_defaults(func=cmd_validate)

    # mark-sent
    ms = sub.add_parser("mark-sent", help="Marque un message comme envoye")
    ms.add_argument("message_id")
    _add_data_dir(ms)
    ms.set_defaults(func=cmd_mark_sent)

    # set-status
    ss = sub.add_parser("set-status", help="Transition de statut generique")
    ss.add_argument("message_id")
    ss.add_argument(
        "--status", required=True,
        help=f"Nouveau statut : {', '.join(STATUS_CHOICES)}",
    )
    _add_data_dir(ss)
    ss.set_defaults(func=cmd_set_status)

    # regenerate
    rg = sub.add_parser("regenerate", help="Force la regeneration d'un message existant")
    rg.add_argument("message_id")
    rg.add_argument("--no-llm", action="store_true")
    _add_data_dir(rg)
    rg.set_defaults(func=cmd_regenerate)

    # stats
    st = sub.add_parser("stats", help="Statistiques des messages outreach")
    _add_data_dir(st)
    st.set_defaults(func=cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
