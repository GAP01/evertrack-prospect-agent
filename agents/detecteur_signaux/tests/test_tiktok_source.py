"""
Tests unitaires de la source TikTok (agents/detecteur_signaux/sources/tiktok.py).

Couverture :
  - fetch_via_bridge  : happy path, HTTP errors, timeout, connexion error
  - fetch_via_scraping: happy path, blob absent, JSON invalide, filtre view_count, HTTP error
  - fetch_all         : tier 1 prefere, tier 2 fallback, tier 3 degraded, hashtags par defaut
  - Mapping SignalSource : detected_at fallback, troncature titre, source_name avec/sans auteur
  - keywords.py       : TIKTOK_HASHTAGS, SOURCE_WEIGHTS entrees TikTok

Aucun appel reseau reel. Tous les tests sont deterministes.
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from detecteur_signaux.sources import tiktok
from detecteur_signaux.models import SignalSource

# ---------------------------------------------------------------------------
# Chemin vers les fixtures
# ---------------------------------------------------------------------------
FIXTURES_DIR = Path(__file__).parent / "fixtures"

# IP publique "sure" utilisee dans les tests DNS mocks (example.com)
_PUBLIC_IP = "93.184.216.34"


# ---------------------------------------------------------------------------
# Helper : fabrique un objet Response mock
# ---------------------------------------------------------------------------

def _mock_response(content: bytes, text: str = None, status: int = 200):
    """
    Cree un MagicMock simulant requests.Response, compatible avec _bounded_get
    (stream=True, context-manager, iter_content).
    """
    resp = MagicMock()
    resp.content = content
    resp.text = text if text is not None else content.decode("utf-8", errors="replace")
    resp.status_code = status
    resp.raise_for_status = MagicMock()

    # Context manager : __enter__ retourne resp lui-meme
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)

    # iter_content : yield le contenu en un seul chunk
    resp.iter_content = MagicMock(return_value=iter([content] if content else []))

    return resp


def _mock_response_text(text: str, status: int = 200):
    return _mock_response(text.encode("utf-8"), text=text, status=status)


# ===========================================================================
# Classe 1 — fetch_via_bridge
# ===========================================================================

# Toutes les methodes de cette classe injectent un session mock + patchent DNS
# pour que bridge.example.com soit traite comme une IP publique valide.
@patch("detecteur_signaux.sources.tiktok.socket.gethostbyname", return_value=_PUBLIC_IP)
class TestFetchViaBridge(unittest.TestCase):

    def _bridge_url(self, hashtag="rappelconso"):
        import urllib.parse
        path = tiktok.TIKTOK_BRIDGE_PATH.format(hashtag=urllib.parse.quote(hashtag))
        return "https://bridge.example.com" + path

    # --- 1. Happy path : parse flux Atom complet ---------------------------

    def test_parse_atom_feed(self, _mock_dns):
        """2 entries Atom -> 2 SignalSource valides."""
        fixture = (FIXTURES_DIR / "tiktok_bridge_feed.xml").read_bytes()
        session = MagicMock()
        session.get.return_value = _mock_response(fixture)

        results = tiktok.fetch_via_bridge(
            "rappelconso", "https://bridge.example.com", 0, session=session
        )

        self.assertEqual(len(results), 2)
        for item in results:
            self.assertIsInstance(item, SignalSource)
            self.assertEqual(item.source_type, "tiktok")
            self.assertIsInstance(item.detected_at, datetime)
            self.assertTrue(item.titre, "titre ne doit pas etre vide")

    # --- 2. source_type toujours "tiktok" ----------------------------------

    def test_source_type_is_tiktok(self, _mock_dns):
        fixture = (FIXTURES_DIR / "tiktok_bridge_feed.xml").read_bytes()
        session = MagicMock()
        session.get.return_value = _mock_response(fixture)
        results = tiktok.fetch_via_bridge("rappelconso", "https://bridge.example.com", 0, session=session)
        self.assertTrue(all(r.source_type == "tiktok" for r in results))

    # --- 3. HTTP error -> [] -----------------------------------------------

    def test_bridge_http_error_returns_empty(self, _mock_dns):
        import requests as req
        session = MagicMock()
        session.get.side_effect = req.exceptions.HTTPError("403 Forbidden")
        results = tiktok.fetch_via_bridge("rappelconso", "https://bridge.example.com", 0, session=session)
        self.assertEqual(results, [])

    # --- 4. Timeout -> [] --------------------------------------------------

    def test_bridge_timeout_returns_empty(self, _mock_dns):
        import requests as req
        session = MagicMock()
        session.get.side_effect = req.exceptions.Timeout("timed out")
        results = tiktok.fetch_via_bridge("rappelconso", "https://bridge.example.com", 0, session=session)
        self.assertEqual(results, [])

    # --- 5. ConnectionError -> [] ------------------------------------------

    def test_bridge_request_exception_returns_empty(self, _mock_dns):
        import requests as req
        session = MagicMock()
        session.get.side_effect = req.exceptions.ConnectionError("refused")
        results = tiktok.fetch_via_bridge("rappelconso", "https://bridge.example.com", 0, session=session)
        self.assertEqual(results, [])


# ===========================================================================
# Classe 2 — fetch_via_scraping
# ===========================================================================

class TestFetchViaScraping(unittest.TestCase):

    # --- 6. Happy path : parse blob JSON -----------------------------------

    def test_parse_json_blob(self):
        """HTML fixture avec 2 videos -> 2 SignalSource."""
        fixture = (FIXTURES_DIR / "tiktok_hashtag_page.html").read_bytes()
        session = MagicMock()
        session.get.return_value = _mock_response(fixture)

        results = tiktok.fetch_via_scraping("rappelconso", 0, session=session)

        self.assertEqual(len(results), 2)
        for item in results:
            self.assertIsInstance(item, SignalSource)
            self.assertEqual(item.source_type, "tiktok")
            self.assertTrue(item.source_name.startswith("TikTok @"),
                            f"source_name inattendu : {item.source_name!r}")

    # --- 7. Blob absent -> [] ----------------------------------------------

    def test_missing_blob_returns_empty(self):
        html = "<html><body><p>Aucun script special.</p></body></html>"
        session = MagicMock()
        session.get.return_value = _mock_response_text(html)
        results = tiktok.fetch_via_scraping("rappelconso", 0, session=session)
        self.assertEqual(results, [])

    # --- 8. JSON invalide -> [] --------------------------------------------

    def test_malformed_json_returns_empty(self):
        html = (
            "<html><body><script>"
            "__UNIVERSAL_DATA_FOR_REHYDRATION__ = {not json}</script>"
            "</body></html>"
        )
        session = MagicMock()
        session.get.return_value = _mock_response_text(html)
        results = tiktok.fetch_via_scraping("rappelconso", 0, session=session)
        self.assertEqual(results, [])

    # --- 9. Filtre view_count : seule la video >= 1000 passe --------------

    def test_view_count_filter(self):
        """playCount=5000 passe, playCount=500 filtre (< 1000)."""
        payload = {
            "VideoFeedPage": {
                "videoList": [
                    {
                        "id": "1111",
                        "desc": "video avec beaucoup de vues",
                        "createTime": 1714564800,
                        "author": {"uniqueId": "user_a"},
                        "stats": {"playCount": 5000},
                    },
                    {
                        "id": "2222",
                        "desc": "video avec peu de vues",
                        "createTime": 1714564800,
                        "author": {"uniqueId": "user_b"},
                        "stats": {"playCount": 500},
                    },
                ]
            }
        }
        html = (
            "<html><body><script>"
            "__UNIVERSAL_DATA_FOR_REHYDRATION__ = "
            + json.dumps(payload)
            + "</script></body></html>"
        )
        session = MagicMock()
        session.get.return_value = _mock_response_text(html)

        results = tiktok.fetch_via_scraping("rappelconso", min_view_count=1000, session=session)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].titre, "video avec beaucoup de vues")

    # --- 10. HTTP error dans scraping -> [] --------------------------------

    def test_scraping_http_error_returns_empty(self):
        import requests as req
        session = MagicMock()
        session.get.side_effect = req.exceptions.HTTPError("403")
        results = tiktok.fetch_via_scraping("rappelconso", 0, session=session)
        self.assertEqual(results, [])


# ===========================================================================
# Classe 3 — fetch_all (orchestrateur tiers)
# ===========================================================================

class TestFetchAll(unittest.TestCase):

    BRIDGE_URL = "https://bridge.example.com"

    def _make_signal(self, n=1):
        return [
            SignalSource(
                source_type="tiktok",
                source_name=f"TikTok @user{i}",
                source_url=f"https://www.tiktok.com/@user{i}/video/{i}",
                titre=f"signal {i}",
                detected_at=datetime(2026, 5, 1),
            )
            for i in range(n)
        ]

    # --- 11. Bridge configure : mode user appele, scraping hashtag aussi ---

    def test_bridge_user_called_when_bridge_set(self):
        """Bridge configure -> fetch_via_bridge_user appele par user.

        Note : depuis le pivot RSS-Bridge user-mode, le bridge n'est plus utilise
        pour les hashtags (RSS-Bridge stock ne supporte que "By user"). Bridge
        users et scraping hashtags tournent en parallele.
        """
        bridge_items = self._make_signal(2)
        hashtags = ["rappelconso", "listeria"]
        users = ["60millions", "dgccrf"]

        with patch.object(tiktok, "fetch_via_bridge_user", return_value=bridge_items) as mock_bu, \
             patch.object(tiktok, "fetch_via_scraping", return_value=[]) as mock_scrape:

            results = list(tiktok.fetch_all(
                hashtags, self.BRIDGE_URL, min_view_count=0, bridge_users=users,
            ))

        # 2 users x 2 items = 4 items (scraping hashtag retourne [])
        self.assertEqual(len(results), len(users) * len(bridge_items))
        self.assertEqual(mock_bu.call_count, len(users))
        # Scraping hashtag est toujours tente (pas de skip si bridge OK)
        self.assertEqual(mock_scrape.call_count, len(hashtags))

    # --- 12. Tier 2 fallback quand bridge vide ----------------------------

    def test_tier2_fallback_when_bridge_returns_empty(self):
        """Bridge configure mais renvoie [] -> scraping appele."""
        scrape_items = self._make_signal(1)
        hashtags = ["rappelconso"]

        with patch.object(tiktok, "fetch_via_bridge", return_value=[]), \
             patch.object(tiktok, "fetch_via_scraping", return_value=scrape_items) as mock_scrape:

            results = list(tiktok.fetch_all(hashtags, self.BRIDGE_URL, min_view_count=0))

        mock_scrape.assert_called_once()
        self.assertEqual(len(results), 1)

    # --- 13. Tier 3 degraded : bridge absent + scraping vide = [] sans exception

    def test_tier3_degraded_when_no_bridge_and_no_scrape(self):
        """Pas de bridge, scraping vide -> liste vide, pas d'exception."""
        hashtags = ["rappelconso", "listeria"]

        with patch.object(tiktok, "fetch_via_scraping", return_value=[]):
            results = list(tiktok.fetch_all(hashtags, bridge_base_url=None, min_view_count=0))

        self.assertEqual(results, [])

    # --- 14. hashtags=None -> utilise TIKTOK_HASHTAGS depuis keywords ------

    def test_uses_default_hashtags_if_none(self):
        """Quand hashtags=None, fetch_all itere sur TIKTOK_HASHTAGS."""
        from detecteur_signaux.keywords import TIKTOK_HASHTAGS

        called_hashtags = []

        def fake_scrape(hashtag, min_view_count, session=None):
            called_hashtags.append(hashtag)
            return []

        with patch.object(tiktok, "fetch_via_scraping", side_effect=fake_scrape):
            list(tiktok.fetch_all(None, bridge_base_url=None, min_view_count=0))

        self.assertEqual(called_hashtags, list(TIKTOK_HASHTAGS))


