"""Tests pour la nouvelle logique dédup (semaine + familles pathogènes)."""

from __future__ import annotations

import unittest
from datetime import datetime

from detecteur_signaux.deduplicator import (
    compute_signal_id,
    iso_week_bucket,
    symptome_family,
)


class TestSymptomeFamily(unittest.TestCase):
    def test_listeria_specific(self):
        self.assertEqual(symptome_family("listeria"), "listeria")
        self.assertEqual(symptome_family("Listeria monocytogenes"), "listeria")
        self.assertEqual(symptome_family("listeriose"), "listeria")

    def test_salmonelle_specific(self):
        self.assertEqual(symptome_family("salmonelle"), "salmonelle")
        self.assertEqual(symptome_family("Salmonellose"), "salmonelle")

    def test_ecoli_specific(self):
        self.assertEqual(symptome_family("e.coli"), "ecoli")
        self.assertEqual(symptome_family("Escherichia coli"), "ecoli")
        self.assertEqual(symptome_family("STEC"), "ecoli")

    def test_generic_bacterien(self):
        # Termes génériques → bucket générique
        self.assertEqual(
            symptome_family("contamination bactérienne"), "bacterie_generique",
        )
        self.assertEqual(symptome_family("bactérie"), "bacterie_generique")
        self.assertEqual(symptome_family("toxi-infection"), "bacterie_generique")

    def test_corps_etranger_hierarchie(self):
        # Spécifique "verre" gagne sur générique "corps étranger"
        self.assertEqual(symptome_family("corps étranger (verre)"), "verre")
        self.assertEqual(symptome_family("morceau de verre"), "verre")

    def test_corps_etranger_generique(self):
        self.assertEqual(symptome_family("corps étranger"), "corps_etranger")

    def test_unknown_returns_none(self):
        self.assertIsNone(symptome_family("quelque chose d'étrange"))
        self.assertIsNone(symptome_family(""))
        self.assertIsNone(symptome_family(None))


class TestIsoWeekBucket(unittest.TestCase):
    def test_same_week(self):
        d1 = datetime(2026, 4, 20)  # lundi
        d2 = datetime(2026, 4, 24)  # vendredi
        self.assertEqual(iso_week_bucket(d1), iso_week_bucket(d2))

    def test_different_weeks(self):
        d1 = datetime(2026, 4, 19)  # dimanche → semaine N
        d2 = datetime(2026, 4, 20)  # lundi    → semaine N+1
        self.assertNotEqual(iso_week_bucket(d1), iso_week_bucket(d2))

    def test_format(self):
        self.assertRegex(iso_week_bucket(datetime(2026, 4, 20)), r"^2026-W\d{2}$")


class TestSignalIdV2(unittest.TestCase):
    def test_same_week_same_marque_same_family(self):
        """Deux articles la même semaine sur 'Nestlé listeria' → même signal_id."""
        d1 = datetime(2026, 4, 20, 10, 0)  # lundi
        d2 = datetime(2026, 4, 23, 15, 0)  # jeudi, même semaine
        id1 = compute_signal_id("Nestlé", "listeria", "Titre 1", d1)
        id2 = compute_signal_id("Nestlé", "listeria", "Titre 2", d2)
        self.assertEqual(id1, id2)

    def test_listeria_vs_listeriose_same_family(self):
        """Symptomes synonymes → même famille → même signal_id."""
        d = datetime(2026, 4, 20)
        id1 = compute_signal_id("Nestlé", "listeria", "T", d)
        id2 = compute_signal_id("Nestlé", "listeriose", "T", d)
        self.assertEqual(id1, id2)

    def test_generic_vs_specific_different_buckets(self):
        """'contamination bactérienne' (générique) ≠ 'listeria' (spécifique)."""
        d = datetime(2026, 4, 20)
        id1 = compute_signal_id("Nestlé", "contamination bactérienne", "T", d)
        id2 = compute_signal_id("Nestlé", "listeria", "T", d)
        self.assertNotEqual(id1, id2)

    def test_different_weeks_different_ids(self):
        """Deux articles distants de > 7j → signal_ids différents."""
        d1 = datetime(2026, 4, 20)  # semaine 17
        d2 = datetime(2026, 5, 4)   # semaine 19
        id1 = compute_signal_id("Nestlé", "listeria", "T", d1)
        id2 = compute_signal_id("Nestlé", "listeria", "T", d2)
        self.assertNotEqual(id1, id2)

    def test_different_brands_different_ids(self):
        d = datetime(2026, 4, 20)
        id1 = compute_signal_id("Nestlé", "listeria", "T", d)
        id2 = compute_signal_id("Lactalis", "listeria", "T", d)
        self.assertNotEqual(id1, id2)


if __name__ == "__main__":
    unittest.main()
