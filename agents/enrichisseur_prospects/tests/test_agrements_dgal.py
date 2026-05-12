"""Tests du cache local DGAL des établissements agréés."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import MagicMock, patch

from enrichisseur_prospects import agrements_dgal


# Cassette CSV — extrait représentatif du fichier SSA1_VIAN_ONG_DOM.txt
_CASSETTE_CSV = b'''"Numero de departement","Numero agrement/Approval number","SIRET","Raison SOCIALE - Enseigne commerciale/Name","Adresse/Adress","Code postal/Postal code","Commune/Town","Categorie/Category","Activites associees/Associated activities","Espece/Specy"
"01","01.004.002","08678020200031","CENTRE VIANDES BEAUVALLET FILS"," 659 AV LEON BLUM","01500","AMBERIEU-EN-BUGEY","CP","0(CS);V(MP)","B-C/O-P"
"69","69.068.013","12345678900012","FROMAGERIE EXEMPLE","123 RUE DU FROMAGE","69100","VILLEURBANNE","CP","IX(LP)","L"
"02","02.127.001","42101581900012","FLAMANT PHILIPPE","15 RUE ETIENNE FLAMAMNT","02130","BRUYERES SUR FERE","CP","",""
'''


class TestParseAgrement(unittest.TestCase):
    """Normalisation des numéros d'agrément en clé canonique 'DD.III.EEE'."""

    def test_format_complet_uppercase(self):
        self.assertEqual(agrements_dgal.parse_agrement("FR 69.068.013.CE"), "69.068.013")

    def test_sans_espaces_ni_separateurs(self):
        self.assertEqual(agrements_dgal.parse_agrement("FR69.068.013CE"), "69.068.013")

    def test_lowercase_avec_espaces_internes(self):
        self.assertEqual(agrements_dgal.parse_agrement("  fr 69 068 013 ce  "), "69.068.013")

    def test_clef_brute_seule(self):
        self.assertEqual(agrements_dgal.parse_agrement("69.068.013"), "69.068.013")

    def test_separateur_tiret(self):
        self.assertEqual(agrements_dgal.parse_agrement("69-068-013"), "69.068.013")

    def test_zero_padding_preserve(self):
        self.assertEqual(agrements_dgal.parse_agrement("FR 01.033.001.CE"), "01.033.001")

    def test_garbage(self):
        self.assertIsNone(agrements_dgal.parse_agrement("garbage"))
        self.assertIsNone(agrements_dgal.parse_agrement(""))
        self.assertIsNone(agrements_dgal.parse_agrement(None))


class TestFormatDisplay(unittest.TestCase):
    def test_format_canonical(self):
        self.assertEqual(
            agrements_dgal.format_agrement_display("69.068.013"),
            "FR 69.068.013.CE",
        )

    def test_format_normalises_input(self):
        self.assertEqual(
            agrements_dgal.format_agrement_display("FR 01.033.001.CE"),
            "FR 01.033.001.CE",
        )


class TestIterSectionRows(unittest.TestCase):
    """Parsing CSV DGAL → dicts normalisés."""

    def test_parses_all_valid_rows(self):
        rows = list(agrements_dgal._iter_section_rows(_CASSETTE_CSV, "Section I"))
        self.assertEqual(len(rows), 3)

    def test_first_row_fields(self):
        rows = list(agrements_dgal._iter_section_rows(_CASSETTE_CSV, "Section I"))
        r = rows[0]
        self.assertEqual(r["numero"], "01.004.002")
        self.assertEqual(r["siret"], "08678020200031")
        self.assertEqual(r["raison_sociale"], "CENTRE VIANDES BEAUVALLET FILS")
        self.assertEqual(r["commune"], "AMBERIEU-EN-BUGEY")
        self.assertEqual(r["section"], "Section I")

    def test_skips_lines_without_valid_agrement(self):
        bad = b'''"x","y"
"01","not_a_number"
'''
        # Avec ce header non-standard, no record valide
        rows = list(agrements_dgal._iter_section_rows(bad, "Test"))
        self.assertEqual(rows, [])


class TestRefreshAndLookup(unittest.TestCase):
    """Refresh complet end-to-end avec session HTTP mockée + lookup."""

    def setUp(self):
        # Base SQLite éphémère
        self.tmp = NamedTemporaryFile(delete=False, suffix=".sqlite")
        self.tmp.close()
        self.db_path = Path(self.tmp.name)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_refresh_then_lookup(self):
        # Mock requests.Session.get pour retourner notre cassette
        with patch.object(agrements_dgal.requests, "Session") as mock_sess_cls:
            sess = MagicMock()
            sess.headers = {}
            resp = MagicMock()
            resp.content = _CASSETTE_CSV
            resp.raise_for_status = MagicMock()
            sess.get.return_value = resp
            mock_sess_cls.return_value = sess

            report = agrements_dgal.refresh_all(
                db_path=self.db_path,
                sections=["SSA1_VIAN_ONG_DOM"],  # une seule section pour le test
            )

        self.assertEqual(len(report["sections_ok"]), 1)
        self.assertEqual(report["sections_ko"], [])
        self.assertEqual(report["total_rows_in_db"], 3)

        # Lookup OK : "FR 69.068.013.CE" → "FROMAGERIE EXEMPLE"
        result = agrements_dgal.lookup("FR 69.068.013.CE", db_path=self.db_path)
        self.assertIsNotNone(result)
        self.assertEqual(result["raison_sociale"], "FROMAGERIE EXEMPLE")
        self.assertEqual(result["siret"], "12345678900012")
        self.assertEqual(result["commune"], "VILLEURBANNE")

    def test_lookup_unknown_returns_none(self):
        # Refresh d'abord (avec mock)
        with patch.object(agrements_dgal.requests, "Session") as mock_sess_cls:
            sess = MagicMock()
            sess.headers = {}
            resp = MagicMock()
            resp.content = _CASSETTE_CSV
            resp.raise_for_status = MagicMock()
            sess.get.return_value = resp
            mock_sess_cls.return_value = sess
            agrements_dgal.refresh_all(
                db_path=self.db_path,
                sections=["SSA1_VIAN_ONG_DOM"],
            )
        # Maintenant lookup d'un numéro absent
        self.assertIsNone(agrements_dgal.lookup("FR 99.999.999.CE", db_path=self.db_path))

    def test_lookup_invalid_format_returns_none(self):
        self.assertIsNone(agrements_dgal.lookup("garbage", db_path=self.db_path))
        self.assertIsNone(agrements_dgal.lookup("", db_path=self.db_path))


if __name__ == "__main__":
    unittest.main()
