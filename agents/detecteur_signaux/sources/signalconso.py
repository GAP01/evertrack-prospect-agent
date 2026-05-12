"""
Source SignalConso (DGCCRF) — détecteur d'anomalies de volume.

CONTEXTE — pivot du modèle initial
----------------------------------
Le dataset open data publié par la DGCCRF sur data.economie.gouv.fr ne
contient pas de texte libre, ni de marque, ni de SIRET. Champs disponibles
(cf. discover_schema 2026-04-27) :
    id, category[], subcategories[], creationdate, tags[], dep_code,
    dep_name, reg_code, reg_name, signalement_transmis (int 0/1),
    signalement_lu (int 0/1), signalement_reponse (int 0/1),
    contactagreement, status, forwardtoreponseconso

Le modèle initial (1 signalement → 1 SignalSource avec marque extraite)
est donc impossible. À la place, ce collector détecte les **anomalies de
volume** par couple (category, dep_code) sur la dernière semaine ISO,
comparé à une baseline 12 semaines.

MODÈLE
------
1. Une seule requête ODS agrégée (group_by) ramène les comptages
   hebdomadaires par (category, dep_code).
2. Pour chaque couple, on compare le count de la fenêtre courante au
   z-score modifié d'Iglewicz-Hoaglin (médiane + MAD) calculé sur les
   12 semaines précédentes.
3. z_mod >= 3.5 ET median(baseline) >= 5 → on émet un SignalSource avec
   source_type="signalconso_volume".

Le SignalSource produit est marqué pour bypass de l'extracteur LLM (pas
de texte) et utilise un scoring spécifique côté detecteur.run_detect()
basé sur z_mod plutôt que sur le scoring standard (cf. cadrage v2 §6).

ENDPOINT
--------
    https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/signalconso/records

Sans authentification, rate limit ODS public (~5 req/s).
"""

from __future__ import annotations

import json
import logging
import statistics
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Iterator, Optional

import requests

from ..models import SignalSource
from .config import SourceConfig
from .registry import register

logger = logging.getLogger(__name__)


# --- Configuration --------------------------------------------------------

ODS_BASE_URL = "https://data.economie.gouv.fr/api/explore/v2.1"
DATASET_ID = "signalconso"

USER_AGENT = "EverTrackDetecteurSignaux/0.1 (signalconso volume detector)"
REQUEST_TIMEOUT = 30
ODS_PAGE_LIMIT = 100

# Champs réels du dataset (cf. discover_schema 2026-04-27)
FIELD_DATE = "creationdate"        # type=date
FIELD_CATEGORY = "category"        # type=text, contient un array
FIELD_SUBCATS = "subcategories"    # type=text, array
FIELD_TAGS = "tags"                # type=text, array
FIELD_DEP_CODE = "dep_code"
FIELD_DEP_NAME = "dep_name"

# Catégories réelles du dataset (validées 2026-04-27 via group_by).
# Choix scope EverTrack : intoxication + restauration + retraits-rappels +
# alim/hygiène. Pas d'équivalent cosmétique pur dans le dataset open data.
# Volume cumulé : ~87k records sur l'historique total — viable pour
# baseline 12 semaines.
DEFAULT_CATEGORIES = (
    "IntoxicationAlimentaire",          # 15029 records
    "CafeRestaurant",                   # 71334 records
    "RetraitRappelSpecifique",          # 44 records (CamelCase)
    "Retrait-Rappel Spécifique",        # 11 records (variante avec espaces)
    "Nourriture et boissons",           # 401 records
    "Produit alimentaire",              # 16 records
    "Hygiène des locaux",               # 22 records
    "Pratique d'hygiène",               # 406 records
)

# --- Détection d'anomalie -------------------------------------------------

# Fenêtre courante : N dernières semaines à analyser
CURRENT_WINDOW_WEEKS = 1
# Baseline : N semaines précédentes pour la stat de référence
BASELINE_WINDOW_WEEKS = 12
# Garde-fou : on n'émet pas de signal si la médiane baseline est trop basse
MIN_BASELINE_MEDIAN = 5
# Seuil d'anomalie z-score modifié (Iglewicz-Hoaglin)
Z_MOD_THRESHOLD = 3.5
# Constante z-score modifié (cf. doc statistique standard)
IGLEWICZ_HOAGLIN_K = 0.6745


