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
    _build_allowed_link_tokens,
    _build_allowed_tokens,
    _extract_emails,
    _extract_numeric_tokens,
    _extract_phone_tokens,
    _extract_urls,
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
    """
    Tests du comportement core de rewrite() (API key, fallbacks, garde-fous).

    load_style_example est patche a None dans setUp pour isoler ces tests du
    contenu reel de style_examples/example_default.txt. Les tests dédies a
    l'injection de style sont dans TestStyleInjection et gerent leur propre patch.
    """

    def setUp(self) -> None:
        patcher = patch(
            "redacteur_outreach.llm_rewriter.load_style_example",
            return_value=None,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

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


class TestStyleInjection(unittest.TestCase):
    """
    Verifie l'injection de l'exemple stylistique dans le user prompt
    et le comportement du garde-fou hallucination vis-a-vis des chiffres
    presents dans l'exemple mais absents du contexte/pitch/fallback.
    """

    # --- Test : exemple charge injecte dans le user prompt ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.load_style_example", return_value="exemple bidon")
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_system_prompt_contains_example_when_loaded(
        self,
        mock_anthropic_class: MagicMock,
        mock_load_style: MagicMock,
    ) -> None:
        """Quand load_style_example retourne un texte, le bloc STYLE_EXAMPLE
        doit apparaitre dans le contenu passe a messages.create (Call 1)."""
        mock_client = _make_mock_client(_make_clean_body_llm(), "Objet test")
        mock_anthropic_class.return_value = mock_client

        rewrite(_make_body_fallback(), _make_context(), _make_pitch())

        # Call 1 = index 0 dans call_args_list
        first_call = mock_client.messages.create.call_args_list[0]
        user_content = first_call.kwargs["messages"][0]["content"]
        self.assertIn("<STYLE_EXAMPLE>", user_content)
        self.assertIn("exemple bidon", user_content)

    # --- Test : pas de bloc exemple si load_style_example retourne None ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.load_style_example", return_value=None)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_system_prompt_no_example_block_when_none(
        self,
        mock_anthropic_class: MagicMock,
        mock_load_style: MagicMock,
    ) -> None:
        """Quand load_style_example retourne None, le bloc STYLE_EXAMPLE
        ne doit pas apparaitre dans le user prompt (pas de 'None' non plus)."""
        mock_client = _make_mock_client(_make_clean_body_llm(), "Objet test")
        mock_anthropic_class.return_value = mock_client

        rewrite(_make_body_fallback(), _make_context(), _make_pitch())

        first_call = mock_client.messages.create.call_args_list[0]
        user_content = first_call.kwargs["messages"][0]["content"]
        self.assertNotIn("<STYLE_EXAMPLE>", user_content)
        self.assertNotIn("EXEMPLE DE STYLE", user_content)
        # S'assure que la valeur litterale "None" n'est pas injectee
        self.assertNotIn("None", user_content)

    # --- Test : exemple vide ("") se comporte comme None ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.load_style_example", return_value="")
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_system_prompt_no_example_block_when_empty_string(
        self,
        mock_anthropic_class: MagicMock,
        mock_load_style: MagicMock,
    ) -> None:
        """Quand load_style_example retourne une chaine vide, le comportement
        doit etre identique au cas None : pas de bloc STYLE_EXAMPLE."""
        mock_client = _make_mock_client(_make_clean_body_llm(), "Objet test")
        mock_anthropic_class.return_value = mock_client

        rewrite(_make_body_fallback(), _make_context(), _make_pitch())

        first_call = mock_client.messages.create.call_args_list[0]
        user_content = first_call.kwargs["messages"][0]["content"]
        self.assertNotIn("<STYLE_EXAMPLE>", user_content)

    # --- Test critique : un chiffre de l'exemple qui fuite declenche hallucination ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch(
        "redacteur_outreach.llm_rewriter.load_style_example",
        return_value="notre taux de conversion est de 87%",
    )
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_hallucination_guard_triggers_on_example_number_leak(
        self,
        mock_anthropic_class: MagicMock,
        mock_load_style: MagicMock,
    ) -> None:
        """
        L'exemple contient '87' mais ce chiffre est absent du contexte, du
        pitch et du body_fallback. Si le LLM le repete dans sa sortie, le
        garde-fou hallucination doit se declencher et retourner le fallback.

        C'est l'invariant fondamental de T3 : l'exemple ne pollue pas le set
        de tokens autorises.
        """
        body_fallback = _make_body_fallback()
        # Verifie que "87" n'est pas dans le contexte ni le pitch ni le fallback
        context = _make_context(score_total=75.0)
        pitch = _make_pitch()
        allowed = _build_allowed_tokens(body_fallback, context, pitch)
        self.assertNotIn("87", allowed, "87 ne doit pas etre dans le set autorise")

        # Le LLM retourne un body qui contient "87" (fuite du chiffre de l'exemple)
        body_leaked = (
            "Bonjour Dupont,\n\n"
            "Notre taux de conversion est de 87 pour cent. "
            "EverTrack peut vous aider.\n\n"
            "Cordialement,\nEquipe EverTrack"
        )
        mock_client = _make_mock_client(body_leaked, "Objet test")
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, context, pitch)

        self.assertFalse(result["llm_used"])
        self.assertEqual(result["reason"], "hallucination_detected")
        self.assertEqual(result["body_md"], body_fallback)

    # --- Test : chiffre de l'exemple present dans le contexte = OK (pas de double comptage) ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch(
        "redacteur_outreach.llm_rewriter.load_style_example",
        return_value="notre taux de conversion est de 87%",
    )
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_number_in_both_example_and_context_not_flagged(
        self,
        mock_anthropic_class: MagicMock,
        mock_load_style: MagicMock,
    ) -> None:
        """
        Si un chiffre est AUSSI present dans le contexte (score_total=87), il
        est dans le set autorise. Le LLM peut le reprendre sans declencher
        le garde-fou — ce n'est pas une hallucination.
        """
        body_fallback = _make_body_fallback()
        context = _make_context(score_total=87.0)  # 87 present dans le contexte
        pitch = _make_pitch()
        allowed = _build_allowed_tokens(body_fallback, context, pitch)
        self.assertIn("87", allowed, "87 doit etre autorise car present dans le contexte")

        body_llm = (
            "Bonjour Dupont,\n\n"
            "Le score de priorite de cet incident est de 87. "
            "EverTrack peut vous aider.\n\n"
            "Cordialement,\nEquipe EverTrack"
        )
        mock_client = _make_mock_client(body_llm, "Objet test")
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, context, pitch)

        self.assertTrue(result["llm_used"], f"reason={result['reason']!r}")
        self.assertIsNone(result["reason"])

    # --- Test : chiffres reels de l'exemple (telephone) declenchent fallback ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch(
        "redacteur_outreach.llm_rewriter.load_style_example",
        return_value="Contact : +33 6 26 64 98 41",
    )
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_hallucination_guard_triggers_on_example_phone_leak(
        self,
        mock_anthropic_class: MagicMock,
        mock_load_style: MagicMock,
    ) -> None:
        """
        L'exemple contient un numero de telephone (+33 6 26 64 98 41).
        Si le LLM fuit "06 26 64 98 41" dans sa sortie, "26", "64", "98", "41"
        sont des tokens absents du contexte/pitch/fallback.
        Seuls les tokens >= 2 chiffres declenchent le garde-fou : "26", "64",
        "98", "41" font tous >= 2 chiffres => fallback hallucination_detected.
        """
        body_fallback = _make_body_fallback()
        context = _make_context(score_total=75.0)
        pitch = _make_pitch()
        allowed = _build_allowed_tokens(body_fallback, context, pitch)
        # Verifie que les segments du numero ne sont pas dans le set autorise
        for token in ("26", "64", "98", "41"):
            self.assertNotIn(token, allowed, f"{token} ne doit pas etre autorise")

        # LLM retourne un body avec le numero tel quel
        body_leaked = (
            "Bonjour Dupont,\n\n"
            "Appelez-nous au 06 26 64 98 41 pour en discuter.\n\n"
            "Cordialement,\nEquipe EverTrack"
        )
        mock_client = _make_mock_client(body_leaked, "Objet test")
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, context, pitch)

        self.assertFalse(result["llm_used"])
        self.assertEqual(result["reason"], "hallucination_detected")
        self.assertEqual(result["body_md"], body_fallback)


