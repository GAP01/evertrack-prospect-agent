"""Tests des @rx.var outreach_kpi_* dans DashboardState.

Stratégie : la logique de chaque var est testée via un helper _extract_kpi_vars()
qui reproduit exactement le même calcul que les vars mais en Python pur, sans
instancier DashboardState (ce qui nécessiterait Reflex).

Quand Reflex est disponible (via @skipUnless), on instancie DashboardState et
on vérifie que les vars rendent les mêmes valeurs que le helper.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# agents/ dans le path pour les imports transitifs
_SERVICES_DIR = Path(__file__).resolve().parents[1]
_AGENTS_ROOT = Path(__file__).resolve().parents[5]
for _p in (str(_SERVICES_DIR), str(_AGENTS_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from data import build_outreach_kpi  # noqa: E402


# ---------------------------------------------------------------------------
# Helper : reproduit la logique des @rx.var en Python pur
# (doit rester en sync avec state.py si la logique change)
# ---------------------------------------------------------------------------

def _extract_kpi_vars(selected_outreach: dict) -> dict:
    """Calcule les valeurs que les @rx.var outreach_kpi_* retourneraient."""
    kpi = (selected_outreach or {}).get("kpi") or {}

    # score_sanitaire
    score_block = kpi.get("score_sanitaire") or {}
    try:
        score_value = max(0, min(100, int(score_block.get("value") or 0)))
    except (TypeError, ValueError):
        score_value = 0
    score_label = str(score_block.get("label") or "")
    score_color = str(score_block.get("color") or "gray")

    # sources_media
    sources_block = kpi.get("sources_media") or {}
    try:
        sources_total = int(sources_block.get("total") or 0)
    except (TypeError, ValueError):
        sources_total = 0
    raw_by_source = sources_block.get("by_source") or []
    sources_data = [
        {"source": str(item.get("source") or ""), "count": int(item.get("count") or 0)}
        for item in raw_by_source
        if isinstance(item, dict)
    ]

    # confidence_prospect
    conf_block = kpi.get("confidence_prospect") or {}
    try:
        conf_value = max(0.0, min(1.0, float(conf_block.get("value") or 0.0)))
    except (TypeError, ValueError):
        conf_value = 0.0
    try:
        conf_percent = max(0, min(100, int(conf_block.get("percent") or 0)))
    except (TypeError, ValueError):
        conf_percent = 0
    conf_status = str(conf_block.get("status") or "")

    has_data = score_value > 0 or sources_total > 0 or conf_value > 0.0

    return {
        "outreach_kpi_score_value": score_value,
        "outreach_kpi_score_label": score_label,
        "outreach_kpi_score_color": score_color,
        "outreach_kpi_sources_total": sources_total,
        "outreach_kpi_sources_data": sources_data,
        "outreach_kpi_confidence_value": conf_value,
        "outreach_kpi_confidence_percent": conf_percent,
        "outreach_kpi_confidence_status": conf_status,
        "outreach_kpi_has_data": has_data,
    }


def _make_selected_outreach(context_json: str) -> dict:
    """Construit un dict selected_outreach comme le ferait _normalize_outreach."""
    return {
        "status": "a_valider",
        "message_id": "abc123",
        "objet": "Objet test",
        "body_md": "Corps test",
        "body_fallback": "Fallback",
        "llm_used": True,
        "generated_at": "2026-05-12T10:00:00",
        "validated_at": "",
        "sent_at": "",
        "notes": "",
        "source": "rappelconso",
        "source_id": "TEST001",
        "canal": "email",
        "context_json": context_json,
        "kpi": build_outreach_kpi(context_json),
    }


def _make_context_json_full() -> str:
    import json
    return json.dumps({
        "incident": {"marque": "ACME", "motif": "Presence de Listeria"},
        "score": {
            "score_total": 72,
            "tier": "eleve",
            "dimensions": [
                {"name": "risque_sanitaire", "raw": 80, "weight": 0.5},
                {"name": "ampleur_geo", "raw": 60, "weight": 0.25},
            ],
        },
        "enrichissement": {
            "confidence": 0.85,
            "contact_type": "cible",
            "contact_nom": "Jean Dupont",
            "contact_titre": "Directeur Qualite",
        },
        "signaux_summary": [
            {"source_name": "Marmiton", "titre": "Rappel fromage"},
            {"source_name": "TF1 Info", "titre": "Alerte lait"},
            {"source_name": "Marmiton", "titre": "Suite fromage"},
        ],
    }, ensure_ascii=True)


# ---------------------------------------------------------------------------
# _OUTREACH_EMPTY minimal (pour le cas "payload vide")
# On reconstruit le même que state.py pour ne pas importer state.py hors Reflex.
# ---------------------------------------------------------------------------

_OUTREACH_EMPTY = {
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


# ---------------------------------------------------------------------------
# Tests logique pure (sans Reflex)
# ---------------------------------------------------------------------------

class TestKpiVarsPayloadComplet(unittest.TestCase):
    """payload complet → les vars retournent les bonnes valeurs."""

    def setUp(self):
        ctx_json = _make_context_json_full()
        selected = _make_selected_outreach(ctx_json)
        self.vars = _extract_kpi_vars(selected)

    def test_score_value(self):
        self.assertEqual(self.vars["outreach_kpi_score_value"], 72)

    def test_score_label(self):
        self.assertEqual(self.vars["outreach_kpi_score_label"], "Eleve")

    def test_score_color(self):
        self.assertEqual(self.vars["outreach_kpi_score_color"], "orange")

    def test_sources_total(self):
        # 3 signaux dont 2 Marmiton + 1 TF1 Info
        self.assertEqual(self.vars["outreach_kpi_sources_total"], 3)

    def test_sources_data_length(self):
        # 2 sources distinctes
        self.assertEqual(len(self.vars["outreach_kpi_sources_data"]), 2)

    def test_sources_data_first_source(self):
        # Marmiton en tête (2 occurrences)
        self.assertEqual(self.vars["outreach_kpi_sources_data"][0]["source"], "Marmiton")
        self.assertEqual(self.vars["outreach_kpi_sources_data"][0]["count"], 2)

    def test_sources_data_second_source(self):
        self.assertEqual(self.vars["outreach_kpi_sources_data"][1]["source"], "TF1 Info")
        self.assertEqual(self.vars["outreach_kpi_sources_data"][1]["count"], 1)

    def test_confidence_value(self):
        self.assertAlmostEqual(self.vars["outreach_kpi_confidence_value"], 0.85)

    def test_confidence_percent(self):
        self.assertEqual(self.vars["outreach_kpi_confidence_percent"], 85)

    def test_confidence_status(self):
        self.assertEqual(self.vars["outreach_kpi_confidence_status"], "cible")

    def test_has_data_true(self):
        self.assertTrue(self.vars["outreach_kpi_has_data"])


class TestKpiVarsPayloadVide(unittest.TestCase):
    """_OUTREACH_EMPTY → outreach_kpi_has_data == False, scores à 0, listes vides."""

    def setUp(self):
        self.vars = _extract_kpi_vars(dict(_OUTREACH_EMPTY))

    def test_has_data_false(self):
        self.assertFalse(self.vars["outreach_kpi_has_data"])

    def test_score_value_zero(self):
        self.assertEqual(self.vars["outreach_kpi_score_value"], 0)

    def test_sources_total_zero(self):
        self.assertEqual(self.vars["outreach_kpi_sources_total"], 0)

    def test_sources_data_empty(self):
        self.assertEqual(self.vars["outreach_kpi_sources_data"], [])

    def test_confidence_value_zero(self):
        self.assertAlmostEqual(self.vars["outreach_kpi_confidence_value"], 0.0)

    def test_confidence_percent_zero(self):
        self.assertEqual(self.vars["outreach_kpi_confidence_percent"], 0)

    def test_confidence_status_empty(self):
        self.assertEqual(self.vars["outreach_kpi_confidence_status"], "")

    def test_score_color_default_gray(self):
        # Quand label="Faible" et color="green" vient du KPI vide, la var retourne "green"
        # car _OUTREACH_EMPTY.kpi.score_sanitaire.color = "green"
        self.assertIn(self.vars["outreach_kpi_score_color"], ("green", "gray"))


class TestKpiVarsCleKpiManquante(unittest.TestCase):
    """Dict avec autres champs mais sans clé 'kpi' → défauts sûrs, pas d'exception."""

    def setUp(self):
        # Simule un dict qui aurait pu être construit sans T5
        self.selected = {
            "status": "a_valider",
            "message_id": "xyz",
            "objet": "Test",
            "body_md": "Corps",
            "context_json": _make_context_json_full(),
            # Pas de clé 'kpi' intentionnellement
        }
        self.vars = _extract_kpi_vars(self.selected)

    def test_no_exception(self):
        # setUp aurait levé si une exception avait été propagée
        self.assertIsNotNone(self.vars)

    def test_has_data_false(self):
        # Sans kpi, tout est défaut → has_data False
        self.assertFalse(self.vars["outreach_kpi_has_data"])

    def test_score_value_zero(self):
        self.assertEqual(self.vars["outreach_kpi_score_value"], 0)

    def test_sources_data_empty(self):
        self.assertEqual(self.vars["outreach_kpi_sources_data"], [])

    def test_confidence_zero(self):
        self.assertAlmostEqual(self.vars["outreach_kpi_confidence_value"], 0.0)

    def test_score_color_default(self):
        self.assertEqual(self.vars["outreach_kpi_score_color"], "gray")