# --- Helpers temporels ----------------------------------------------------

def _iso_week_start(d: date) -> date:
    """Retourne le lundi de la semaine ISO contenant `d`."""
    return d - timedelta(days=d.weekday())


def _iso_week_label(d: date) -> str:
    """Retourne 'YYYY-WNN' (semaine ISO du lundi de la semaine de `d`)."""
    iso = d.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


# --- Fetch ODS agrégé -----------------------------------------------------

def _build_aggregate_url(
    categories: Iterable[str],
    since: date,
) -> str:
    """
    Construit l'URL ODS pour un fetch agrégé par (category, dep_code, semaine).

    Utilise le pattern OpenDataSoft v2.1 :
        select = category, dep_code, dep_name, count(*) as n
        group_by = category, dep_code, dep_name, date_format(creationdate, 'YYYY-WW')

    Limite haute : on a 13 semaines × ~100 dept × ~3 catégories = ~3900
    lignes max théoriquement, ODS_PAGE_LIMIT=100 nous oblige à paginer.
    """
    cat_list = list(categories)
    if cat_list:
        cat_clause = " OR ".join(f'{FIELD_CATEGORY}="{c}"' for c in cat_list)
        where = f"({cat_clause}) AND {FIELD_DATE}>='{since.isoformat()}'"
    else:
        where = f"{FIELD_DATE}>='{since.isoformat()}'"

    # Bucketing quotidien côté ODS — date_format() n'accepte pas le format
    # 'YYYY-WW' selon ODSQL ("Invalid date format" 400). On groupe par jour
    # et on bucket en semaines ISO côté Python dans detect_anomalies.
    select = (
        f"{FIELD_CATEGORY},{FIELD_DEP_CODE},{FIELD_DEP_NAME},"
        f"count(*) as n,"
        f"{FIELD_DATE} as day"
    )
    group_by = (
        f"{FIELD_CATEGORY},{FIELD_DEP_CODE},{FIELD_DEP_NAME},"
        f"{FIELD_DATE}"
    )

    params = {
        "select": select,
        "where": where,
        "group_by": group_by,
        "limit": str(ODS_PAGE_LIMIT),
        "offset": "0",
    }
    return f"{ODS_BASE_URL}/catalog/datasets/{DATASET_ID}/records?" + urllib.parse.urlencode(params)


def _fetch_aggregated(
    categories: Iterable[str],
    since: date,
    session: Optional[requests.Session] = None,
) -> list[dict[str, Any]]:
    """
    Récupère tous les comptages agrégés depuis ODS, en paginant.

    Retourne une liste de dicts : {category, dep_code, dep_name, iso_week, n}.
    """
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT})

    base_url = _build_aggregate_url(categories, since)
    url = base_url
    all_rows: list[dict[str, Any]] = []
    offset = 0
    safety_max_pages = 500

    for _ in range(safety_max_pages):
        # Patch offset dans l'URL
        if "offset=" in url:
            parts = url.split("offset=", 1)
            tail = parts[1].split("&", 1)
            tail[0] = str(offset)
            url = parts[0] + "offset=" + "&".join(tail)

        logger.info("SignalConso aggregate fetch offset=%d", offset)
        try:
            resp = sess.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            body = ""
            try:
                body = exc.response.text[:500] if exc.response is not None else ""
            except Exception:
                pass
            logger.warning(
                "SignalConso aggregate failed (offset=%d): %s | body=%s",
                offset, exc, body,
            )
            return all_rows
        except requests.RequestException as exc:
            logger.warning("SignalConso aggregate failed (offset=%d): %s", offset, exc)
            return all_rows

        try:
            payload = resp.json()
        except ValueError as exc:
            logger.warning("SignalConso aggregate JSON invalide: %s", exc)
            return all_rows

        records = payload.get("results") or payload.get("records") or []
        if not records:
            break

        for rec in records:
            fields = rec.get("fields") if isinstance(rec, dict) and "fields" in rec else rec
            if not isinstance(fields, dict):
                continue
            all_rows.append(fields)

        if len(records) < ODS_PAGE_LIMIT:
            break
        offset += ODS_PAGE_LIMIT

    logger.info("SignalConso : %d lignes agrégées récupérées", len(all_rows))
    return all_rows


