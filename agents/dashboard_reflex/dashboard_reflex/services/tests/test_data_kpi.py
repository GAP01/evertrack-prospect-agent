"""Tests unitaires pour build_outreach_kpi dans services/data.py.

Ces tests ne nécessitent pas Reflex ni SQLite : ils ciblent uniquement
la logique de parsing du context_json et de construction du payload KPI.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Rend le module dashboard_reflex importable sans lancer Reflex.
# On insère agents/ dans sys.path pour permettre les imports de dépendances
# transitives (redacteur_outreach, etc.) si nécessaire, puis on importe
# uniquement build_outreach_kpi qui n'a aucune dépendance Reflex.
_SERVICES_DIR = Path(__file__).resolve().parents[1]
_AGENTS_ROOT = Path(__file__).resolve().parents[5]
for _p in (str(_SERVICES_DIR), str(_AGENTS_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import direct depuis le module data pour éviter le bootstrap Reflex complet.
from data import build_outreach_kpi  # noqa: E402


def _make_context_json(
    score_total: int = 72,
    tier: str = "eleve",
    dimensions: list | None = None,
    signaux: list | None = None,
    confidence: float = 0.85,
    contact_type: str = "cible",
    match_status: str = "found",
) -> str:
    """Construit un context_json complet pour les fixtures de test."""
    if dimensions is None:
        dimensions = [
            {"name": "risque_sanitaire", "raw": 80, "weight": 0.5, "rationale": "Listeria"},
            {"name": "ampleur_geo", "raw": 60, "weight": 0.25, "rationale": "National"},
        ]
    if signaux is None:
        signaux = [
            {"signal_id": "abc1", "source_name": "Marmiton", "titre": "Rappel fromage"},
            {"signal_id": "abc2", "source_name": "TF1 Info", "titre": "Alerte lait"},
            {"signal_id": "abc3", "source_name": "Marmiton", "titre": "Suite fromage"},
        ]
    ctx = {
        "incident": {"marque": "ACME", "motif": "Presence de Listeria"},
        "score": {
            "score_total": score_total,
            "tier": tier,
            "dimensions": dimensions,
        },
        "enrichissement": {
            "siren": "123456789",
            "raison_sociale": "ACME SAS",
            "contact_nom": "Jean Dupont",
            "contact_titre": "Directeur Qualite",
            "contact_type": contact_type,
            "confidence": confidence,
            "match_status": match_status,
        },
        "signaux_summary": signaux,
    }
    return json.dumps(ctx, ensure_ascii=True)


class TestBuildOutreachKpiComplete(unittest.TestCase):
    """context_json complet → payload correct."""

    def setUp(self):
        self.payload = build_outreach_kpi(_make_context_json())

    def test_top_level_keys(self):
        self.assertIn("score_sanitaire", self.payload)
        self.assertIn("sources_media", self.payload)
        self.assertIn("confidence_prospect", self.payload)

    def test_score_value(self):
        self.assertEqual(self.payload["score_sanitaire"]["value"], 72)

    def test_score_label_eleve(self):
        self.assertEqual(self.payload["score_sanitaire"]["label"], "Eleve")

    def test_score_color_eleve(self):
        self.assertEqual(self.payload["score_sanitaire"]["color"], "orange")

    def test_sources_total(self):
        # 3 signaux : 2 Marmiton + 1 TF1 Info
        self.assertEqual(self.payload["sources_media"]["total"], 3)

    def test_sources_aggregation(self):
        by_source = self.payload["sources_media"]["by_source"]
        # Marmiton doit être en tête (2 occurrences)
        self.assertEqual(by_source[0]["source"], "Marmiton")
        self.assertEqual(by_source[0]["count"], 2)
        self.assertEqual(by_source[1]["source"], "TF1 Info")
        self.assertEqual(by_source[1]["count"], 1)

    def test_confidence_value(self):
        self.assertAlmostEqual(self.payload["confidence_prospect"]["value"], 0.85)

    def test_confidence_percent(self):
        self.assertEqual(self.payload["confidence_prospect"]["percent"], 85)

    def test_confidence_status(self):
        self.assertEqual(self.payload["confidence_prospect"]["status"], "cible")


class TestBuildOutreachKpiNone(unittest.TestCase):
    """context_json = None → payload vide cohérent, pas d'exception."""

    def setUp(self):
        self.payload = build_outreach_kpi(None)

    def test_no_exception(self):
        # setUp aurait levé une exception si build_outreach_kpi en levait une
        self.assertIsNotNone(self.payload)

    def test_score_value_zero(self):
        self.assertEqual(self.payload["score_sanitaire"]["value"], 0)

    def test_sources_total_zero(self):
        self.assertEqual(self.payload["sources_media"]["total"], 0)

    def test_sources_by_source_empty(self):
        self.assertEqual(self.payload["sources_media"]["by_source"], [])

    def test_confidence_value_zero(self):
        self.assertAlmostEqual(self.payload["confidence_prospect"]["value"], 0.0)

    def test_confidence_percent_zero(self):
        self.assertEqual(self.payload["confidence_prospect"]["percent"], 0)