class TestLinkInjectionGuard(unittest.TestCase):
    """
    Verifie le garde-fou link_injection :
    - URLs, emails, numeros de telephone hors set autorise => fallback link_injection.
    - Les liens presents dans pitch.json et body_fallback restent autorises.
    """

    # --- Test : URL de l'exemple fuit dans la sortie LLM ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch(
        "redacteur_outreach.llm_rewriter.load_style_example",
        return_value=(
            "Visitez www.evertrack.io pour en savoir plus. "
            "Contact : sylvain.zawal@evertrack.io"
        ),
    )
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_url_injection_from_example_triggers_fallback(
        self,
        mock_anthropic_class: MagicMock,
        mock_load_style: MagicMock,
    ) -> None:
        """
        L'exemple contient www.evertrack.io. Le LLM reprend cette URL dans
        sa sortie => garde-fou link_injection => fallback.
        """
        body_fallback = _make_body_fallback()
        # Verifie que www.evertrack.io n'est pas dans le pitch ni le fallback
        pitch = _make_pitch()
        allowed_urls, _, _ = _build_allowed_link_tokens(body_fallback, pitch)
        self.assertNotIn("www.evertrack.io", allowed_urls)

        body_with_url = (
            "Bonjour Dupont,\n\n"
            "Pour plus d information, consultez www.evertrack.io.\n\n"
            "Cordialement,\nEquipe EverTrack"
        )
        mock_client = _make_mock_client(body_with_url, "Objet test")
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(), pitch)

        self.assertFalse(result["llm_used"])
        self.assertEqual(result["reason"], "link_injection")
        self.assertEqual(result["body_md"], body_fallback)

    # --- Test : email de l'exemple fuit dans la sortie LLM ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch(
        "redacteur_outreach.llm_rewriter.load_style_example",
        return_value="Contactez-nous : sylvain.zawal@evertrack.io",
    )
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_email_injection_from_example_triggers_fallback(
        self,
        mock_anthropic_class: MagicMock,
        mock_load_style: MagicMock,
    ) -> None:
        """
        L'exemple contient sylvain.zawal@evertrack.io. Le LLM le reprend
        dans sa sortie => garde-fou link_injection => fallback.
        """
        body_fallback = _make_body_fallback()
        pitch = _make_pitch()
        _, allowed_emails, _ = _build_allowed_link_tokens(body_fallback, pitch)
        self.assertNotIn("sylvain.zawal@evertrack.io", allowed_emails)

        body_with_email = (
            "Bonjour Dupont,\n\n"
            "Repondez a sylvain.zawal@evertrack.io pour planifier un echange.\n\n"
            "Cordialement,\nEquipe EverTrack"
        )
        mock_client = _make_mock_client(body_with_email, "Objet test")
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(), pitch)

        self.assertFalse(result["llm_used"])
        self.assertEqual(result["reason"], "link_injection")
        self.assertEqual(result["body_md"], body_fallback)

    # --- Test : telephone de l'exemple fuit dans la sortie LLM ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch(
        "redacteur_outreach.llm_rewriter.load_style_example",
        return_value="Contact : +33 6 26 64 98 41",
    )
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_phone_injection_from_example_triggers_fallback(
        self,
        mock_anthropic_class: MagicMock,
        mock_load_style: MagicMock,
    ) -> None:
        """
        L'exemple contient +33 6 26 64 98 41. Le LLM reprend le numero dans
        sa sortie => garde-fou link_injection (ou hallucination si segments
        absents du contexte). On verifie juste que llm_used=False.

        Note : le garde-fou hallucination peut aussi se declencher si les
        segments numeriques (26, 64, 98, 41) sont absents du set autorise.
        Dans les deux cas le fallback est utilise.
        """
        body_fallback = _make_body_fallback()
        pitch = _make_pitch()

        body_with_phone = (
            "Bonjour Dupont,\n\n"
            "Appelez-nous au 06 26 64 98 41 pour en discuter.\n\n"
            "Cordialement,\nEquipe EverTrack"
        )
        mock_client = _make_mock_client(body_with_phone, "Objet test")
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(), pitch)

        self.assertFalse(result["llm_used"])
        # Declenche hallucination_detected (segments num) ou link_injection (prefixe +33)
        self.assertIn(result["reason"], ("hallucination_detected", "link_injection"))
        self.assertEqual(result["body_md"], body_fallback)

    # --- Test : URL du pitch est autorisee ---

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch(
        "redacteur_outreach.llm_rewriter.load_style_example",
        return_value="Exemple sans lien pertinent.",
    )
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_url_from_pitch_signature_is_allowed(
        self,
        mock_anthropic_class: MagicMock,
        mock_load_style: MagicMock,
    ) -> None:
        """
        Une URL presente dans pitch.json.signature est dans le set autorise.
        Le LLM peut la reprendre sans declencher link_injection.
        """
        body_fallback = _make_body_fallback()
        # Pitch avec URL dans la signature
        pitch = _make_pitch()
        pitch["signature"] = "Cordialement,\nEquipe EverTrack\nwww.evertrack.io"

        # Verifie que l'URL est bien dans le set autorise
        allowed_urls, _, _ = _build_allowed_link_tokens(body_fallback, pitch)
        self.assertIn("www.evertrack.io", allowed_urls)

        body_with_allowed_url = (
            "Bonjour Dupont,\n\n"
            "Decouvrez notre solution sur www.evertrack.io.\n\n"
            "Cordialement,\nEquipe EverTrack\nwww.evertrack.io"
        )
        mock_client = _make_mock_client(body_with_allowed_url, "Objet test")
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, _make_context(), pitch)

        self.assertTrue(result["llm_used"], f"reason={result['reason']!r}")
        self.assertIsNone(result["reason"])


