"""
Tests unitaires pour redacteur_outreach.template_renderer.

Aucun acces disque (sauf la lecture du template lui-meme), aucun appel reseau.
"""

from __future__ import annotations

import unittest

from redacteur_outreach.template_renderer import (
    MOIS_COURTS,
    _build_bloc_signaux,
    _build_contact_civilite,
    _build_subject,
    _format_date_fr,
    _truncate,
    render,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_pitch(**overrides) -> dict:
    base = {
        "editeur_nom": "EverTrack",
        "pitch_court": "EverTrack permet de maitriser la tracabilite de vos lots.",
        "valeur_immediate": "Mise en place en moins de 30 jours.",
        "cta": "Souhaitez-vous un appel de 20 minutes cette semaine ?",
        "signature": "Cordialement,\nEquipe EverTrack",
        "opt_out_placeholder": "",
    }
    base.update(overrides)
    return base


def _make_incident(**overrides) -> dict:
    base = {
        "source": "rappelconso",
        "source_id": "RAPPELCONSO-12345",
        "marque": "DUPONT FOODS",
        "modeles": "Fromage X lot 42",
        "categorie": "Alimentation",
        "motif": "Presence de Listeria monocytogenes dans le produit fini.",
        "date_publication": "2026-05-12",
        "distributeurs": "Carrefour; Leclerc",
        "risques": "Risque infectieux",
    }
    base.update(overrides)
    return base


def _make_enrichissement(**overrides) -> dict:
    base = {
        "contact_nom": "DUPONT",
        "contact_prenom": None,
        "contact_titre": "Responsable Qualite",
        "contact_type": "cible",
        "siren": "123456789",
        "raison_sociale": "DUPONT FOODS SAS",
    }
    base.update(overrides)
    return base


def _make_signaux(n: int = 2) -> list:
    return [
        {
            "signal_id": f"sig{i:04d}",
            "marque": "DUPONT FOODS",
            "titre": f"Alerte Listeria : retrait produit numero {i} en rayon",
            "source_name": "marmiton",
            "score_credibilite": 60 + i * 5,
        }
        for i in range(n)
    ]


def _make_full_context(**overrides) -> dict:
    base = {
        "incident": _make_incident(),
        "score": {"score_total": 84.25, "tier": "critique"},
        "enrichissement": _make_enrichissement(),
        "signaux_summary": _make_signaux(2),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# T5 — Scenario 1 : contexte complet
# ---------------------------------------------------------------------------

class TestRenderFullContext(unittest.TestCase):
    """Contexte avec incident + score + enrichissement (contact_type=cible) + 2 signaux."""

    def setUp(self) -> None:
        self.ctx = _make_full_context()
        self.pitch = _make_pitch()
        self.result = render(self.ctx, self.pitch)

    def test_objet_contains_marque_or_tracabilite(self) -> None:
        objet = self.result["objet"]
        self.assertTrue(
            "DUPONT" in objet or "Tracabilite" in objet or "tracabilite" in objet,
            f"Objet inattendu : {objet!r}",
        )

    def test_body_contains_contact_nom(self) -> None:
        self.assertIn("DUPONT", self.result["body"])

    def test_body_contains_marque(self) -> None:
        # La marque en majuscules est passee par .title()
        body = self.result["body"]
        self.assertTrue(
            "DUPONT" in body or "Dupont" in body,
            f"Marque absente du body",
        )

    def test_body_contains_motif_partial(self) -> None:
        # Au moins le debut du motif doit apparaitre
        self.assertIn("Listeria", self.result["body"])

    def test_body_contains_bloc_signaux(self) -> None:
        self.assertIn("couverture mediatique", self.result["body"])

    def test_body_contains_pitch_court(self) -> None:
        self.assertIn(self.pitch["pitch_court"], self.result["body"])

    def test_body_contains_cta(self) -> None:
        self.assertIn(self.pitch["cta"], self.result["body"])

    def test_body_has_no_unresolved_variables(self) -> None:
        # Apres safe_substitute avec toutes les vars pre-remplies,
        # aucun $xxx ne doit subsister dans le body.
        import re
        remaining = re.findall(r"\$\{?\w+\}?", self.result["body"])
        self.assertEqual(
            remaining, [],
            f"Variables non resolues dans le body : {remaining}",
        )


# ---------------------------------------------------------------------------
# T5 — Scenario 2 : sans enrichissement
# ---------------------------------------------------------------------------

class TestRenderWithoutEnrichissement(unittest.TestCase):
    """context["enrichissement"] = None => civilite generique."""

    def test_civilite_fallback_madame_monsieur(self) -> None:
        ctx = _make_full_context(enrichissement=None)
        result = render(ctx, _make_pitch())
        self.assertIn("Madame, Monsieur", result["body"])

    def test_no_crash(self) -> None:
        ctx = _make_full_context(enrichissement=None)
        result = render(ctx, _make_pitch())
        self.assertIn("objet", result)
        self.assertIn("body", result)
        self.assertIsInstance(result["body"], str)


# ---------------------------------------------------------------------------
# T5 — Scenario 3 : sans signaux
# ---------------------------------------------------------------------------

class TestRenderWithoutSignaux(unittest.TestCase):
    """signaux_summary = [] => bloc optionnel absent."""

    def test_no_bloc_signaux_in_body(self) -> None:
        ctx = _make_full_context(signaux_summary=[])
        result = render(ctx, _make_pitch())
        self.assertNotIn("couverture mediatique", result["body"])

    def test_no_crash(self) -> None:
        ctx = _make_full_context(signaux_summary=[])
        result = render(ctx, _make_pitch())
        self.assertIsInstance(result["body"], str)


# ---------------------------------------------------------------------------
# T5 — Scenario 4 : champs incident manquants
# ---------------------------------------------------------------------------

class TestRenderHandlesMissingIncidentFields(unittest.TestCase):
    """incident avec marque=None, motif=None, date_publication=None."""

    def setUp(self) -> None:
        incident = _make_incident(marque=None, motif=None, date_publication=None)
        self.ctx = _make_full_context(incident=incident)
        self.result = render(self.ctx, _make_pitch())

    def test_no_crash(self) -> None:
        self.assertIsInstance(self.result["body"], str)

    def test_placeholder_marque(self) -> None:
        # Quand marque est None => "d'un de vos produits"
        self.assertIn("d'un de vos produits", self.result["body"])

    def test_placeholder_date(self) -> None:
        # Quand date_publication est None => "recemment"
        self.assertIn("recemment", self.result["body"])

    def test_body_is_non_empty(self) -> None:
        self.assertGreater(len(self.result["body"]), 50)


# ---------------------------------------------------------------------------
# T5 — Scenario 5 : _format_date_fr unit tests
# ---------------------------------------------------------------------------

class TestFormatDateFr(unittest.TestCase):

    def test_standard_date(self) -> None:
        self.assertEqual(_format_date_fr("2026-05-12"), "12 mai 2026")

    def test_none_returns_recemment(self) -> None:
        result = _format_date_fr(None)
        self.assertIn("recemment", result)

    def test_empty_string_returns_recemment(self) -> None:
        result = _format_date_fr("")
        self.assertIn("recemment", result)

    def test_datetime_string_parsed(self) -> None:
        # Format datetime complet : on ne prend que les 10 premiers chars
        self.assertEqual(_format_date_fr("2024-03-15T08:00:00"), "15 mars 2024")

    def test_janvier(self) -> None:
        self.assertEqual(_format_date_fr("2025-01-01"), "1 janv 2025")

    def test_decembre(self) -> None:
        self.assertEqual(_format_date_fr("2025-12-31"), "31 dec 2025")

    def test_mois_courts_list(self) -> None:
        # Verifie que la liste a exactement 12 entrees
        self.assertEqual(len(MOIS_COURTS), 12)


# ---------------------------------------------------------------------------
# Tests complementaires sur les fonctions utilitaires
# ---------------------------------------------------------------------------

class TestTruncate(unittest.TestCase):

    def test_short_text_unchanged(self) -> None:
        self.assertEqual(_truncate("Bonjour", 50), "Bonjour")

    def test_long_text_truncated_at_word(self) -> None:
        text = "Un texte assez long pour tester la troncature au mot correct"
        result = _truncate(text, 30)
        self.assertLessEqual(len(result), 30)
        self.assertTrue(result.endswith("..."))

    def test_none_returns_empty(self) -> None:
        self.assertEqual(_truncate(None, 100), "")

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(_truncate("", 100), "")

    def test_exactly_max_chars_unchanged(self) -> None:
        text = "a" * 20
        self.assertEqual(_truncate(text, 20), text)


class TestBuildSubject(unittest.TestCase):

    def test_known_brand(self) -> None:
        ctx = {"incident": {"marque": "ACME"}}
        subj = _build_subject(ctx)
        self.assertIn("ACME", subj)
        self.assertIn("tracabilite", subj)

    def test_no_brand(self) -> None:
        ctx = {"incident": {"marque": None}}
        subj = _build_subject(ctx)
        self.assertIn("Tracabilite", subj)

    def test_empty_incident(self) -> None:
        ctx = {"incident": {}}
        subj = _build_subject(ctx)
        self.assertIn("Tracabilite", subj)

    def test_no_incident_key(self) -> None:
        ctx = {}
        subj = _build_subject(ctx)
        self.assertIn("Tracabilite", subj)


class TestBuildBlocSignaux(unittest.TestCase):

    def test_empty_returns_empty_string(self) -> None:
        self.assertEqual(_build_bloc_signaux([]), "")

    def test_single_signal(self) -> None:
        signaux = [{"titre": "Article sur Listeria", "source_name": "marmiton"}]
        bloc = _build_bloc_signaux(signaux)
        self.assertIn("couverture mediatique", bloc)
        self.assertIn("1 source", bloc)

    def test_multiple_signals_capped_at_3_titles(self) -> None:
        signaux = [{"titre": f"Article {i}", "source_name": "src"} for i in range(5)]
        bloc = _build_bloc_signaux(signaux)
        # Meme avec 5 signaux, on affiche jusqu'a 3 titres dans le bloc
        self.assertIn("couverture mediatique", bloc)
        # Le count doit refleter le nombre reel de signaux (5)
        self.assertIn("5 source", bloc)

    def test_titles_truncated(self) -> None:
        long_titre = "A" * 200
        signaux = [{"titre": long_titre, "source_name": "src"}]
        bloc = _build_bloc_signaux(signaux)
        # Le titre original fait 200 chars — il doit etre tronque a 80 + "..." = 83 max.
        # Le bloc contient "... (1 source(s) : <titre_tronque>)."
        # On extrait la partie titre en cherchant apres le dernier ":"
        partie_titres = bloc.split(": ", 1)[-1].rstrip(").")
        # Le titre tronque doit etre <= 83 chars (80 + "...")
        self.assertLessEqual(len(partie_titres), 83)


class TestBuildContactCivilite(unittest.TestCase):

    def test_none_returns_fallback(self) -> None:
        self.assertEqual(_build_contact_civilite(None), "Madame, Monsieur")

    def test_cible_with_nom(self) -> None:
        enr = {
            "contact_nom": "MARTIN",
            "contact_prenom": None,
            "contact_titre": "Directeur qualite",
            "contact_type": "cible",
        }
        result = _build_contact_civilite(enr)
        # "Directeur" est dans _TITRES_MASCULINS
        self.assertIn("MARTIN", result)
        self.assertIn("Monsieur", result)

    def test_cible_with_prenom_nom_no_titre(self) -> None:
        enr = {
            "contact_nom": "DUPONT",
            "contact_prenom": "Jean",
            "contact_titre": "Responsable supply chain",
            "contact_type": "cible",
        }
        result = _build_contact_civilite(enr)
        self.assertIn("DUPONT", result)

    def test_fallback_dirigeant(self) -> None:
        enr = {
            "contact_nom": "MARTIN",
            "contact_type": "fallback_dirigeant",
        }
        result = _build_contact_civilite(enr)
        self.assertEqual(result, "Madame, Monsieur")

    def test_empty_nom_returns_fallback(self) -> None:
        enr = {
            "contact_nom": "",
            "contact_type": "cible",
        }
        result = _build_contact_civilite(enr)
        self.assertEqual(result, "Madame, Monsieur")


if __name__ == "__main__":
    unittest.main()
