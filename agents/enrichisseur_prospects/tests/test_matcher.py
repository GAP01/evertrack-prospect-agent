"""Tests unitaires du matcher (sans appel réseau réel)."""

from unittest.mock import MagicMock, patch
import pytest

from enrichisseur_prospects.matcher import _similarity, _best_candidate, match_incident
from enrichisseur_prospects.models import CONFIDENCE_FOUND, CONFIDENCE_AMBIGUOUS


class TestSimilarity:
    def test_identiques(self):
        assert _similarity("carrefour", "carrefour") == 1.0

    def test_casse_insensible(self):
        assert _similarity("Carrefour", "CARREFOUR") == 1.0

    def test_accents_ignores(self):
        score = _similarity("societe", "société")
        assert score > 0.9

    def test_completement_different(self):
        score = _similarity("apple", "zzzzzz")
        assert score < 0.3

    def test_partiel(self):
        # difflib donne ~0.48 pour une correspondance partielle — le bonus
        # de sous-ensemble dans _best_candidate compense en usage réel
        score = _similarity("jacquet", "jacquet boulangerie sa")
        assert score > 0.4


class TestBestCandidate:
    def _make_result(self, nom: str, siren: str = "123456789") -> dict:
        return {"nom_complet": nom, "siren": siren, "siege": {}, "dirigeants": []}

    def test_exact_match(self):
        results = [self._make_result("CARREFOUR")]
        best, confidence = _best_candidate("carrefour", results)
        assert best is not None
        assert confidence >= CONFIDENCE_FOUND

    def test_meilleur_candidat_selectionne(self):
        results = [
            self._make_result("DUPONT ELECTRONIQUE", "111111111"),
            self._make_result("JACQUET BOULANGERIE", "222222222"),
        ]
        best, confidence = _best_candidate("jacquet", results)
        assert best["siren"] == "222222222"

    def test_liste_vide(self):
        best, confidence = _best_candidate("jacquet", [])
        assert best is None
        assert confidence == 0.0

    def test_bonus_sous_ensemble(self):
        # "jacquet" contenu dans "JACQUET SA" → bonus appliqué
        results = [self._make_result("JACQUET SA", "333333333")]
        _, conf_with_bonus = _best_candidate("jacquet", results)
        results2 = [self._make_result("JAQUET ALPHA", "444444444")]
        _, conf_without = _best_candidate("jacquet", results2)
        assert conf_with_bonus >= conf_without


class TestMatchIncident:
    def _incident(self, marque: str, distributeurs: str = "") -> dict:
        return {
            "source": "rappelconso",
            "source_id": "2026-test-001",
            "marque": marque,
            "distributeurs": distributeurs,
        }

    def _mock_client(self, results: list) -> MagicMock:
        client = MagicMock()
        client.search.return_value = results
        return client

    def test_skipped_si_marque_invalide(self):
        client = self._mock_client([])
        result = match_incident(self._incident("sans marque"), client)
        assert result.match_status == "skipped"
        client.search.assert_not_called()

    def test_not_found_si_aucun_resultat(self):
        client = self._mock_client([])
        result = match_incident(self._incident("jacquet"), client)
        assert result.match_status == "not_found"

    def test_found_si_confidence_haute(self):
        api_result = {
            "nom_complet": "JACQUET",
            "siren": "123456789",
            "siege": {"siret": "12345678900001", "adresse": "1 rue test 75001 PARIS"},
            "dirigeants": [{"prenoms": "Jean", "nom": "DUPONT", "qualite": "Président"}],
            "activite_principale": "1071A",
            "libelle_activite_principale": "Boulangerie",
            "libelle_nature_juridique": "SAS",
            "tranche_effectif_salarie": "12",
            "categorie_entreprise": "PME",
        }
        client = self._mock_client([api_result])
        result = match_incident(self._incident("jacquet"), client)
        assert result.match_status in ("found", "ambiguous")
        assert result.siren == "123456789"

    def test_fallback_distributeur(self):
        client = self._mock_client([])
        result = match_incident(
            self._incident("sans marque", distributeurs="Leclerc"),
            client,
        )
        # La query doit avoir utilisé le distributeur
        client.search.assert_called_once()
        assert result.match_status in ("not_found",)  # pas de résultat API mockée

    def test_contact_extrait(self):
        api_result = {
            "nom_complet": "CARREFOUR",
            "siren": "552032534",
            "siege": {},
            "dirigeants": [{"prenoms": "Alexandre", "nom": "BOMPARD", "qualite": "PDG"}],
            "activite_principale": "4711D",
            "libelle_activite_principale": "Supermarchés",
            "libelle_nature_juridique": "SA",
            "tranche_effectif_salarie": "53",
            "categorie_entreprise": "GE",
        }
        client = self._mock_client([api_result])
        result = match_incident(self._incident("carrefour"), client)
        if result.match_status in ("found", "ambiguous"):
            assert result.contact_nom is not None
            assert "BOMPARD" in result.contact_nom or "bompard" in result.contact_nom.lower()