# --- Statistique anomalie -------------------------------------------------

def _mad(values: list[float]) -> float:
    """Median Absolute Deviation."""
    if not values:
        return 0.0
    med = statistics.median(values)
    return statistics.median(abs(v - med) for v in values)


def _z_mod(count: float, baseline: list[float]) -> Optional[float]:
    """
    Z-score modifié d'Iglewicz-Hoaglin.

        z_mod = 0.6745 * (x - median) / MAD

    Retourne None si MAD=0 (baseline complètement plate) ou baseline vide.
    """
    if not baseline:
        return None
    med = statistics.median(baseline)
    mad = _mad(baseline)
    if mad == 0:
        # MAD nul : si count > median, on peut quand même flag avec une
        # valeur élevée arbitraire ; sinon pas d'anomalie.
        return 99.0 if count > med else 0.0
    return IGLEWICZ_HOAGLIN_K * (count - med) / mad


def _normalize_category(value: Any) -> str:
    """Le champ category est un array — on prend la 1re valeur."""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


# --- Construction du SignalSource ----------------------------------------

def _make_volume_signal(
    category: str,
    dep_code: str,
    dep_name: str,
    iso_week: str,
    count_actuel: int,
    baseline: list[float],
    z_mod_value: float,
) -> SignalSource:
    """Construit le SignalSource pour un pic détecté."""
    baseline_median = statistics.median(baseline) if baseline else 0
    baseline_mad = _mad(baseline)

    # Date de detected_at = lundi de la semaine ISO
    # Format iso_week = "YYYY-WW" (sortie ODS date_format)
    try:
        year_str, week_str = iso_week.split("-W") if "-W" in iso_week else iso_week.split("-")
        year_int = int(year_str)
        week_int = int(week_str.lstrip("W"))
        # Lundi semaine ISO 1 : utiliser fromisocalendar (Python 3.8+)
        detected_at_dt = datetime.fromisocalendar(year_int, week_int, 1)
    except (ValueError, AttributeError):
        detected_at_dt = datetime.utcnow()

    titre = (
        f"Pic signalements {category} en {dep_name or dep_code} "
        f"({count_actuel} actuels, baseline ~{int(baseline_median)})"
    )

    payload = {
        "category": category,
        "dep_code": dep_code,
        "dep_name": dep_name,
        "iso_week": iso_week,
        "count_actuel": int(count_actuel),
        "baseline_median": float(baseline_median),
        "baseline_mad": float(baseline_mad),
        "baseline_n_samples": len(baseline),
        "z_mod": round(z_mod_value, 3),
        "z_mod_threshold": Z_MOD_THRESHOLD,
        "method": "iglewicz_hoaglin",
    }
    contenu = json.dumps(payload, ensure_ascii=False)

    src_url = f"signalconso://stats/{category}/{dep_code}/{iso_week}"
    forced_id = f"scvol_{category}_{dep_code}_{iso_week}".replace(" ", "_")[:64]

    return SignalSource(
        source_type="signalconso_volume",
        source_name=f"SignalConso/{category}/{dep_name or dep_code}",
        source_url=src_url,
        titre=titre[:300],
        detected_at=detected_at_dt,
        contenu=contenu[:2000],
        forced_signal_id=forced_id,
    )


# --- Orchestration --------------------------------------------------------

