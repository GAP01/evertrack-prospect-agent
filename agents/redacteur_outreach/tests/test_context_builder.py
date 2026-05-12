"""
Tests unitaires pour redacteur_outreach.context_builder.

Toutes les bases SQLite sont creees dans un TemporaryDirectory —
aucun appel reseau, aucun acces aux bases de donnees de production.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from redacteur_outreach.context_builder import (
    IncidentNotFoundError,
    build_context,
)


# ---------------------------------------------------------------------------
# Helpers de fixture
# ---------------------------------------------------------------------------

def _create_incidents_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE incidents (
            source           TEXT NOT NULL,
            source_id        TEXT NOT NULL,
            marque           TEXT,
            modeles          TEXT,
            categorie        TEXT,
            sous_categorie   TEXT,
            motif            TEXT,
            risques          TEXT,
            distributeurs    TEXT,
            date_publication TEXT,
            source_url       TEXT,
            zone_geographique TEXT,
            PRIMARY KEY (source, source_id)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO incidents
        (source, source_id, marque, modeles, categorie, sous_categorie,
         motif, risques, distributeurs, date_publication, source_url, zone_geographique)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rappelconso",
            "RAPPELCONSO-12345",
            "ACME",
            "Fromage X lot 42",
            "Alimentation",
            "Produits laitiers",
            "Presence de Listeria monocytogenes",
            "Risque infectieux",
            "Carrefour; Leclerc",
            "2024-03-15",
            "https://rappel.conso.gouv.fr/fiche-rappel/12345",
            "National",
        ),
    )
    conn.commit()
    conn.close()


def _create_scores_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE scores (
            source          TEXT NOT NULL,
            source_id       TEXT NOT NULL,
            score           REAL NOT NULL,
            tier            TEXT NOT NULL,
            dimensions_json TEXT NOT NULL,
            scored_at       TEXT NOT NULL,
            scorer_version  TEXT NOT NULL,
            llm_used        INTEGER NOT NULL,
            PRIMARY KEY (source, source_id, scorer_version, scored_at)
        )
        """
    )
    dims = json.dumps([
        {"name": "risque_sanitaire", "raw": 92.0, "weight": 0.5,
         "rationale": "[LLM] Listeria detectee"},
        {"name": "ampleur_geo", "raw": 75.0, "weight": 0.25,
         "rationale": "[regles] National"},
        {"name": "population_vulnerable", "raw": 60.0, "weight": 0.15,
         "rationale": "[regles] Population generale"},
        {"name": "volume_distributeurs", "raw": 50.0, "weight": 0.1,
         "rationale": "[regles] 2 enseignes"},
    ])
    conn.execute(
        """
        INSERT INTO scores
        (source, source_id, score, tier, dimensions_json, scored_at,
         scorer_version, llm_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rappelconso",
            "RAPPELCONSO-12345",
            84.25,
            "critique",
            dims,
            "2024-03-16T10:00:00",
            "v1",
            1,
        ),
    )
    conn.commit()
    conn.close()


def _create_enrichissements_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE enrichissements (
            source               TEXT NOT NULL,
            source_id            TEXT NOT NULL,
            enricher_version     TEXT NOT NULL,
            siren                TEXT,
            siret_siege          TEXT,
            raison_sociale       TEXT,
            adresse              TEXT,
            contact_nom          TEXT,
            contact_titre        TEXT,
            contact_source       TEXT,
            contact_type         TEXT,
            confidence           REAL,
            match_status         TEXT NOT NULL,
            PRIMARY KEY (source, source_id, enricher_version)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO enrichissements
        (source, source_id, enricher_version, siren, siret_siege, raison_sociale,
         adresse, contact_nom, contact_titre, contact_source, contact_type,
         confidence, match_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rappelconso",
            "RAPPELCONSO-12345",
            "v1",
            "123456789",
            "12345678900012",
            "ACME SAS",
            "1 rue de la Paix, 75001 Paris",
            "Dupont",
            "Responsable qualite",
            "sirene",
            "cible",
            0.85,
            "found",
        ),
    )
    conn.commit()
    conn.close()


def _create_signaux_db(db_path: str, nb_signaux: int = 1) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE signaux (
            signal_id        TEXT PRIMARY KEY,
            marque           TEXT,
            symptome         TEXT,
            score            INTEGER,
            detected_at      TEXT NOT NULL,
            source_name      TEXT,
            titre            TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE signal_incident_matches (
            signal_id          TEXT NOT NULL,
            incident_source    TEXT NOT NULL,
            incident_source_id TEXT NOT NULL,
            score              REAL NOT NULL,
            user_confirmed     INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (signal_id, incident_source, incident_source_id)
        )
        """
    )
    for i in range(nb_signaux):
        sid = f"sig{i:04d}"
        conn.execute(
            """
            INSERT INTO signaux
            (signal_id, marque, symptome, score, detected_at, source_name, titre)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid,
                "ACME",
                "listeria",
                # Scores croissants pour verifier le tri DESC : signal 0 a le score le plus bas
                50 + i * 10,
                f"2024-03-{10 + i:02d}T08:00:00",
                "marmiton",
                f"Alerte Listeria produit {i}",
            ),
        )
        conn.execute(
            """
            INSERT INTO signal_incident_matches
            (signal_id, incident_source, incident_source_id, score, user_confirmed)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sid, "rappelconso", "RAPPELCONSO-12345", 0.75 + i * 0.01, 0),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Suite de tests
