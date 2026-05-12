"""
Cache local de la base DGAL des établissements agréés CE 853/2004.

Source officielle :
    https://agriculture.gouv.fr/tous-les-etablissements-agrees-...
    Mise à jour quotidienne, ~18 fichiers TXT (CSV) par section d'activité.

Format CSV (séparateur virgule, valeurs entre guillemets, encoding UTF-8) :
    "Numero de département","Numéro agrément","SIRET","Raison sociale",
    "Adresse","Code postal","Commune","Catégorie","Activités","Espèce"

USAGE
-----
    python -m enrichisseur_prospects.agrements_dgal refresh
    python -m enrichisseur_prospects.agrements_dgal lookup 69.068.013
    python -m enrichisseur_prospects.agrements_dgal stats

Programmatique :
    from enrichisseur_prospects.agrements_dgal import lookup
    lookup("FR 69.068.013.CE")  # → {siret, raison_sociale, adresse, ...}
"""

from __future__ import annotations

import csv
import io
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import requests

logger = logging.getLogger(__name__)


# --- Configuration -------------------------------------------------------

BASE_URL = "https://fichiers-publics.agriculture.gouv.fr/dgal/ListesOfficielles"

# Slug de fichier → libellé Section (pour traçabilité)
SECTIONS: dict[str, str] = {
    "SSA1_ACTIV_GEN":           "Section 0 — Activités générales",
    "SSA1_VIAN_ONG_DOM":        "Section I — Viandes ongulés domestiques",
    "SSA1_VIAN_COL_LAGO":       "Section II — Volailles et lagomorphes",
    "SSA1_VIAN_GIB_ELEV":       "Section III — Gibier d'élevage",
    "SSA1_VIAN_GIB_SAUV":       "Section IV — Gibier sauvage",
    "SSA1_VIAND_HACHE_VSM":     "Section V — Viandes hachées et VSM",
    "SSA4_AGSANPROBASEVDE_PRV": "Section VI — Produits à base de viande",
    "SSA4B_AS_CE_PRODCOQUI_COV":"Section VII — Mollusques bivalves",
    "SSA4B_AS_CE_PRODPECHE_COV":"Section VIII — Produits de la pêche",
    "SSA1_LAIT":                "Section IX — Lait et produits laitiers",
    "SSA1_OEUF":                "Section X — Œufs et ovoproduits",
    "SSA1_GREN_ESCARG":         "Section XI — Cuisses de grenouille et escargots",
    "SSA4_AGSANGREXPR_PRV":     "Section XII — Graisses animales fondues",
    "SSA4_AGR_ESVEBO_PRV":      "Section XIII — Estomacs, vessies, boyaux",
    "SSA4_AGSANGELAT_PRV":      "Section XIV — Gélatine",
    "SSA4_AGSANCOLL_PRV":       "Section XV — Collagène",
    "SSA_PROD_RAFF":            "Section XVI — Produits hautement raffinés",
    "SSA4_ASCCC_PRV":           "Section — Cuisines centrales",
}

USER_AGENT = "EverTrackEnrichisseur/0.1 (DGAL agrements collector)"
REQUEST_TIMEOUT = 30

# Pattern de numéro d'agrément accepté en entrée :
#   "FR 69.068.013.CE", "FR69.068.013CE", "69-068-013", "69.068.013", etc.
_AGREMENT_RE = re.compile(r"(\d{2})[\s\.\-]?(\d{3})[\s\.\-]?(\d{3})")


# --- SQLite local --------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agrements_dgal (
    numero          TEXT PRIMARY KEY,
    departement     TEXT,
    siret           TEXT,
    raison_sociale  TEXT,
    adresse         TEXT,
    code_postal     TEXT,
    commune         TEXT,
    categorie       TEXT,
    activites       TEXT,
    espece          TEXT,
    section         TEXT,
    last_seen_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_agrements_siret ON agrements_dgal (siret);
