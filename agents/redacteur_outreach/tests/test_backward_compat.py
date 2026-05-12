"""
Tests de compatibilite ascendante pour les messages outreach v1.0.

Verifie que les messages persistes avec redacteur_version="1.0" (avant PLAN-006)
restent lisibles, affichables et exploitables par le code mis a jour (v1.1).

Trois axes couverts :
  1. normalize_outreach_pure(fixture_v1_0) ne leve pas, retourne un dict avec 'kpi'.
     Importe depuis services/normalize.py (sans Reflex) -- tourne dans tout venv.
  2. build_outreach_kpi avec context_json minimaliste retourne le payload "vide coherent".
  3. build_outreach_kpi avec context_json None ou vide retourne aussi le payload "vide coherent".

Convention d'import :
  - build_outreach_kpi est importe directement depuis services/data.py (pas de Reflex).
  - normalize_outreach_pure est importe depuis services/normalize.py (pas de Reflex).
    Ces tests ne sont plus skippes en environnement sans Reflex.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup des chemins d'import
# ---------------------------------------------------------------------------

# Ce fichier est dans agents/redacteur_outreach/tests/
# agents/ est 3 niveaux au-dessus.
_TESTS_DIR = Path(__file__).resolve().parent
_AGENTS_ROOT = _TESTS_DIR.parents[1]  # agents/ (parents[0]=redacteur_outreach, parents[1]=agents)

# services/ est dans agents/dashboard_reflex/dashboard_reflex/services/
_SERVICES_DIR = (
    _AGENTS_ROOT / "dashboard_reflex" / "dashboard_reflex" / "services"
)

# Ajoute agents/ dans sys.path une seule fois pour les imports transitifs
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))


def _import_build_outreach_kpi():
    """
    Importe build_outreach_kpi depuis dashboard_reflex/services/data.py via
    importlib pour eviter les conflits de nommage avec d'autres modules 'data'
    dans sys.path (notamment le module stdlib 'data' ou les paquets agents/).
    """
    import importlib.util
    data_path = _SERVICES_DIR / "data.py"
    if not data_path.exists():
        raise ImportError(
            f"services/data.py introuvable : {data_path}"
        )
    spec = importlib.util.spec_from_file_location(
        "dashboard_services_data", str(data_path)
    )
    if spec is None or spec.loader is None:
        raise ImportError("Impossible de charger dashboard_services_data")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.build_outreach_kpi


def _import_normalize_outreach_pure():
    """
    Importe normalize_outreach_pure depuis dashboard_reflex/services/normalize.py.
    Ce module n'a pas de dependance Reflex et fonctionne dans tout venv Python 3.12.
    """
    import importlib.util
    normalize_path = _SERVICES_DIR / "normalize.py"
    if not normalize_path.exists():
        raise ImportError(
            f"services/normalize.py introuvable : {normalize_path}"
        )
    spec = importlib.util.spec_from_file_location(
        "dashboard_services_normalize", str(normalize_path)
    )
    if spec is None or spec.loader is None:
        raise ImportError("Impossible de charger dashboard_services_normalize")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.normalize_outreach_pure


build_outreach_kpi = _import_build_outreach_kpi()
normalize_outreach_pure = _import_normalize_outreach_pure()


# ---------------------------------------------------------------------------
# Fixture v1.0
# ---------------------------------------------------------------------------

def _make_v1_0_message(context_json: str | None = None) -> dict:
    """
    Simule un dict tel qu'il serait retourne par OutreachStorage._row_to_message
    converti en dict (via dataclasses.asdict ou row-to-dict) pour un message
    genere en version 1.0.

    Le context_json est volontairement minimaliste : seule la cle "incident"
    est presente, sans "score", "enrichissement", ni "signaux_summary".
    C'est le cas typique d'un message genere avant que build_context ne soit
    complete ou que les DBs score/enrichissement ne soient renseignees.
    """
    if context_json is None:
        context_json = json.dumps({"incident": {"marque": "X"}}, ensure_ascii=True)
    return {
        "message_id": "abc1234567890def",
        "source": "rappelconso",
        "source_id": "RC-2025-001",
        "canal": "email",
        "objet": "Suite au rappel X - tracabilite",
        "body_md": "Bonjour,\n\nSuite au rappel du produit X...",
        "body_fallback": "Bonjour,\n\nSuite au rappel du produit X...",
        "llm_used": False,
        "redacteur_version": "1.0",
        "context_json": context_json,
        "pitch_version": "1.0",
        "status": "brouillon",
        "generated_at": "2025-11-15T14:30:00+00:00",
        "validated_at": None,
        "sent_at": None,
        "notes": None,
    }


# ---------------------------------------------------------------------------
# Test 1 : normalize_outreach_pure sur fixture v1.0
# ---------------------------------------------------------------------------
# Ces tests utilisent normalize_outreach_pure (services/normalize.py) qui
# n'a pas de dependance Reflex. Ils tournent dans tout venv Python 3.12.
# Plus de @skipUnless conditionnant sur la presence de Reflex.

class TestNormalizeOutreachV10(unittest.TestCase):
    """
    normalize_outreach_pure doit traiter un message v1.0 sans lever d'exception
    et retourner un dict avec la cle 'kpi' peuplee.
    """

    def setUp(self):
        self.fixture = _make_v1_0_message()
        self.result = normalize_outreach_pure(self.fixture)

    def test_no_exception_raised(self):
        # setUp aurait propage une exception si normalize_outreach_pure en levait une.
        self.assertIsNotNone(self.result)

    def test_result_is_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_kpi_key_present(self):
        self.assertIn("kpi", self.result)

    def test_kpi_has_score_sanitaire(self):
        self.assertIn("score_sanitaire", self.result["kpi"])

    def test_kpi_has_sources_media(self):
        self.assertIn("sources_media", self.result["kpi"])

    def test_kpi_has_confidence_prospect(self):
        self.assertIn("confidence_prospect", self.result["kpi"])

    def test_kpi_score_value_defaults_to_zero(self):
        # context_json minimaliste sans score -> score_total absent -> 0
        self.assertEqual(self.result["kpi"]["score_sanitaire"]["value"], 0)

    def test_kpi_sources_media_total_zero(self):
        # context_json minimaliste sans signaux_summary -> total = 0
        self.assertEqual(self.result["kpi"]["sources_media"]["total"], 0)

    def test_kpi_sources_media_by_source_empty(self):
        self.assertEqual(self.result["kpi"]["sources_media"]["by_source"], [])

    def test_kpi_confidence_value_zero(self):
        # context_json minimaliste sans enrichissement -> confidence = 0.0
        self.assertAlmostEqual(
            self.result["kpi"]["confidence_prospect"]["value"], 0.0
        )

    def test_context_json_preserved_as_string(self):
        # Le context_json serialise doit etre retourne intact (str).
        self.assertIsInstance(self.result["context_json"], str)
        self.assertEqual(
            self.result["context_json"], self.fixture["context_json"]
        )

    def test_version_field_not_in_result(self):
        # normalize_outreach_pure ne copie que les champs str_fields + llm_used + kpi.
        # 'redacteur_version' n'en fait pas partie — ne doit pas provoquer de KeyError.
        # (Sa presence ou absence dans le resultat n'est pas garantie — on verifie
        # simplement que l'appel n'a pas leve.)
        self.assertIsNotNone(self.result)


class TestNormalizeOutreachV10NoneInput(unittest.TestCase):
    """
    normalize_outreach_pure(None) retourne le dict vide coherent avec 'kpi' + 'context_json'.
    Ce cas correspond a un prospect sans message genere — mais on verifie la
    robustesse du code mis a jour.
    """

    def setUp(self):
        self.result = normalize_outreach_pure(None)

    def test_no_exception(self):
        self.assertIsNotNone(self.result)

    def test_context_json_is_empty_string(self):
        self.assertIn("context_json", self.result)
        self.assertEqual(self.result["context_json"], "")

    def test_kpi_present(self):
        self.assertIn("kpi", self.result)

    def test_kpi_score_zero(self):
        self.assertEqual(self.result["kpi"]["score_sanitaire"]["value"], 0)

    def test_kpi_sources_empty(self):
        self.assertEqual(self.result["kpi"]["sources_media"]["by_source"], [])

    def test_kpi_confidence_zero(self):
        self.assertAlmostEqual(
            self.result["kpi"]["confidence_prospect"]["value"], 0.0
        )


# ---------------------------------------------------------------------------
# Test 2 : build_outreach_kpi avec context_json minimaliste (v1.0)
# ---------------------------------------------------------------------------

class TestBuildOutreachKpiV10Minimal(unittest.TestCase):
    """
    build_outreach_kpi avec un context_json minimaliste tel que genere par un
    message v1.0 (seule cle 'incident', pas de 'score', 'enrichissement',
    ni 'signaux_summary') retourne le payload "vide coherent".
    """

    def setUp(self):
        minimal_ctx = json.dumps(
            {"incident": {"marque": "X"}}, ensure_ascii=True
        )
        self.payload = build_outreach_kpi(minimal_ctx)

    def test_no_exception(self):
        self.assertIsNotNone(self.payload)

    def test_top_level_keys_present(self):
        self.assertIn("score_sanitaire", self.payload)
        self.assertIn("sources_media", self.payload)
        self.assertIn("confidence_prospect", self.payload)

    def test_score_value_zero(self):
        # Pas de cle 'score' dans le context_json -> score_total absent -> 0
        self.assertEqual(self.payload["score_sanitaire"]["value"], 0)

    def test_score_label_is_faible(self):
        # Score 0 correspond a la tranche "Faible"
        self.assertEqual(self.payload["score_sanitaire"]["label"], "Faible")

    def test_score_color_is_green(self):
        self.assertEqual(self.payload["score_sanitaire"]["color"], "green")

    def test_sources_total_zero(self):
        # Pas de 'signaux_summary' -> total = 0
        self.assertEqual(self.payload["sources_media"]["total"], 0)

    def test_sources_by_source_empty_list(self):
        self.assertIsInstance(self.payload["sources_media"]["by_source"], list)
        self.assertEqual(len(self.payload["sources_media"]["by_source"]), 0)

    def test_confidence_value_zero(self):
        # Pas d' 'enrichissement' -> confidence = 0.0
        self.assertAlmostEqual(
            self.payload["confidence_prospect"]["value"], 0.0
        )

    def test_confidence_percent_zero(self):
        self.assertEqual(self.payload["confidence_prospect"]["percent"], 0)

    def test_confidence_status_empty(self):
        self.assertEqual(self.payload["confidence_prospect"]["status"], "")


class TestBuildOutreachKpiV10WithIncidentAndScore(unittest.TestCase):
    """
    Regression : un context_json v1.0 qui a un 'score' mais pas d' 'enrichissement'
    ni de 'signaux_summary' doit retourner le score sans lever d'exception.
    """

    def setUp(self):
        ctx = json.dumps(
            {
                "incident": {"marque": "ACME", "motif": "Listeria"},
                "score": {"score_total": 65, "tier": "eleve"},
                # Pas d'enrichissement, pas de signaux
            },
            ensure_ascii=True,
        )
        self.payload = build_outreach_kpi(ctx)

    def test_no_exception(self):
        self.assertIsNotNone(self.payload)

    def test_score_value_populated(self):
        self.assertEqual(self.payload["score_sanitaire"]["value"], 65)

    def test_score_label_eleve(self):
        self.assertEqual(self.payload["score_sanitaire"]["label"], "Eleve")

    def test_sources_total_zero(self):
        self.assertEqual(self.payload["sources_media"]["total"], 0)

    def test_confidence_zero(self):
        self.assertAlmostEqual(
            self.payload["confidence_prospect"]["value"], 0.0
        )


# ---------------------------------------------------------------------------
# Test 3 : context_json None ou vide -> payload "vide coherent"
# ---------------------------------------------------------------------------

class TestBuildOutreachKpiEmptyOrNone(unittest.TestCase):
    """
    build_outreach_kpi avec context_json=None, "", ou "{}" retourne le payload
    vide coherent sans lever d'exception.
    Couvre le cas d'un message genere sans donnees DB disponibles.
    """

    _EXPECTED_EMPTY_SCORE = {
        "value": 0,
        "label": "Faible",
        "color": "green",
    }

    def _assert_is_empty_payload(self, payload: dict, case_label: str) -> None:
        with self.subTest(case=case_label):
            self.assertIsNotNone(payload, f"{case_label} : payload ne doit pas etre None")
            self.assertIn("score_sanitaire", payload)
            self.assertIn("sources_media", payload)
            self.assertIn("confidence_prospect", payload)
            self.assertEqual(
                payload["score_sanitaire"]["value"], 0,
                f"{case_label} : score_value doit etre 0"
            )
            self.assertEqual(
                payload["sources_media"]["total"], 0,
                f"{case_label} : sources_total doit etre 0"
            )
            self.assertEqual(
                payload["sources_media"]["by_source"], [],
                f"{case_label} : by_source doit etre []"
            )
            self.assertAlmostEqual(
                payload["confidence_prospect"]["value"], 0.0,
                msg=f"{case_label} : confidence_value doit etre 0.0"
            )
            self.assertEqual(
                payload["confidence_prospect"]["percent"], 0,
                f"{case_label} : confidence_percent doit etre 0"
            )

    def test_none_returns_empty_payload(self):
        self._assert_is_empty_payload(build_outreach_kpi(None), "None")

    def test_empty_string_returns_empty_payload(self):
        self._assert_is_empty_payload(build_outreach_kpi(""), "empty string")

    def test_json_empty_dict_returns_empty_payload(self):
        self._assert_is_empty_payload(build_outreach_kpi("{}"), "'{}'")

    def test_invalid_json_returns_empty_payload(self):
        self._assert_is_empty_payload(
            build_outreach_kpi("{invalid json"), "malformed JSON"
        )

    def test_json_array_returns_empty_payload(self):
        # JSON valide mais pas un dict
        self._assert_is_empty_payload(
            build_outreach_kpi("[1, 2, 3]"), "JSON array"
        )

    def test_none_score_sanitaire_has_correct_structure(self):
        payload = build_outreach_kpi(None)
        score = payload["score_sanitaire"]
        self.assertIsInstance(score["value"], int)
        self.assertIsInstance(score["label"], str)
        self.assertIsInstance(score["color"], str)

    def test_none_sources_media_by_source_is_list(self):
        payload = build_outreach_kpi(None)
        self.assertIsInstance(payload["sources_media"]["by_source"], list)

    def test_none_confidence_value_is_float(self):
        payload = build_outreach_kpi(None)
        self.assertIsInstance(payload["confidence_prospect"]["value"], float)


# ---------------------------------------------------------------------------
# Regression : context_json avec cles inattendues ne leve pas
# ---------------------------------------------------------------------------

class TestBuildOutreachKpiUnexpectedKeys(unittest.TestCase):
    """
    Un context_json v1.0 avec des cles non documentees ou manquantes ne doit
    pas lever d'exception (robustesse de la couche KPI).
    """

    def test_extra_top_level_keys_ignored(self):
        ctx = json.dumps(
            {
                "incident": {"marque": "X"},
                "champ_inconnu": {"foo": "bar"},
                "autre_inconnu": 42,
            },
            ensure_ascii=True,
        )
        payload = build_outreach_kpi(ctx)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["score_sanitaire"]["value"], 0)

    def test_score_with_none_score_total(self):
        ctx = json.dumps(
            {
                "incident": {"marque": "X"},
                "score": {"score_total": None, "tier": "inconnu"},
            },
            ensure_ascii=True,
        )
        payload = build_outreach_kpi(ctx)
        self.assertEqual(payload["score_sanitaire"]["value"], 0)

    def test_enrichissement_as_empty_dict(self):
        ctx = json.dumps(
            {
                "incident": {"marque": "X"},
                "enrichissement": {},
            },
            ensure_ascii=True,
        )
        payload = build_outreach_kpi(ctx)
        self.assertAlmostEqual(payload["confidence_prospect"]["value"], 0.0)
        self.assertEqual(payload["confidence_prospect"]["status"], "")

    def test_signaux_summary_with_missing_source_name(self):
        ctx = json.dumps(
            {
                "incident": {"marque": "X"},
                "signaux_summary": [
                    {"titre": "Sans source_name"},
                    {"source_name": None, "titre": "source_name None"},
                    {"source_name": "Valide", "titre": "ok"},
                ],
            },
            ensure_ascii=True,
        )
        payload = build_outreach_kpi(ctx)
        # Seule la source "Valide" doit apparaitre
        self.assertEqual(payload["sources_media"]["total"], 1)
        self.assertEqual(
            payload["sources_media"]["by_source"][0]["source"], "Valide"
        )


if __name__ == "__main__":
    unittest.main()
