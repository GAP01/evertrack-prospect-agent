"""Tests unitaires du scorer de crédibilité."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from detecteur_signaux.scorer import (
    compute_score,
    score_brand_known,
    score_recency,
    score_recurrence,
    score_sentiment,
    score_source_weight,
    status_for_score,
)


class TestSourceWeight(unittest.TestCase):
    def test_exact_match_lsa(self):
        self.assertEqual(score_source_weight("LSA"), 30)

    def test_substring_le_monde(self):
        self.assertEqual(score_source_weight("Le Monde.fr"), 28)

    def test_reddit_france(self):
        self.assertEqual(score_source_weight("r/france"), 15)

    def test_unknown_default(self):
        # source inconnue → poids par défaut (12 après ajustement)
        self.assertEqual(score_source_weight("BlogQuelconque.fr"), 12)

    def test_empty_source(self):
        self.assertEqual(score_source_weight(""), 12)

    def test_case_insensitive(self):
        self.assertEqual(score_source_weight("LE MONDE"), 28)


class TestRecurrence(unittest.TestCase):
    def test_zero_sources(self):
        self.assertEqual(score_recurrence(0), 0)

    def test_one_source(self):
        self.assertEqual(score_recurrence(1), 10)

    def test_three_sources_cap(self):
        # 3 sources = 30, et on ne dépasse pas
        self.assertEqual(score_recurrence(3), 30)

    def test_many_sources_capped(self):
        self.assertEqual(score_recurrence(10), 30)


class TestRecency(unittest.TestCase):
    def test_fresh(self):
        now = datetime(2026, 4, 23, 12, 0, 0)
        detected = now - timedelta(hours=1)
        self.assertEqual(score_recency(detected, now=now), 15)

    def test_two_days(self):
        now = datetime(2026, 4, 23, 12, 0, 0)
        detected = now - timedelta(hours=48)
        self.assertEqual(score_recency(detected, now=now), 10)

    def test_five_days(self):
        now = datetime(2026, 4, 23, 12, 0, 0)
        detected = now - timedelta(days=5)
        self.assertEqual(score_recency(detected, now=now), 5)

    def test_very_old(self):
        now = datetime(2026, 4, 23, 12, 0, 0)
        detected = now - timedelta(days=30)
        self.assertEqual(score_recency(detected, now=now), 0)


class TestBrandKnown(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "incidents.sqlite"
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("CREATE TABLE incidents (marque TEXT)")
            conn.executemany(
                "INSERT INTO incidents (marque) VALUES (?)",
                [("Nestlé",), ("Lustucru",), ("Carrefour",)],
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        try:
            self.tmpdir.cleanup()
        except (OSError, PermissionError):
            pass  # Windows : fichier SQLite parfois encore locké

    def test_exact_brand_known(self):
        self.assertEqual(score_brand_known("Nestlé", self.path), 10)

    def test_accents_insensitive(self):
        self.assertEqual(score_brand_known("nestle", self.path), 10)

    def test_substring_match(self):
        # "Nestlé France" doit matcher "Nestlé" dans la DB
        self.assertEqual(score_brand_known("Nestlé France", self.path), 0)
        # Mais inversement, si la marque de la DB contient le needle
        # (needle court dans brand long). Notre impl fait needle in brand,
        # donc "Nest" (court) devrait trouver "Nestlé" (long).
        self.assertEqual(score_brand_known("Nestl", self.path), 10)

    def test_unknown_brand(self):
        self.assertEqual(score_brand_known("InconnuBrand", self.path), 0)

    def test_no_brand(self):
        self.assertEqual(score_brand_known(None, self.path), 0)
        self.assertEqual(score_brand_known("", self.path), 0)

    def test_missing_db(self):
        self.assertEqual(
            score_brand_known("Nestlé", Path("/nonexistent/path.sqlite")), 0
        )

    def test_none_db(self):
        self.assertEqual(score_brand_known("Nestlé", None), 0)


class TestSentiment(unittest.TestCase):
    def test_no_negatives(self):
        self.assertEqual(score_sentiment("Nouveau produit en rayon"), 0)

    def test_one_negative(self):
        self.assertEqual(score_sentiment("Alerte sur un produit"), 5)

    def test_two_negatives(self):
        self.assertEqual(
            score_sentiment("Alerte grave, risque de décès possible"), 10
        )

    def test_accents_insensitive(self):
        # "décès" doit être détecté malgré les accents
        self.assertEqual(score_sentiment("Risque de deces"), 5)


class TestCompose(unittest.TestCase):
    def test_full_composition(self):
        now = datetime(2026, 4, 23, 12, 0, 0)
        score, breakdown = compute_score(
            source_name="Le Monde",
            n_sources=2,
            detected_at=now - timedelta(hours=1),
            marque=None,
            titre="Alerte listeria grave",
            contenu="",
            incidents_db=None,
            now=now,
        )
        # source_weight = 28, recurrence = 20, recency = 15,
        # brand_known = 0, sentiment = 10 (alerte + grave = 2 négatifs) = 73
        self.assertEqual(breakdown["source_weight"], 28)
        self.assertEqual(breakdown["recurrence"], 20)
        self.assertEqual(breakdown["recency"], 15)
        self.assertEqual(breakdown["brand_known"], 0)
        self.assertEqual(breakdown["sentiment"], 10)
        self.assertEqual(score, 73)


class TestStatusForScore(unittest.TestCase):
    def test_below_threshold(self):
        self.assertEqual(status_for_score(39), "faible")

    def test_at_threshold(self):
        self.assertEqual(status_for_score(40), "a_valider")

    def test_above(self):
        self.assertEqual(status_for_score(90), "a_valider")


if __name__ == "__main__":
    unittest.main()