class TestBuildOutreachKpiEmptyJson(unittest.TestCase):
    """context_json = '{}' (JSON vide) → payload vide cohérent."""

    def setUp(self):
        self.payload = build_outreach_kpi("{}")

    def test_no_exception(self):
        self.assertIsNotNone(self.payload)

    def test_score_value_zero(self):
        self.assertEqual(self.payload["score_sanitaire"]["value"], 0)

    def test_sources_total_zero(self):
        self.assertEqual(self.payload["sources_media"]["total"], 0)

    def test_confidence_zero(self):
        self.assertAlmostEqual(self.payload["confidence_prospect"]["value"], 0.0)


class TestBuildOutreachKpiMalformedJson(unittest.TestCase):
    """context_json malformé → payload vide cohérent, pas d'exception."""

    def test_invalid_json_string(self):
        payload = build_outreach_kpi("{not valid json")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["score_sanitaire"]["value"], 0)
        self.assertEqual(payload["sources_media"]["by_source"], [])
        self.assertEqual(payload["confidence_prospect"]["percent"], 0)

    def test_json_array_not_dict(self):
        # JSON valide mais pas un dict : [1, 2, 3]
        payload = build_outreach_kpi("[1, 2, 3]")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["score_sanitaire"]["value"], 0)

    def test_empty_string(self):
        payload = build_outreach_kpi("")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["score_sanitaire"]["value"], 0)


class TestScoreLabelColorMapping(unittest.TestCase):
    """Mapping label/color pour 4 points représentatifs du barème."""

    def _kpi(self, score: int) -> dict:
        ctx = _make_context_json(score_total=score, tier="test")
        return build_outreach_kpi(ctx)["score_sanitaire"]

    def test_score_20_faible(self):
        kpi = self._kpi(20)
        self.assertEqual(kpi["label"], "Faible")
        self.assertEqual(kpi["color"], "green")
        self.assertEqual(kpi["value"], 20)

    def test_score_50_modere(self):
        kpi = self._kpi(50)
        self.assertEqual(kpi["label"], "Modere")
        self.assertEqual(kpi["color"], "amber")
        self.assertEqual(kpi["value"], 50)

    def test_score_75_eleve(self):
        kpi = self._kpi(75)
        self.assertEqual(kpi["label"], "Eleve")
        self.assertEqual(kpi["color"], "orange")
        self.assertEqual(kpi["value"], 75)

    def test_score_95_critique(self):
        kpi = self._kpi(95)
        self.assertEqual(kpi["label"], "Critique")
        self.assertEqual(kpi["color"], "red")
        self.assertEqual(kpi["value"], 95)


class TestSourcesAggregation(unittest.TestCase):
    """Agrégation des sources médiatiques depuis signaux_summary."""

    def test_single_source(self):
        ctx = _make_context_json(
            signaux=[
                {"source_name": "RTL", "titre": "t1"},
                {"source_name": "RTL", "titre": "t2"},
            ]
        )
        payload = build_outreach_kpi(ctx)
        self.assertEqual(payload["sources_media"]["total"], 2)
        self.assertEqual(len(payload["sources_media"]["by_source"]), 1)
        self.assertEqual(payload["sources_media"]["by_source"][0]["count"], 2)

    def test_three_distinct_sources_sorted(self):
        ctx = _make_context_json(
            signaux=[
                {"source_name": "A", "titre": ""},
                {"source_name": "B", "titre": ""},
                {"source_name": "B", "titre": ""},
                {"source_name": "C", "titre": ""},
                {"source_name": "C", "titre": ""},
                {"source_name": "C", "titre": ""},
            ]
        )
        payload = build_outreach_kpi(ctx)
        by_source = payload["sources_media"]["by_source"]
        counts = [e["count"] for e in by_source]
        # Tri décroissant attendu : [3, 2, 1]
        self.assertEqual(counts, [3, 2, 1])
        self.assertEqual(by_source[0]["source"], "C")

    def test_missing_source_name_skipped(self):
        ctx = _make_context_json(
            signaux=[
                {"source_name": "Valide", "titre": "ok"},
                {"source_name": "", "titre": "sans source"},
                {"titre": "sans cle source_name"},
            ]
        )
        payload = build_outreach_kpi(ctx)
        # Seule la source "Valide" doit apparaître
        self.assertEqual(payload["sources_media"]["total"], 1)
        self.assertEqual(payload["sources_media"]["by_source"][0]["source"], "Valide")

    def test_empty_signaux_list(self):
        ctx = _make_context_json(signaux=[])
        payload = build_outreach_kpi(ctx)
        self.assertEqual(payload["sources_media"]["total"], 0)
        self.assertEqual(payload["sources_media"]["by_source"], [])