CREATE INDEX IF NOT EXISTS idx_agrements_departement ON agrements_dgal (departement);
"""


def _default_db_path() -> Path:
    return Path("data/agrements_dgal.sqlite")


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    db = Path(db_path) if db_path else _default_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


# --- Normalisation -------------------------------------------------------

def parse_agrement(value: str) -> Optional[str]:
    """
    Extrait la clé canonique "DD.III.EEE" depuis n'importe quel format d'entrée.

    Exemples acceptés :
        "FR 69.068.013.CE"   → "69.068.013"
        "FR69.068.013CE"     → "69.068.013"
        "69-068-013"         → "69.068.013"
        "  fr 69 068 013 ce" → "69.068.013"
    """
    if not value:
        return None
    m = _AGREMENT_RE.search(value)
    if not m:
        return None
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"


def format_agrement_display(numero: str) -> str:
    """Retourne le format affichable 'FR DD.III.EEE.CE'."""
    n = parse_agrement(numero) or numero
    return f"FR {n}.CE"


# --- Téléchargement et parsing ------------------------------------------

def _fetch_section(slug: str, session: Optional[requests.Session] = None) -> bytes:
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT})
    url = f"{BASE_URL}/{slug}.txt"
    logger.info("DGAL fetch : %s", slug)
    resp = sess.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def _iter_section_rows(blob: bytes, section_label: str) -> Iterable[dict]:
    """Parse un blob CSV DGAL et yield des dicts normalisés."""
    text = blob.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    headers = None
    for row in reader:
        if not row:
            continue
        if headers is None:
            headers = [h.strip() for h in row]
            continue
        # Tolérant aux variations : nb colonnes parfois moindre quand pas d'activité
        cells = list(row) + [""] * (len(headers) - len(row))
        rec = dict(zip(headers, cells))
        # Normalisation d'accès aux colonnes (libellés FR variant légèrement)
        def get(*names):
            for n in names:
                for k in rec:
                    if n.lower() in k.lower():
                        return rec[k].strip()
            return ""
        numero_brut = get("Numéro agrément", "Numero agrement")
        numero = parse_agrement(numero_brut)
        if not numero:
            continue
        yield {
            "numero": numero,
            "departement": get("Numero de département", "departement").strip().lstrip("0").zfill(2)
                            if get("Numero de département", "departement") else "",
            "siret": get("SIRET").strip(),
            "raison_sociale": get("Raison SOCIALE", "Raison sociale", "Name"),
            "adresse": get("Adresse", "Adress"),
            "code_postal": get("Code postal", "Postal code"),
            "commune": get("Commune", "Town"),
            "categorie": get("Catégorie", "Category"),
            "activites": get("Activités", "activites associees", "Associated activities"),
            "espece": get("Espèce", "Specy"),
            "section": section_label,
        }


def refresh_all(
    db_path: Optional[Path] = None,
    sections: Optional[Iterable[str]] = None,
) -> dict:
    """
    Télécharge toutes les sections (ou un sous-ensemble) et upsert en base.

    Retourne un rapport : sections_ok, sections_ko, total_rows.
    """
    slugs = list(sections) if sections else list(SECTIONS.keys())
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    conn = _connect(db_path)
    total_rows = 0
    sections_ok: list[str] = []
    sections_ko: list[tuple[str, str]] = []

    for slug in slugs:
        label = SECTIONS.get(slug, slug)
        try:
            blob = _fetch_section(slug, session=session)
        except requests.RequestException as exc:
            logger.warning("Section %s KO : %s", slug, exc)
            sections_ko.append((slug, str(exc)))
            continue

        n_section = 0
        for rec in _iter_section_rows(blob, label):
            conn.execute(
                """
                INSERT INTO agrements_dgal
                    (numero, departement, siret, raison_sociale, adresse,
                     code_postal, commune, categorie, activites, espece, section, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(numero) DO UPDATE SET
                    departement=excluded.departement,
                    siret=excluded.siret,
                    raison_sociale=excluded.raison_sociale,
                    adresse=excluded.adresse,
                    code_postal=excluded.code_postal,
                    commune=excluded.commune,
                    categorie=excluded.categorie,
                    activites=excluded.activites,
                    espece=excluded.espece,
                    section=excluded.section,
                    last_seen_at=datetime('now')
                """,
                (
                    rec["numero"], rec["departement"], rec["siret"],
                    rec["raison_sociale"], rec["adresse"], rec["code_postal"],
                    rec["commune"], rec["categorie"], rec["activites"],
                    rec["espece"], rec["section"],
                ),
            )
            n_section += 1
        conn.commit()
        sections_ok.append(slug)
        total_rows += n_section
        logger.info("Section %s : %d lignes upsert", slug, n_section)

    total_in_db = conn.execute("SELECT COUNT(*) FROM agrements_dgal").fetchone()[0]
    conn.close()
    return {
        "sections_requested": len(slugs),
        "sections_ok": sections_ok,
        "sections_ko": sections_ko,
        "total_rows_processed": total_rows,
        "total_rows_in_db": total_in_db,
        "completed_at": datetime.utcnow().isoformat(),
    }


# --- Lookup --------------------------------------------------------------

def lookup(value: str, db_path: Optional[Path] = None) -> Optional[dict]:
    """
    Lookup direct par numéro d'agrément. Accepte tous les formats
    (cf. parse_agrement). Retourne None si introuvable.
    """
    numero = parse_agrement(value)
    if not numero:
        return None
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT * FROM agrements_dgal WHERE numero = ?", (numero,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def stats(db_path: Optional[Path] = None) -> dict:
    """Statistiques sur la base locale."""
    conn = _connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM agrements_dgal").fetchone()[0]
    by_section = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT section, COUNT(*) FROM agrements_dgal GROUP BY section"
        ).fetchall()
    }
    last_seen = conn.execute(
        "SELECT MAX(last_seen_at) FROM agrements_dgal"
    ).fetchone()[0]
    conn.close()
    return {
        "total": total,
        "by_section": by_section,
        "last_refresh_at": last_seen,
    }


# --- CLI -----------------------------------------------------------------

def _cli():
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="agrements_dgal")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_refresh = sub.add_parser("refresh", help="Télécharge toutes les sections DGAL")
    p_refresh.add_argument("--db", type=Path, default=None)
    p_refresh.add_argument(
        "--sections", nargs="*", default=None,
        help="Slugs de sections à fetch (défaut : toutes)",
    )

    p_lookup = sub.add_parser("lookup", help="Lookup d'un numéro d'agrément")
    p_lookup.add_argument("numero")
    p_lookup.add_argument("--db", type=Path, default=None)

    p_stats = sub.add_parser("stats", help="Statistiques de la base locale")
    p_stats.add_argument("--db", type=Path, default=None)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "refresh":
        report = refresh_all(db_path=args.db, sections=args.sections)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.cmd == "lookup":
        result = lookup(args.numero, db_path=args.db)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.cmd == "stats":
        print(json.dumps(stats(db_path=args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
