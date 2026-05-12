"""Tests du collector SignalConso v2 — détecteur d'anomalies de volume."""

from __future__ import annotations

import json
import statistics
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from detecteur_signaux.sources import signalconso
from detecteur_signaux.sources.config import SourceConfig


# Cassette : payload ODS v2.1 fictif simulant des comptages agrégés
# (category, dep_code, dep_name, iso_week, n).
def _make_aggregate_row(cat, dep_code, dep_name, iso_week, n):
    return {
        signalconso.FIELD_CATEGORY: [cat],
        signalconso.FIELD_DEP_CODE: dep_code,
        signalconso.FIELD_DEP_NAME: dep_name,
        "iso_week": iso_week,
        "n": n,
    }


class TestStatsHelpers(unittest.TestCase):
    """MAD + z-score modifié."""

    def test_mad_basic(self):
        # Median = 5, deviations = [4, 2, 0, 2, 4] -> median = 2
        self.assertEqual(signalconso._mad([1, 3, 5, 7, 9]), 2)

    def test_mad_empty(self):
        self.assertEqual(signalconso._mad([]), 0.0)

    def test_z_mod_normal_baseline(self):
        # Baseline stable autour de 10, count=20 → z élevé
        baseline = [10, 11, 9, 10, 12, 8, 10, 11, 9, 10, 11, 10]
        z = signalconso._z_mod(20, baseline)
        self.assertIsNotNone(z)
        self.assertGreater(z, 3.5)

    def test_z_mod_no_anomaly(self):
        baseline = [10, 11, 9, 10, 12, 8, 10, 11, 9, 10, 11, 10]
        z = signalconso._z_mod(11, baseline)
        self.assertLess(z, 3.5)

    def test_z_mod_flat_baseline_above(self):
        """MAD=0 + count > median → on flag avec valeur élevée."""
        baseline = [10, 10, 10, 10, 10]
        self.assertEqual(signalconso._z_mod(20, baseline), 99.0)

    def test_z_mod_flat_baseline_at_median(self):
        baseline = [10, 10, 10]
        self.assertEqual(signalconso._z_mod(10, baseline), 0.0)

    def test_z_mod_empty_baseline(self):
        self.assertIsNone(signalconso._z_mod(10, []))


class TestNormalizeCategory(unittest.TestCase):
    """Le champ category est array dans le dataset réel."""

    def test_array(self):
        self.assertEqual(signalconso._normalize_category(["Alimentation"]), "Alimentation")

    def test_string(self):
        self.assertEqual(signalconso._normalize_category("Alimentation"), "Alimentation")

    def test_empty_array(self):
        self.assertEqual(signalconso._normalize_category([]), "")

    def test_none(self):
        self.assertEqual(signalconso._normalize_category(None), "")


class TestMakeVolumeSignal(unittest.TestCase):
    """Construction du SignalSource de type signalconso_volume."""

    def test_full_signal(self):
        baseline = [10, 11, 9, 10, 12, 8, 10, 11, 9, 10, 11, 10]
        sig = signalconso._make_volume_signal(
            category="Alimentation",
            dep_code="17",
            dep_name="Charente-Maritime",
            iso_week="2026-17",
            count_actuel=22,
            baseline=baseline,
            z_mod_value=4.2,
        )
        self.assertEqual(sig.source_type, "signalconso_volume")
        self.assertIn("Charente-Maritime", sig.source_name)
        self.assertIn("Alimentation", sig.source_name)
        self.assertEqual(
            sig.source_url,
            "signalconso://stats/Alimentation/17/2026-17",
        )
        self.assertIsNotNone(sig.forced_signal_id)
        self.assertIn("17", sig.forced_signal_id)
        self.assertIn("Alimentation", sig.forced_signal_id)
        self.assertIn("Pic signalements", sig.titre)

        # Le contenu doit être un JSON valide avec les clés stat
        payload = json.loads(sig.contenu)
        self.assertEqual(payload["category"], "Alimentation")
        self.assertEqual(payload["dep_code"], "17")
        self.assertEqual(payload["count_actuel"], 22)
        self.assertEqual(payload["z_mod"], 4.2)
        self.assertIn("baseline_median", payload)
        self.assertIn("baseline_mad", payload)