class TestKpiVarsCritique(unittest.TestCase):
    """Score 95 (Critique) → label/color corrects."""

    def setUp(self):
        import json
        ctx = json.dumps({
            "score": {"score_total": 95, "tier": "critique"},
            "signaux_summary": [],
            "enrichissement": {},
        })
        self.vars = _extract_kpi_vars(_make_selected_outreach(ctx))

    def test_score_value(self):
        self.assertEqual(self.vars["outreach_kpi_score_value"], 95)

    def test_score_label(self):
        self.assertEqual(self.vars["outreach_kpi_score_label"], "Critique")

    def test_score_color(self):
        self.assertEqual(self.vars["outreach_kpi_score_color"], "red")

    def test_has_data_true(self):
        self.assertTrue(self.vars["outreach_kpi_has_data"])


class TestKpiVarsConfidenceFallback(unittest.TestCase):
    """contact_type = fallback_dirigeant → status correct."""

    def setUp(self):
        import json
        ctx = json.dumps({
            "score": {"score_total": 55, "tier": "modere"},
            "signaux_summary": [{"source_name": "RTL", "titre": "t1"}],
            "enrichissement": {
                "confidence": 0.55,
                "contact_type": "fallback_dirigeant",
            },
        })
        self.vars = _extract_kpi_vars(_make_selected_outreach(ctx))

    def test_confidence_status(self):
        self.assertEqual(self.vars["outreach_kpi_confidence_status"], "fallback_dirigeant")

    def test_confidence_percent(self):
        self.assertEqual(self.vars["outreach_kpi_confidence_percent"], 55)

    def test_sources_total(self):
        self.assertEqual(self.vars["outreach_kpi_sources_total"], 1)


