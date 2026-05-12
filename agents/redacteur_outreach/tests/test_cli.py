"""
Tests unitaires pour redacteur_outreach.cli.

Strategy :
  - Redacteur et OutreachStorage sont patches au niveau du module cli.
  - _iter_candidates est patche directement pour generate-batch.
  - Sorties capturees via contextlib.redirect_stdout.
  - Codes retour verifies via valeur de retour de cli.main().
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from dataclasses import asdict
from unittest.mock import MagicMock, call, patch

from redacteur_outreach import cli
from redacteur_outreach.context_builder import IncidentNotFoundError
from redacteur_outreach.models import OutreachMessage, STATUS_CHOICES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_msg(
    message_id: str = "abc123def456abcd",
    source: str = "rappelconso",
    source_id: str = "RC-001",
    status: str = "brouillon",
    llm_used: bool = False,
    objet: str = "Objet test",
    body_md: str = "Corps du message test.",
    body_fallback: str = "Corps du message test.",
    generated_at: str = "2026-05-12T10:00:00+00:00",
    context_json: str | None = None,
) -> OutreachMessage:
    return OutreachMessage(
        message_id=message_id,
        source=source,
        source_id=source_id,
        status=status,
        llm_used=llm_used,
        objet=objet,
        body_md=body_md,
        body_fallback=body_fallback,
        generated_at=generated_at,
        context_json=context_json,
    )


def _run(argv: list[str]) -> tuple[int, str]:
    """Lance main() et capture stdout. Retourne (code_retour, stdout_str)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(argv)
    return rc, buf.getvalue()


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

class TestCmdGenerate(unittest.TestCase):

    @patch("redacteur_outreach.cli.Redacteur")
    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_generate_new_message_prints_ok(
        self, mock_storage_class: MagicMock, mock_redacteur_class: MagicMock
    ) -> None:
        """Nouveau message : affiche [ok] avec message_id et status."""
        fake_msg = _make_msg(status="brouillon", llm_used=False)

        storage_inst = MagicMock()
        storage_inst.get_by_source.return_value = None  # pas d'existant
        mock_storage_class.return_value = storage_inst

        mock_redacteur = MagicMock()
        mock_redacteur.generate.return_value = fake_msg
        mock_redacteur_class.return_value = mock_redacteur

        rc, out = _run(["generate", "RC-001", "--no-llm"])

        self.assertEqual(rc, 0)
        self.assertIn("[ok]", out)
        self.assertIn("abc123def456abcd", out)
        self.assertIn("brouillon", out)

    @patch("redacteur_outreach.cli.Redacteur")
    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_generate_existing_message_prints_tilde(
        self, mock_storage_class: MagicMock, mock_redacteur_class: MagicMock
    ) -> None:
        """Message existant sans --force : affiche [~] et ne regenere pas."""
        fake_msg = _make_msg(status="a_valider")

        storage_inst = MagicMock()
        storage_inst.get_by_source.return_value = fake_msg
        mock_storage_class.return_value = storage_inst

        mock_redacteur = MagicMock()
        mock_redacteur_class.return_value = mock_redacteur

        rc, out = _run(["generate", "RC-001"])

        self.assertEqual(rc, 0)
        self.assertIn("[~]", out)
        self.assertIn("message existant", out)
        self.assertIn("abc123def456abcd", out)
        # generate ne doit pas etre appele (idempotence)
        mock_redacteur.generate.assert_not_called()

    @patch("redacteur_outreach.cli.Redacteur")
    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_generate_incident_not_found_returns_1(
        self, mock_storage_class: MagicMock, mock_redacteur_class: MagicMock
    ) -> None:
        """Incident inconnu : affiche [x] et retourne 1."""
        storage_inst = MagicMock()
        storage_inst.get_by_source.return_value = None
        mock_storage_class.return_value = storage_inst

        mock_redacteur = MagicMock()
        mock_redacteur.generate.side_effect = IncidentNotFoundError("nope")
        mock_redacteur_class.return_value = mock_redacteur

        rc, out = _run(["generate", "RC-INCONNU"])

        self.assertEqual(rc, 1)
        self.assertIn("[x]", out)
        self.assertIn("incident inconnu", out)

    @patch("redacteur_outreach.cli.Redacteur")
    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_generate_force_calls_redacteur_even_if_existing(
        self, mock_storage_class: MagicMock, mock_redacteur_class: MagicMock
    ) -> None:
        """Avec --force, generate est appele meme si un message existe."""
        existing = _make_msg(status="brouillon")
        new_msg = _make_msg(status="brouillon", message_id="abc123def456abcd")

        storage_inst = MagicMock()
        storage_inst.get_by_source.return_value = existing
        mock_storage_class.return_value = storage_inst

        mock_redacteur = MagicMock()
        mock_redacteur.generate.return_value = new_msg
        mock_redacteur_class.return_value = mock_redacteur

        rc, out = _run(["generate", "RC-001", "--force"])

        self.assertEqual(rc, 0)
        mock_redacteur.generate.assert_called_once()
        self.assertIn("[ok]", out)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

