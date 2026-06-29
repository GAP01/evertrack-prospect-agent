"""State Reflex du dashboard EverTrack."""

from __future__ import annotations

import copy
from typing import Any

import reflex as rx

from .services import data as data_service
from .services.normalize import normalize_outreach_pure


_ENRICH_ROW_KEYS = (
    "source", "source_id", "marque_input", "match_status",
    "raison_sociale", "siren", "contact_nom", "contact_titre",
    "contact_type", "adresse", "effectif_tranche",
)

_ENRICH_DETAIL_KEYS = (
    "source", "source_id", "marque_input", "query_used",
    "match_status", "siren", "siret_siege", "raison_sociale",
    "forme_juridique", "code_naf", "libelle_naf", "adresse",
    "effectif_tranche", "categorie_entreprise",
    "contact_nom", "contact_titre", "contact_type", "contact_source",
    "api_used", "enriched_at",
)

_SIGNAL_ROW_KEYS = (
    "signal_id", "marque", "produit", "symptome", "titre",
    "source_type", "source_name", "source_url", "status",
    "detected_at", "last_seen_at",
)

_SIGNAL_DETAIL_KEYS = _SIGNAL_ROW_KEYS + ("resume", "detector_version")

_OUTREACH_EMPTY: dict = {
    "status": "absent",
    "message_id": "",
    "objet": "",
    "body_md": "",
    "body_fallback": "",
    "llm_used": False,
    "generated_at": "",
    "validated_at": "",
    "sent_at": "",
    "notes": "",
    "source": "",
    "source_id": "",
    "canal": "email",
    "context_json": "",
    "kpi": {
        "score_sanitaire": {"value": 0, "label": "Faible", "color": "green"},
        "sources_media": {"total": 0, "by_source": []},
        "confidence_prospect": {"value": 0.0, "percent": 0, "status": ""},
    },
}


def _normalize_outreach(msg: dict | None) -> dict:
    """
    Convertit un dict OutreachMessage (ou None) en dict safe pour Reflex Var.

    Delegue a normalize_outreach_pure (services/normalize.py) qui n'importe
    pas Reflex et peut etre testee dans tout venv Python 3.12.
    """
    return normalize_outreach_pure(msg)


def _normalize_signal_match(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise un rappel officiel matché avec un signal (côté signal drawer)."""
    return {
        "inc_source": str(row.get("inc_source") or ""),
        "inc_source_id": str(row.get("inc_source_id") or ""),
        "inc_url": str(row.get("inc_url") or ""),
        "inc_marque": str(row.get("inc_marque") or "-"),
        "inc_categorie": str(row.get("inc_categorie") or "-"),
        "inc_motif": str(row.get("inc_motif") or "")[:200],
        "inc_date": str(row.get("inc_date") or "")[:10],
        "score": float(row.get("score") or 0.0),
        "lead_time_days": int(row.get("lead_time_days") or 0),
        "user_confirmed": int(row.get("user_confirmed") or 0),
    }


def _normalize_incident_match(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise un signal matché avec un incident (côté incident drawer)."""
    return {
        "signal_id": str(row.get("signal_id") or ""),
        "marque": str(row.get("marque") or "-"),
        "symptome": str(row.get("symptome") or "-"),
        "produit": str(row.get("produit") or ""),
        "titre": str(row.get("titre") or ""),
        "source_type": str(row.get("source_type") or ""),
        "source_name": str(row.get("source_name") or ""),
        "source_url": str(row.get("source_url") or ""),
        "status": str(row.get("status") or ""),
        "signal_score": int(row.get("signal_score") or 0),
        "detected_at": str(row.get("detected_at") or "")[:10],
        "score": float(row.get("score") or 0.0),
        "lead_time_days": int(row.get("lead_time_days") or 0),
        "user_confirmed": int(row.get("user_confirmed") or 0),
    }


def _normalize_volume_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise un signal volume + son payload JSON pour la table dashboard."""
    payload = row.get("payload") or {}
    return {
        "signal_id": str(row.get("signal_id") or ""),
        "status": str(row.get("status") or ""),
        "score": int(row.get("score") or 0),
        "detected_at": str(row.get("detected_at") or "")[:10],
        "category": str(payload.get("category") or ""),
        "dep_code": str(payload.get("dep_code") or ""),
        "dep_name": str(payload.get("dep_name") or ""),
        "iso_week": str(payload.get("iso_week") or ""),
        "count_actuel": int(payload.get("count_actuel") or 0),
        "baseline_median": float(payload.get("baseline_median") or 0),
        "baseline_mad": float(payload.get("baseline_mad") or 0),
        "z_mod": float(payload.get("z_mod") or 0),
    }


def _normalize_volume_detail(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise le détail d'un signal volume pour le drawer."""
    if not row:
        return {}
    payload = row.get("payload") or {}
    return {
        "signal_id": str(row.get("signal_id") or ""),
        "status": str(row.get("status") or ""),
        "score": int(row.get("score") or 0),
        "titre": str(row.get("titre") or ""),
        "detected_at": str(row.get("detected_at") or "")[:10],
        "last_seen_at": str(row.get("last_seen_at") or "")[:16],
        "category": str(payload.get("category") or ""),
        "dep_code": str(payload.get("dep_code") or ""),
        "dep_name": str(payload.get("dep_name") or ""),
        "iso_week": str(payload.get("iso_week") or ""),
        "count_actuel": int(payload.get("count_actuel") or 0),
        "baseline_median": float(payload.get("baseline_median") or 0),
        "baseline_mad": float(payload.get("baseline_mad") or 0),
        "baseline_n_samples": int(payload.get("baseline_n_samples") or 0),
        "z_mod": float(payload.get("z_mod") or 0),
        "z_mod_threshold": float(payload.get("z_mod_threshold") or 3.5),
        "method": str(payload.get("method") or ""),
    }


def _normalize_signal_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: str(row.get(k) or "") for k in _SIGNAL_ROW_KEYS}
    out["score"] = int(row.get("score") or 0)
    out["n_sources"] = int(row.get("n_sources") or 0)
    # Tronque les timestamps ISO à YYYY-MM-DD pour l'affichage en table
    out["detected_at"] = out["detected_at"][:10] if out["detected_at"] else ""
    out["last_seen_at"] = out["last_seen_at"][:10] if out["last_seen_at"] else ""
    return out


