"""
Tests unitaires pour redacteur_outreach.style_loader.

Verifie la normalisation ASCII, le cache module-level, la tolerance aux
fichiers absents et la compression des lignes vides.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Necessite que le cache soit remis a zero entre les tests qui utilisent des
# fichiers temporaires differents — on manipule _CACHE directement.
import redacteur_outreach.style_loader as _sl
from redacteur_outreach.style_loader import load_style_example


class TestStyleLoaderAscii(unittest.TestCase):

    def test_output_is_ascii_strict(self) -> None:
        """La sortie ne doit contenir aucun caractere > 127."""
        result = load_style_example()
        self.assertIsNotNone(result, "Le fichier example_default.txt doit exister")
        self.assertTrue(
            result.isascii(),
            "Des caracteres non-ASCII ont survecu a la normalisation",
        )

    def test_output_is_string(self) -> None:
        """load_style_example() doit retourner une str (pas bytes, pas None)."""
        result = load_style_example()
        self.assertIsInstance(result, str)


class TestStyleLoaderContent(unittest.TestCase):

    def test_contient_bonjour(self) -> None:
        result = load_style_example()
        self.assertIsNotNone(result)
        self.assertIn("Bonjour", result)

    def test_contient_sylvain_zawal(self) -> None:
        result = load_style_example()
        self.assertIsNotNone(result)
        # La normalisation NFKD preserve les caracteres ASCII — "Sylvain Zawal"
        # ne contient pas d'accents donc survit intact.
        self.assertIn("Sylvain Zawal", result)

    def test_contient_evertrack_io(self) -> None:
        result = load_style_example()
        self.assertIsNotNone(result)
        self.assertIn("evertrack.io", result)


class TestStyleLoaderMissingFile(unittest.TestCase):

    def test_fichier_manquant_retourne_none(self) -> None:
        """Un chemin inexistant doit retourner None sans lever d'exception."""
        chemin_inexistant = Path("/chemin/absolument/inexistant/style_xyz.txt")
        # Assure que ce chemin n'est pas en cache
        _sl._CACHE.pop(str(chemin_inexistant.resolve()), None)

        result = load_style_example(path=chemin_inexistant)
        self.assertIsNone(result)

    def test_fichier_manquant_ne_leve_pas_exception(self) -> None:
        chemin_inexistant = Path("/chemin/absolument/inexistant/autre_style.txt")
        _sl._CACHE.pop(str(chemin_inexistant.resolve()), None)

        try:
            load_style_example(path=chemin_inexistant)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"load_style_example a leve une exception inattendue : {exc}")


class TestStyleLoaderCache(unittest.TestCase):

    def test_cache_un_seul_io(self) -> None:
        """Deux appels successifs sur le meme chemin ne declenchent qu'une seule IO."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as fh:
            fh.write("Bonjour,\n\nExemple stylistique.\n\nCordialement.")
            tmp_path = Path(fh.name)

        resolved = str(tmp_path.resolve())
        # Nettoie le cache pour ce chemin avant le test
        _sl._CACHE.pop(resolved, None)

        read_call_count = 0
        original_read_text = Path.read_text

        def counting_read_text(self: Path, *args, **kwargs) -> str:  # type: ignore[override]
            nonlocal read_call_count
            if str(self.resolve()) == resolved:
                read_call_count += 1
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read_text):
            load_style_example(path=tmp_path)
            load_style_example(path=tmp_path)

        tmp_path.unlink(missing_ok=True)
        self.assertEqual(read_call_count, 1, "read_text doit etre appele une seule fois")


class TestStyleLoaderBlankLines(unittest.TestCase):

    def test_max_une_ligne_vide_consecutive(self) -> None:
        """
        Un fichier avec 3+ newlines consecutifs doit etre compresse
        a au plus 1 ligne vide (2 newlines consecutifs).
        """
        contenu = "Ligne A\n\n\n\nLigne B\n\n\nLigne C\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as fh:
            fh.write(contenu)
            tmp_path = Path(fh.name)

        resolved = str(tmp_path.resolve())
        _sl._CACHE.pop(resolved, None)

        result = load_style_example(path=tmp_path)
        tmp_path.unlink(missing_ok=True)

        self.assertIsNotNone(result)
        # Apres normalisation : pas de 3 newlines consecutifs
        self.assertNotIn("\n\n\n", result)

    def test_strip_trim_global(self) -> None:
        """Le resultat ne doit pas commencer ou finir par des espaces/newlines."""
        contenu = "\n\n  Bonjour.\n\nCordialement.  \n\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as fh:
            fh.write(contenu)
            tmp_path = Path(fh.name)

        resolved = str(tmp_path.resolve())
        _sl._CACHE.pop(resolved, None)

        result = load_style_example(path=tmp_path)
        tmp_path.unlink(missing_ok=True)

        self.assertIsNotNone(result)
        self.assertEqual(result, result.strip())


class TestStyleLoaderNormalisation(unittest.TestCase):

    def test_accents_supprimes(self) -> None:
        """Les accents du fichier source doivent disparaitre apres normalisation."""
        contenu_accent = "Bonjour, voici un cafe et une eglise."
        # Ecrit avec des caracteres accentues
        contenu_avec_accents = "Bonjour, voici un caf\xe9 et une \xe9glise.\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as fh:
            fh.write(contenu_avec_accents)
            tmp_path = Path(fh.name)

        resolved = str(tmp_path.resolve())
        _sl._CACHE.pop(resolved, None)

        result = load_style_example(path=tmp_path)
        tmp_path.unlink(missing_ok=True)

        self.assertIsNotNone(result)
        self.assertTrue(result.isascii())
        # Le contenu normalise sans accent doit correspondre
        self.assertEqual(result, contenu_accent.strip())

    def test_max_chars_troncature(self) -> None:
        """Un fichier depasse max_chars : la sortie doit etre <= max_chars."""
        # Genere 3000 caracteres
        contenu = ("Mot " * 750).strip()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False
        ) as fh:
            fh.write(contenu)
            tmp_path = Path(fh.name)

        resolved = str(tmp_path.resolve())
        _sl._CACHE.pop(resolved, None)

        result = load_style_example(path=tmp_path, max_chars=500)
        tmp_path.unlink(missing_ok=True)

        self.assertIsNotNone(result)
        self.assertLessEqual(len(result), 500)


if __name__ == "__main__":
    unittest.main()