# ===========================================================================
# Classe 4 — Mapping SignalSource (details de construction)
# ===========================================================================

@patch("detecteur_signaux.sources.tiktok.socket.gethostbyname", return_value=_PUBLIC_IP)
class TestSignalSourceMapping(unittest.TestCase):

    def _feed_with_entry(self, entry_overrides: dict) -> bytes:
        """Construit un flux Atom minimal avec une seule entry personnalisable."""
        defaults = {
            "title": "Titre de test",
            "link": "https://www.tiktok.com/@tester/video/9999",
            "published": "2026-05-01T10:00:00Z",
            "summary": "Contenu de test.",
            "author_name": "tester",
        }
        defaults.update(entry_overrides)

        author_block = (
            f"<author><name>{defaults['author_name']}</name></author>"
            if defaults.get("author_name")
            else ""
        )

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test feed</title>
  <entry>
    <title>{defaults['title']}</title>
    <link href="{defaults['link']}"/>
    <published>{defaults['published']}</published>
    <summary>{defaults['summary']}</summary>
    {author_block}
  </entry>
</feed>"""
        return xml.encode("utf-8")

    # --- 15. detected_at est un datetime meme sans published_parsed --------

    def test_detected_at_is_datetime(self, _mock_dns):
        """Si published_parsed absent du feedparser entry, fallback datetime.utcnow().

        feedparser est importe en local dans fetch_via_bridge, donc on patche
        directement feedparser.parse via son module.
        """
        import feedparser as _fp

        original_parse = _fp.parse
        fixture = self._feed_with_entry({})

        def fake_parse(content, *args, **kwargs):
            result = original_parse(content, *args, **kwargs)
            for entry in result.entries:
                # Retire published_parsed pour forcer le fallback utcnow()
                entry.pop("published_parsed", None)
            return result

        session = MagicMock()
        session.get.return_value = _mock_response(fixture)

        with patch.object(_fp, "parse", side_effect=fake_parse):
            results = tiktok.fetch_via_bridge("rappelconso", "https://bridge.example.com", 0, session=session)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0].detected_at, datetime)

    # --- 16. Titre tronque a 200 caracteres --------------------------------

    def test_titre_truncated_to_200(self, _mock_dns):
        long_title = "A" * 300
        fixture = self._feed_with_entry({"title": long_title})
        session = MagicMock()
        session.get.return_value = _mock_response(fixture)

        results = tiktok.fetch_via_bridge("rappelconso", "https://bridge.example.com", 0, session=session)

        self.assertEqual(len(results), 1)
        self.assertLessEqual(len(results[0].titre), 200)

    # --- 17. source_name avec auteur : "TikTok @{auteur}" -----------------

    def test_source_name_with_author(self, _mock_dns):
        fixture = self._feed_with_entry({"author_name": "dgccrf_officiel"})
        session = MagicMock()
        session.get.return_value = _mock_response(fixture)

        results = tiktok.fetch_via_bridge("rappelconso", "https://bridge.example.com", 0, session=session)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source_name, "TikTok @dgccrf_officiel")

    # --- 18. source_name sans auteur : "TikTok #{hashtag}" ----------------

    def test_source_name_without_author(self, _mock_dns):
        # Flux sans <author>
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test feed</title>
  <entry>
    <title>Titre sans auteur</title>
    <link href="https://www.tiktok.com/@anon/video/1234"/>
    <published>2026-05-01T10:00:00Z</published>
    <summary>Pas d auteur.</summary>
  </entry>
</feed>"""
        session = MagicMock()
        session.get.return_value = _mock_response(xml)

        results = tiktok.fetch_via_bridge("rappelconso", "https://bridge.example.com", 0, session=session)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source_name, "TikTok #rappelconso")