class TestDetectAnomalies(unittest.TestCase):
    """Pipeline détection : rows agrégés → SignalSource si anomalie."""

    def test_emits_signal_for_clear_pic(self):
        # Baseline stable à ~10, current week à 30 → forte anomalie
        rows = []
        for week in range(1, 13):
            rows.append(_make_aggregate_row(
                "Alimentation", "17", "Charente-Maritime",
                f"2026-{week:02d}", 10 + (week % 3),
            ))
        rows.append(_make_aggregate_row(
            "Alimentation", "17", "Charente-Maritime", "2026-17", 30,
        ))

        signals = list(signalconso.detect_anomalies(rows, current_week="2026-17"))
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].source_type, "signalconso_volume")

    def test_skips_low_baseline(self):
        # Median baseline trop basse (3) → on skip même avec gros pic
        rows = []
        for week in range(1, 13):
            rows.append(_make_aggregate_row(
                "Cosmetiques", "75", "Paris",
                f"2026-{week:02d}", 2 if week % 2 else 3,
            ))
        rows.append(_make_aggregate_row(
            "Cosmetiques", "75", "Paris", "2026-17", 50,
        ))
        signals = list(signalconso.detect_anomalies(rows, current_week="2026-17"))
        self.assertEqual(signals, [])

    def test_skips_no_anomaly(self):
        # Baseline stable, current dans la plage normale → pas de signal
        rows = []
        for week in range(1, 13):
            rows.append(_make_aggregate_row(
                "Alimentation", "75", "Paris",
                f"2026-{week:02d}", 20 + (week % 4),
            ))
        rows.append(_make_aggregate_row(
            "Alimentation", "75", "Paris", "2026-17", 21,
        ))
        signals = list(signalconso.detect_anomalies(rows, current_week="2026-17"))
        self.assertEqual(signals, [])

    def test_skips_insufficient_history(self):
        # Seulement 2 semaines de baseline → on skip (besoin de >=3)
        rows = [
            _make_aggregate_row("Alimentation", "75", "Paris", "2026-15", 10),
            _make_aggregate_row("Alimentation", "75", "Paris", "2026-16", 11),
            _make_aggregate_row("Alimentation", "75", "Paris", "2026-17", 50),
        ]
        signals = list(signalconso.detect_anomalies(rows, current_week="2026-17"))
        self.assertEqual(signals, [])

    def test_skips_when_current_zero(self):
        # Aucun signalement la semaine courante → rien à détecter
        rows = []
        for week in range(1, 13):
            rows.append(_make_aggregate_row(
                "Alimentation", "75", "Paris",
                f"2026-{week:02d}", 10,
            ))
        signals = list(signalconso.detect_anomalies(rows, current_week="2026-17"))
        self.assertEqual(signals, [])


    def test_buckets_daily_rows_into_iso_weeks(self):
        """
        Les rows ODS arrivent quotidiens (champ 'day' = date YYYY-MM-DD).
        Le code agrège par semaine ISO côté Python avant la détection.
        """
        # Lundi 2026-04-27 = semaine ISO 18 ; on génère 12 semaines de baseline
        # à 2 signalements/jour → ~14/semaine, puis 30 sur la semaine 18.
        rows = []
        for week_offset in range(1, 13):
            # Lundi de la semaine ISO 18 - week_offset
            from datetime import date, timedelta
            monday = date(2026, 4, 27) - timedelta(weeks=week_offset)
            for day_offset in range(7):
                d = monday + timedelta(days=day_offset)
                rows.append({
                    signalconso.FIELD_CATEGORY: ["Alimentation"],
                    signalconso.FIELD_DEP_CODE: "17",
                    signalconso.FIELD_DEP_NAME: "Charente-Maritime",
                    "day": d.isoformat(),
                    "n": 2,  # 14/semaine baseline
                })
        # Pic semaine courante : 30 signalements le 27 avril
        rows.append({
            signalconso.FIELD_CATEGORY: ["Alimentation"],
            signalconso.FIELD_DEP_CODE: "17",
            signalconso.FIELD_DEP_NAME: "Charente-Maritime",
            "day": "2026-04-27",
            "n": 30,
        })

        signals = list(signalconso.detect_anomalies(rows, current_week="2026-W18"))
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].source_type, "signalconso_volume")
        # Vérifier que le payload reflète bien la somme hebdo (14)
        import json
        payload = json.loads(signals[0].contenu)
        self.assertEqual(payload["count_actuel"], 30)
        # Baseline ~14/semaine
        self.assertAlmostEqual(payload["baseline_median"], 14, delta=1)

