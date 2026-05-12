"""
Tests unitaires pour redacteur_outreach.redacteur.Redacteur.

Strategy de mock :
  - build_context, render (template_renderer), llm_rewrite et load_pitch sont
    patches au niveau du module redacteur_outreach.redacteur (la cible des imports).
  - OutreachStorage est reel, tourne en memoire (:memory:).

Chaque test setUp cree un Storage frais et des patches par defaut ; les tests
qui ont besoin de comportements differents surchargent les mocks localement.
"""

from __future__ import annotations

import json
import re
import unittest
from unittest.mock import MagicMock, patch, call

from redacteur_outreach.context_builder import IncidentNotFoundError
from redacteur_outreach.models import OutreachMessage, REDACTEUR_VERSION
from redacteur_outreach.redacteur import Redacteur
from redacteur_outreach.storage import OutreachStorage


# ---------------------------------------------------------------------------
# Fixtures partagees
# ---------------------------------------------------------------------------

_FAKE_CONTEXT = {
    "incident": {
        "source": "rappelconso",
        "source_id": "RC-2026-TEST",
        "marque": "ACME",
        "modeles": "Fromage frais",
        "categorie": "Produits laitiers",
        "motif": "Risque listeria",
        "date_publication": "2026-05-10",
    },
    "score": {
        "score_total": 75.0,
        "tier": "critique",
    },
    "enrichissement": {
        "contact_nom": "DUPONT",
        "contact_titre": "Responsable qualite",
        "contact_type": "cible",
    },
    "signaux_summary": [],
}

_FAKE_RENDERED = {
    "body": "Bonjour DUPONT,\n\nSuite au rappel ACME du 15 mai 2026...\n\nCordialement",
    "objet": "Suite au rappel ACME - tracabilite produit",
}

_FAKE_PITCH = {
    "version": "1.0",
    "editeur_nom": "EverTrack",
    "pitch_court": "EverTrack securise la tracabilite.",
    "valeur_immediate": "",
    "cta": "Prenez contact.",
    "signature": "Cordialement,\nEquipe EverTrack",
    "opt_out_placeholder": "",
}


def _make_storage() -> OutreachStorage:
    return OutreachStorage(":memory:")


def _make_redacteur(storage: OutreachStorage, patch_load_pitch) -> Redacteur:
    """Construit un Redacteur avec le storage fourni.

    load_pitch est deja patche par l'appelant ; on passe pitch_path="dummy"
    pour que l'appel dans __init__ soit intercepte par le patch.
    """
    patch_load_pitch.return_value = _FAKE_PITCH
    return Redacteur(storage, data_dir="data", pitch_path="dummy")


# ---------------------------------------------------------------------------
# Classe de test principale
# ---------------------------------------------------------------------------