class TestCmdList(unittest.TestCase):

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_list_empty_prints_tilde(self, mock_storage_class: MagicMock) -> None:
        """Aucun message : affiche [~] aucun message."""
        storage_inst = MagicMock()
        storage_inst.list_all.return_value = []
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["list"])

        self.assertEqual(rc, 0)
        self.assertIn("[~]", out)
        self.assertIn("aucun message", out)

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_list_with_results_prints_table(self, mock_storage_class: MagicMock) -> None:
        """Avec messages : affiche un tableau contenant les message_id et statuts."""
        msg1 = _make_msg(message_id="id_alpha_00000001", source_id="RC-001", status="brouillon")
        msg2 = _make_msg(message_id="id_beta_000000002", source_id="RC-002", status="a_valider")

        storage_inst = MagicMock()
        storage_inst.list_all.return_value = [msg1, msg2]
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["list"])

        self.assertEqual(rc, 0)
        self.assertIn("id_alpha_00000001", out)
        self.assertIn("id_beta_000000002", out)
        self.assertIn("brouillon", out)
        self.assertIn("a_valider", out)

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_list_filter_by_status(self, mock_storage_class: MagicMock) -> None:
        """--status a_valider passe le bon statut a list_by_status."""
        storage_inst = MagicMock()
        storage_inst.list_by_status.return_value = []
        mock_storage_class.return_value = storage_inst

        _run(["list", "--status", "a_valider"])

        storage_inst.list_by_status.assert_called_once_with("a_valider")
        storage_inst.list_all.assert_not_called()


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