# ===========================================================================
# Classe 5 — keywords.py : TIKTOK_HASHTAGS et SOURCE_WEIGHTS
# ===========================================================================

class TestKeywords(unittest.TestCase):

    # --- 19. TIKTOK_HASHTAGS : au moins 8 entrees --------------------------

    def test_tiktok_hashtags_defined(self):
        from detecteur_signaux.keywords import TIKTOK_HASHTAGS
        self.assertGreaterEqual(
            len(TIKTOK_HASHTAGS), 8,
            f"TIKTOK_HASHTAGS trop court : {TIKTOK_HASHTAGS}"
        )

    # --- 20. SOURCE_WEIGHTS entrees TikTok ---------------------------------

    def test_source_weights_tiktok_generic(self):
        from detecteur_signaux.keywords import SOURCE_WEIGHTS
        self.assertEqual(SOURCE_WEIGHTS.get("tiktok"), 10)

    def test_source_weights_tiktok_60millions(self):
        from detecteur_signaux.keywords import SOURCE_WEIGHTS
        self.assertEqual(SOURCE_WEIGHTS.get("tiktok @60millions"), 25)

    def test_source_weights_tiktok_dgccrf(self):
        from detecteur_signaux.keywords import SOURCE_WEIGHTS
        self.assertEqual(SOURCE_WEIGHTS.get("tiktok @dgccrf"), 30)