class TestAllowedTokensRestrictedSubset(unittest.TestCase):
    """
    Verifie que _build_allowed_tokens n'inclut pas les champs sensibles
    du contexte (siren, siret) dans le set de tokens autorises.
    """

    def test_siren_in_context_not_allowed_in_body(self) -> None:
        """
        Le contexte contient siren='123456789'. Le LLM renvoie un body
        qui contient ce SIREN. => fallback hallucination_detected car
        '123456789' n'est pas dans le set autorise (sous-set restreint).
        """
        body_fallback = _make_body_fallback()
        context = _make_context()
        pitch = _make_pitch()

        # Verifie que le siren n'est PAS dans le set autorise
        allowed = _build_allowed_tokens(body_fallback, context, pitch)
        self.assertNotIn("123456789", allowed, "siren ne doit pas etre dans le set autorise")

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False)
    @patch("redacteur_outreach.llm_rewriter.load_style_example", return_value=None)
    @patch("redacteur_outreach.llm_rewriter.Anthropic")
    def test_siren_in_body_llm_triggers_hallucination(
        self,
        mock_anthropic_class: MagicMock,
        mock_load_style: MagicMock,
    ) -> None:
        """
        Si le LLM inclut le SIREN '123456789' dans sa sortie, le garde-fou
        hallucination_detected doit se declencher (SIREN exclu du set autorise).
        """
        body_fallback = _make_body_fallback()
        context = _make_context()
        pitch = _make_pitch()

        body_with_siren = (
            "Bonjour Dupont,\n\n"
            "L entreprise ACME (SIREN 123456789) a procede a un rappel.\n\n"
            "Cordialement,\nEquipe EverTrack"
        )
        mock_client = _make_mock_client(body_with_siren, "Objet test")
        mock_anthropic_class.return_value = mock_client

        result = rewrite(body_fallback, context, pitch)

        self.assertFalse(result["llm_used"])
        self.assertEqual(result["reason"], "hallucination_detected")
        self.assertEqual(result["body_md"], body_fallback)


