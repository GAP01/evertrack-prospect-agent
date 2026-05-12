"""Tests du registre pluggable des collectors."""

from __future__ import annotations

import unittest
from datetime import datetime
from typing import Iterator

from detecteur_signaux.models import SignalSource
from detecteur_signaux.sources import (
    COLLECTORS,
    SourceConfig,
    get_collector,
    list_collectors,
    register,
)


class TestRegistry(unittest.TestCase):
    """Le registre indexe les collectors enregistrés via @register."""

    def test_default_collectors_registered(self):
        """google_news, reddit, signalconso et tiktok sont enregistres au chargement du package."""
        names = list_collectors()
        self.assertIn("google_news", names)
        self.assertIn("reddit", names)
        self.assertIn("tiktok", names)

    def test_get_collector_returns_callable(self):
        """get_collector retourne un callable pour une source connue."""
        col = get_collector("google_news")
        self.assertIsNotNone(col)
        self.assertTrue(callable(col))

    def test_get_collector_unknown_returns_none(self):
        """Une source inconnue donne None (pas d'exception)."""
        self.assertIsNone(get_collector("source_qui_existe_pas"))

    def test_register_decorator_adds_to_registry(self):
        """@register ajoute le collector au dict global."""
        @register("__test_dummy_source__")
        def _dummy(cfg: SourceConfig) -> Iterator[SignalSource]:
            yield SignalSource(
                source_type="__test__",
                source_name="dummy",
                source_url="https://example.test/",
                titre="dummy",
                detected_at=datetime(2026, 4, 27),
            )
        try:
            self.assertIn("__test_dummy_source__", COLLECTORS)
            col = get_collector("__test_dummy_source__")
            items = list(col(SourceConfig()))
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].source_name, "dummy")
        finally:
            COLLECTORS.pop("__test_dummy_source__", None)


class TestSourceConfig(unittest.TestCase):
    """SourceConfig : valeurs par défaut + champs spécifiques sources."""

    def test_defaults_safe(self):
        cfg = SourceConfig()
        self.assertIsNone(cfg.max_items)
        self.assertEqual(cfg.since_days, 7)
        self.assertIsNone(cfg.google_news_queries)
        self.assertIsNone(cfg.reddit_subreddits)
        self.assertIsNone(cfg.signalconso_categories)
        self.assertFalse(cfg.rasff_include_feed)

    def test_partial_override(self):
        cfg = SourceConfig(
            max_items=50,
            google_news_queries=["test query"],
        )
        self.assertEqual(cfg.max_items, 50)
        self.assertEqual(cfg.google_news_queries, ["test query"])
        # Les autres champs restent à None / defaults
        self.assertIsNone(cfg.reddit_subreddits)


if __name__ == "__main__":
    unittest.main()