def _try_import_normalize_outreach():
    """
    Tente d'importer _normalize_outreach depuis state.py.
    Retourne None si Reflex n'est pas installé (worktree sans venv dédié).
    """
    try:
        # state.py est 2 niveaux au-dessus du dossier services/tests/
        _state_dir = str(Path(__file__).resolve().parents[2])
        if _state_dir not in sys.path:
            sys.path.insert(0, _state_dir)
        from state import _normalize_outreach  # noqa: PLC0415
        return _normalize_outreach
    except ImportError:
        return None


_normalize_outreach = _try_import_normalize_outreach()
_REFLEX_AVAILABLE = _normalize_outreach is not None


class TestBuildOutreachKpiSizeCap(unittest.TestCase):
    """
    build_outreach_kpi doit retourner le payload vide si context_json
    depasse 64 Ko (protection contre injection de contenu volumineux).
    """

    def test_100kb_string_returns_empty_payload(self):
        """Un context_json de 100 Ko retourne le payload vide sans exception."""
        # Construit un JSON valide mais enorme (rempli de valeurs)
        large_str = "x" * (100 * 1024)  # 100 Ko de caracteres
        payload = build_outreach_kpi(large_str)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["score_sanitaire"]["value"], 0)
        self.assertEqual(payload["sources_media"]["total"], 0)
        self.assertEqual(payload["sources_media"]["by_source"], [])
        self.assertAlmostEqual(payload["confidence_prospect"]["value"], 0.0)

    def test_65537_bytes_triggers_cap(self):
        """Un string de 65537 octets (juste au-dessus de 64 Ko) est rejete."""
        over_cap = "a" * 65537
        payload = build_outreach_kpi(over_cap)
        self.assertEqual(payload["score_sanitaire"]["value"], 0)

    def test_65536_bytes_not_capped(self):
        """Un string de exactement 65536 octets (= 64 Ko) est tente de parser."""
        # 65536 octets de JSON invalide -> fallback ValueError, pas cap
        at_cap = "x" * 65536
        payload = build_outreach_kpi(at_cap)
        # Resultat : payload vide (JSON invalide), mais pas a cause du cap
        self.assertEqual(payload["score_sanitaire"]["value"], 0)


@unittest.skipUnless(_REFLEX_AVAILABLE, "Reflex non disponible dans cet environnement")
class TestNormalizeOutreachContextJson(unittest.TestCase):
    """_normalize_outreach inclut context_json et kpi (nécessite Reflex installé)."""

    def test_context_json_preserved(self):
        raw_ctx = '{"incident": {"marque": "ACME"}}'
        result = _normalize_outreach({"context_json": raw_ctx})
        self.assertEqual(result["context_json"], raw_ctx)

    def test_kpi_present_in_result(self):
        raw_ctx = _make_context_json()
        result = _normalize_outreach({"context_json": raw_ctx})
        self.assertIn("kpi", result)
        self.assertIn("score_sanitaire", result["kpi"])

    def test_normalize_none_has_context_json(self):
        result = _normalize_outreach(None)
        self.assertIn("context_json", result)
        self.assertEqual(result["context_json"], "")

    def test_normalize_none_has_kpi(self):
        result = _normalize_outreach(None)
        self.assertIn("kpi", result)
        self.assertEqual(result["kpi"]["score_sanitaire"]["value"], 0)


if __name__ == "__main__":
    unittest.main()