# ---------------------------------------------------------------------------

class TestBuildContextFull(unittest.TestCase):
    """Toutes les bases presentes et populees."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        d = self.tmpdir.name
        _create_incidents_db(os.path.join(d, "incidents.sqlite"))
        _create_scores_db(os.path.join(d, "scores.sqlite"))
        _create_enrichissements_db(os.path.join(d, "enrichissements.sqlite"))
        _create_signaux_db(os.path.join(d, "signaux.sqlite"), nb_signaux=1)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_build_context_full(self) -> None:
        ctx = build_context("rappelconso", "RAPPELCONSO-12345", self.tmpdir.name)

        self.assertIsNotNone(ctx["incident"])
        self.assertEqual(ctx["incident"]["source_id"], "RAPPELCONSO-12345")
        self.assertEqual(ctx["incident"]["marque"], "ACME")

        self.assertIsNotNone(ctx["score"])
        self.assertAlmostEqual(ctx["score"]["score_total"], 84.25, places=2)

        self.assertIsNotNone(ctx["enrichissement"])
        self.assertEqual(ctx["enrichissement"]["siren"], "123456789")

        self.assertEqual(len(ctx["signaux_summary"]), 1)
        self.assertEqual(ctx["signaux_summary"][0]["signal_id"], "sig0000")


class TestBuildContextIncidentOnly(unittest.TestCase):
    """Seule incidents.sqlite est presente — les autres cles doivent etre None/[]."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        _create_incidents_db(os.path.join(self.tmpdir.name, "incidents.sqlite"))
        # scores, enrichissements, signaux : fichiers absents

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_build_context_incident_only(self) -> None:
        ctx = build_context("rappelconso", "RAPPELCONSO-12345", self.tmpdir.name)

        self.assertIsNotNone(ctx["incident"])
        self.assertIsNone(ctx["score"])
        self.assertIsNone(ctx["enrichissement"])
        self.assertEqual(ctx["signaux_summary"], [])


class TestBuildContextUnknownIncident(unittest.TestCase):
    """source_id inexistant doit lever IncidentNotFoundError."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        _create_incidents_db(os.path.join(self.tmpdir.name, "incidents.sqlite"))

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_build_context_unknown_incident(self) -> None:
        with self.assertRaises(IncidentNotFoundError):
            build_context("rappelconso", "INCONNU-99999", self.tmpdir.name)


class TestSignauxLimit3(unittest.TestCase):
    """5 signaux inseres — seuls les 3 meilleurs scores doivent etre retournes."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        d = self.tmpdir.name
        _create_incidents_db(os.path.join(d, "incidents.sqlite"))
        _create_signaux_db(os.path.join(d, "signaux.sqlite"), nb_signaux=5)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_signaux_limit_3(self) -> None:
        ctx = build_context("rappelconso", "RAPPELCONSO-12345", self.tmpdir.name)
        summary = ctx["signaux_summary"]

        self.assertEqual(len(summary), 3)

        # Les scores dans signaux sont 50,60,70,80,90 (i=0..4).
        # Tri DESC => sig0004 (90), sig0003 (80), sig0002 (70).
        scores = [s["score_credibilite"] for s in summary]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(summary[0]["signal_id"], "sig0004")
        self.assertEqual(summary[1]["signal_id"], "sig0003")
        self.assertEqual(summary[2]["signal_id"], "sig0002")


class TestMissingSignauxDbReturnsEmpty(unittest.TestCase):
    """signaux.sqlite absent => signaux_summary == []."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        _create_incidents_db(os.path.join(self.tmpdir.name, "incidents.sqlite"))
        # signaux.sqlite volontairement absent

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_missing_signaux_db_returns_empty(self) -> None:
        ctx = build_context("rappelconso", "RAPPELCONSO-12345", self.tmpdir.name)
        self.assertEqual(ctx["signaux_summary"], [])


class TestResultIsJsonSerializable(unittest.TestCase):
    """Le dict retourne doit etre serialisable via json.dumps sans exception."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        d = self.tmpdir.name
        _create_incidents_db(os.path.join(d, "incidents.sqlite"))
        _create_scores_db(os.path.join(d, "scores.sqlite"))
        _create_enrichissements_db(os.path.join(d, "enrichissements.sqlite"))
        _create_signaux_db(os.path.join(d, "signaux.sqlite"), nb_signaux=2)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_result_is_json_serializable(self) -> None:
        ctx = build_context("rappelconso", "RAPPELCONSO-12345", self.tmpdir.name)
        # Ne doit pas lever
        serialized = json.dumps(ctx)
        # Verification minimale que le JSON est non-vide
        self.assertIn("RAPPELCONSO-12345", serialized)


if __name__ == "__main__":
    unittest.main()