# ===========================================================================
# Classe 6 — TestSecurityHardening
# ===========================================================================

class TestSecurityHardening(unittest.TestCase):
    """Tests de securite : SSRF, cap taille reponse, cap items, except large."""

    # Helpers

    def _make_streaming_response(self, total_bytes: int, chunk_size: int = 64 * 1024):
        """
        Cree un MagicMock de response streaming dont iter_content yielde total_bytes.
        Supporte le protocole context-manager.
        """
        resp = MagicMock()
        resp.raise_for_status = MagicMock()

        chunks = []
        remaining = total_bytes
        while remaining > 0:
            current = min(chunk_size, remaining)
            chunks.append(b"x" * current)
            remaining -= current

        resp.iter_content = MagicMock(return_value=iter(chunks))
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    # --- 21. localhost rejete par validation SSRF ----------------------------

    def test_bridge_url_localhost_rejected(self):
        """http://127.0.0.1:6379 -> fetch_via_bridge retourne [] sans appel HTTP."""
        mock_session = MagicMock()

        results = tiktok.fetch_via_bridge(
            "rappelconso", "http://127.0.0.1:6379", 0, session=mock_session
        )

        self.assertEqual(results, [])
        mock_session.get.assert_not_called()

    # --- 22. IP privee rejetee -------------------------------------------

    @patch("detecteur_signaux.sources.tiktok.socket.gethostbyname", return_value="192.168.1.1")
    def test_bridge_url_private_ip_rejected(self, _mock_dns):
        """http://192.168.1.1 (IP privee) -> [] sans appel HTTP."""
        mock_session = MagicMock()

        results = tiktok.fetch_via_bridge(
            "rappelconso", "http://192.168.1.1", 0, session=mock_session
        )

        self.assertEqual(results, [])
        mock_session.get.assert_not_called()

    # --- 23. IP metadata AWS rejetee -------------------------------------

    def test_bridge_url_metadata_aws_rejected(self):
        """http://169.254.169.254/ (link-local metadata AWS/GCP) -> []."""
        mock_session = MagicMock()

        results = tiktok.fetch_via_bridge(
            "rappelconso", "http://169.254.169.254/", 0, session=mock_session
        )

        self.assertEqual(results, [])
        mock_session.get.assert_not_called()

    # --- 24. Schema file:// rejete --------------------------------------

    def test_bridge_url_invalid_scheme_rejected(self):
        """file:///etc/passwd -> schema invalide -> []."""
        mock_session = MagicMock()

        results = tiktok.fetch_via_bridge(
            "rappelconso", "file:///etc/passwd", 0, session=mock_session
        )

        self.assertEqual(results, [])
        mock_session.get.assert_not_called()

    # --- 25. IP publique acceptee -> requete effectuee -------------------

    @patch("detecteur_signaux.sources.tiktok.socket.gethostbyname", return_value=_PUBLIC_IP)
    def test_bridge_url_https_public_accepted(self, _mock_dns):
        """IP publique (93.184.216.34 = example.com) -> validation OK, requete emise."""
        atom_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test</title>
  <entry>
    <title>Test entry</title>
    <link href="https://www.tiktok.com/@user/video/999"/>
    <published>2026-05-01T10:00:00Z</published>
    <summary>Test content.</summary>
    <author><name>user</name></author>
  </entry>