class TestCmdShow(unittest.TestCase):

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_show_md_format(self, mock_storage_class: MagicMock) -> None:
        """Format md : affiche objet, body_md, status."""
        msg = _make_msg(objet="Objet du test", body_md="Corps en **markdown**.")

        storage_inst = MagicMock()
        storage_inst.get.return_value = msg
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["show", "abc123def456abcd"])

        self.assertEqual(rc, 0)
        self.assertIn("Objet du test", out)
        self.assertIn("Corps en **markdown**.", out)
        self.assertIn("brouillon", out)

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_show_json_format(self, mock_storage_class: MagicMock) -> None:
        """Format json : sortie parsable en JSON."""
        msg = _make_msg()

        storage_inst = MagicMock()
        storage_inst.get.return_value = msg
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["show", "abc123def456abcd", "--format", "json"])

        self.assertEqual(rc, 0)
        parsed = json.loads(out)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["message_id"], "abc123def456abcd")

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_show_eml_format(self, mock_storage_class: MagicMock) -> None:
        """Format eml : headers RFC 2822 minimaux, ASCII only, double newline avant body."""
        msg = _make_msg(objet="Test objet email", body_md="Corps email ASCII.")

        storage_inst = MagicMock()
        storage_inst.get.return_value = msg
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["show", "abc123def456abcd", "--format", "eml"])

        self.assertEqual(rc, 0)
        self.assertIn("Subject:", out)
        self.assertIn("From:", out)
        self.assertIn("To:", out)
        # Double newline (ligne vide) entre headers et body
        self.assertIn("\n\n", out)
        self.assertIn("Corps email ASCII.", out)
        # ASCII only : aucun caractere > 127
        self.assertTrue(
            all(ord(c) < 128 for c in out),
            "La sortie eml contient des caracteres non-ASCII",
        )

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_show_eml_strips_crlf_in_subject(
        self, mock_storage_class: MagicMock
    ) -> None:
        """Format eml : un objet avec CRLF n'injecte pas de header Bcc (CWE-93)."""
        msg = _make_msg(
            objet="Hello\r\nBcc: attacker@evil",
            body_md="Corps.",
        )
        storage_inst = MagicMock()
        storage_inst.get.return_value = msg
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["show", "abc123def456abcd", "--format", "eml"])

        self.assertEqual(rc, 0)
        # La ligne Subject ne doit pas contenir de CR ni de LF.
        subject_line = next(l for l in out.splitlines() if l.startswith("Subject:"))
        self.assertNotIn("\r", subject_line)
        self.assertNotIn("\n", subject_line)
        # Le payload injecte ne doit pas apparaitre comme header separe (injection CRLF).
        # "Bcc:" peut rester dans la valeur du Subject (concatene), mais ne doit
        # pas etre une ligne independante commencant par "Bcc:".
        lines = out.splitlines()
        self.assertFalse(
            any(l.startswith("Bcc:") for l in lines),
            "Bcc: ne doit pas etre un header injecte independant",
        )

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_show_unknown_id_returns_1(self, mock_storage_class: MagicMock) -> None:
        """Message inconnu : affiche [x] et retourne 1."""
        storage_inst = MagicMock()
        storage_inst.get.return_value = None
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["show", "inexistant"])

        self.assertEqual(rc, 1)
        self.assertIn("[x]", out)
        self.assertIn("message inconnu", out)

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_eml_uses_contact_email_from_context_json(
        self, mock_storage_class: MagicMock
    ) -> None:
        """Format eml extrait contact_email du context_json si present."""
        ctx = {
            "incident": {"source_id": "RC-001"},
            "enrichissement": {"contact_email": "qualite@exemple.fr"},
        }
        msg_with_email = _make_msg(
            context_json=json.dumps(ctx),
            objet="Test",
            body_md="Body.",
        )

        storage_inst = MagicMock()
        storage_inst.get.return_value = msg_with_email
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["show", "abc123def456abcd", "--format", "eml"])

        self.assertEqual(rc, 0)
        self.assertIn("qualite@exemple.fr", out)

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_eml_fallback_when_no_contact_email(
        self, mock_storage_class: MagicMock
    ) -> None:
        """Format eml utilise l'adresse fallback si contact_email absent."""
        ctx = {
            "incident": {"source_id": "RC-002"},
            "enrichissement": {"contact_nom": "DUPONT"},  # pas de contact_email
        }
        msg_no_email = _make_msg(
            context_json=json.dumps(ctx),
            objet="Test",
            body_md="Body.",
        )

        storage_inst = MagicMock()
        storage_inst.get.return_value = msg_no_email
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["show", "abc123def456abcd", "--format", "eml"])

        self.assertEqual(rc, 0)
        self.assertIn("TBD@destinataire.invalid", out)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

