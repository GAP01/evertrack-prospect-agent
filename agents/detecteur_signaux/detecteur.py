"""
Orchestrateur principal du détecteur de signaux faibles.

Pipeline :
    1. Fetch Google News + Reddit → `SignalSource[]`
    2. Pour chaque source :
        a. Extract (LLM ou regex) → marque + produit + symptôme + is_alim
        b. Skip si is_alim = False (faux positif)
        c. Compute signal_id (dedup)
        d. Attach source au signal (insert ou idempotent)
    3. Pour chaque signal touché (nouveau ou mis à jour) :
        a. Recompute score avec n_sources à jour
        b. Upsert signal avec status = a_valider si score >= seuil
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from dotenv import load_dotenv

from .deduplicator import compute_signal_id
from .extractor import Extraction, extract
from .merger import merge_duplicates
from .models import (
    DETECTOR_VERSION,
    SignalAlerte,
    SignalSource,
    STATUS_FAIBLE,
)
from .rappelconso_link import find_rappelconso_url_for_source
from .scorer import compute_score, status_for_score
from .sources import SourceConfig, get_collector, list_collectors
from .storage import SignalStorage

import requests

logger = logging.getLogger(__name__)




# Buckets de source qui n'ont pas de texte exploitable et bypassent
# l'extracteur LLM + scoring standard (cf. cadrage signalconso_volumes).
VOLUME_BUCKETS = frozenset({"signalconso_volume"})


def _synthesize_volume_extraction(src: "SignalSource") -> Extraction:
    """
    Construit une Extraction synthétique pour les sources de type "volume"
    (pas de texte libre, pas de marque dispo). Le symptome est dérivé
    de la catégorie portée par src.contenu (JSON sérialisé).
    """
    category = ""
    try:
        if src.contenu:
            payload = json.loads(src.contenu)
            category = payload.get("category", "")
    except (ValueError, TypeError):
        pass

    # Mapping catégorie → label de symptôme. Conservatif : on utilise un
    # label explicite "anomalie_volume_<cat>" si pas de mapping connu.
    symptom_map = {
        "IntoxicationAlimentaire": "intoxication_alimentaire_collective",
        "CafeRestaurant": "signalement_restauration",
        "RetraitRappelSpecifique": "retrait_rappel_signale",
        "Retrait-Rappel Spécifique": "retrait_rappel_signale",
        "Nourriture et boissons": "anomalie_alimentaire_locale",
        "Produit alimentaire": "anomalie_alimentaire_locale",
        "Hygiène des locaux": "anomalie_hygiene_locaux",
        "Pratique d'hygiène": "anomalie_hygiene_pratique",
    }
    symptome = symptom_map.get(category, f"anomalie_volume_{category}" if category else "anomalie_volume")

    return Extraction(
        marque=None,
        produit=None,
        symptome=symptome,
        resume=src.titre,
        is_alim=True,  # passer le filtre is_alim ; le filtrage métier est déjà fait côté collector
        source="volume_synthetic",
    )


def _score_volume_signal(src: "SignalSource") -> tuple[int, dict[str, Any]]:
    """
    Score d'un signal volume directement depuis le z_mod (cf. cadrage §6).

        score = clip(20 + 15 * (z_mod - 3.5), 20, 100)

    Retourne (score, breakdown).
    """
    z = 0.0
    payload: dict[str, Any] = {}
    try:
        if src.contenu:
            payload = json.loads(src.contenu)
            z = float(payload.get("z_mod", 0.0))
    except (ValueError, TypeError):
        pass

    raw = 20 + 15 * (z - 3.5)
    score = max(20, min(100, int(raw)))
    breakdown = {
        "method": "volume_anomaly",
        "z_mod": z,
        "z_mod_threshold": payload.get("z_mod_threshold", 3.5),
        "baseline_median": payload.get("baseline_median"),
        "baseline_mad": payload.get("baseline_mad"),
        "count_actuel": payload.get("count_actuel"),
        "score_formula": "clip(20 + 15*(z-3.5), 20, 100)",
    }
    return score, breakdown

def _iter_sources(
    sources: list[str],
    cfg: SourceConfig,
    runs_log: Optional[dict[str, dict[str, Any]]] = None,
) -> Iterator[SignalSource]:
    """
    Itère sur toutes les sources demandées en passant par le registre.

    Une source inconnue est loggée en warning et ignorée (pas d'exception)
    pour préserver le run même si --sources contient une coquille.

    Si `runs_log` est fourni, chaque collector qui s'exécute (même partiellement
    ou avec 0 émission) ajoute une entrée :
        {name: {"started_at": dt, "ended_at": dt, "emitted": int}}
    Le `finally` garantit l'enregistrement même si l'outer for break (cap
    `max_items`) ou si le collector lève une exception. Les collectors jamais
    atteints à cause d'un break précoce ne sont pas loggés (sémantique correcte :
    "n'a pas tourné" ≠ "a tourné mais rien trouvé").
    """
    available = list_collectors()
    for name in sources:
        collector = get_collector(name)
        if collector is None:
            logger.warning(
                "Source inconnue %r ignorée. Disponibles : %s",
                name, ", ".join(available),
            )
            continue
        n_yielded = 0
        started_at = datetime.utcnow()
        try:
            for item in collector(cfg):
                n_yielded += 1
                yield item
        except Exception as exc:
            logger.exception("Collector %r a échoué : %s", name, exc)
        finally:
            if runs_log is not None:
                runs_log[name] = {
                    "started_at": started_at,
                    "ended_at": datetime.utcnow(),
                    "emitted": n_yielded,
                }


def run_detect(
    signaux_db: Path,
    incidents_db: Optional[Path] = None,
    sources: Optional[list[str]] = None,
    use_llm: bool = True,
    max_items: Optional[int] = None,
    scrape_articles: bool = True,
) -> dict[str, Any]:
    """
    Lance un cycle complet de détection.

    Retourne un rapport : sources_fetched, signaux_new, signaux_updated,
    alerts, llm_used_count, skipped.
    """
    # override=True : une var vide dans l'env shell doit être remplacée par
    # celle du .env (utile sur Windows où des tools posent des vars vides).
    load_dotenv(override=True)

    sources = sources or ["google_news", "reddit"]
    storage = SignalStorage(signaux_db)

    # Config commune passée à chaque collector. None partout = chaque
    # source utilise ses defaults (GOOGLE_NEWS_QUERIES, REDDIT_SUBREDDITS, ...).
    cfg = SourceConfig(max_items=max_items)

    report: dict[str, Any] = {
        "detector_version": DETECTOR_VERSION,
        "started_at": datetime.utcnow().isoformat(),
        "sources_fetched": 0,
        "signaux_new": 0,
        "signaux_updated": 0,
        "alerts": 0,
        "llm_used_count": 0,
        "skipped_not_alim": 0,
        "skipped_no_symptom": 0,
        "rappelconso_urls_found": 0,
    }

    # Session HTTP partagée pour le scrapping (connection reuse)
    scrape_session = requests.Session() if scrape_articles else None

    # Index (signal_id -> first-seen SignalSource) pour scoring à la fin
    touched: dict[str, dict[str, Any]] = {}

    # Trace par collector pour la table source_runs (rempli via finally
    # dans _iter_sources, donc cohérent même si max_items break la boucle).
    runs_log: dict[str, dict[str, Any]] = {}

    for idx, src in enumerate(_iter_sources(sources=sources, cfg=cfg, runs_log=runs_log)):
        if max_items is not None and idx >= max_items:
            logger.info("max_items=%d atteint, arrêt fetch", max_items)
            break

        report["sources_fetched"] += 1

        # Extract marque/produit/symptôme.
        # Bypass pour les sources de type "volume" : pas de texte exploitable,
        # on synthétise depuis la donnée structurée (catégorie → symptôme).
        if src.source_type in VOLUME_BUCKETS:
            extracted = _synthesize_volume_extraction(src)
        else:
            try:
                extracted = extract(
                    titre=src.titre,
                    contenu=src.contenu or "",
                    source_name=src.source_name,
                    use_llm=use_llm,
                )
            except Exception as exc:
                logger.exception("Extraction échouée pour %r : %s", src.titre[:50], exc)
                continue

        if extracted.source == "llm":
            report["llm_used_count"] += 1

        if not extracted.is_alim:
            report["skipped_not_alim"] += 1
            continue

        # On exige au moins un symptôme détecté (filtre silence)
        if not extracted.symptome:
            report["skipped_no_symptom"] += 1
            continue

        # Dedup. Si le collector a imposé un signal_id (ex: signalconso_volume
        # qui inclut dep_code), on le respecte ; sinon on calcule normalement.
        if src.forced_signal_id:
            signal_id = src.forced_signal_id
        else:
            signal_id = compute_signal_id(
                marque=extracted.marque,
                symptome=extracted.symptome,
                titre=src.titre,
                detected_at=src.detected_at,
                produit=extracted.produit,
            )

        # Cherche un lien direct vers une fiche RappelConso dans l'article.
        # Niveau 1 : dans le snippet RSS. Niveau 2 : dans le HTML de l'article.
        rc_url = None
        try:
            rc_url = find_rappelconso_url_for_source(
                content_rss=src.contenu or "",
                source_url=src.source_url,
                scrape=scrape_articles,
                session=scrape_session,
            )
        except Exception as exc:
            logger.debug("find_rappelconso_url KO : %s", exc)
        if rc_url:
            report["rappelconso_urls_found"] += 1
            logger.info("RappelConso URL found for %s: %s", src.source_url[:60], rc_url)

        # Attach source (idempotent sur signal_id + url)
        is_new_source = storage.attach_source(signal_id, src, rappelconso_url=rc_url)

        # On agrège les infos de la 1re source rencontrée dans ce run
        if signal_id not in touched:
            touched[signal_id] = {
                "src": src,
                "extracted": extracted,
            }
        if is_new_source:
            # Update last_seen pour les signaux existants
            existing = storage.get(signal_id)
            if existing is not None:
                storage.update_last_seen(signal_id, datetime.utcnow())

    # Phase 2 : scoring final
    for signal_id, info in touched.items():
        src: SignalSource = info["src"]
        ext = info["extracted"]

        n_sources = storage.count_sources(signal_id)

        # detected_at du signal = date de publication de l'article le plus ancien
        # qui en parle (pas le moment où on l'a détecté). Reflète le "quand ça
        # a commencé à paraître dans la presse/social".
        pub_date = storage.earliest_source_date(signal_id) or src.detected_at

        if src.source_type in VOLUME_BUCKETS:
            # Scoring custom : dérivé du z_mod stocké dans src.contenu.
            score, breakdown = _score_volume_signal(src)
        else:
            score, breakdown = compute_score(
                source_name=src.source_name,
                n_sources=n_sources,
                detected_at=pub_date,
                marque=ext.marque,
                titre=src.titre,
                contenu=src.contenu or "",
                incidents_db=incidents_db,
            )
        status = status_for_score(score)

        existing = storage.get(signal_id)
        is_new = existing is None

        # Préserve le statut si l'humain a déjà traité (valide/rejete/promu)
        if existing is not None:
            prev_status = existing.get("status") or STATUS_FAIBLE
            if prev_status in ("valide", "rejete", "promu"):
                status = prev_status

        signal = SignalAlerte(
            signal_id=signal_id,
            detector_version=DETECTOR_VERSION,
            marque=ext.marque,
            produit=ext.produit,
            symptome=ext.symptome,
            titre=src.titre,
            resume=ext.resume,
            source_type=src.source_type,
            source_name=src.source_name,
            source_url=src.source_url,
            score=score,
            score_breakdown=breakdown,
            status=status,
            # detected_at = date de publication la plus ancienne parmi les
            # sources (≠ last_seen_at qui est la dernière passe du crawler).
            detected_at=pub_date,
            last_seen_at=datetime.utcnow(),
            raw_json=json.dumps(src.to_dict(), ensure_ascii=False),
        )

        # Preserve promotion refs si signal déjà connu
        if existing is not None:
            signal.promu_vers_source = existing.get("promu_vers_source")
            signal.promu_vers_source_id = existing.get("promu_vers_source_id")

        storage.upsert_signal(signal)

        if is_new:
            report["signaux_new"] += 1
        else:
            report["signaux_updated"] += 1

        if status == "a_valider":
            report["alerts"] += 1

    # Phase 2bis : enregistre le dernier run de chaque collector qui a tourné.
    # Permet au dashboard d'afficher "Dernier scan" basé sur la dernière
    # exécution réelle (et pas seulement sur la date d'apparition d'un signal).
    try:
        for src_name, info in runs_log.items():
            storage.record_source_run(
                source_type=src_name,
                last_emitted=int(info.get("emitted", 0)),
                started_at=info.get("started_at"),
                ended_at=info.get("ended_at"),
            )
        report["source_runs"] = {
            name: {"emitted": info["emitted"]}
            for name, info in runs_log.items()
        }
    except Exception as exc:
        logger.exception("Enregistrement source_runs échoué : %s", exc)

    # Phase 3 : fusion des signaux redondants (même URL RappelConso ou
    # même clé de dédup après normalisation). Suit le scraping pour bénéficier
    # des rappelconso_url découverts.
    try:
        merge_report = merge_duplicates(
            signaux_db=signaux_db,
            incidents_db=incidents_db,
            rescore=True,
        )
        report["merge"] = {
            "merged_by_url": merge_report["merge_rappelconso_url"]["signaux_merged"],
            "merged_by_key": merge_report["merge_recomputed_key"]["signaux_merged"],
            "signaux_rescored": merge_report.get("signaux_rescored", 0),
        }
    except Exception as exc:
        logger.exception("Merge de signaux échoué : %s", exc)
        report["merge"] = {"error": str(exc)}

    report["ended_at"] = datetime.utcnow().isoformat()
    return report


def validate_signal(
    signaux_db: Path,
    signal_id: str,
    accept: bool,
) -> dict[str, Any]:
    """Accepte ou rejette un signal (action humaine)."""
    storage = SignalStorage(signaux_db)
    existing = storage.get(signal_id)
    if existing is None:
        return {"ok": False, "error": f"signal {signal_id!r} introuvable"}

    new_status = "valide" if accept else "rejete"
    storage.set_status(signal_id, new_status)
    return {"ok": True, "signal_id": signal_id, "status": new_status}


def promote_signal(
    signaux_db: Path,
    incidents_db: Path,
    signal_id: str,
) -> dict[str, Any]:
    """
    Promeut un signal `valide` en incident dans incidents.sqlite.

    L'incident créé a :
        source    = "signal_detecteur"
        source_id = signal_id
    """
    import sqlite3

    storage = SignalStorage(signaux_db)
    sig = storage.get(signal_id)
    if sig is None:
        return {"ok": False, "error": f"signal {signal_id!r} introuvable"}
    if sig["status"] not in ("valide", "a_valider"):
        return {"ok": False, "error": f"status='{sig['status']}', doit être valide/a_valider"}

    # Insertion côté incidents.sqlite (schéma du veilleur)
    db = Path(incidents_db)
    if not db.exists():
        return {"ok": False, "error": f"incidents.sqlite introuvable : {db}"}

    now_iso = datetime.utcnow().isoformat()
    with sqlite3.connect(db) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(incidents)").fetchall()]
        if not cols:
            return {"ok": False, "error": "table 'incidents' absente"}

        base = {
            "source": "signal_detecteur",
            "source_id": signal_id,
            "source_url": sig.get("source_url"),
            "marque": sig.get("marque"),
            "sous_categorie": sig.get("produit"),
            "motif": sig.get("resume") or sig.get("titre"),
            "risques": sig.get("symptome"),
            "categorie": "Signal externe",
            "nature_juridique": "Signal faible",
            "date_publication": now_iso[:10],
            "raw": json.dumps({"signal_id": signal_id, "origin": "detecteur_signaux"}),
        }
        insert_cols = [c for c in base.keys() if c in cols]
        placeholders = ",".join("?" * len(insert_cols))
        sql = (
            f"INSERT OR REPLACE INTO incidents ({','.join(insert_cols)}) "
            f"VALUES ({placeholders})"
        )
        conn.execute(sql, [base[c] for c in insert_cols])

    storage.mark_promoted(signal_id, "signal_detecteur", signal_id)
    return {"ok": True, "signal_id": signal_id, "promoted_to_incident_id": signal_id}
