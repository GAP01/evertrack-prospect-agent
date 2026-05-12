"""Tests unitaires pour OutreachStorage."""

from __future__ import annotations

import tempfile
import unittest

from redacteur_outreach.models import OutreachMessage, REDACTEUR_VERSION
from redacteur_outreach.storage import OutreachStorage


def _make_message(**kwargs) -> OutreachMessage:
    """Construit un OutreachMessage avec des valeurs par defaut."""
    defaults = dict(
        message_id="msg-001",
        source="rappelconso",
        source_id="RC-2026-0001",
        canal="email",
        objet="Rappel produit : action recommandee",
        body_md="## Bonjour\n\nNous vous contactons...",
        body_fallback="Bonjour, Nous vous contactons...",
        llm_used=True,
        redacteur_version=REDACTEUR_VERSION,
        status="brouillon",
        context_json='{"incident_id": "RC-2026-0001"}',
        pitch_version="v1",
        generated_at="2026-05-12T10:00:00",
        validated_at=None,
        sent_at=None,
        notes="Premiere generation",
    )
    defaults.update(kwargs)
    return OutreachMessage(**defaults)


class TestOutreachStorage(unittest.TestCase):

    def setUp(self) -> None:
        self.storage = OutreachStorage(":memory:")

    def tearDown(self) -> None:
        self.storage.close()

    # ------------------------------------------------------------------
    # 1. save + get complet
    # ------------------------------------------------------------------

    def test_save_and_get(self) -> None:
        msg = _make_message()
        self.storage.save(msg)
        fetched = self.storage.get("msg-001")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched, msg)

    # ------------------------------------------------------------------
    # 2. Message minimal (defaults)
    # ------------------------------------------------------------------

    def test_save_minimal_message(self) -> None:
        minimal = OutreachMessage(
            message_id="msg-min",
            source="rappelconso",
            source_id="RC-2026-0002",
            redacteur_version=REDACTEUR_VERSION,
        )
        self.storage.save(minimal)
        fetched = self.storage.get("msg-min")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.canal, "email")
        self.assertFalse(fetched.llm_used)
        self.assertEqual(fetched.status, "brouillon")

    # ------------------------------------------------------------------
    # 3. Round-trip bool llm_used
    # ------------------------------------------------------------------

    def test_llm_used_roundtrip(self) -> None:
        msg_true = _make_message(message_id="msg-llm-true", llm_used=True)
        msg_false = _make_message(message_id="msg-llm-false", llm_used=False)
        self.storage.save(msg_true)
        self.storage.save(msg_false)
        self.assertIs(self.storage.get("msg-llm-true").llm_used, True)
        self.assertIs(self.storage.get("msg-llm-false").llm_used, False)

    # ------------------------------------------------------------------
    # 4. get inconnu -> None
    # ------------------------------------------------------------------

    def test_get_unknown_returns_none(self) -> None:
        self.assertIsNone(self.storage.get("inexistant"))

    # ------------------------------------------------------------------
    # 5. get_by_source
    # ------------------------------------------------------------------

    def test_get_by_source(self) -> None:
        msg_a = _make_message(
            message_id="msg-a",
            source="rappelconso",
            source_id="RC-001",
            generated_at="2026-05-12T09:00:00",
        )
        msg_b = _make_message(
            message_id="msg-b",
            source="rappelconso",
            source_id="RC-002",
            generated_at="2026-05-12T09:01:00",
        )
        self.storage.save(msg_a)
        self.storage.save(msg_b)

        found = self.storage.get_by_source("rappelconso", "RC-001")
        self.assertIsNotNone(found)
        self.assertEqual(found.message_id, "msg-a")

        not_found = self.storage.get_by_source("rappelconso", "RC-999")
        self.assertIsNone(not_found)

    # ------------------------------------------------------------------
    # 6. list_by_status
    # ------------------------------------------------------------------

    def test_list_by_status(self) -> None:
        self.storage.save(_make_message(message_id="msg-1", status="brouillon"))
        self.storage.save(_make_message(message_id="msg-2", status="a_valider"))
        self.storage.save(_make_message(message_id="msg-3", status="a_valider"))

        results = self.storage.list_by_status("a_valider")
        self.assertEqual(len(results), 2)
        ids = {m.message_id for m in results}
        self.assertIn("msg-2", ids)
        self.assertIn("msg-3", ids)

        self.assertEqual(len(self.storage.list_by_status("envoye")), 0)

    # ------------------------------------------------------------------
    # 7. set_status + timestamps
    # ------------------------------------------------------------------

    def test_set_status_updates_timestamps(self) -> None:
        self.storage.save(_make_message(message_id="msg-ts"))

        self.storage.set_status("msg-ts", "valide", validated_at="2026-05-12")
        fetched = self.storage.get("msg-ts")
        self.assertEqual(fetched.status, "valide")
        self.assertEqual(fetched.validated_at, "2026-05-12")
        self.assertIsNone(fetched.sent_at)

        self.storage.set_status("msg-ts", "envoye", sent_at="2026-05-13")
        fetched = self.storage.get("msg-ts")
        self.assertEqual(fetched.status, "envoye")
        self.assertEqual(fetched.sent_at, "2026-05-13")

    # ------------------------------------------------------------------
    # 8. set_status rejette statut invalide
    # ------------------------------------------------------------------

    def test_set_status_rejects_invalid(self) -> None:
        self.storage.save(_make_message(message_id="msg-inv"))
        with self.assertRaises(ValueError):
            self.storage.set_status("msg-inv", "n_importe_quoi")

    # ------------------------------------------------------------------
    # 9. count_by_status
    # ------------------------------------------------------------------

    def test_count_by_status(self) -> None:
        self.storage.save(_make_message(message_id="m1", status="brouillon"))
        self.storage.save(_make_message(message_id="m2", status="brouillon"))
        self.storage.save(_make_message(message_id="m3", status="a_valider"))

        counts = self.storage.count_by_status()
        self.assertEqual(counts.get("brouillon"), 2)
        self.assertEqual(counts.get("a_valider"), 1)
        self.assertNotIn("envoye", counts)

    # ------------------------------------------------------------------
    # 10. delete
    # ------------------------------------------------------------------

    def test_delete(self) -> None:
        self.storage.save(_make_message(message_id="msg-del"))
        deleted = self.storage.delete("msg-del")
        self.assertTrue(deleted)
        self.assertIsNone(self.storage.get("msg-del"))

        # Supprimer une seconde fois doit retourner False
        self.assertFalse(self.storage.delete("msg-del"))

    # ------------------------------------------------------------------
    # 11. Idempotence init (fichier temporaire)
    # ------------------------------------------------------------------

    def test_idempotent_init(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            path = f.name

        s1 = OutreachStorage(path)
        s1.save(_make_message(message_id="msg-idem"))
        s1.close()

        # Deuxieme ouverture : schema + migrations idempotents
        s2 = OutreachStorage(path)
        fetched = s2.get("msg-idem")
        s2.close()

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.message_id, "msg-idem")

    # ------------------------------------------------------------------
    # 12. INSERT OR REPLACE
    # ------------------------------------------------------------------

    def test_save_replaces_existing(self) -> None:
        original = _make_message(message_id="msg-rep", objet="Objet initial")
        self.storage.save(original)

        updated = _make_message(message_id="msg-rep", objet="Objet modifie")
        self.storage.save(updated)

        fetched = self.storage.get("msg-rep")
        self.assertEqual(fetched.objet, "Objet modifie")


if __name__ == "__main__":
    unittest.main()