class TestRedacteur(unittest.TestCase):

    def setUp(self) -> None:
        self.storage = _make_storage()

    def tearDown(self) -> None:
        self.storage.close()

    # ------------------------------------------------------------------
    # 1. generate cree un message dans le storage
    # ------------------------------------------------------------------

    @patch("redacteur_outreach.redacteur.llm_rewrite")
    @patch("redacteur_outreach.redacteur.render_template")
    @patch("redacteur_outreach.redacteur.build_context")
    @patch("redacteur_outreach.redacteur.load_pitch")
    def test_generate_creates_message_in_storage(
        self, mock_load_pitch, mock_build_context, mock_render_template, mock_llm_rewrite
    ) -> None:
        mock_build_context.return_value = _FAKE_CONTEXT
        mock_render_template.return_value = _FAKE_RENDERED
        # no_llm=True donc llm_rewrite ne doit pas etre appele
        mock_llm_rewrite.return_value = {
            "body_md": _FAKE_RENDERED["body"],
            "objet": _FAKE_RENDERED["objet"],
            "llm_used": False,
            "reason": "no_llm_requested",
        }

        r = _make_redacteur(self.storage, mock_load_pitch)
        msg = r.generate("rappelconso", "RC-2026-TEST", no_llm=True)

        # Retour correct
        self.assertIsInstance(msg, OutreachMessage)
        self.assertIsNotNone(msg.message_id)

        # Persiste en base
        stored = self.storage.get(msg.message_id)
        self.assertIsNotNone(stored)

        # Status brouillon (no_llm -> no_api_key equivalent)
        self.assertEqual(msg.status, "brouillon")

        # llm_used False
        self.assertFalse(msg.llm_used)

        # body_md == body_fallback (pas de rewrite)
        self.assertEqual(msg.body_md, _FAKE_RENDERED["body"])

        # context_json parsable JSON
        ctx = json.loads(msg.context_json)
        self.assertIsInstance(ctx, dict)

    # ------------------------------------------------------------------
    # 2. Idempotence : 2eme appel retourne l'existant sans rebuild context
    # ------------------------------------------------------------------

    @patch("redacteur_outreach.redacteur.llm_rewrite")
    @patch("redacteur_outreach.redacteur.render_template")
    @patch("redacteur_outreach.redacteur.build_context")
    @patch("redacteur_outreach.redacteur.load_pitch")
    def test_generate_idempotent_returns_existing(
        self, mock_load_pitch, mock_build_context, mock_render_template, mock_llm_rewrite
    ) -> None:
        mock_build_context.return_value = _FAKE_CONTEXT
        mock_render_template.return_value = _FAKE_RENDERED

        r = _make_redacteur(self.storage, mock_load_pitch)

        msg1 = r.generate("rappelconso", "RC-IDEM", no_llm=True)
        msg2 = r.generate("rappelconso", "RC-IDEM", no_llm=True)

        # build_context appele une seule fois (2eme appel court-circuite)
        self.assertEqual(mock_build_context.call_count, 1)

        # Meme message_id retourne
        self.assertEqual(msg1.message_id, msg2.message_id)

    # ------------------------------------------------------------------
    # 3. force=True regenere : build_context appele 2 fois
    # ------------------------------------------------------------------

    @patch("redacteur_outreach.redacteur.llm_rewrite")
    @patch("redacteur_outreach.redacteur.render_template")
    @patch("redacteur_outreach.redacteur.build_context")
    @patch("redacteur_outreach.redacteur.load_pitch")
    def test_generate_force_regenerates(
        self, mock_load_pitch, mock_build_context, mock_render_template, mock_llm_rewrite
    ) -> None:
        body_v1 = "Body version 1"
        body_v2 = "Body version 2"

        # Premier appel
        mock_build_context.return_value = _FAKE_CONTEXT
        mock_render_template.return_value = {"body": body_v1, "objet": "Objet v1"}

        r = _make_redacteur(self.storage, mock_load_pitch)
        msg1 = r.generate("rappelconso", "RC-FORCE", no_llm=True)
        self.assertEqual(msg1.body_md, body_v1)

        # Deuxieme appel avec force=True et un body different
        mock_render_template.return_value = {"body": body_v2, "objet": "Objet v2"}
        msg2 = r.generate("rappelconso", "RC-FORCE", no_llm=True, force=True)

        # build_context appele 2 fois au total
        self.assertEqual(mock_build_context.call_count, 2)

        # La DB reflete la derniere generation
        stored = self.storage.get(msg1.message_id)
        self.assertEqual(stored.body_md, body_v2)

    # ------------------------------------------------------------------
    # 4. Incident inconnu -> IncidentNotFoundError, rien persiste
    # ------------------------------------------------------------------

    @patch("redacteur_outreach.redacteur.llm_rewrite")
    @patch("redacteur_outreach.redacteur.render_template")
    @patch("redacteur_outreach.redacteur.build_context")
    @patch("redacteur_outreach.redacteur.load_pitch")
    def test_generate_unknown_incident_raises(
        self, mock_load_pitch, mock_build_context, mock_render_template, mock_llm_rewrite
    ) -> None:
        mock_build_context.side_effect = IncidentNotFoundError("nope")

        r = _make_redacteur(self.storage, mock_load_pitch)

        with self.assertRaises(IncidentNotFoundError):
            r.generate("rappelconso", "RC-INEXISTANT", no_llm=True)

        # Aucun message en base
        self.assertEqual(len(self.storage.list_all()), 0)

    # ------------------------------------------------------------------
    # 5. LLM succes -> status a_valider, llm_used True
    # ------------------------------------------------------------------

    @patch("redacteur_outreach.redacteur.llm_rewrite")
    @patch("redacteur_outreach.redacteur.render_template")
    @patch("redacteur_outreach.redacteur.build_context")
    @patch("redacteur_outreach.redacteur.load_pitch")
    def test_generate_with_llm_success(
        self, mock_load_pitch, mock_build_context, mock_render_template, mock_llm_rewrite
    ) -> None:
        mock_build_context.return_value = _FAKE_CONTEXT
        mock_render_template.return_value = _FAKE_RENDERED
        mock_llm_rewrite.return_value = {
            "body_md": "reecrit",
            "objet": "objet reecrit",
            "llm_used": True,
            "reason": None,
        }

        r = _make_redacteur(self.storage, mock_load_pitch)
        msg = r.generate("rappelconso", "RC-LLM-OK")

        self.assertEqual(msg.status, "a_valider")
        self.assertTrue(msg.llm_used)
        self.assertEqual(msg.body_md, "reecrit")
        self.assertEqual(msg.objet, "objet reecrit")

    # ------------------------------------------------------------------
    # 6. LLM hallucination -> status a_valider, notes == reason
    # ------------------------------------------------------------------

    @patch("redacteur_outreach.redacteur.llm_rewrite")
    @patch("redacteur_outreach.redacteur.render_template")
    @patch("redacteur_outreach.redacteur.build_context")
    @patch("redacteur_outreach.redacteur.load_pitch")
    def test_generate_with_llm_hallucination_status_a_valider(
        self, mock_load_pitch, mock_build_context, mock_render_template, mock_llm_rewrite
    ) -> None:
        mock_build_context.return_value = _FAKE_CONTEXT
        mock_render_template.return_value = _FAKE_RENDERED
        mock_llm_rewrite.return_value = {
            "body_md": _FAKE_RENDERED["body"],
            "objet": _FAKE_RENDERED["objet"],
            "llm_used": False,
            "reason": "hallucination_detected",
        }

        r = _make_redacteur(self.storage, mock_load_pitch)
        msg = r.generate("rappelconso", "RC-HALLUCINATION")

        self.assertEqual(msg.status, "a_valider")
        self.assertEqual(msg.notes, "hallucination_detected")

    # ------------------------------------------------------------------
    # 7. no_api_key -> status brouillon
    # ------------------------------------------------------------------

    @patch("redacteur_outreach.redacteur.llm_rewrite")
    @patch("redacteur_outreach.redacteur.render_template")
    @patch("redacteur_outreach.redacteur.build_context")
    @patch("redacteur_outreach.redacteur.load_pitch")
    def test_generate_with_no_api_key_status_brouillon(
        self, mock_load_pitch, mock_build_context, mock_render_template, mock_llm_rewrite
    ) -> None:
        mock_build_context.return_value = _FAKE_CONTEXT
        mock_render_template.return_value = _FAKE_RENDERED
        mock_llm_rewrite.return_value = {
            "body_md": _FAKE_RENDERED["body"],
            "objet": _FAKE_RENDERED["objet"],
            "llm_used": False,
            "reason": "no_api_key",
        }

        r = _make_redacteur(self.storage, mock_load_pitch)
        msg = r.generate("rappelconso", "RC-NO-KEY")

        self.assertEqual(msg.status, "brouillon")

    # ------------------------------------------------------------------
    # 8. message_id stable entre deux appels identiques
    # ------------------------------------------------------------------

    def test_message_id_stable_across_runs(self) -> None:
        id1 = Redacteur._build_message_id("rappelconso", "RC-001")
        id2 = Redacteur._build_message_id("rappelconso", "RC-001")
        self.assertEqual(id1, id2)

    # ------------------------------------------------------------------
    # 9. message_id different pour des inputs differents
    # ------------------------------------------------------------------

    def test_message_id_differs_for_different_inputs(self) -> None:
        id_a = Redacteur._build_message_id("rappelconso", "RC-001")
        id_b = Redacteur._build_message_id("rappelconso", "RC-002")
        id_c = Redacteur._build_message_id("autre_source", "RC-001")
        self.assertNotEqual(id_a, id_b)
        self.assertNotEqual(id_a, id_c)

    # ------------------------------------------------------------------
    # 10. regenerate appelle build_context 2 fois (initial + regen)
    # ------------------------------------------------------------------

    @patch("redacteur_outreach.redacteur.llm_rewrite")
    @patch("redacteur_outreach.redacteur.render_template")
    @patch("redacteur_outreach.redacteur.build_context")
    @patch("redacteur_outreach.redacteur.load_pitch")
    def test_regenerate_existing_message(
        self, mock_load_pitch, mock_build_context, mock_render_template, mock_llm_rewrite
    ) -> None:
        mock_build_context.return_value = _FAKE_CONTEXT
        mock_render_template.return_value = _FAKE_RENDERED
        # regenerate appelle generate sans no_llm=True : llm_rewrite sera appele.
        # On simule le cas no_api_key pour que le resultat soit deterministe.
        mock_llm_rewrite.return_value = {
            "body_md": _FAKE_RENDERED["body"],
            "objet": _FAKE_RENDERED["objet"],
            "llm_used": False,
            "reason": "no_api_key",
        }

        r = _make_redacteur(self.storage, mock_load_pitch)
        msg1 = r.generate("rappelconso", "RC-REGEN", no_llm=True)

        msg2 = r.regenerate(msg1.message_id)

        # build_context appele une 2eme fois lors de regenerate
        self.assertEqual(mock_build_context.call_count, 2)

        # message_id identique (meme (source, source_id))
        self.assertEqual(msg1.message_id, msg2.message_id)

    # ------------------------------------------------------------------
    # 11. regenerate sur message_id inconnu -> ValueError
    # ------------------------------------------------------------------

    @patch("redacteur_outreach.redacteur.load_pitch")
    def test_regenerate_unknown_message_raises_value_error(
        self, mock_load_pitch
    ) -> None:
        r = _make_redacteur(self.storage, mock_load_pitch)
        with self.assertRaises(ValueError):
            r.regenerate("inexistant_id")

    # ------------------------------------------------------------------
    # 12. context_json contient la cle "incident"
    # ------------------------------------------------------------------

    @patch("redacteur_outreach.redacteur.llm_rewrite")
    @patch("redacteur_outreach.redacteur.render_template")
    @patch("redacteur_outreach.redacteur.build_context")
    @patch("redacteur_outreach.redacteur.load_pitch")
    def test_context_json_serialized(
        self, mock_load_pitch, mock_build_context, mock_render_template, mock_llm_rewrite
    ) -> None:
        mock_build_context.return_value = _FAKE_CONTEXT
        mock_render_template.return_value = _FAKE_RENDERED

        r = _make_redacteur(self.storage, mock_load_pitch)
        msg = r.generate("rappelconso", "RC-CTX-JSON", no_llm=True)

        ctx = json.loads(msg.context_json)
        self.assertIsInstance(ctx, dict)
        self.assertIn("incident", ctx)

    # ------------------------------------------------------------------
    # 13. generated_at est au format ISO-8601 avec timezone UTC
    # ------------------------------------------------------------------

    @patch("redacteur_outreach.redacteur.llm_rewrite")
    @patch("redacteur_outreach.redacteur.render_template")
    @patch("redacteur_outreach.redacteur.build_context")
    @patch("redacteur_outreach.redacteur.load_pitch")
    def test_generated_at_is_iso8601(
        self, mock_load_pitch, mock_build_context, mock_render_template, mock_llm_rewrite
    ) -> None:
        mock_build_context.return_value = _FAKE_CONTEXT
        mock_render_template.return_value = _FAKE_RENDERED

        r = _make_redacteur(self.storage, mock_load_pitch)
        msg = r.generate("rappelconso", "RC-DATE", no_llm=True)

        self.assertIsNotNone(msg.generated_at)
        # Format attendu : YYYY-MM-DDTHH:MM:SS+00:00
        # datetime.isoformat(timespec="seconds") avec timezone UTC produit ce format.
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$"
        self.assertRegex(
            msg.generated_at,
            pattern,
            msg=f"generated_at {msg.generated_at!r} n'est pas ISO-8601 avec timezone",
        )


if __name__ == "__main__":
    unittest.main()