class TestExtractHelpers(unittest.TestCase):
    """Tests des helpers d'extraction URLs/emails/telefone."""

    def test_extract_urls_https(self) -> None:
        urls = _extract_urls("Voir https://example.com/page pour details.")
        self.assertIn("https://example.com/page", urls)

    def test_extract_urls_www(self) -> None:
        urls = _extract_urls("Visitez www.evertrack.io maintenant.")
        self.assertIn("www.evertrack.io", urls)

    def test_extract_urls_empty(self) -> None:
        self.assertEqual(_extract_urls("aucune url ici"), set())

    def test_extract_emails_basic(self) -> None:
        emails = _extract_emails("Contactez contact@example.com svp.")
        self.assertIn("contact@example.com", emails)

    def test_extract_emails_case_insensitive(self) -> None:
        emails = _extract_emails("Email: Contact@Example.COM")
        self.assertIn("contact@example.com", emails)

    def test_extract_emails_empty(self) -> None:
        self.assertEqual(_extract_emails("pas d email ici"), set())

    def test_extract_phone_tokens_intl_prefix(self) -> None:
        tokens = _extract_phone_tokens("Appelez +33 6 12 34 56 78.")
        self.assertIn("+33", tokens)

    def test_extract_phone_tokens_groups(self) -> None:
        tokens = _extract_phone_tokens("Tel : 06 26 64 98 41")
        # Doit trouver le groupe "06 26 64 98 41" (4+ groupes de 2 chiffres)
        self.assertTrue(len(tokens) > 0, "Doit detecter un groupe de telephone")

    def test_extract_phone_tokens_empty(self) -> None:
        tokens = _extract_phone_tokens("Aucun numero ici")
        self.assertEqual(tokens, set())

    def test_build_allowed_link_tokens_pitch_url(self) -> None:
        pitch = _make_pitch()
        pitch["signature"] = "Cordialement\nwww.exemple.fr"
        allowed_urls, _, _ = _build_allowed_link_tokens("", pitch)
        self.assertIn("www.exemple.fr", allowed_urls)

    def test_build_allowed_link_tokens_excludes_example(self) -> None:
        """L'exemple n'est pas passe a _build_allowed_link_tokens."""
        body_fallback = ""
        pitch = _make_pitch()  # signature sans URL
        allowed_urls, allowed_emails, _ = _build_allowed_link_tokens(body_fallback, pitch)
        # Aucune URL ni email dans pitch ni fallback vide
        self.assertNotIn("www.evertrack.io", allowed_urls)
        self.assertNotIn("sylvain.zawal@evertrack.io", allowed_emails)


if __name__ == "__main__":
    unittest.main()