def _normalize_signal_detail(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: str(row.get(k) or "") for k in _SIGNAL_DETAIL_KEYS}
    out["score"] = int(row.get("score") or 0)
    # Breakdown : dict str->int
    import json as _json
    try:
        breakdown_raw = row.get("score_breakdown") or "{}"
        breakdown = _json.loads(breakdown_raw) if isinstance(breakdown_raw, str) else breakdown_raw
        out["breakdown"] = {k: int(v) for k, v in (breakdown or {}).items()}
    except (ValueError, TypeError):
        out["breakdown"] = {}
    # Sources : liste de dicts normalisés
    raw_sources = row.get("sources") or []
    out["sources"] = [
        {
            "source_type": str(s.get("source_type") or ""),
            "source_name": str(s.get("source_name") or ""),
            "source_url": str(s.get("source_url") or ""),
            "titre": str(s.get("titre") or ""),
            "detected_at": str(s.get("detected_at") or "")[:19].replace("T", " "),
        }
        for s in raw_sources
    ]
    return out


def _normalize_enrich_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: str(row.get(k) or "") for k in _ENRICH_ROW_KEYS}
    out["confidence"] = float(row.get("confidence") or 0.0)
    return out


def _normalize_enrich_detail(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: str(row.get(k) or "") for k in _ENRICH_DETAIL_KEYS}
    out["confidence"] = float(row.get("confidence") or 0.0)
    return out


_INCIDENT_KEYS = (
    "source",
    "source_id",
    "date_publication",
    "marque",
    "marque_salubrite",  # agrément DGAL CE 853/2004 — identifie l'usine de production
    "sous_categorie",
    "motif",
    "risques",
    "distributeurs",
    "zone_geographique",
    "source_url",
    "modeles",
    "nature_juridique",
    "categorie",
)


def _normalize_incident(inc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: str(inc.get(k) or "") for k in _INCIDENT_KEYS}
    out["date_publication"] = out["date_publication"][:10] if out["date_publication"] else ""
    return out


def _sort_rows(
    rows: list[dict[str, Any]],
    column: str,
    direction: str,
) -> list[dict[str, Any]]:
    """
    Trie des rows par colonne, direction asc/desc. Valeurs vides toujours
    à la fin. Tente float() d'abord, fallback lowercase string.
    """
    if not column:
        return rows
    reverse = direction == "desc"

    def _is_empty(v: Any) -> bool:
        return v is None or v == ""

    def _key(row: dict[str, Any]) -> Any:
        v = row.get(column)
        if isinstance(v, (int, float)):
            return v
        s = str(v)
        try:
            return float(s)
        except (ValueError, TypeError):
            return s.lower()

    non_empty = [r for r in rows if not _is_empty(r.get(column))]
    empty = [r for r in rows if _is_empty(r.get(column))]
    try:
        non_empty = sorted(non_empty, key=_key, reverse=reverse)
    except TypeError:
        pass
    return non_empty + empty


def _normalize_dimension(d: dict[str, Any]) -> dict[str, Any]:
    # La dataclass DimensionScore utilise `raw` et `rationale`.
    return {
        "name": str(d.get("name") or ""),
        "score": float(d.get("raw", d.get("score")) or 0),
        "weight": float(d.get("weight") or 0),
        "reason": str(d.get("rationale", d.get("reason")) or ""),
    }


def _normalize_score(sc: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": float(sc.get("score") or 0),
        "tier": str(sc.get("tier") or "faible"),
        "dimensions": [
            _normalize_dimension(d)
            for d in (sc.get("dimensions") or [])
            if isinstance(d, dict)
        ],
    }