def detect_anomalies(
    rows: list[dict[str, Any]],
    current_week: str,
    z_threshold: float = Z_MOD_THRESHOLD,
    min_baseline_median: int = MIN_BASELINE_MEDIAN,
) -> Iterator[SignalSource]:
    """
    Étant donné un set de lignes agrégées (cat, dept, semaine, n), émet un
    SignalSource pour chaque (cat, dept) dont le count de `current_week`
    dépasse le seuil d'anomalie vs la baseline historique.
    """
    # Group by (category, dep_code) → {iso_week: count}.
    # Les rows entrants sont quotidiens (un par jour), on les bucket en
    # semaine ISO ici puis on somme les counts par semaine.
    by_pair: dict[tuple[str, str, str], dict[str, int]] = {}

    for row in rows:
        cat = _normalize_category(row.get(FIELD_CATEGORY))
        dep_code = str(row.get(FIELD_DEP_CODE) or "")
        dep_name = str(row.get(FIELD_DEP_NAME) or dep_code)
        n = int(row.get("n") or 0)

        # Récupère le jour (formats possibles : "day", FIELD_DATE, ou "iso_week"
        # pour compatibilité avec d'anciens tests).
        day_raw = row.get("day") or row.get(FIELD_DATE) or row.get("iso_week") or ""
        iso_week = ""
        if day_raw:
            day_str = str(day_raw)[:10]
            # Si c'est déjà au format YYYY-WNN ou YYYY-WW (rétrocompat tests),
            # on prend tel quel. Sinon on parse comme date et on convertit.
            if "W" in day_str or (len(day_str) == 7 and day_str[4] == "-"):
                iso_week = day_str
            else:
                try:
                    d = date.fromisoformat(day_str)
                    iso_week = _iso_week_label(d)
                except ValueError:
                    continue

        if not cat or not dep_code or not iso_week:
            continue

        key = (cat, dep_code, dep_name)
        bucket = by_pair.setdefault(key, {})
        bucket[iso_week] = bucket.get(iso_week, 0) + n

    logger.info(
        "SignalConso detect_anomalies : %d couples (cat,dept) à analyser pour semaine %s",
        len(by_pair), current_week,
    )
    n_no_actual = n_short_history = n_low_baseline = n_below_threshold = n_emitted = 0

    for (cat, dep_code, dep_name), week_counts in by_pair.items():
        actual = week_counts.get(current_week, 0)
        if actual == 0:
            n_no_actual += 1
            continue

        baseline_counts = [
            float(c) for w, c in week_counts.items() if w != current_week
        ]
        if len(baseline_counts) < 3:
            n_short_history += 1
            continue

        med = statistics.median(baseline_counts)
        if med < min_baseline_median:
            n_low_baseline += 1
            continue

        z = _z_mod(actual, baseline_counts)
        if z is None or z < z_threshold:
            n_below_threshold += 1
            continue

        n_emitted += 1
        logger.info(
            "SignalConso ANOMALIE : %s/%s %s (count=%d, baseline_med=%.1f, z=%.2f)",
            cat, dep_code, current_week, actual, med, z,
        )
        yield _make_volume_signal(
            category=cat,
            dep_code=dep_code,
            dep_name=dep_name,
            iso_week=current_week,
            count_actuel=actual,
            baseline=baseline_counts,
            z_mod_value=z,
        )


    logger.info(
        "SignalConso detect_anomalies done : emitted=%d, "
        "skip_no_actual=%d, skip_short_history=%d, "
        "skip_low_baseline=%d, skip_below_threshold=%d",
        n_emitted, n_no_actual, n_short_history, n_low_baseline, n_below_threshold,
    )


@register("signalconso_volume")
def collect(cfg: SourceConfig) -> Iterator[SignalSource]:
    """
    Adaptateur registry. Lance un cycle de détection d'anomalies de volume.

    Stratégie :
    1. Fetch agrégé sur les (BASELINE_WINDOW_WEEKS + CURRENT_WINDOW_WEEKS)
       dernières semaines.
    2. Détecte les anomalies sur la semaine ISO courante.
    """
    categories = cfg.signalconso_categories or list(DEFAULT_CATEGORIES)

    today = date.today()
    current_monday = _iso_week_start(today)

    # On vise la **dernière semaine ISO complète** (N-1), pas la semaine en cours.
    # Raison : latence de publication SignalConso (J+3 à J+7 typiquement) — la
    # semaine N a généralement encore 0 ligne au moment où on fetch, ce qui ferait
    # skip toutes les anomalies en "no_actual".
    analysis_monday = current_monday - timedelta(weeks=1)
    current_week = _iso_week_label(analysis_monday)

    # Baseline = 12 semaines AVANT la fenêtre d'analyse (donc N-13 à N-2).
    since = analysis_monday - timedelta(weeks=BASELINE_WINDOW_WEEKS)

    rows = _fetch_aggregated(categories=categories, since=since)
    logger.info(
        "SignalConso collect : %d rows agrégées reçues, semaine analysée=%s "
        "(semaine ISO précédente, complète), categories=%s",
        len(rows), current_week, categories,
    )
    if not rows:
        logger.warning(
            "SignalConso: 0 rows ramenées. Catégories filtrées (%s) probablement"
            " absentes du dataset. Lance `python -m detecteur_signaux.sources.signalconso`"
            " pour voir les vraies catégories via group_by.",
            categories,
        )
        return

    # Diagnostic : list des semaines couvertes par les rows ramenées
    weeks_seen: set[str] = set()
    for row in rows:
        day_raw = row.get("day") or row.get(FIELD_DATE) or ""
        if day_raw:
            try:
                d = date.fromisoformat(str(day_raw)[:10])
                weeks_seen.add(_iso_week_label(d))
            except ValueError:
                continue
    sorted_weeks = sorted(weeks_seen)
    if sorted_weeks:
        logger.info(
            "SignalConso semaines présentes dans les rows : %d distinctes "
            "(de %s à %s). Cible analyse : %s — %s.",
            len(sorted_weeks),
            sorted_weeks[0],
            sorted_weeks[-1],
            current_week,
            "OK, présente" if current_week in weeks_seen else "ABSENTE — skip total attendu",
        )

    yield from detect_anomalies(
        rows=rows,
        current_week=current_week,
        z_threshold=Z_MOD_THRESHOLD,
        min_baseline_median=MIN_BASELINE_MEDIAN,
    )


