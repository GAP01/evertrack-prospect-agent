"""Tests pour le module merger (fusion de signaux redondants)."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from detecteur_signaux.merger import (
    merge_by_rappelconso_url,
    merge_duplicates,
    _pick_survivor,
)
from detecteur_signaux.storage import SignalStorage


class TestPickSurvivor(unittest.TestCase):
    def test_most_sources_wins(self):
        candidates = [
            {"signal_id": "a", "_n_sources": 1, "detected_at": "2026-04-20T10:00:00"},
            {"signal_id": "b", "_n_sources": 3, "detected_at": "2026-04-22T10:00:00"},
        ]
        self.assertEqual(_pick_survivor(candidates)["signal_id"], "b")

    def test_tie_breaks_on_earliest(self):
        candidates = [
            {"signal_id": "late",  "_n_sources": 2, "detected_at": "2026-04-22T10:00:00"},
            {"signal_id": "early", "_n_sources": 2, "detected_at": "2026-04-20T10:00:00"},
        ]
        self.assertEqual(_pick_survivor(candidates)["signal_id"], "early")


class TestMergeByRappelConsoURL(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tmpdir.name) / "signaux.sqlite"
        self.storage = SignalStorage(self.db)
        # Insère 2 signaux distincts partageant la même fiche RappelConso
        conn = sqlite3.connect(self.db)
        conn.executemany(
            """
            INSERT INTO signaux
            (signal_id, detector_version, marque, symptome, titre,
             source_type, source_name, source_url, score, score_breakdown,
             status, detected_at, last_seen_at)
            VALUES (?, 'v0.1', ?, ?, ?, 'google_news', 'Marmiton', 'url_primary',
                    30, '{}', 'faible', ?, ?)
            """,
            [
                ("sig_a", "Super U", "listeria",    "Article A", "2026-04-20T10:00:00", "2026-04-20T10:00:00"),
                ("sig_b", "Super U", "contamination bacterienne", "Article B",
                 "2026-04-22T10:00:00", "2026-04-22T10:00:00"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO signaux_sources
            (signal_id, source_type, source_name, source_url, titre, detected_at, rappelconso_url)
            VALUES (?, 'google_news', 'Marmiton', ?, 'T', ?, ?)
            """,
            [
                ("sig_a", "http://marmiton.org/a", "2026-04-20T10:00:00",
                 "https://rappel.conso.gouv.fr/fiche-rappel/22030/Interne"),
                ("sig_b", "http://tf1info.fr/b", "2026-04-22T10:00:00",
                 "https://rappel.conso.gouv.fr/fiche-rappel/22030/interne"),
            ],
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            self.tmpdir.cleanup()
        except (OSError, PermissionError):
            pass

    def test_merge_by_url_fuses_signals(self):
        result = merge_by_rappelconso_url(self.db)
        self.assertEqual(result["signaux_merged"], 1)

        # Un seul signal doit rester (sig_a, le plus ancien)
        conn = sqlite3.connect(self.db)
        remaining = [r[0] for r in conn.execute("SELECT signal_id FROM signaux").fetchall()]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0], "sig_a")

        # Les 2 sources doivent être rattachées à sig_a
        srcs = conn.execute(
            "SELECT source_url FROM signaux_sources WHERE signal_id = 'sig_a'"
        ).fetchall()
        self.assertEqual(len(srcs), 2)
        conn.close()

    def test_idempotent(self):
        merge_by_rappelconso_url(self.db)
        result2 = merge_by_rappelconso_url(self.db)
        self.assertEqual(result2["signaux_merged"], 0)


class TestMergeDuplicates(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tmpdir.name) / "signaux.sqlite"
        self.storage = SignalStorage(self.db)

    def tearDown(self):
        try:
            self.tmpdir.cleanup()
        except (OSError, PermissionError):
            pass

    def test_no_duplicates_clean_run(self):
        """Sur une base vide, merge ne fait rien et ne plante pas."""
        result = merge_duplicates(self.db, rescore=False)
        self.assertEqual(result["merge_rappelconso_url"]["signaux_merged"], 0)
        self.assertEqual(result["merge_recomputed_key"]["signaux_merged"], 0)


if __name__ == "__main__":
    unittest.main()
