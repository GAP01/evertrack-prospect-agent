"""Tests unitaires du fallback regex de l'extractor.

Les tests LLM sont mockés — on vérifie la structure du fallback qui est
utilisée quand ANTHROPIC_API_KEY absente.
"""

from __future__ import annotations

import unittest

from detecteur_signaux.extractor import (
    Extraction,
    extract,
    has_negative_filter,
    has_symptom_keyword,
)


class TestNegativeFilter(unittest.TestCase):
    def test_rappel_chiens(self):
        self.assertTrue(has_negative_filter("Grand rappel des chiens errants"))

    def test_rappel_automobile(self):
        self.assertTrue(has_negative_filter("Rappel automobile Renault"))

    def test_legitimate_rappel(self):
        self.assertFalse(has_negative_filter("Rappel produit alimentaire Leclerc"))


class TestSymptomKeyword(unittest.TestCase):
    def test_listeria_present(self):
        self.assertTrue(has_symptom_keyword("Alerte listeria chez Nestlé"))

    def test_accents_tolerant(self):
        self.assertTrue(has_symptom_keyword("Allergene non declare"))

    def test_no_symptom(self):
        self.assertFalse(has_symptom_keyword("Météo du jour"))


class TestExtractRegexFallback(unittest.TestCase):
    def test_extract_listeria(self):
        res = extract(
            titre="Rappel listeria chez Nestlé",
            contenu="",
            source_name="Le Monde",
            use_llm=False,
        )
        self.assertTrue(res.is_alim)
        self.assertEqual(res.symptome, "listeria")
        self.assertEqual(res.source, "regex")

    def test_extract_corps_etranger(self):
        res = extract(
            titre="Morceau de verre dans des yaourts",
            contenu="",
            source_name="LSA",
            use_llm=False,
        )
        self.assertTrue(res.is_alim)
        self.assertIn("verre", (res.symptome or "").lower())

    def test_negative_filter_rejects(self):
        res = extract(
            titre="Rappel automobile Renault",
            contenu="",
            source_name="Le Figaro",
            use_llm=False,
        )
        self.assertFalse(res.is_alim)

    def test_no_symptom_not_alim(self):
        res = extract(
            titre="Le marché des cosmétiques en hausse",
            contenu="",
            source_name="Les Échos",
            use_llm=False,
        )
        self.assertFalse(res.is_alim)

    def test_resume_is_title(self):
        res = extract(
            titre="Rappel listeria chez Nestlé",
            contenu="",
            source_name="X",
            use_llm=False,
        )
        self.assertEqual(res.resume, "Rappel listeria chez Nestlé")

    def test_marque_extraction_pattern(self):
        res = extract(
            titre="Rappel listeria sur un produit de la marque Lactalis",
            contenu="",
            source_name="LSA",
            use_llm=False,
        )
        self.assertEqual(res.symptome, "listeria")
        # Le pattern "de la marque X" doit capturer Lactalis
        self.assertIsNotNone(res.marque)
        self.assertIn("Lactalis", res.marque or "")


if __name__ == "__main__":
    unittest.main()