class TestCmdValidate(unittest.TestCase):

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_validate_accept_calls_set_status_valide(
        self, mock_storage_class: MagicMock
    ) -> None:
        """--accept : appelle set_status avec 'valide' et validated_at."""
        msg = _make_msg(status="a_valider")

        storage_inst = MagicMock()
        storage_inst.get.return_value = msg
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["validate", "abc123def456abcd", "--accept"])

        self.assertEqual(rc, 0)
        self.assertIn("[ok]", out)
        self.assertIn("valide", out)
        args_called = storage_inst.set_status.call_args
        self.assertEqual(args_called[0][0], "abc123def456abcd")
        self.assertEqual(args_called[0][1], "valide")
        self.assertIn("validated_at", args_called[1])

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_validate_reject_calls_set_status_rejete(
        self, mock_storage_class: MagicMock
    ) -> None:
        """--reject : appelle set_status avec 'rejete' et validated_at."""
        msg = _make_msg(status="a_valider")

        storage_inst = MagicMock()
        storage_inst.get.return_value = msg
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["validate", "abc123def456abcd", "--reject"])

        self.assertEqual(rc, 0)
        self.assertIn("rejete", out)
        args_called = storage_inst.set_status.call_args
        self.assertEqual(args_called[0][1], "rejete")
        self.assertIn("validated_at", args_called[1])


# ---------------------------------------------------------------------------
# mark-sent
# ---------------------------------------------------------------------------

class TestCmdMarkSent(unittest.TestCase):

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_mark_sent_calls_set_status_envoye(
        self, mock_storage_class: MagicMock
    ) -> None:
        """mark-sent appelle set_status avec 'envoye' et sent_at."""
        msg = _make_msg(status="valide")

        storage_inst = MagicMock()
        storage_inst.get.return_value = msg
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["mark-sent", "abc123def456abcd"])

        self.assertEqual(rc, 0)
        self.assertIn("[ok]", out)
        self.assertIn("marque envoye", out)
        args_called = storage_inst.set_status.call_args
        self.assertEqual(args_called[0][0], "abc123def456abcd")
        self.assertEqual(args_called[0][1], "envoye")
        self.assertIn("sent_at", args_called[1])


# ---------------------------------------------------------------------------
# set-status
# ---------------------------------------------------------------------------

class TestCmdSetStatus(unittest.TestCase):

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_set_status_rejects_invalid(self, mock_storage_class: MagicMock) -> None:
        """Statut invalide : affiche [x] avec la liste des statuts valides."""
        storage_inst = MagicMock()
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["set-status", "abc123def456abcd", "--status", "badstatus"])

        self.assertEqual(rc, 1)
        self.assertIn("[x]", out)
        # Tous les statuts valides doivent etre mentionnes dans le message d'erreur.
        for s in STATUS_CHOICES:
            self.assertIn(s, out)

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_set_status_valid_calls_set_status(
        self, mock_storage_class: MagicMock
    ) -> None:
        """Statut valide : appelle set_status correctement."""
        msg = _make_msg(status="brouillon")

        storage_inst = MagicMock()
        storage_inst.get.return_value = msg
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["set-status", "abc123def456abcd", "--status", "valide"])

        self.assertEqual(rc, 0)
        self.assertIn("[ok]", out)
        storage_inst.set_status.assert_called_once_with("abc123def456abcd", "valide")


# ---------------------------------------------------------------------------
# regenerate
# ---------------------------------------------------------------------------

class TestCmdRegenerate(unittest.TestCase):

    @patch("redacteur_outreach.cli.Redacteur")
    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_regenerate_calls_redacteur_generate_force(
        self, mock_storage_class: MagicMock, mock_redacteur_class: MagicMock
    ) -> None:
        """regenerate appelle Redacteur.generate avec force=True."""
        existing = _make_msg(status="brouillon")
        regen_msg = _make_msg(status="brouillon")

        storage_inst = MagicMock()
        storage_inst.get.return_value = existing
        mock_storage_class.return_value = storage_inst

        mock_redacteur = MagicMock()
        mock_redacteur.generate.return_value = regen_msg
        mock_redacteur_class.return_value = mock_redacteur

        rc, out = _run(["regenerate", "abc123def456abcd", "--no-llm"])

        self.assertEqual(rc, 0)
        self.assertIn("[ok]", out)
        self.assertIn("regenere", out)

        # Verifie force=True dans l'appel a generate
        call_kwargs = mock_redacteur.generate.call_args[1]
        self.assertTrue(call_kwargs.get("force", False))

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_regenerate_unknown_id_returns_1(
        self, mock_storage_class: MagicMock
    ) -> None:
        """message_id inconnu : affiche [x] et retourne 1."""
        storage_inst = MagicMock()
        storage_inst.get.return_value = None
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["regenerate", "inexistant"])

        self.assertEqual(rc, 1)
        self.assertIn("[x]", out)
        self.assertIn("message inconnu", out)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

