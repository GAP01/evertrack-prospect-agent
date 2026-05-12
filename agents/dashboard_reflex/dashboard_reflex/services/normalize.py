"""
Fonctions pures de normalisation des messages outreach.

Ce module n'importe pas Reflex, ce qui permet de le tester dans le venv
standard des agents (sans venv Reflex dedie).

La logique ici est extraite de state._normalize_outreach pour que les tests
de compatibilite ascendante (TestNormalizeOutreachV10) puissent tourner dans
tout environnement Python 3.12 dispose des agents.
"""

from __future__ import annotations

import json
from typing import Any

# Champs textuels copies tels quels depuis le dict message vers le dict Var.
_OUTREACH_STR_FIELDS = (
    "status", "message_id", "objet", "body_md", "body_fallback",
    "generated_at", "validated_at", "sent_at", "notes", "source",
    "source_id", "canal", "context_json",
)

# Structure vide coherente retournee quand msg est None ou incomplet.
# Dupliquee ici (et non importee depuis state.py) pour eviter l'import Reflex.
_OUTREACH_EMPTY_PURE: dict[str, Any] = {
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


def build_outreach_kpi_pure(context_json_str: str | None) -> dict[str, Any]:
    """
    Version pure (sans imports services/data) de build_outreach_kpi.

    Utilisee par normalize_outreach_pure pour calculer le KPI sans dependre
    de data.py (qui importe dashboard.data_access et peut echouer hors contexte
    Reflex/agents).

    Effectue le meme parsing que services/data.build_outreach_kpi, duplique
    la logique deliberement pour eviter le couplage circulaire.
    """
    _SCORE_TIERS: tuple[tuple[int, str, str], ...] = (
        (80, "Critique", "red"),
        (60, "Eleve", "orange"),
        (40, "Modere", "amber"),
        (0, "Faible", "green"),
    )

    def _empty() -> dict[str, Any]:
        import copy
        return copy.deepcopy(_OUTREACH_EMPTY_PURE["kpi"])

    if not context_json_str:
        return _empty()
    if len(context_json_str) > 65536:
        return _empty()
    try:
        ctx = json.loads(context_json_str)
    except (ValueError, TypeError):
        return _empty()
    if not isinstance(ctx, dict):
        return _empty()

    # score_sanitaire
    score_block = ctx.get("score") or {}
    raw_score = score_block.get("score_total") if isinstance(score_block, dict) else None
    try:
        score_value = max(0, min(100, int(float(raw_score)))) if raw_score is not None else 0
    except (TypeError, ValueError):
        score_value = 0

    label, color = "Faible", "green"
    for threshold, lbl, clr in _SCORE_TIERS:
        if score_value >= threshold:
            label, color = lbl, clr
            break

    # sources_media
    signaux_summary = ctx.get("signaux_summary") or []
    source_counts: dict[str, int] = {}
    if isinstance(signaux_summary, list):
        for sig in signaux_summary:
            if not isinstance(sig, dict):
                continue
            src = str(sig.get("source_name") or "").strip()
            if src:
                source_counts[src] = source_counts.get(src, 0) + 1
    by_source = sorted(
        [{"source": src, "count": cnt} for src, cnt in source_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )

    # confidence_prospect
    enrich = ctx.get("enrichissement") or {}
    if isinstance(enrich, dict):
        raw_conf = enrich.get("confidence")
        try:
            conf_value = max(0.0, min(1.0, float(raw_conf))) if raw_conf is not None else 0.0
        except (TypeError, ValueError):
            conf_value = 0.0
        contact_status = str(enrich.get("contact_type") or enrich.get("match_status") or "")
    else:
        conf_value = 0.0
        contact_status = ""

    return {
        "score_sanitaire": {"value": score_value, "label": label, "color": color},
        "sources_media": {
            "total": sum(source_counts.values()),
            "by_source": by_source,
        },
        "confidence_prospect": {
            "value": conf_value,
            "percent": round(conf_value * 100),
            "status": contact_status,
        },
    }


def normalize_outreach_pure(msg: dict[str, Any] | None) -> dict[str, Any]:
    """
    Convertit un dict OutreachMessage (ou None) en dict normalise safe.

    Equivalent pur (sans Reflex) de state._normalize_outreach.
    Peut etre utilise dans les tests du venv standard.

    Le KPI est calcule par build_outreach_kpi_pure (pas par data.py).
    """
    import copy

    if msg is None:
        return copy.deepcopy(_OUTREACH_EMPTY_PURE)

    out: dict[str, Any] = {k: (msg.get(k) or "") for k in _OUTREACH_STR_FIELDS}
    out["llm_used"] = bool(msg.get("llm_used"))
    out["kpi"] = build_outreach_kpi_pure(out["context_json"])
    return out
