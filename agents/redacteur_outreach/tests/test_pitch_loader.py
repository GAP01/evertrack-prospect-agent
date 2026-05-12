"""Tests unitaires pour pitch_loader."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from redacteur_outreach.pitch_loader import DEFAULT_PITCH, load_pitch


class TestPitchLoader(unittest.TestCase):

    # ------------------------------------------------------------------
    # 1. Chargement du fichier livre avec le module
    # ------------------------------------------------------------------

    def test_load_default_file_returns_full_dict(self) -> None:
        result = load_pitch(None)
        for key in DEFAULT_PITCH:
            self.assertIn(key, result, f"Cle manquante : {key}")

    # ------------------------------------------------------------------
    # 2. Fichier custom valide
    # ------------------------------------------------------------------

    def test_load_custom_file(self) -> None:
        data = {
            "version": "2.0",
            "editeur_nom": "AcmeCorp",
            "pitch_court": "TEST_VALUE",
            "cta": "Contactez-nous.",
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            tmp_path = fh.name

        try:
            result = load_pitch(tmp_path)
            self.assertEqual(result["pitch_court"], "TEST_VALUE")
            self.assertEqual(result["editeur_nom"], "AcmeCorp")
            self.assertEqual(result["version"], "2.0")
        finally:
            os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # 3. Fichier absent => defaults
    # ------------------------------------------------------------------

    def test_missing_file_returns_default(self) -> None:
        result = load_pitch("/inexistant_evertrack_pitch.json")
        self.assertEqual(result, DEFAULT_PITCH)
        # Ne doit pas etre la meme instance
        self.assertIsNot(result, DEFAULT_PITCH)

    # ------------------------------------------------------------------
    # 4. JSON invalide => defaults
    # ------------------------------------------------------------------

    def test_invalid_json_returns_default(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("not json{{{")
            tmp_path = fh.name

        try:
            result = load_pitch(tmp_path)
            self.assertEqual(result, DEFAULT_PITCH)
        finally:
            os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # 5. JSON partiel => merge avec defaults
    # ------------------------------------------------------------------

    def test_partial_json_merged_with_defaults(self) -> None:
        data = {"pitch_court": "X"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(data, fh)
            tmp_path = fh.name

        try:
            result = load_pitch(tmp_path)
            self.assertEqual(result["pitch_court"], "X")
            # Les cles absentes du fichier doivent etre remplies par les defaults
            self.assertEqual(result["editeur_nom"], DEFAULT_PITCH["editeur_nom"])
            self.assertEqual(result["signature"], DEFAULT_PITCH["signature"])
            self.assertEqual(result["cta"], DEFAULT_PITCH["cta"])
            self.assertIn("opt_out_placeholder", result)
        finally:
            os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # 6. Isolation : muter le dict retourne ne modifie pas DEFAULT_PITCH
    # ------------------------------------------------------------------

    def test_return_is_copy_not_reference(self) -> None:
        r1 = load_pitch(None)
        r2 = load_pitch(None)

        # Deux appels => deux instances distinctes
        self.assertIsNot(r1, r2)

        # Muter r1 ne doit pas affecter r2 ni DEFAULT_PITCH
        r1["editeur_nom"] = "MUTATED"
        self.assertNotEqual(DEFAULT_PITCH["editeur_nom"], "MUTATED")
        self.assertNotEqual(r2["editeur_nom"], "MUTATED")


if __name__ == "__main__":
    unittest.main()