class TestCmdStats(unittest.TestCase):

    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_stats_prints_counts(self, mock_storage_class: MagicMock) -> None:
        """stats affiche les compteurs par statut."""
        storage_inst = MagicMock()
        storage_inst.count_by_status.return_value = {
            "brouillon": 3,
            "a_valider": 1,
            "valide": 2,
            "envoye": 0,
            "rejete": 1,
        }
        mock_storage_class.return_value = storage_inst

        rc, out = _run(["stats"])

        self.assertEqual(rc, 0)
        self.assertIn("[ok]", out)
        self.assertIn("3", out)   # brouillon
        self.assertIn("1", out)   # a_valider
        self.assertIn("2", out)   # valide


# ---------------------------------------------------------------------------
# generate-batch
# ---------------------------------------------------------------------------

class TestCmdGenerateBatch(unittest.TestCase):

    @patch("redacteur_outreach.cli._iter_candidates")
    @patch("redacteur_outreach.cli.Redacteur")
    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_generate_batch_iterates_candidates(
        self,
        mock_storage_class: MagicMock,
        mock_redacteur_class: MagicMock,
        mock_iter: MagicMock,
    ) -> None:
        """generate-batch appelle generate pour chaque candidat et affiche le recap."""
        mock_iter.return_value = iter([
            ("rappelconso", "RC-001", 80.0),
            ("rappelconso", "RC-002", 65.0),
        ])

        storage_inst = MagicMock()
        storage_inst.get_by_source.return_value = None  # aucun existant
        mock_storage_class.return_value = storage_inst

        fake_msg1 = _make_msg(message_id="id1_0000000000001", source_id="RC-001")
        fake_msg2 = _make_msg(message_id="id2_0000000000002", source_id="RC-002")
        mock_redacteur = MagicMock()
        mock_redacteur.generate.side_effect = [fake_msg1, fake_msg2]
        mock_redacteur_class.return_value = mock_redacteur

        rc, out = _run(["generate-batch", "--no-llm"])

        self.assertEqual(rc, 0)
        self.assertEqual(mock_redacteur.generate.call_count, 2)
        self.assertIn("[ok]", out)
        self.assertIn("candidats", out)
        self.assertIn("2", out)

    @patch("redacteur_outreach.cli._iter_candidates")
    @patch("redacteur_outreach.cli.Redacteur")
    @patch("redacteur_outreach.cli.OutreachStorage")
    def test_generate_batch_counts_existing_as_idempotent(
        self,
        mock_storage_class: MagicMock,
        mock_redacteur_class: MagicMock,
        mock_iter: MagicMock,
    ) -> None:
        """Les messages deja generes sont comptes dans 'existants' sans appel LLM."""
        mock_iter.return_value = iter([
            ("rappelconso", "RC-001", 80.0),
        ])

        existing = _make_msg(source_id="RC-001", status="brouillon")
        storage_inst = MagicMock()
        storage_inst.get_by_source.return_value = existing
        mock_storage_class.return_value = storage_inst

        mock_redacteur = MagicMock()
        mock_redacteur_class.return_value = mock_redacteur

        rc, out = _run(["generate-batch"])

        self.assertEqual(rc, 0)
        mock_redacteur.generate.assert_not_called()
        self.assertIn("existants", out)
        self.assertIn("1", out)  # 1 existant


# ---------------------------------------------------------------------------
# main sans subcommand
# ---------------------------------------------------------------------------

class TestMainNoSubcommand(unittest.TestCase):

    def test_no_subcommand_returns_2(self) -> None:
        """Sans subcommand, main retourne 2 (usage)."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main([])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
