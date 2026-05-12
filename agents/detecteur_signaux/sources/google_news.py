"""
Source Google News via flux RSS.

Pas d'authentification nécessaire. URL publique :
    https://news.google.com/rss/search?q={query}&hl=fr&gl=FR&ceid=FR:fr

Retourne des `SignalSource` normalisés — l'extraction marque/produit/symptôme
se fait plus loin dans le pipeline (`extractor.py`).
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Iterable, Iterator, Optional
from xml.etree import ElementTree as ET

import requests

from ..models import SignalSource
from ..keywords import GOOGLE_NEWS_QUERIES
from .config import SourceConfig
from .registry import register

logger = logging.getLogger(__name__)


GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
USER_AGENT = "Mozilla/5.0 (compatible; EverTrackDetecteurSignaux/0.1)"
REQUEST_TIMEOUT = 15  # secondes


def _build_url(query: str) -> str:
    params = {
        "q": query,
        "hl": "fr",
        "gl": "FR",
        "ceid": "FR:fr",
    }
    return GOOGLE_NEWS_RSS_URL + "?" + urllib.parse.urlencode(params)


def _parse_pubdate(value: Optional[str]) -> datetime:
    """Parse RFC 2822 date. Retourne now() en cas d'échec."""
    if not value:
        return datetime.utcnow()
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(value)
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return datetime.utcnow()


def _extract_source_name(item_source_el: Optional[ET.Element], fallback: str = "") -> str:
    """Le nom du média est dans <source> enfant de <item>."""
    if item_source_el is not None and item_source_el.text:
        return item_source_el.text.strip()
    return fallback


def _clean_html(text: str) -> str:
    """Enlève les tags HTML basiques du résumé Google News."""
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def fetch_query(query: str, session: Optional[requests.Session] = None) -> list[SignalSource]:
    """Fetch une requête Google News et retourne les items normalisés."""
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT})

    url = _build_url(query)
    logger.info("Google News fetch : %s", query)

    try:
        resp = sess.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Google News fetch failed for %r : %s", query, exc)
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        logger.warning("Google News XML invalide pour %r : %s", query, exc)
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    signals: list[SignalSource] = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = _clean_html(item.findtext("description") or "")
        pub_date = _parse_pubdate(item.findtext("pubDate"))
        source_name = _extract_source_name(item.find("source"), fallback="Google News")

        if not title or not link:
            continue

        signals.append(
            SignalSource(
                source_type="google_news",
                source_name=source_name,
                source_url=link,
                titre=title,
                detected_at=pub_date,
                contenu=description[:2000] if description else None,
            )
        )

    logger.info("Google News [%s] -> %d items", query, len(signals))
    return signals


def fetch_all(queries: Optional[Iterable[str]] = None) -> Iterator[SignalSource]:
    """Itère sur toutes les requêtes configurées."""
    queries = list(queries) if queries is not None else GOOGLE_NEWS_QUERIES
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for q in queries:
        try:
            yield from fetch_query(q, session=session)
        except Exception as exc:
            logger.exception("Erreur fetch Google News '%s' : %s", q, exc)


@register("google_news")
def collect(cfg: SourceConfig) -> Iterator[SignalSource]:
    """Adaptateur registry. Délègue à `fetch_all` avec les queries du cfg."""
    yield from fetch_all(queries=cfg.google_news_queries)
