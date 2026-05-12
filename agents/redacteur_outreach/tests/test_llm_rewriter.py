"""
Tests unitaires pour redacteur_outreach.llm_rewriter.

Aucun appel reel a l'API Anthropic — les appels sont interceptes via MagicMock.
Pattern : patch("redacteur_outreach.llm_rewriter.Anthropic") pour remplacer
la classe avant instanciation dans rewrite().
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, call, patch


# Importe le module pour acceder aux constantes sans declencher les appels
from redacteur_outreach import llm_rewriter
from redacteur_outreach.llm_rewriter import (
    _build_allowed_tokens,
    _extract_numeric_tokens,
    _summarize_context,
    _truncate_objet,
    rewrite,
)


# ---------------------------------------------------------------------------
# Fixtures partagees
# ---------------------------------------------------------------------------

def _make_body_fallback() -> str:
    return (
        "Bonjour Dupont,\n\n"
        "Je vous contacte suite au rappel ACME du 2026-05-10 concernant "
        "le fromage frais lot 42.\n\n"
        "Motif : risque listeria.\n\n"
        "EverTrack securise la tracabilite produit.\n\n"
        "Cordialement,\nEquipe EverTrack"
    )


def _make_context(score_total: float = 75.0) -> dict:
    return {
        "incident": {
            "source": "rappelconso",
            "source_id": "RAPPELCONSO-42",
            "marque": "ACME",
            "modeles": "Fromage frais",
            "categorie": "Produits laitiers",
            "motif": "Risque listeria",
            "date_publication": "2026-05-10",
            "distributeurs": "Carrefour; Leclerc",
            "risques": "Risque infectieux",
        },
        "score": {
            "score_total": score_total,
            "tier": "critique",
        },
        "enrichissement": {
            "contact_nom": "DUPONT",
            "contact_titre": "Responsable Qualite",
            "contact_type": "cible",
            "siren": "123456789",
            "raison_sociale": "ACME SAS",
        },
        "signaux_summary": [
            {
                "signal_id": "sig0001",
                "titre": "Alerte listeria chez ACME",
                "source_name": "marmiton",
                "score_credibilite": 65,
            }
        ],
    }


def _make_pitch() -> dict:
    return {
        "version": "1.0",
        "editeur_nom": "EverTrack",
        "pitch_court": "EverTrack securise la tracabilite produit.",
        "valeur_immediate": "Identification des lots en quelques minutes.",
        "cta": "Auriez-vous 20 minutes la semaine prochaine ?",
        "signature": "Cordialement,\nEquipe EverTrack",
        "opt_out_placeholder": "",
    }


def _make_clean_body_llm() -> str:
    """Body LLM plausible : ASCII, sans chiffres inventes, sans accents."""
    return (
        "Bonjour Dupont,\n\n"
        "Permettez-moi de vous contacter au sujet du rappel ACME survenu le "
        "2026-05-10 pour votre fromage frais. Le motif retenu est un risque "
        "listeria. Nos equipes ont egalement releve une couverture mediatique "
        "recente sur ce sujet.\n\n"
        "EverTrack vous permet de securiser la tracabilite de vos lots et "
        "d identifier les produits concernes en quelques minutes.\n\n"
        "Auriez-vous 20 minutes la semaine prochaine pour en discuter ?\n\n"
        "Cordialement,\nEquipe EverTrack"
    )


def _make_mock_client(body_text: str, objet_text: str) -> MagicMock:
    """Configure un mock client Anthropic retournant body_text puis objet_text."""
    mock_client = MagicMock()

    body_response = MagicMock()
    body_response.content = [MagicMock(text=body_text)]

    objet_response = MagicMock()
    objet_response.content = [MagicMock(text=objet_text)]

    mock_client.messages.create.side_effect = [body_response, objet_response]
    return mock_client


# ---------------------------------------------------------------------------
# Suite de tests
# ---------------------------------------------------------------------------

class TestLLMRewriter(unittest.TestCase):

    # --- Test 1 : pas de cle API ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_no_api_key_returns_fallback(self, mock_anthropic_class: MagicMock) -> None:
        """Sans ANTHROPIC_API_KEY, retourne body_fallback sans appeler Anthropic."""
        body_fallback = _make_body_fallback()
        result = rewrite(body_fallback, _make_context(), _make_pitch())

        self.assertFalse(result["llm_used"])
        self.assertEqual(result["reason"], "no_api_key")
        self.assertEqual(result["body_md"], body_fallback)
        mock_anthropic_class.assert_not_called()

    # --- Test 2 : reecriture reussie ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_normal_rewrite_success(self, mock_anthropic_class: MagicMock) -> None:
        """Mock retourne un body propre et un objet valide — llm_used=True."""
        body_fallback = _make_body_fallback()
        body_llm = _make_clean_body_llm()
        objet_llm = "Suite au rappel ACME - tracabilite produit"

        mock_client = _make_mock_client(body_llm, objet_llm)
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(), _make_pitch())

        self.assertTrue(result["llm_used"])
        self.assertIsNone(result["reason"])
        self.assertNotEqual(result["body_md"], body_fallback)
        self.assertEqual(result["body_md"], body_llm)
        self.assertGreater(len(result["objet"]), 0)
        # Verifie que les 2 appels Anthropic ont ete effectues
        self.assertEqual(mock_client.messages.create.call_count, 2)

    # --- Test 3 : exception API ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_api_exception_returns_fallback(self, mock_anthropic_class: MagicMock) -> None:
        """Exception lors de l'appel API => fallback, reason='api_error'."""
        body_fallback = _make_body_fallback()

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("boom")
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(), _make_pitch())

        self.assertFalse(result["llm_used"])
        self.assertEqual(result["reason"], "api_error")
        self.assertEqual(result["body_md"], body_fallback)

    # --- Test 4 : hallucination detec tee ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_hallucination_detected_returns_fallback(self, mock_anthropic_class: MagicMock) -> None:
        """Body reecrit contient un chiffre invente (99) absent du contexte."""
        body_fallback = _make_body_fallback()
        # Le contexte ne contient pas "99" — seul "75" est dans score_total,
        # "42" dans le fallback, "10" dans la date, etc.
        body_hallucine = (
            "Bonjour Dupont,\n\n"
            "Suite au rappel ACME, notre score de risque est de 99/100. "
            "Cordialement,\nEquipe EverTrack"
        )
        objet_llm = "Rappel ACME - information tracabilite"

        mock_client = _make_mock_client(body_hallucine, objet_llm)
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(score_total=75.0), _make_pitch())

        self.assertFalse(result["llm_used"])
        self.assertEqual(result["reason"], "hallucination_detected")
        self.assertEqual(result["body_md"], body_fallback)

    # --- Test 5 : non-ASCII detecte ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_non_ascii_detected_returns_fallback(self, mock_anthropic_class: MagicMock) -> None:
        """Body reecrit contient des accents => fallback, reason='non_ascii_detected'."""
        body_fallback = _make_body_fallback()
        # Accent sur "a" : caractere non-ASCII
        body_avec_accents = "Bonjour Madame, a vous de decider. Cordialement, EverTrack"
        # On force un accent pour le test
        body_avec_accents = "Bonjour Madame, \xe0 vous de d\xe9cider."
        objet_llm = "Rappel ACME tracabilite"

        mock_client = _make_mock_client(body_avec_accents, objet_llm)
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(), _make_pitch())

        self.assertFalse(result["llm_used"])
        self.assertEqual(result["reason"], "non_ascii_detected")
        self.assertEqual(result["body_md"], body_fallback)

    # --- Test 6 : chiffres legitimes du contexte acceptes ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_chiffres_legitimes_du_contexte_acceptes(self, mock_anthropic_class: MagicMock) -> None:
        """
        Le contexte contient score_total=75. Le body LLM reprend 'score 75'.
        Pas d'hallucination => llm_used=True.
        """
        body_fallback = _make_body_fallback()
        # "75" est legitime car il est dans context["score"]["score_total"]
        body_llm = (
            "Bonjour Dupont,\n\n"
            "Le score de priorite de cet incident est de 75. "
            "EverTrack peut vous aider.\n\n"
            "Cordialement,\nEquipe EverTrack"
        )
        objet_llm = "Rappel ACME score 75 tracabilite produit"

        mock_client = _make_mock_client(body_llm, objet_llm)
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(score_total=75.0), _make_pitch())

        self.assertTrue(result["llm_used"], f"Attendu llm_used=True, reason={result['reason']!r}")
        self.assertIsNone(result["reason"])

    # --- Test 7 : chiffres du pitch acceptes ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_chiffres_du_pitch_acceptes(self, mock_anthropic_class: MagicMock) -> None:
        """
        Le pitch contient '20 minutes' dans le cta.
        Le body LLM reprend '20 minutes' : pas d'hallucination.
        """
        body_fallback = _make_body_fallback()
        # "20" est dans pitch["cta"] = "Auriez-vous 20 minutes la semaine prochaine ?"
        body_llm = (
            "Bonjour Dupont,\n\n"
            "Suite au rappel ACME, je souhaite vous proposer un echange de "
            "20 minutes la semaine prochaine.\n\n"
            "Cordialement,\nEquipe EverTrack"
        )
        objet_llm = "Rappel ACME - echange 20 minutes"

        pitch = _make_pitch()
        # Verifie que "20" est bien dans le pitch avant d'executer le test
        self.assertIn("20", pitch["cta"])

        mock_client = _make_mock_client(body_llm, objet_llm)
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(), pitch)

        self.assertTrue(result["llm_used"], f"Attendu llm_used=True, reason={result['reason']!r}")
        self.assertIsNone(result["reason"])

    # --- Test 8 : objet tronque si trop long ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_objet_truncated_if_too_long(self, mock_anthropic_class: MagicMock) -> None:
        """
        Call 2 retourne un objet de plus de 70 chars.
        Strategy : on tronque au dernier espace avant la limite (_truncate_objet).
        Le resultat doit etre <= 70 chars.
        """
        body_fallback = _make_body_fallback()
        objet_long = (
            "Information importante concernant le rappel ACME du mois de mai "
            "2026 - tracabilite et gestion des lots affectes par la contamination"
        )
        self.assertGreater(len(objet_long), 70)

        mock_client = _make_mock_client(_make_clean_body_llm(), objet_long)
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(), _make_pitch())

        self.assertTrue(result["llm_used"])
        self.assertLessEqual(len(result["objet"]), 70)
        # La troncature au mot doit produire quelque chose de lisible
        self.assertGreater(len(result["objet"]), 0)

    # --- Test 9 : override du param model ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_model_param_override(self, mock_anthropic_class: MagicMock) -> None:
        """model='other-model' doit etre passe tel quel a messages.create()."""
        body_fallback = _make_body_fallback()
        mock_client = _make_mock_client(_make_clean_body_llm(), "Objet test")
        mock_anthropic_class.return_value = mock_client

        rewrite(body_fallback, _make_context(), _make_pitch(), model="other-model")

        calls = mock_client.messages.create.call_args_list
        self.assertEqual(len(calls), 2)
        for c in calls:
            self.assertEqual(c.kwargs.get("model") or c.args[0] if c.args else c.kwargs["model"], "other-model")

    # ---------------------------------------------------------------------------
    # Tests des helpers internes
    # ---------------------------------------------------------------------------

    def test_extract_numeric_tokens_basic(self) -> None:
        tokens = _extract_numeric_tokens("score 75 sur 100 en 2026")
        self.assertIn("75", tokens)
        self.assertIn("100", tokens)
        self.assertIn("2026", tokens)

    def test_extract_numeric_tokens_empty(self) -> None:
        self.assertEqual(_extract_numeric_tokens("aucun chiffre ici"), set())

    def test_build_allowed_tokens_includes_context_and_pitch(self) -> None:
        context = _make_context(score_total=75.0)
        pitch = _make_pitch()
        body = "brouillon sans chiffre"
        tokens = _build_allowed_tokens(body, context, pitch)
        # score_total=75 dans le contexte
        self.assertIn("75", tokens)
        # "20" dans le cta du pitch
        self.assertIn("20", tokens)

    def test_summarize_context_contains_marque(self) -> None:
        summary = _summarize_context(_make_context())
        self.assertIn("ACME", summary)

    def test_summarize_context_contains_score(self) -> None:
        summary = _summarize_context(_make_context(score_total=84.0))
        self.assertIn("84", summary)

    def test_summarize_context_empty_dict(self) -> None:
        # Ne doit pas lever d'exception
        summary = _summarize_context({})
        self.assertIsInstance(summary, str)
        self.assertGreater(len(summary), 0)

    def test_truncate_objet_under_limit_unchanged(self) -> None:
        objet = "Rappel ACME - tracabilite produit"
        self.assertEqual(_truncate_objet(objet, 70), objet)

    def test_truncate_objet_over_limit_cuts_at_word(self) -> None:
        objet = "A " * 40  # 80 chars
        result = _truncate_objet(objet, 70)
        self.assertLessEqual(len(result), 70)

    def test_truncate_objet_no_space_falls_back_to_hard_cut(self) -> None:
        objet = "A" * 100
        result = _truncate_objet(objet, 70)
        self.assertEqual(len(result), 70)

    # --- Cas limite : Anthropic=None (SDK non installe) ---

    def test_anthropic_none_returns_fallback(self) -> None:
        """Si le SDK n'est pas installe (Anthropic=None), fallback immediat."""
        original = llm_rewriter.Anthropic
        try:
            llm_rewriter.Anthropic = None  # type: ignore[assignment]
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False):
                result = rewrite(_make_body_fallback(), _make_context(), _make_pitch())
            self.assertFalse(result["llm_used"])
            self.assertEqual(result["reason"], "anthropic_not_installed")
        finally:
            llm_rewriter.Anthropic = original  # type: ignore[assignment]

    # --- Cas limite : objet vide apres nettoyage ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_empty_objet_falls_back_to_default(self, mock_anthropic_class: MagicMock) -> None:
        """Si Call 2 retourne une chaine vide, l'objet par defaut est utilise."""
        body_fallback = _make_body_fallback()
        mock_client = _make_mock_client(_make_clean_body_llm(), "   ")
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(), _make_pitch())

        self.assertTrue(result["llm_used"])
        # L'objet ne doit pas etre vide — le default est utilise
        self.assertGreater(len(result["objet"]), 0)
        self.assertIn("ACME", result["objet"])


if __name__ == "__main__":
    unittest.main()
