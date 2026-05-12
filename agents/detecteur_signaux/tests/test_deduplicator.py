"""Tests unitaires du déduplicateur."""

from __future__ import annotations

import unittest
from datetime import datetime

from detecteur_signaux.deduplicator import (
    compute_signal_id,
    normalize_title,
)


class TestNormalizeTitle(unittest.TestCase):
    def test_basic_lowercase(self):
        self.assertEqual(normalize_title("Hello World"), "hello world")

    def test_accents_stripped(self):
        self.assertEqual(normalize_title("Nestlé Éveille"), "nestle eveille")

    def test_punctuation_removed(self):
        self.assertEqual(normalize_title("Rappel, alerte! Urgent."), "rappel alerte urgent")

    def test_truncated_to_80(self):
        s = "a" * 200
        self.assertEqual(len(normalize_title(s)), 80)

    def test_empty(self):
        self.assertEqual(normalize_title(""), "")


class TestSignalId(unittest.TestCase):
    def test_same_brand_symptom_day_returns_same_id(self):
        dt1 = datetime(2026, 4, 23, 10, 0, 0)
        dt2 = datetime(2026, 4, 23, 18, 0, 0)

        id1 = compute_signal_id("Nestlé", "listeria", "Titre A", dt1)
        id2 = compute_signal_id("Nestlé", "listeria", "Titre B bien différent", dt2)
        self.assertEqual(id1, id2)

    def test_different_brand_different_id(self):
        dt = datetime(2026, 4, 23, 10, 0, 0)
        id1 = compute_signal_id("Nestlé", "listeria", "T", dt)
        id2 = compute_signal_id("Lactalis", "listeria", "T", dt)
        self.assertNotEqual(id1, id2)

    def test_different_week_different_id(self):
        # Depuis v2 la fenêtre est la semaine ISO, pas le jour.
        # 23/04/2026 = semaine 17, 1er/05/2026 = semaine 18
        id1 = compute_signal_id("Nestlé", "listeria", "T", datetime(2026, 4, 23))
        id2 = compute_signal_id("Nestlé", "listeria", "T", datetime(2026, 5, 1))
        self.assertNotEqual(id1, id2)

    def test_same_week_same_id(self):
        # Deux jours différents mais même semaine → même signal_id
        id1 = compute_signal_id("Nestlé", "listeria", "T", datetime(2026, 4, 20))
        id2 = compute_signal_id("Nestlé", "listeria", "T", datetime(2026, 4, 24))
        self.assertEqual(id1, id2)

    def test_different_symptom_different_id(self):
        dt = datetime(2026, 4, 23)
        id1 = compute_signal_id("Nestlé", "listeria", "T", dt)
        id2 = compute_signal_id("Nestlé", "salmonelle", "T", dt)
        self.assertNotEqual(id1, id2)

    def test_no_brand_same_produit_symptome_fusion(self):
        """Sans marque mais avec même produit+symptome+jour → même signal."""
        dt = datetime(2026, 4, 23)
        id1 = compute_signal_id(None, "listeria", "Titre A", dt, produit="raclette")
        id2 = compute_signal_id(None, "listeria", "Titre totalement différent", dt, produit="raclette")
        self.assertEqual(id1, id2)

    def test_no_brand_different_produit_different_id(self):
        dt = datetime(2026, 4, 23)
        id1 = compute_signal_id(None, "listeria", "T", dt, produit="raclette")
        id2 = compute_signal_id(None, "listeria", "T", dt, produit="reblochon")
        self.assertNotEqual(id1, id2)

    def test_no_brand_no_produit_symptome_only_fusion(self):
        """Sans marque ni produit : tous les signaux du même symptome+jour fusionnent."""
        dt = datetime(2026, 4, 23)
        id1 = compute_signal_id(None, "listeria", "Rappel produit", dt)
        id2 = compute_signal_id(None, "listeria", "Alerte générale", dt)
        self.assertEqual(id1, id2)

    def test_no_symptom_fallback_to_title(self):
        """Sans symptome ni marque : fallback sur le titre."""
        dt = datetime(2026, 4, 23)
        id1 = compute_signal_id(None, None, "Titre X", dt)
        id2 = compute_signal_id(None, None, "Titre X", dt)
        self.assertEqual(id1, id2)

        id3 = compute_signal_id(None, None, "Autre titre", dt)
        self.assertNotEqual(id1, id3)

    def test_id_length(self):
        id1 = compute_signal_id("Nestlé", "listeria", "T", datetime(2026, 4, 23))
        self.assertEqual(len(id1), 16)

    def test_accents_case_insensitive(self):
        dt = datetime(2026, 4, 23)
        id1 = compute_signal_id("Nestlé", "listeria", "T", dt)
        id2 = compute_signal_id("NESTLE", "LISTERIA", "T", dt)
        self.assertEqual(id1, id2)


if __name__ == "__main__":
    unittest.main()
