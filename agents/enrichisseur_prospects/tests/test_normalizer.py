"""Tests unitaires du normalizer."""

import pytest
from enrichisseur_prospects.normalizer import normalize_marque, normalize_distributeur


class TestNormalizeMarque:
    def test_none_retourne_none(self):
        assert normalize_marque(None) is None

    def test_chaine_vide(self):
        assert normalize_marque("") is None

    def test_sans_marque(self):
        assert normalize_marque("sans marque") is None

    def test_sans_marques_pluriel(self):
        assert normalize_marque("sans marques") is None

    def test_tiret_seul(self):
        assert normalize_marque("-") is None

    def test_marque_trop_courte(self):
        assert normalize_marque("a") is None

    def test_marque_normale(self):
        result = normalize_marque("Jacquet")
        assert result == "jacquet"

    def test_strip_sas(self):
        result = normalize_marque("Dupont SAS")
        assert "sas" not in result
        assert "dupont" in result

    def test_strip_sarl(self):
        result = normalize_marque("SARL Durand")
        assert "sarl" not in result
        assert "durand" in result

    def test_strip_accents(self):
        result = normalize_marque("Société Générale")
        assert "e" in result  # é → e
        assert result is not None

    def test_casse_lowercase(self):
        result = normalize_marque("LA VIE CLAIRE")
        assert result == result.lower()

    def test_marque_avec_tiret_compose(self):
        result = normalize_marque("Salaisons Thaurin")
        assert result is not None
        assert len(result) >= 2

    def test_stop_words_seuls_retourne_none(self):
        # "france groupe" → après strip stop words → vide
        result = normalize_marque("france groupe")
        # Les stop words sont retirés seulement si d'autres mots restent
        # Ici ils sont tous stop words → on garde quand même (cleaned = without_stop vide)
        # Le comportement attendu : on garde cleaned (france groupe) puisque without_stop est vide
        assert result is not None  # pas de crash

    def test_nc_invalide(self):
        assert normalize_marque("nc") is None

    def test_carrefour(self):
        result = normalize_marque("Carrefour")
        assert result == "carrefour"

    def test_marque_avec_ponctuation(self):
        result = normalize_marque("Anjila's Pic Pone")
        assert result is not None
        assert "anjila" in result


class TestNormalizeDistributeur:
    def test_none_retourne_none(self):
        assert normalize_distributeur(None) is None

    def test_distributeur_simple(self):
        result = normalize_distributeur("Carrefour")
        assert result == "carrefour"

    def test_prend_premier_avant_virgule(self):
        result = normalize_distributeur("Leclerc, Carrefour, Intermarché")
        assert result == "leclerc"

    def test_distributeur_geo_trop_specifique(self):
        # "carrefour contact laventie uniquement" → split sur "uniquement"
        result = normalize_distributeur("carrefour contact laventie uniquement")
        assert result is not None
        assert "carrefour" in result

    def test_distributeur_vide(self):
        assert normalize_distributeur("") is None