</feed>"""

        mock_session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.iter_content = MagicMock(return_value=iter([atom_xml]))
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = resp

        results = tiktok.fetch_via_bridge(
            "rappelconso", "https://example.com", 0, session=mock_session
        )

        # La requete HTTP doit avoir ete emise
        mock_session.get.assert_called_once()
        self.assertIsInstance(results, list)

    # --- 26. TIKTOK_ALLOW_INSECURE_BRIDGE=1 bypasse la validation ----------

    def test_bridge_allow_insecure_override(self):
        """Avec TIKTOK_ALLOW_INSECURE_BRIDGE=1, http://127.0.0.1:6379 peut etre appele."""
        atom_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test</title>
</feed>"""

        mock_session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.iter_content = MagicMock(return_value=iter([atom_xml]))
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = resp

        original_env = os.environ.get("TIKTOK_ALLOW_INSECURE_BRIDGE")
        try:
            os.environ["TIKTOK_ALLOW_INSECURE_BRIDGE"] = "1"
            results = tiktok.fetch_via_bridge(
                "rappelconso", "http://127.0.0.1:6379", 0, session=mock_session
            )
        finally:
            if original_env is None:
                os.environ.pop("TIKTOK_ALLOW_INSECURE_BRIDGE", None)
            else:
                os.environ["TIKTOK_ALLOW_INSECURE_BRIDGE"] = original_env

        # La requete doit avoir ete tentee (validation bypassee)
        mock_session.get.assert_called_once()
        self.assertIsInstance(results, list)

    # --- 27. Cap taille reponse Atom (fetch_via_bridge) -------------------

    @patch("detecteur_signaux.sources.tiktok.socket.gethostbyname", return_value=_PUBLIC_IP)
    def test_response_size_cap_atom(self, _mock_dns):
        """Body de 5 MB depasse MAX_RESPONSE_BYTES_ATOM (2 MB) -> [] + WARNING."""
        five_mb = 5 * 1024 * 1024
        mock_session = MagicMock()
        mock_session.get.return_value = self._make_streaming_response(five_mb)

        with self.assertLogs("detecteur_signaux.sources.tiktok", level="WARNING") as cm:
            results = tiktok.fetch_via_bridge(
                "rappelconso", "https://example.com", 0, session=mock_session
            )

        self.assertEqual(results, [])
        self.assertTrue(any("depasse" in line for line in cm.output))

    # --- 28. Cap taille reponse HTML (fetch_via_scraping) ----------------

    def test_response_size_cap_html(self):
        """Body de 15 MB depasse MAX_RESPONSE_BYTES_HTML (10 MB) -> [] + WARNING."""
        fifteen_mb = 15 * 1024 * 1024
        mock_session = MagicMock()
        mock_session.get.return_value = self._make_streaming_response(fifteen_mb)

        with self.assertLogs("detecteur_signaux.sources.tiktok", level="WARNING") as cm:
            results = tiktok.fetch_via_scraping(
                "rappelconso", 0, session=mock_session
            )

        self.assertEqual(results, [])
        self.assertTrue(any("depasse" in line for line in cm.output))

    # --- 29. Cap MAX_ITEMS_PER_HASHTAG -----------------------------------

    def test_max_items_per_hashtag(self):
        """300 videos dans le blob JSON -> au plus 200 items retournes."""
        video_list = [
            {
                "id": str(i),
                "desc": f"video {i}",
                "createTime": 1714564800,
                "author": {"uniqueId": f"user{i}"},
                "stats": {"playCount": 9999},
            }
            for i in range(300)
        ]
        payload = {"VideoFeedPage": {"videoList": video_list}}
        body_bytes = (
            "<html><body><script>"
            "__UNIVERSAL_DATA_FOR_REHYDRATION__ = "
            + json.dumps(payload)
            + "</script></body></html>"
        ).encode("utf-8")

        mock_session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.iter_content = MagicMock(return_value=iter([body_bytes]))
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = resp

        results = tiktok.fetch_via_scraping("rappelconso", 0, session=mock_session)

        self.assertLessEqual(len(results), tiktok.MAX_ITEMS_PER_HASHTAG)
        self.assertEqual(len(results), 200)

    # --- 30. Video mal formee skipee sans crash (except large) -----------

    def test_malformed_video_skipped_not_crashed(self):
        """
        3 videos dont 1 avec stats=42 (pas un dict, non-falsy) -> AttributeError
        sur 42.get("playCount"). L'ancien except (KeyError, TypeError) ne la
        catchait pas ; le nouveau except Exception la skippe proprement.
        2 items retournes sans exception levee.
        """
        video_list = [
            {
                "id": "1001",
                "desc": "video normale 1",
                "createTime": 1714564800,
                "author": {"uniqueId": "user1"},
                "stats": {"playCount": 9999},
            },
            {
                # stats=42 : truthy donc `42 or {}` retourne 42,
                # puis 42.get("playCount") -> AttributeError,
                # NON catchee par l'ancien except (KeyError, TypeError)
                "id": "1002",
                "desc": "video mal formee stats",
                "createTime": 1714564800,
                "author": {"uniqueId": "user2"},
                "stats": 42,
            },
            {
                "id": "1003",
                "desc": "video normale 2",
                "createTime": 1714564800,
                "author": {"uniqueId": "user3"},
                "stats": {"playCount": 9999},
            },
        ]
        payload = {"VideoFeedPage": {"videoList": video_list}}
        body_bytes = (
            "<html><body><script>"
            "__UNIVERSAL_DATA_FOR_REHYDRATION__ = "
            + json.dumps(payload)
            + "</script></body></html>"
        ).encode("utf-8")

        mock_session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.iter_content = MagicMock(return_value=iter([body_bytes]))
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = resp

        # Ne doit pas lever d'exception
        results = tiktok.fetch_via_scraping("rappelconso", 0, session=mock_session)

        # Les 2 videos valides passent, la malformee est skippee
        self.assertEqual(len(results), 2)
        titres = {r.titre for r in results}
        self.assertIn("video normale 1", titres)
        self.assertIn("video normale 2", titres)


if __name__ == "__main__":
    unittest.main()