class DashboardState(rx.State):
    # --- Page ---
    current_page: str = "radar"  # "radar" | "prospects" | "signaux" | "volumes"

    # --- Incidents (radar) ---
    stats: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    sous_categories: list[str] = []

    tier_filter: str = "all"
    sous_cat_filter: str = "all"
    incident_search: str = ""
    incident_date_from: str = ""
    incident_date_to: str = ""
    limit: int = 25

    drawer_open: bool = False
    selected_source: str = ""
    selected_source_id: str = ""
    selected_incident: dict[str, Any] = {}
    selected_score: dict[str, Any] = {}

    # --- Enrichissements (prospects) ---
    enrich_rows: list[dict[str, Any]] = []
    enrich_stats: dict[str, Any] = {}
    enrich_match_filter: str = "all"
    enrich_search: str = ""
    enrich_limit: int = 100

    prospect_drawer_open: bool = False
    selected_enrich: dict[str, Any] = {}

    # --- Signaux faibles ---
    signal_rows: list[dict[str, Any]] = []
    signal_stats: dict[str, Any] = {}
    signal_status_filter: str = "all"
    signal_search: str = ""
    signal_date_from: str = ""
    signal_date_to: str = ""
    signal_limit: int = 100

    signal_drawer_open: bool = False
    selected_signal: dict[str, Any] = {}

    # Cross-référence (matches signaux ↔ incidents)
    match_stats: dict[str, Any] = {}
    selected_signal_matches: list[dict[str, Any]] = []
    selected_incident_matches: list[dict[str, Any]] = []

    # Pression médiatique (marques avec plusieurs signaux sur 7j glissants)
    media_pressure: dict[str, Any] = {}
    selected_signal_media_pressure: int = 0

    # Tri des grilles (cliqué sur en-tête de colonne)
    # "" = ordre par défaut du data layer. "asc" | "desc".
    incident_sort_column: str = ""
    incident_sort_direction: str = "desc"
    signal_sort_column: str = ""
    signal_sort_direction: str = "desc"
    prospect_sort_column: str = ""
    prospect_sort_direction: str = "desc"
    volume_sort_column: str = ""
    volume_sort_direction: str = "desc"

    # --- Signaux volumes (signalconso_volume) ---
    volume_rows: list[dict[str, Any]] = []
    volume_stats: dict[str, Any] = {}
    volume_status_filter: str = "all"
    volume_category_filter: str = "all"
    volume_dep_filter: str = ""
    volume_min_score: int = 0
    volume_limit: int = 100

    volume_drawer_open: bool = False
    selected_volume: dict[str, Any] = {}

    # --- Outreach (Agent 5) ---
    outreach_drawer_open: bool = False
    selected_outreach: dict = {}
    outreach_busy: bool = False
    outreach_kpi_a_valider: int = 0

    demo_mode: bool = data_service.DEMO_MODE

    last_message: str = ""
    last_message_kind: str = "info"
    loading: bool = False

    @rx.var
    def tier_options(self) -> list[str]:
        return ["all", "critique", "eleve", "modere", "faible"]

    @rx.var
    def sous_cat_options(self) -> list[str]:
        return ["all"] + self.sous_categories

    @rx.var
    def incidents_total(self) -> int:
        return int(self.stats.get("incidents_total") or 0)

    @rx.var
    def scores_total(self) -> int:
        return int(self.stats.get("scores_total") or 0)

    @rx.var
    def last_score_at(self) -> str:
        v = self.stats.get("last_score_at") or ""
        return v[:10] if v else "jamais"

    @rx.var
    def row_count(self) -> int:
        return len(self.rows)

    @rx.var
    def count_by_tier(self) -> dict[str, int]:
        out = {"critique": 0, "eleve": 0, "modere": 0, "faible": 0}
        for r in self.rows:
            t = r.get("tier") or ""
            if t in out:
                out[t] += 1
        return out

    # --- Computed : enrichissements ---

    @rx.var
    def enrich_match_options(self) -> list[str]:
        return ["all", "found", "ambiguous", "not_found", "skipped"]

    @rx.var
    def enrich_total(self) -> int:
        return int(self.enrich_stats.get("total") or 0)

    @rx.var
    def enrich_found(self) -> int:
        return int((self.enrich_stats.get("by_status") or {}).get("found") or 0)

    @rx.var
    def enrich_with_contact(self) -> int:
        return int(self.enrich_stats.get("with_contact") or 0)

    @rx.var
    def enrich_with_cible(self) -> int:
        return int(self.enrich_stats.get("with_cible") or 0)

    @rx.var
    def enrich_row_count(self) -> int:
        return len(self.enrich_rows)

    @rx.var
    def selected_enrich_title(self) -> str:
        marque = self.selected_enrich.get("marque_input") or ""
        raison = self.selected_enrich.get("raison_sociale") or ""
        return raison if raison else (marque or "(inconnu)")

    @rx.var
    def selected_enrich_confidence(self) -> float:
        return float(self.selected_enrich.get("confidence") or 0.0)

    # --- Computed : incidents ---

    @rx.var
    def selected_incident_title(self) -> str:
        marque = (self.selected_incident or {}).get("marque") or "(marque non renseignee)"
        sous_cat = (self.selected_incident or {}).get("sous_categorie") or ""
        if sous_cat:
            return marque + " - " + sous_cat
        return marque

    @rx.var
    def selected_score_value(self) -> float:
        return float((self.selected_score or {}).get("score") or 0)

    @rx.var
    def selected_score_tier(self) -> str:
        return (self.selected_score or {}).get("tier") or "faible"

    @rx.var
    def selected_dimensions(self) -> list[dict[str, Any]]:
        return (self.selected_score or {}).get("dimensions") or []

    # --- Computed : signaux ---

    @rx.var
    def volume_total(self) -> int:
        return int(self.volume_stats.get("total") or 0)

    @rx.var
    def volume_en_alerte(self) -> int:
        return int(self.volume_stats.get("en_alerte") or 0)

    @rx.var
    def volume_top_category(self) -> str:
        return str(self.volume_stats.get("top_category") or "-")

    @rx.var
    def volume_top_dep(self) -> str:
        return str(self.volume_stats.get("top_dep") or "-")

    @rx.var
    def volume_max_z(self) -> str:
        z = self.volume_stats.get("max_z")
        if z is None:
            return "-"
        return f"{float(z):.2f}"

    @rx.var
    def volume_row_count(self) -> int:
        return len(self.volume_rows)

    @rx.var
    def volume_categories_distinct(self) -> list[str]:
        # "Toutes" + les valeurs effectivement présentes en base
        return ["all"] + list(self.volume_stats.get("categories_distinct") or [])

    @rx.var
    def volume_status_options(self) -> list[str]:
        return ["all", "a_valider", "valide", "rejete", "promu", "faible"]

    @rx.var
    def volume_last_seen(self) -> str:
        v = self.volume_stats.get("last_seen_at") or ""
        return str(v)[:16] if v else "jamais"

    @rx.var
    def selected_volume_title(self) -> str:
        cat = self.selected_volume.get("category") or ""
        dep = self.selected_volume.get("dep_name") or self.selected_volume.get("dep_code") or ""
        if cat and dep:
            return f"{cat} — {dep}"
        return self.selected_volume.get("titre") or "(signal volume)"

    @rx.var
    def signal_status_options(self) -> list[str]:
        return ["all", "a_valider", "valide", "rejete", "promu", "faible"]

    @rx.var
    def signal_total(self) -> int:
        return int(self.signal_stats.get("total") or 0)

    @rx.var
    def signal_en_alerte(self) -> int:
        return int(self.signal_stats.get("en_alerte") or 0)

    @rx.var
    def signal_a_valider(self) -> int:
        return int((self.signal_stats.get("by_status") or {}).get("a_valider") or 0)

    @rx.var
    def signal_promus(self) -> int:
        return int((self.signal_stats.get("by_status") or {}).get("promu") or 0)

    @rx.var
    def signal_row_count(self) -> int:
        return len(self.signal_rows)

    @rx.var
    def signal_last_seen(self) -> str:
        v = self.signal_stats.get("last_seen_at") or ""
        return v[:19].replace("T", " ") if v else "jamais"

    @rx.var
    def selected_signal_title(self) -> str:
        marque = self.selected_signal.get("marque") or ""
        symptome = self.selected_signal.get("symptome") or ""
        if marque and symptome:
            return marque + " — " + symptome
        if marque:
            return marque
        return self.selected_signal.get("titre") or "(signal)"

    @rx.var
    def selected_signal_score(self) -> int:
        return int(self.selected_signal.get("score") or 0)

    @rx.var
    def selected_signal_sources(self) -> list[dict[str, Any]]:
        return self.selected_signal.get("sources") or []

    @rx.var
    def selected_signal_breakdown(self) -> list[dict[str, Any]]:
        b = self.selected_signal.get("breakdown") or {}
        labels = {
            "source_weight": "Qualité source",
            "recurrence": "Récurrence",
            "recency": "Fraîcheur",
            "brand_known": "Marque connue",
            "sentiment": "Sentiment négatif",
        }
        out = []
        for key, label in labels.items():
            out.append({"label": label, "value": int(b.get(key) or 0)})
        return out

    # --- Computed : matches signaux ↔ incidents -----------------------

    @rx.var
    def total_matches(self) -> int:
        return int(self.match_stats.get("total_matches") or 0)

    @rx.var
    def strong_matches(self) -> int:
        return int(self.match_stats.get("strong_matches") or 0)

    @rx.var
    def avg_lead_time(self) -> str:
        v = self.match_stats.get("avg_lead_time_days")
        if v is None:
            return "—"
        return f"{v:+.1f} j"

    @rx.var
    def signals_ahead(self) -> int:
        return int(self.match_stats.get("signals_ahead_count") or 0)

    @rx.var
    def selected_signal_match_count(self) -> int:
        return len(self.selected_signal_matches)

    @rx.var
    def selected_incident_match_count(self) -> int:
        return len(self.selected_incident_matches)

    # --- Computed : pression médiatique ------------------------------

    @rx.var
    def n_brands_under_pressure(self) -> int:
        return int(self.media_pressure.get("n_brands_under_pressure") or 0)

    @rx.var
    def top_brands_under_pressure(self) -> list[dict[str, Any]]:
        return self.media_pressure.get("top") or []

    @rx.var
    def selected_signal_pressure_label(self) -> str:
        n = self.selected_signal_media_pressure
        if n <= 1:
            return ""
        return f"{n} signaux cette semaine"

    # --- Computed : outreach KPI ---
    # Ces vars lisent selected_outreach["kpi"], garanti présent par
    # _normalize_outreach (via build_outreach_kpi). Elles sont plates pour
    # que les composants Reflex n'aient pas à imbriquer des accès de dict.

    @rx.var
    def outreach_kpi_score_value(self) -> int:
        kpi = (self.selected_outreach or {}).get("kpi") or {}
        score = kpi.get("score_sanitaire") or {}
        try:
            return max(0, min(100, int(score.get("value") or 0)))
        except (TypeError, ValueError):
            return 0

    @rx.var
    def outreach_kpi_score_label(self) -> str:
        kpi = (self.selected_outreach or {}).get("kpi") or {}
        score = kpi.get("score_sanitaire") or {}
        return str(score.get("label") or "")

    @rx.var
    def outreach_kpi_score_color(self) -> str:
        kpi = (self.selected_outreach or {}).get("kpi") or {}
        score = kpi.get("score_sanitaire") or {}
        return str(score.get("color") or "gray")

    @rx.var
    def outreach_kpi_sources_total(self) -> int:
        kpi = (self.selected_outreach or {}).get("kpi") or {}
        sources = kpi.get("sources_media") or {}
        try:
            return int(sources.get("total") or 0)
        except (TypeError, ValueError):
            return 0

    @rx.var
    def outreach_kpi_sources_data(self) -> list[dict]:
        kpi = (self.selected_outreach or {}).get("kpi") or {}
        sources = kpi.get("sources_media") or {}
        raw = sources.get("by_source") or []
        # Garantit que chaque élément est un dict avec les bons types
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            out.append({
                "source": str(item.get("source") or ""),
                "count": int(item.get("count") or 0),
            })
        return out

    @rx.var
    def outreach_kpi_confidence_value(self) -> float:
        kpi = (self.selected_outreach or {}).get("kpi") or {}
        conf = kpi.get("confidence_prospect") or {}
        try:
            return max(0.0, min(1.0, float(conf.get("value") or 0.0)))
        except (TypeError, ValueError):
            return 0.0

    @rx.var
    def outreach_kpi_confidence_percent(self) -> int:
        kpi = (self.selected_outreach or {}).get("kpi") or {}
        conf = kpi.get("confidence_prospect") or {}
        try:
            return max(0, min(100, int(conf.get("percent") or 0)))
        except (TypeError, ValueError):
            return 0

    @rx.var
    def outreach_kpi_confidence_status(self) -> str:
        kpi = (self.selected_outreach or {}).get("kpi") or {}
        conf = kpi.get("confidence_prospect") or {}
        return str(conf.get("status") or "")

    @rx.var
    def outreach_kpi_has_data(self) -> bool:
        # True si un context_json non-vide est present dans le message selectionne.
        # Ce critere est prefere aux seuils KPI > 0 qui masqueraient les messages
        # legitimes avec score=0 (ex : incident sans risque sanitaire identifie).
        ctx = (self.selected_outreach or {}).get("context_json") or ""
        return ctx.strip() != ""

    # --- Navigation ---

    def nav_radar(self):
        self.current_page = "radar"

    def nav_prospects(self):
        self.current_page = "prospects"
        self._load_enrichissements()

    def nav_signaux(self):
        self.current_page = "signaux"
        self._load_signaux()

    def nav_volumes(self):
        self.current_page = "volumes"
        self._load_volumes()

    # --- Enrichissements ---

    def _load_enrichissements(self):
        self.enrich_stats = data_service.get_enrichissement_stats()
        status = None if self.enrich_match_filter == "all" else self.enrich_match_filter
        raw = data_service.get_enrichissements(
            limit=self.enrich_limit,
            match_status=status,
            search=self.enrich_search or None,
        )
        rows = [_normalize_enrich_row(r) for r in raw]
        if self.prospect_sort_column:
            rows = _sort_rows(rows, self.prospect_sort_column, self.prospect_sort_direction)
        self.enrich_rows = rows

    def set_enrich_match_filter(self, value: str):
        self.enrich_match_filter = value
        self._load_enrichissements()

    def set_enrich_search(self, value: str):
        self.enrich_search = value
        self._load_enrichissements()

    def set_enrich_limit(self, value: str):
        try:
            self.enrich_limit = max(5, min(500, int(value)))
        except (TypeError, ValueError):
            self.enrich_limit = 100
        self._load_enrichissements()

    def reset_enrich_filters(self):
        self.enrich_match_filter = "all"
        self.enrich_search = ""
        self._load_enrichissements()

    def open_prospect(self, source: str, source_id: str):
        detail = data_service.get_enrichissement(source, source_id)
        if detail:
            self.selected_enrich = _normalize_enrich_detail(detail)
        else:
            self.selected_enrich = _normalize_enrich_detail({})
        self.prospect_drawer_open = True

    def close_prospect_drawer(self):
        self.prospect_drawer_open = False

    def set_prospect_drawer_open(self, value: bool):
        self.prospect_drawer_open = value

    # --- Outreach (Agent 5) ---

    def open_outreach_drawer(self, source: str, source_id: str):
        msg = data_service.get_outreach_message(source, source_id)
        if msg is None:
            # Aucun message genere : placeholder avec les ids pour generation ulterieure
            placeholder = copy.deepcopy(_OUTREACH_EMPTY)
            placeholder["source"] = source
            placeholder["source_id"] = source_id
            self.selected_outreach = placeholder
        else:
            self.selected_outreach = _normalize_outreach(msg)
        self.outreach_drawer_open = True

    def close_outreach_drawer(self):
        self.outreach_drawer_open = False

    def set_outreach_drawer_open(self, value: bool):
        self.outreach_drawer_open = value

    def generate_outreach(self):
        source = self.selected_outreach.get("source") or ""
        source_id = self.selected_outreach.get("source_id") or ""
        if not source or not source_id:
            self._notify("Source manquante pour la generation", "error")
            return
        self.outreach_busy = True
        yield
        try:
            from redacteur_outreach.storage import OutreachStorage
            from redacteur_outreach.redacteur import Redacteur
            from dashboard_reflex.services import data as _data_svc
            storage = OutreachStorage(str(_data_svc.OUTREACH_DB))
            redacteur = Redacteur(storage, data_dir=str(_data_svc.DATA_DIR))
            redacteur.generate(source, source_id)
            storage.close()
            # Recharge le message depuis la base
            msg = data_service.get_outreach_message(source, source_id)
            self.selected_outreach = _normalize_outreach(msg)
            self._refresh_outreach_kpi()
            self._notify("Message genere", "success")
        except Exception as exc:
            self._notify("Erreur generation : " + str(exc), "error")
        finally:
            self.outreach_busy = False

    def regenerate_outreach(self):
        source = self.selected_outreach.get("source") or ""
        source_id = self.selected_outreach.get("source_id") or ""
        if not source or not source_id:
            self._notify("Source manquante pour la regeneration", "error")
            return
        self.outreach_busy = True
        yield
        try:
            from redacteur_outreach.storage import OutreachStorage
            from redacteur_outreach.redacteur import Redacteur
            from dashboard_reflex.services import data as _data_svc
            storage = OutreachStorage(str(_data_svc.OUTREACH_DB))
            redacteur = Redacteur(storage, data_dir=str(_data_svc.DATA_DIR))
            redacteur.generate(source, source_id, force=True)
            storage.close()
            msg = data_service.get_outreach_message(source, source_id)
            self.selected_outreach = _normalize_outreach(msg)
            self._refresh_outreach_kpi()
            self._notify("Message regenere", "success")
        except Exception as exc:
            self._notify("Erreur regeneration : " + str(exc), "error")
        finally:
            self.outreach_busy = False

    def validate_outreach(self):
        message_id = self.selected_outreach.get("message_id") or ""
        if not message_id:
            return
        from datetime import datetime as _dt, timezone as _tz
        now_iso = _dt.now(_tz.utc).isoformat(timespec="seconds")
        data_service.set_outreach_status(message_id, "valide", validated_at=now_iso)
        source = self.selected_outreach.get("source") or ""
        source_id = self.selected_outreach.get("source_id") or ""
        msg = data_service.get_outreach_message(source, source_id)
        self.selected_outreach = _normalize_outreach(msg)
        self._refresh_outreach_kpi()
        self._notify("Message valide", "success")

    def reject_outreach(self):
        message_id = self.selected_outreach.get("message_id") or ""
        if not message_id:
            return
        data_service.set_outreach_status(message_id, "rejete")
        source = self.selected_outreach.get("source") or ""
        source_id = self.selected_outreach.get("source_id") or ""
        msg = data_service.get_outreach_message(source, source_id)
        self.selected_outreach = _normalize_outreach(msg)
        self._refresh_outreach_kpi()
        self._notify("Message rejete", "info")

    def mark_outreach_sent(self):
        message_id = self.selected_outreach.get("message_id") or ""
        if not message_id:
            return
        from datetime import datetime as _dt, timezone as _tz
        now_iso = _dt.now(_tz.utc).isoformat(timespec="seconds")
        data_service.set_outreach_status(message_id, "envoye", sent_at=now_iso)
        source = self.selected_outreach.get("source") or ""
        source_id = self.selected_outreach.get("source_id") or ""
        msg = data_service.get_outreach_message(source, source_id)
        self.selected_outreach = _normalize_outreach(msg)
        self._refresh_outreach_kpi()
        self._notify("Message marque comme envoye", "success")

    def _refresh_outreach_kpi(self):
        self.outreach_kpi_a_valider = data_service.count_outreach_a_valider()

    # --- Signaux faibles ---

    def _load_signaux(self):
        self.signal_stats = data_service.get_signal_stats()
        self.match_stats = data_service.get_match_stats()
        self.media_pressure = data_service.get_media_pressure_summary(window_days=7)
        status = None if self.signal_status_filter == "all" else self.signal_status_filter
        raw = data_service.get_signaux(
            limit=self.signal_limit,
            status=status,
            search=self.signal_search or None,
            date_from=self.signal_date_from or None,
            date_to=self.signal_date_to or None,
        )
        rows = [_normalize_signal_row(r) for r in raw]
        if self.signal_sort_column:
            rows = _sort_rows(rows, self.signal_sort_column, self.signal_sort_direction)
        self.signal_rows = rows

    def set_signal_status_filter(self, value: str):
        self.signal_status_filter = value
        self._load_signaux()

    def set_signal_search(self, value: str):
        self.signal_search = value
        self._load_signaux()

    def set_signal_date_from(self, value: str):
        self.signal_date_from = value
        self._load_signaux()

    def set_signal_date_to(self, value: str):
        self.signal_date_to = value
        self._load_signaux()

    def set_signal_limit(self, value: str):
        try:
            self.signal_limit = max(5, min(500, int(value)))
        except (TypeError, ValueError):
            self.signal_limit = 100
        self._load_signaux()

    def reset_signal_filters(self):
        self.signal_status_filter = "all"
        self.signal_search = ""
        self.signal_date_from = ""
        self.signal_date_to = ""
        self._load_signaux()

    def open_signal(self, signal_id: str):
        detail = data_service.get_signal(signal_id)
        if detail:
            self.selected_signal = _normalize_signal_detail(detail)
        else:
            self.selected_signal = _normalize_signal_detail({})
        # Charge les rappels officiels correspondants
        self.selected_signal_matches = [
            _normalize_signal_match(m)
            for m in data_service.get_matches_for_signal(signal_id)
        ]
        # Pression médiatique sur la marque (7j glissants)
        marque = (detail or {}).get("marque") if detail else None
        self.selected_signal_media_pressure = data_service.get_brand_media_pressure(
            marque, window_days=7,
        )
        self.signal_drawer_open = True

    def close_signal_drawer(self):
        self.signal_drawer_open = False

    def set_signal_drawer_open(self, value: bool):
        self.signal_drawer_open = value

    def validate_signal(self, signal_id: str):
        """Marque un signal comme validé."""
        if data_service.set_signal_status(signal_id, "valide"):
            self._load_signaux()
            # Rafraîchit le détail affiché si c'est le même
            if self.selected_signal.get("signal_id") == signal_id:
                detail = data_service.get_signal(signal_id)
                if detail:
                    self.selected_signal = _normalize_signal_detail(detail)
            self._notify("Signal validé", "success")

    def reject_signal(self, signal_id: str):
        """Marque un signal comme rejeté."""
        if data_service.set_signal_status(signal_id, "rejete"):
            self._load_signaux()
            if self.selected_signal.get("signal_id") == signal_id:
                detail = data_service.get_signal(signal_id)
                if detail:
                    self.selected_signal = _normalize_signal_detail(detail)
            self._notify("Signal rejeté", "info")

    # --- Validation humaine des matches signal ↔ incident ----------------

    def confirm_signal_match(
        self, signal_id: str, inc_source: str, inc_source_id: str,
    ):
        """Valide un lien entre un signal et un rappel officiel."""
        if data_service.confirm_match(signal_id, inc_source, inc_source_id):
            # Refresh drawer courant si ouvert sur ce signal
            if self.selected_signal.get("signal_id") == signal_id:
                self.selected_signal_matches = [
                    _normalize_signal_match(m)
                    for m in data_service.get_matches_for_signal(signal_id)
                ]
            # Refresh incident drawer si c'est l'incident courant
            if (self.selected_source == inc_source
                    and self.selected_source_id == inc_source_id):
                self.selected_incident_matches = [
                    _normalize_incident_match(m)
                    for m in data_service.get_matches_for_incident(
                        inc_source, inc_source_id
                    )
                ]
            self._notify("Lien validé", "success")

    def unconfirm_signal_match(
        self, signal_id: str, inc_source: str, inc_source_id: str,
    ):
        """Retire la validation humaine d'un lien."""
        if data_service.unconfirm_match(signal_id, inc_source, inc_source_id):
            if self.selected_signal.get("signal_id") == signal_id:
                self.selected_signal_matches = [
                    _normalize_signal_match(m)
                    for m in data_service.get_matches_for_signal(signal_id)
                ]
            if (self.selected_source == inc_source
                    and self.selected_source_id == inc_source_id):
                self.selected_incident_matches = [
                    _normalize_incident_match(m)
                    for m in data_service.get_matches_for_incident(
                        inc_source, inc_source_id
                    )
                ]
            self._notify("Validation retirée", "info")

    # --- Incidents ---

    # --- Signaux volumes ---

    def _load_volumes(self):
        self.volume_stats = data_service.get_volume_stats()
        status = None if self.volume_status_filter == "all" else self.volume_status_filter
        cat = None if self.volume_category_filter == "all" else self.volume_category_filter
        dep = self.volume_dep_filter.strip() or None
        min_score = self.volume_min_score if self.volume_min_score > 0 else None
        raw = data_service.get_volume_signaux(
            limit=self.volume_limit,
            status=status,
            category=cat,
            dep_code=dep,
            min_score=min_score,
        )
        rows = [_normalize_volume_row(r) for r in raw]
        if self.volume_sort_column:
            rows = _sort_rows(rows, self.volume_sort_column, self.volume_sort_direction)
        self.volume_rows = rows

    def set_volume_status_filter(self, value: str):
        self.volume_status_filter = value
        self._load_volumes()

    def set_volume_category_filter(self, value: str):
        self.volume_category_filter = value
        self._load_volumes()

    def set_volume_dep_filter(self, value: str):
        self.volume_dep_filter = value
        self._load_volumes()

    def set_volume_min_score(self, value: str):
        try:
            self.volume_min_score = max(0, min(100, int(value)))
        except (TypeError, ValueError):
            self.volume_min_score = 0
        self._load_volumes()

    def set_volume_limit(self, value: str):
        try:
            self.volume_limit = max(5, min(500, int(value)))
        except (TypeError, ValueError):
            self.volume_limit = 100
        self._load_volumes()

    def set_volume_sort(self, column: str):
        if self.volume_sort_column == column:
            self.volume_sort_direction = "asc" if self.volume_sort_direction == "desc" else "desc"
        else:
            self.volume_sort_column = column
            self.volume_sort_direction = "desc"
        self._load_volumes()

    def open_volume(self, signal_id: str):
        detail = data_service.get_volume_signal(signal_id)
        if detail:
            self.selected_volume = _normalize_volume_detail(detail)
        else:
            self.selected_volume = _normalize_volume_detail({})
        self.volume_drawer_open = True

    def close_volume_drawer(self):
        self.volume_drawer_open = False

    def set_volume_drawer_open(self, value: bool):
        self.volume_drawer_open = value

    def load_initial(self):
        self.sous_categories = data_service.list_sous_categories()
        self._refresh()
        self._refresh_outreach_kpi()

    def _refresh(self):
        self.stats = data_service.get_stats()
        tier = None if self.tier_filter == "all" else self.tier_filter
        sous_cat = None if self.sous_cat_filter == "all" else self.sous_cat_filter
        raw = data_service.get_top(
            limit=self.limit,
            tier=tier,
            sous_categorie=sous_cat,
            search=self.incident_search or None,
            date_from=self.incident_date_from or None,
            date_to=self.incident_date_to or None,
        )
        flat: list[dict[str, Any]] = []
        for r in raw:
            inc = r.get("incident") or {}
            date_pub = inc.get("date_publication") or ""
            flat.append({
                "source": str(r.get("source") or ""),
                "source_id": str(r.get("source_id") or ""),
                "score": float(r.get("score") or 0),
                "tier": str(r.get("tier") or "faible"),
                "date": date_pub[:10] if isinstance(date_pub, str) else "",
                "marque": str(inc.get("marque") or "(sans marque)"),
                "sous_categorie": str(inc.get("sous_categorie") or ""),
                "motif_rappel": str(inc.get("motif") or ""),
            })
        # Tri par défaut : date de publication desc, puis score desc.
        # Le format ISO "YYYY-MM-DD" se trie lexicographiquement = chronologiquement.
        flat.sort(key=lambda x: (x["date"], x["score"]), reverse=True)
        # Si l'utilisateur a cliqué une colonne, on override le tri par défaut
        if self.incident_sort_column:
            flat = _sort_rows(flat, self.incident_sort_column, self.incident_sort_direction)
        self.rows = flat

    # --- Tri des grilles (clic sur en-tête) --------------------------

    def set_incident_sort(self, column: str):
        """Toggle asc/desc si même colonne, sinon switch avec direction par défaut desc."""
        if self.incident_sort_column == column:
            self.incident_sort_direction = "asc" if self.incident_sort_direction == "desc" else "desc"
        else:
            self.incident_sort_column = column
            self.incident_sort_direction = "desc"
        self._refresh()

    def reset_incident_sort(self):
        self.incident_sort_column = ""
        self.incident_sort_direction = "desc"
        self._refresh()

    def set_signal_sort(self, column: str):
        if self.signal_sort_column == column:
            self.signal_sort_direction = "asc" if self.signal_sort_direction == "desc" else "desc"
        else:
            self.signal_sort_column = column
            self.signal_sort_direction = "desc"
        self._load_signaux()

    def reset_signal_sort(self):
        self.signal_sort_column = ""
        self.signal_sort_direction = "desc"
        self._load_signaux()

    def set_prospect_sort(self, column: str):
        if self.prospect_sort_column == column:
            self.prospect_sort_direction = "asc" if self.prospect_sort_direction == "desc" else "desc"
        else:
            self.prospect_sort_column = column
            self.prospect_sort_direction = "desc"
        self._load_enrichissements()

    def reset_prospect_sort(self):
        self.prospect_sort_column = ""
        self.prospect_sort_direction = "desc"
        self._load_enrichissements()

    def set_tier_filter(self, value: str):
        self.tier_filter = value
        self._refresh()

    def set_sous_cat_filter(self, value: str):
        self.sous_cat_filter = value
        self._refresh()

    def set_incident_search(self, value: str):
        self.incident_search = value
        self._refresh()

    def set_incident_date_from(self, value: str):
        self.incident_date_from = value
        self._refresh()

    def set_incident_date_to(self, value: str):
        self.incident_date_to = value
        self._refresh()

    def set_limit(self, value: str):
        try:
            self.limit = max(5, min(200, int(value)))
        except (TypeError, ValueError):
            self.limit = 25
        self._refresh()

    def reset_incident_filters(self):
        self.tier_filter = "all"
        self.sous_cat_filter = "all"
        self.incident_search = ""
        self.incident_date_from = ""
        self.incident_date_to = ""
        self._refresh()

    def refresh(self):
        self._refresh()
        self._refresh_outreach_kpi()
        self._notify("Donnees rechargees", "info")

    def open_incident(self, source: str, source_id: str):
        self.selected_source = source
        self.selected_source_id = source_id
        detail = data_service.get_incident(source, source_id)
        if detail:
            self.selected_incident = _normalize_incident(detail.get("incident") or {})
            self.selected_score = _normalize_score(detail.get("score") or {})
        else:
            self.selected_incident = _normalize_incident({})
            self.selected_score = _normalize_score({})
        # Charge les signaux faibles qui matchent cet incident
        self.selected_incident_matches = [
            _normalize_incident_match(m)
            for m in data_service.get_matches_for_incident(source, source_id)
        ]
        self.drawer_open = True

    def close_drawer(self):
        self.drawer_open = False

    def set_drawer_open(self, value: bool):
        self.drawer_open = value

    def action_fetch(self):
        if self.demo_mode:
            self._notify("Mode demo : action desactivee", "warning")
            return
        self.loading = True
        yield
        try:
            report = data_service.trigger_fetch(since_days=7)
            msg = (
                "Fetch : " + str(report.get("fetched", 0)) + " recuperes, "
                + str(report.get("new", 0)) + " nouveaux, "
                + str(report.get("updated", 0)) + " maj"
            )
            self._notify(msg, "success")
            self._refresh()
        except Exception as exc:
            self._notify("Echec fetch : " + str(exc), "error")
        finally:
            self.loading = False

    def action_score(self):
        if self.demo_mode:
            self._notify("Mode demo : action desactivee", "warning")
            return
        self.loading = True
        yield
        try:
            report = data_service.trigger_score(use_llm=True)
            msg = (
                "Scores : " + str(report.get("scored_now", 0)) + " nouveaux sur "
                + str(report.get("incidents_total", 0)) + " incidents. LLM : "
                + str(report.get("llm_used_count", 0)) + "/"
                + str(report.get("scored_now", 0))
            )
            self._notify(msg, "success")
            self._refresh()
        except Exception as exc:
            self._notify("Echec scoring : " + str(exc), "error")
        finally:
            self.loading = False

    def _notify(self, msg: str, kind: str = "info"):
        self.last_message = msg
        self.last_message_kind = kind