class TestKpiVarsSourcesDataTypes(unittest.TestCase):
    """sources_data : chaque élément a bien les bons types (str, int)."""

    def setUp(self):
        import json
        ctx = json.dumps({
            "score": {"score_total": 40, "tier": "modere"},
            "signaux_summary": [
                {"source_name": "Source A", "titre": "t"},
                {"source_name": "Source A", "titre": "t2"},
                {"source_name": "Source B", "titre": "t3"},
            ],
            "enrichissement": {"confidence": 0.7, "contact_type": "cible"},
        })
        self.vars = _extract_kpi_vars(_make_selected_outreach(ctx))

    def test_sources_data_source_type(self):
        for item in self.vars["outreach_kpi_sources_data"]:
            self.assertIsInstance(item["source"], str)

    def test_sources_data_count_type(self):
        for item in self.vars["outreach_kpi_sources_data"]:
            self.assertIsInstance(item["count"], int)

    def test_sources_data_sorted_desc(self):
        counts = [item["count"] for item in self.vars["outreach_kpi_sources_data"]]
        self.assertEqual(counts, sorted(counts, reverse=True))


# ---------------------------------------------------------------------------
# Tests avec Reflex (optionnels, skippés si Reflex absent)
# ---------------------------------------------------------------------------

def _try_import_dashboard_state():
    """Tente d'importer DashboardState depuis state.py."""
    try:
        _state_dir = str(Path(__file__).resolve().parents[2])
        if _state_dir not in sys.path:
            sys.path.insert(0, _state_dir)
        from state import DashboardState, _OUTREACH_EMPTY as _EMPTY  # noqa: PLC0415
        return DashboardState, _EMPTY
    except ImportError:
        return None, None


_DashboardState, _STATE_OUTREACH_EMPTY = _try_import_dashboard_state()
_REFLEX_AVAILABLE = _DashboardState is not None


@unittest.skipUnless(_REFLEX_AVAILABLE, "Reflex non disponible dans cet environnement")
class TestDashboardStateKpiVars(unittest.TestCase):
    """Vérifie que les @rx.var de DashboardState retournent les mêmes valeurs
    que _extract_kpi_vars (nécessite Reflex installé)."""

    def _make_state(self, selected_outreach: dict):
        state = _DashboardState()  # type: ignore[misc]
        state.selected_outreach = selected_outreach
        return state

    def test_payload_complet_score_value(self):
        ctx_json = _make_context_json_full()
        selected = _make_selected_outreach(ctx_json)
        state = self._make_state(selected)
        self.assertEqual(state.outreach_kpi_score_value, 72)

    def test_payload_complet_has_data(self):
        ctx_json = _make_context_json_full()
        selected = _make_selected_outreach(ctx_json)
        state = self._make_state(selected)
        self.assertTrue(state.outreach_kpi_has_data)

    def test_payload_vide_has_data_false(self):
        state = self._make_state(dict(_STATE_OUTREACH_EMPTY))
        self.assertFalse(state.outreach_kpi_has_data)

    def test_payload_vide_score_value_zero(self):
        state = self._make_state(dict(_STATE_OUTREACH_EMPTY))
        self.assertEqual(state.outreach_kpi_score_value, 0)

    def test_payload_vide_sources_data_empty(self):
        state = self._make_state(dict(_STATE_OUTREACH_EMPTY))
        self.assertEqual(state.outreach_kpi_sources_data, [])

    def test_payload_sans_kpi_defauts(self):
        # Dict sans clé kpi → défauts sûrs
        selected = {
            "status": "a_valider",
            "message_id": "xyz",
            "context_json": _make_context_json_full(),
        }
        state = self._make_state(selected)
        self.assertEqual(state.outreach_kpi_score_value, 0)
        self.assertFalse(state.outreach_kpi_has_data)


if __name__ == "__main__":
    unittest.main()
