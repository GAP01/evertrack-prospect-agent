"""Tests unitaires du cross-referencing signal ↔ incident."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from detecteur_signaux.cross_reference import (
    MATCH_THRESHOLD_POSSIBLE,
    MATCH_THRESHOLD_STRONG,
    brand_similarity,
    compute_match,
    date_proximity,
    lead_time_days,
    product_similarity,
    symptom_match,
)


class TestBrandSimilarity(unittest.TestCase):
    def test_exact_match(self):
        self.assertGreater(brand_similarity("Nestlé", "Nestlé"), 0.95)

    def test_substring_bonus(self):
        # "Super U" contient dans "Coopérative Super U Enseigne"
        self.assertGreaterEqual(
            brand_similarity("Super U", "Coopérative Super U Enseigne"),
            0.80,
        )

    def test_accents_insensitive(self):
        self.assertGreater(brand_similarity("Nestlé", "NESTLE"), 0.95)

    def test_generic_brand_zero(self):
        self.assertEqual(brand_similarity("sans marque", "Nestlé"), 0.0)
        self.assertEqual(brand_similarity("Nestlé", "sans marques"), 0.0)

    def test_empty_zero(self):
        self.assertEqual(brand_similarity(None, "Nestlé"), 0.0)
        self.assertEqual(brand_similarity("", "Nestlé"), 0.0)

    def test_unrelated_low(self):
        self.assertLess(brand_similarity("Nestlé", "Carrefour"), 0.5)


class TestSymptomMatch(unittest.TestCase):
    def test_listeria_match(self):
        self.assertEqual(
            symptom_match(
                "listeria",
                "Présence de Listeria monocytogenes",
                "listeria monocytogenes (agent responsable de la listériose)",
            ),
            1.0,
        )

    def test_salmonelle_match(self):
        self.assertEqual(
            symptom_match("salmonelle", None, "salmonella spp (agent responsable)"),
            1.0,
        )

    def test_ecoli_match(self):
        self.assertEqual(
            symptom_match("e.coli", None, "escherichia coli shiga toxinogène (STEC)"),
            1.0,
        )

    def test_no_match(self):
        self.assertEqual(
            symptom_match("listeria", None, "salmonella spp"),
            0.0,
        )

    def test_empty_signal(self):
        self.assertEqual(symptom_match(None, "Présence de listeria", None), 0.0)

    def test_empty_incident(self):
        self.assertEqual(symptom_match("listeria", None, None), 0.0)

    def test_corps_etranger_verre(self):
        self.assertEqual(
            symptom_match(
                "corps étranger (verre)",
                "présence de morceau de verre",
                "inertes (verre, métal, plastique)",
            ),
            1.0,
        )


class TestProductSimilarity(unittest.TestCase):
    def test_exact_substring(self):
        # "raclette" ⊂ "fromage à raclette"
        self.assertGreaterEqual(
            product_similarity("raclette", "lait et produits laitiers", "fromage à raclette"),
            0.85,
        )

    def test_no_produit(self):
        self.assertEqual(
            product_similarity(None, "lait et produits laitiers", "fromage"),
            0.0,
        )


class TestDateProximity(unittest.TestCase):
    def test_same_day(self):
        d = date(2026, 4, 23)
        self.assertEqual(date_proximity(datetime(2026, 4, 23), d), 1.0)

    def test_within_window(self):
        # 15 jours sur fenêtre 30 → exp(-(15/30)²) = exp(-0.25) ≈ 0.78
        d1 = datetime(2026, 4, 1)
        d2 = date(2026, 4, 16)
        score = date_proximity(d1, d2, window_days=30)
        self.assertGreater(score, 0.7)
        self.assertLess(score, 0.9)

    def test_far_out_zero(self):
        d1 = datetime(2026, 1, 1)
        d2 = date(2026, 6, 1)
        self.assertEqual(date_proximity(d1, d2, window_days=30), 0.0)

    def test_missing_date(self):
        self.assertEqual(date_proximity(None, date(2026, 4, 23)), 0.0)


class TestLeadTime(unittest.TestCase):
    def test_signal_before_incident_positive(self):
        # Signal le 1er avril, incident le 15 avril → lead = 14j positif
        self.assertEqual(
            lead_time_days(datetime(2026, 4, 1), date(2026, 4, 15)),
            14,
        )

    def test_signal_after_incident_negative(self):
        self.assertEqual(
            lead_time_days(datetime(2026, 4, 20), date(2026, 4, 15)),
            -5,
        )

    def test_same_day_zero(self):
        self.assertEqual(
            lead_time_days(datetime(2026, 4, 15), date(2026, 4, 15)),
            0,
        )


class TestComputeMatch(unittest.TestCase):
    def test_strong_match_same_brand_symptom_product(self):
        signal = {
            "marque": "Super U",
            "symptome": "listeria",
            "produit": "fromage raclette",
            "detected_at": "2026-04-20T10:00:00",
        }
        incident = {
            "marque": "Super U",
            "sous_categorie": "lait et produits laitiers",
            "motif": "présence de Listeria monocytogenes dans fromage à raclette",
            "risques": "listeria monocytogenes",
            "date_publication": "2026-04-22",
        }
        m = compute_match(signal, incident)
        # brand 1.0 * 0.40 + symptom 1.0 * 0.30 + product 0.85 * 0.20 + date ~1.0 * 0.10
        # = 0.40 + 0.30 + 0.17 + ~0.10 = ~0.97
        self.assertGreaterEqual(m.score, MATCH_THRESHOLD_STRONG)
        self.assertEqual(m.symptom, 1.0)
        self.assertEqual(m.lead_time, 2)

    def test_possible_match_fuzzy_brand(self):
        """Cas intermédiaire : marque fuzzy + symptôme + produit → match possible."""
        signal = {
            "marque": "Super U",
            "symptome": "listeria",
            "produit": "raclette",
            "detected_at": "2026-04-20T10:00:00",
        }
        incident = {
            "marque": "Coopérative U Enseigne",  # marque floue
            "sous_categorie": "lait et produits laitiers",
            "motif": "Listeria dans fromage à raclette",
            "risques": "listeria monocytogenes",
            "date_publication": "2026-04-22",
        }
        m = compute_match(signal, incident)
        # brand faible + symptom 0.30 + product 0.17 + date 0.10
        # → doit passer le seuil "possible" (0.50) grâce à symptom + product + date
        self.assertGreaterEqual(m.score, MATCH_THRESHOLD_POSSIBLE)
        self.assertEqual(m.symptom, 1.0)

    def test_weak_match_only_symptom(self):
        signal = {
            "marque": "Nestlé",
            "symptome": "listeria",
            "produit": None,
            "detected_at": "2026-04-20T10:00:00",
        }
        incident = {
            "marque": "Carrefour",
            "sous_categorie": "viandes",
            "motif": "listeria dans saucisson",
            "risques": "listeria monocytogenes",
            "date_publication": "2026-04-20",
        }
        m = compute_match(signal, incident)
        # 0 + 0.30 + 0 + 0.10 = 0.40 — en-dessous du possible
        self.assertLess(m.score, MATCH_THRESHOLD_POSSIBLE)

    def test_no_match_different_symptom(self):
        signal = {
            "marque": "Nestlé",
            "symptome": "listeria",
            "produit": "fromage",
            "detected_at": "2026-04-20T10:00:00",
        }
        incident = {
            "marque": "Nestlé",
            "sous_categorie": "lait",
            "motif": "allergène non déclaré",
            "risques": "allergene",
            "date_publication": "2026-04-20",
        }
        m = compute_match(signal, incident)
        self.assertEqual(m.symptom, 0.0)
        # brand 1.0 * 0.40 + 0 + fuzzy product low + date 1.0 * 0.10
        # max possible ~0.50-0.55
        self.assertLess(m.score, MATCH_THRESHOLD_STRONG)


if __name__ == "__main__":
    unittest.main()
