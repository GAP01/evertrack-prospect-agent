"""
Source Reddit via endpoint JSON public.

Pas besoin d'auth pour le read-only :
    https://www.reddit.com/r/{subreddit}/search.json?q={query}&restrict_sr=1&sort=new&t=week

Rate limit bas : User-Agent custom obligatoire, délai 1s entre requêtes.
Filtre les posts avec score < 2 pour réduire le bruit.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Iterable, Iterator, Optional

import requests

from ..models import SignalSource
from ..keywords import REDDIT_SUBREDDITS, REDDIT_QUERIES
from .config import SourceConfig
from .registry import register

logger = logging.getLogger(__name__)


REDDIT_SEARCH_URL = "https://www.reddit.com/r/{sub}/search.json"
USER_AGENT = "EverTrackDetecteurSignaux/0.1 (by /u/evertrack_bot)"
REQUEST_TIMEOUT = 15
MIN_POST_SCORE = 2
RATE_LIMIT_SLEEP = 1.5  # secondes entre requêtes (conservateur)


def _parse_created(created_utc: Optional[float]) -> datetime:
    if not created_utc:
        return datetime.utcnow()
    try:
        return datetime.utcfromtimestamp(float(created_utc))
    except (TypeError, ValueError):
        return datetime.utcnow()


def fetch_query_in_sub(
    subreddit: str,
    query: str,
    session: Optional[requests.Session] = None,
    period: str = "week",
) -> list[SignalSource]:
    """Search dans un subreddit spécifique. Retourne les posts pertinents."""
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT})

    url = REDDIT_SEARCH_URL.format(sub=subreddit)
    params = {
        "q": query,
        "restrict_sr": 1,
        "sort": "new",
        "t": period,
        "limit": 25,
    }
    logger.info("Reddit fetch : r/%s '%s'", subreddit, query)

    try:
        resp = sess.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Reddit fetch failed (r/%s, q=%r) : %s", subreddit, query, exc)
        return []

    try:
        payload = resp.json()
    except ValueError as exc:
        logger.warning("Reddit JSON invalide (r/%s) : %s", subreddit, exc)
        return []

    children = (payload.get("data") or {}).get("children") or []
    signals: list[SignalSource] = []
    for child in children:
        data = child.get("data") or {}
        score = int(data.get("score") or 0)
        if score < MIN_POST_SCORE:
            continue

        title = (data.get("title") or "").strip()
        permalink = data.get("permalink") or ""
        url_full = "https://www.reddit.com" + permalink if permalink else (data.get("url") or "")
        selftext = (data.get("selftext") or "").strip()
        created = _parse_created(data.get("created_utc"))

        if not title or not url_full:
            continue

        signals.append(
            SignalSource(
                source_type="reddit",
                source_name=f"r/{subreddit}",
                source_url=url_full,
                titre=title,
                detected_at=created,
                contenu=selftext[:2000] if selftext else None,
            )
        )

    logger.info("Reddit r/%s q=%r -> %d items (apres filtre score >= %d)",
                subreddit, query, len(signals), MIN_POST_SCORE)
    return signals


def fetch_all(
    subreddits: Optional[Iterable[str]] = None,
    queries: Optional[Iterable[str]] = None,
) -> Iterator[SignalSource]:
    subs = list(subreddits) if subreddits is not None else REDDIT_SUBREDDITS
    qs = list(queries) if queries is not None else REDDIT_QUERIES

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for sub in subs:
        for q in qs:
            try:
                yield from fetch_query_in_sub(sub, q, session=session)
            except Exception as exc:
                logger.exception("Erreur Reddit r/%s q=%r : %s", sub, q, exc)
            time.sleep(RATE_LIMIT_SLEEP)


@register("reddit")
def collect(cfg: SourceConfig) -> Iterator[SignalSource]:
    """Adaptateur registry. Délègue à `fetch_all` avec subreddits/queries du cfg."""
    yield from fetch_all(
        subreddits=cfg.reddit_subreddits,
        queries=cfg.reddit_queries,
    )