# --- Discovery (lancée à la main pour debug) -----------------------------

def discover_schema(session: Optional[requests.Session] = None) -> dict[str, Any]:
    """
    Helper de debug. Cascade :
      1. metadata du dataset
      2. 1 record sans WHERE
      3. group_by sur category pour récupérer les valeurs réelles
         (le facet ODS a retourné [] précédemment, group_by est plus fiable)

    Usage :
        python -m detecteur_signaux.sources.signalconso
    """
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT})

    out: dict[str, Any] = {"endpoint": ODS_BASE_URL, "dataset_id": DATASET_ID}

    # Étape 1
    try:
        r = sess.get(f"{ODS_BASE_URL}/catalog/datasets/{DATASET_ID}", timeout=REQUEST_TIMEOUT)
        out["meta_status"] = r.status_code
        if r.status_code == 200:
            meta = r.json()
            out["fields_from_meta"] = [
                {"name": f.get("name"), "type": f.get("type"), "label": f.get("label")}
                for f in (meta.get("fields") or [])
            ]
        else:
            out["meta_error_body"] = r.text[:1000]
    except Exception as exc:
        out["meta_error"] = str(exc)

    # Étape 2
    try:
        r = sess.get(
            f"{ODS_BASE_URL}/catalog/datasets/{DATASET_ID}/records?limit=1",
            timeout=REQUEST_TIMEOUT,
        )
        out["sample_status"] = r.status_code
        if r.status_code == 200:
            data = r.json()
            results = data.get("results") or []
            out["total_count"] = data.get("total_count")
            if results:
                first = results[0]
                fields = first.get("fields") if isinstance(first, dict) and "fields" in first else first
                out["sample_keys"] = sorted(fields.keys()) if isinstance(fields, dict) else None
                out["sample_record"] = fields
        else:
            out["sample_error_body"] = r.text[:1000]
    except Exception as exc:
        out["sample_error"] = str(exc)

    # Étape 3 : group_by sur category — solution alternative au facet vide
    try:
        params = {
            "select": f"{FIELD_CATEGORY}, count(*) as n",
            "group_by": FIELD_CATEGORY,
            "limit": "100",
        }
        url = f"{ODS_BASE_URL}/catalog/datasets/{DATASET_ID}/records?" + urllib.parse.urlencode(params)
        r = sess.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            cats = []
            for rec in data.get("results") or []:
                fields = rec.get("fields") if isinstance(rec, dict) and "fields" in rec else rec
                if isinstance(fields, dict):
                    cats.append({
                        "category": fields.get(FIELD_CATEGORY),
                        "n": fields.get("n"),
                    })
            out["categories_via_groupby"] = cats
        else:
            out["categories_groupby_error"] = {
                "status": r.status_code,
                "body": r.text[:500],
            }
    except Exception as exc:
        out["categories_groupby_exception"] = str(exc)

    return out


def main() -> None:
    """Run discover_schema et imprime le résultat. Lancé via:
        python -m detecteur_signaux.sources.signalconso
    """
    import logging as _logging
    _logging.basicConfig(level=_logging.WARNING)
    result = discover_schema()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