class TestFetchAggregated(unittest.TestCase):
    """Fetch ODS avec session mockée."""

    def _make_mock_session(self, payloads):
        sess = MagicMock()
        sess.headers = {}
        responses = []
        for p in payloads:
            r = MagicMock()
            r.json.return_value = p
            r.raise_for_status = MagicMock()
            responses.append(r)
        sess.get.side_effect = responses
        return sess

    def test_single_page_fetch(self):
        """Page < ODS_PAGE_LIMIT items → arrêt immédiat, retour direct."""
        from datetime import date
        page = {"total_count": 20, "results": [
            _make_aggregate_row("Alimentation", "75", "Paris", f"2026-{w:02d}", 10)
            for w in range(1, 21)
        ]}
        sess = self._make_mock_session([page])
        rows = signalconso._fetch_aggregated(
            categories=["Alimentation"],
            since=date(2026, 1, 1),
            session=sess,
        )
        self.assertEqual(len(rows), 20)

    def test_paginated_fetch_full_page_triggers_next(self):
        """Une page exactement à ODS_PAGE_LIMIT déclenche la requête suivante."""
        from datetime import date
        page1_full = {"total_count": 150, "results": [
            _make_aggregate_row("Alimentation", "75", "Paris", f"2026-{w%52+1:02d}", 10)
            for w in range(signalconso.ODS_PAGE_LIMIT)
        ]}
        page2 = {"total_count": 150, "results": [
            _make_aggregate_row("Alimentation", "76", "Seine-Maritime", f"2026-{w:02d}", 10)
            for w in range(1, 16)
        ]}
        sess = self._make_mock_session([page1_full, page2])
        rows = signalconso._fetch_aggregated(
            categories=["Alimentation"],
            since=date(2026, 1, 1),
            session=sess,
        )
        # ODS_PAGE_LIMIT (100) + 15 = 115 lignes
        self.assertEqual(len(rows), signalconso.ODS_PAGE_LIMIT + 15)

    def test_http_error_returns_partial(self):
        import requests
        sess = MagicMock()
        sess.headers = {}
        sess.get.side_effect = requests.RequestException("network down")
        from datetime import date
        rows = signalconso._fetch_aggregated(
            categories=["Alimentation"],
            since=date(2026, 1, 1),
            session=sess,
        )
        self.assertEqual(rows, [])


class TestCollectIntegration(unittest.TestCase):
    """Le collector @register utilise SourceConfig + délègue à detect_anomalies."""

    def test_collect_uses_default_categories_when_none(self):
        with patch("detecteur_signaux.sources.signalconso._fetch_aggregated") as mock_fetch:
            mock_fetch.return_value = []
            cfg = SourceConfig()
            list(signalconso.collect(cfg))
            kwargs = mock_fetch.call_args.kwargs
            self.assertEqual(kwargs["categories"], list(signalconso.DEFAULT_CATEGORIES))

    def test_collect_uses_cfg_categories(self):
        with patch("detecteur_signaux.sources.signalconso._fetch_aggregated") as mock_fetch:
            mock_fetch.return_value = []
            cfg = SourceConfig(signalconso_categories=["Alimentation"])
            list(signalconso.collect(cfg))
            kwargs = mock_fetch.call_args.kwargs
            self.assertEqual(kwargs["categories"], ["Alimentation"])

    def test_registered_in_registry(self):
        from detecteur_signaux.sources import get_collector, list_collectors
        self.assertIn("signalconso_volume", list_collectors())
        self.assertIsNotNone(get_collector("signalconso_volume"))


class TestIsoWeekHelpers(unittest.TestCase):
    """Helpers temporels."""

    def test_iso_week_label(self):
        from datetime import date
        # 27 avril 2026 = lundi semaine ISO 18
        d = date(2026, 4, 27)
        self.assertEqual(signalconso._iso_week_label(d), "2026-W18")

    def test_iso_week_start(self):
        from datetime import date
        # 28 avril 2026 (mardi) → lundi 27 avril
        d = date(2026, 4, 28)
        self.assertEqual(signalconso._iso_week_start(d), date(2026, 4, 27))


if __name__ == "__main__":
    unittest.main()
