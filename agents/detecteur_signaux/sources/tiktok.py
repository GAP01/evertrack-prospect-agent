"""
Source TikTok — 3 tiers de fallback.

Tier 1 : RSS-bridge auto-heberge (instance configurable via SourceConfig).
         Construit l'URL Atom TikTok et parse avec feedparser.
Tier 2 : Scraping direct de la page hashtag TikTok.
         Extrait le blob JSON __UNIVERSAL_DATA_FOR_REHYDRATION__.
Tier 3 : Degraded mode — log WARNING, ne yield rien, l'agent continue.

Pas d'envoi automatique, pas d'ecriture sur disque, pas de cache.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
import urllib.parse
from datetime import datetime, timezone
from typing import Iterator, Optional

import requests

from ..models import SignalSource
from ..keywords import TIKTOK_HASHTAGS, TIKTOK_BRIDGE_USERS
from .config import SourceConfig
from .registry import register

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (compatible; EverTrackDetecteurSignaux/0.1)"
REQUEST_TIMEOUT = 15
TIKTOK_BRIDGE_PATH = "/?action=display&bridge=TikTok&context=Hashtag&h={hashtag}&format=Atom"
# Path RSS-Bridge stock (bridge=TikTokBridge, context="By user", param "username").
# %40 = @ URL-encoded.
TIKTOK_BRIDGE_USER_PATH = (
    "/?action=display&bridge=TikTokBridge&context=By+user&username=%40{username}&format=Atom"
)
TIKTOK_HASHTAG_URL = "https://www.tiktok.com/tag/{hashtag}"
JSON_BLOB_PATTERN = r"__UNIVERSAL_DATA_FOR_REHYDRATION__\s*=\s*(\{.+?\})\s*</script>"

# Bornes de taille de reponse HTTP (protection CWE-400)
MAX_RESPONSE_BYTES_ATOM = 2 * 1024 * 1024       # 2 MB — flux Atom bridge
MAX_RESPONSE_BYTES_HTML = 10 * 1024 * 1024      # 10 MB — page HTML scraping

# Cap sur le nombre d'items traites par hashtag (protection CWE-400)
MAX_ITEMS_PER_HASHTAG = 200


# ---------------------------------------------------------------------------
# Helpers prives
# ---------------------------------------------------------------------------

def _parse_struct_time(tup: Optional[tuple]) -> datetime:
    """Convertit un published_parsed (struct_time 9-tuple) en datetime UTC naive."""
    if not tup:
        return datetime.utcnow()
    try:
        return datetime(*tup[:6], tzinfo=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return datetime.utcnow()


def _safe_int(value) -> Optional[int]:
    """Parse defensif en int. Retourne None si non parseable."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _walk_video_list(data: dict) -> list[dict]:
    """
    Essaie plusieurs paths connus dans le blob JSON pour extraire la liste
    de videos. Retourne [] si aucun path ne correspond.

    Paths testes dans l'ordre :
      1. data["VideoFeedPage"]["videoList"]  -- format observe lors des tests
      2. data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["videoList"]
    """
    # Path 1 : format standard page hashtag (structure la plus courante en fixture)
    try:
        videos = data["VideoFeedPage"]["videoList"]
        if isinstance(videos, list):
            return videos
    except (KeyError, TypeError):
        pass

    # Path 2 : scope alternatif (peut varier selon la version du frontend TikTok)
    try:
        scope = data.get("__DEFAULT_SCOPE__", {})
        videos = scope.get("webapp.video-detail", {}).get("videoList", [])
        if isinstance(videos, list):
            return videos
    except (KeyError, TypeError):
        pass

    return []


def _is_safe_bridge_url(url: str) -> bool:
    """
    Valide une URL de bridge RSS-bridge contre les attaques SSRF (CWE-918).

    Regles :
    - Schema doit etre http ou https.
    - Host non vide.
    - L'IP resolue ne doit pas etre privee, loopback, link-local, reservee,
      multicast ou non-specifiee.

    Override : si la variable d'env TIKTOK_ALLOW_INSECURE_BRIDGE=1 est posee,
    la validation est bypassee — utile pour un bridge auto-heberge en reseau
    prive (LAN). NE PAS activer en production exposee.
    """
    if os.environ.get("TIKTOK_ALLOW_INSECURE_BRIDGE") == "1":
        return True

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    host = parsed.hostname
    if not host:
        return False

    try:
        ip_str = socket.gethostbyname(host)
    except socket.gaierror:
        return False

    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False

    return True


def _bounded_get(
    session: requests.Session,
    url: str,
    max_bytes: int,
    timeout: int = REQUEST_TIMEOUT,
) -> Optional[bytes]:
    """
    GET avec borne stricte sur la taille du body. Retourne bytes ou None.

    Si le body depasse max_bytes, abort et retourne None (log WARNING).
    Toute RequestException est egalement logguee et retourne None.
    """
    try:
        with session.get(url, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            chunks = []
            total = 0
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    logger.warning(
                        "[tiktok] payload depasse %d bytes pour %s, abort",
                        max_bytes,
                        url,
                    )
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
    except requests.RequestException as exc:
        logger.warning("[tiktok] HTTP error %s : %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Tier 1 — RSS-bridge
# ---------------------------------------------------------------------------

def fetch_via_bridge(
    hashtag: str,
    bridge_base_url: str,
    min_view_count: int,
    session: Optional[requests.Session] = None,
) -> list[SignalSource]:
    """
    Recupere les videos TikTok via une instance RSS-bridge auto-hebergee.

    Si le bridge est indisponible ou retourne un flux invalide, retourne []
    pour permettre le fallback vers le tier 2.

    La validation SSRF (_is_safe_bridge_url) est appliquee en amont de tout
    appel reseau. Un bridge injoignable ou dont l'URL est privee retourne []
    sans exception.
    """
    import feedparser  # import local pour isoler les erreurs d'import feedparser

    if not _is_safe_bridge_url(bridge_base_url):
        logger.warning(
            "[tiktok bridge] URL bridge rejetee (SSRF check) : %s", bridge_base_url
        )
        return []

    sess = session or requests.Session()
    url = bridge_base_url.rstrip("/") + TIKTOK_BRIDGE_PATH.format(
        hashtag=urllib.parse.quote(hashtag)
    )

    body = _bounded_get(sess, url, MAX_RESPONSE_BYTES_ATOM)
    if body is None:
        # _bounded_get a deja logue le warning
        return []

    feed = feedparser.parse(body)
    if feed.bozo and not feed.entries:
        logger.warning(
            "[tiktok bridge] #%s : flux Atom invalide (bozo=%s)",
            hashtag,
            feed.bozo_exception,
        )
        return []

    entries = list(feed.entries or [])[:MAX_ITEMS_PER_HASHTAG]

    items: list[SignalSource] = []
    for entry in entries:
        try:
            link = entry.get("link") or ""
            if not link:
                continue

            title = (entry.get("title") or "")[:200].strip()

            # Auteur : champ standard ou fallback dans la liste authors
            author = entry.get("author") or ""
            if not author:
                authors = entry.get("authors", [{}])
                author = (authors[0].get("name") or "") if authors else ""
            source_name = f"TikTok @{author}" if author else f"TikTok #{hashtag}"

            detected_at = _parse_struct_time(entry.get("published_parsed"))

            # Contenu : description + tags
            description = entry.get("summary") or entry.get("description") or ""
            tags = [t.get("term") or "" for t in entry.get("tags", [])]
            tags_str = "  " + "  ".join(f"#{t}" for t in tags if t) if tags else ""
            contenu = (description + tags_str)[:2000] or None

            # Filtre view_count (defensif : si non parseable, l'item passe)
            raw_vc = entry.get("view_count") or entry.get("tiktok_viewcount")
            vc = _safe_int(raw_vc)
            if vc is not None and vc < min_view_count:
                continue

            items.append(
                SignalSource(
                    source_type="tiktok",
                    source_name=source_name,
                    source_url=link,
                    titre=title,
                    detected_at=detected_at,
                    contenu=contenu,
                )
            )
        except Exception as exc:
            logger.warning("[tiktok bridge] entry ignoree : %s", exc)
            continue

    logger.info("[tiktok bridge] #%s -> %d items", hashtag, len(items))
    return items


def fetch_via_bridge_user(
    username: str,
    bridge_base_url: str,
    session: Optional[requests.Session] = None,
) -> list[SignalSource]:
    """
    Recupere les videos TikTok d'un compte specifique via RSS-Bridge.

    Le bridge stock RSS-Bridge ne supporte que le mode "By user" pour TikTok,
    pas hashtag. On cible donc des comptes verifies a forte valeur (presse
    conso, autorites, etc.).

    Pas de filtre view_count : le bridge user retourne les dernieres videos
    du compte, deja pre-filtrees par la pertinence editoriale du compte.
    """
    import feedparser

    if not _is_safe_bridge_url(bridge_base_url):
        logger.warning(
            "[tiktok bridge user] URL bridge rejetee (SSRF check) : %s", bridge_base_url
        )
        return []

    sess = session or requests.Session()
    # Normalisation defensive du username (strip @ et caracteres parasites)
    clean = username.lstrip("@").strip()
    url = bridge_base_url.rstrip("/") + TIKTOK_BRIDGE_USER_PATH.format(
        username=urllib.parse.quote(clean)
    )

    body = _bounded_get(sess, url, MAX_RESPONSE_BYTES_ATOM)
    if body is None:
        return []

    feed = feedparser.parse(body)
    if feed.bozo and not feed.entries:
        logger.warning(
            "[tiktok bridge user] @%s : flux Atom invalide (bozo=%s)",
            clean,
            feed.bozo_exception,
        )
        return []

    entries = list(feed.entries or [])[:MAX_ITEMS_PER_HASHTAG]

    items: list[SignalSource] = []
    for entry in entries:
        try:
            link = entry.get("link") or ""
            if not link:
                continue

            title = (entry.get("title") or "")[:200].strip()
            source_name = f"TikTok @{clean}"
            detected_at = _parse_struct_time(entry.get("published_parsed"))

            description = entry.get("summary") or entry.get("description") or ""
            tags = [t.get("term") or "" for t in entry.get("tags", [])]
            tags_str = " " + " ".join(f"#{t}" for t in tags if t) if tags else ""
            contenu = (description + tags_str)[:2000] or None

            items.append(
                SignalSource(
                    source_type="tiktok",
                    source_name=source_name,
                    source_url=link,
                    titre=title,
                    detected_at=detected_at,
                    contenu=contenu,
                )
            )
        except Exception as exc:
            logger.warning("[tiktok bridge user] entry ignoree : %s", exc)
            continue

    logger.info("[tiktok bridge user] @%s -> %d items", clean, len(items))
    return items


# ---------------------------------------------------------------------------
# Tier 2 — Scraping direct
# ---------------------------------------------------------------------------

def fetch_via_scraping(
    hashtag: str,
    min_view_count: int,
    session: Optional[requests.Session] = None,
) -> list[SignalSource]:
    """
    Recupere les videos TikTok par scraping direct de la page hashtag.

    Extrait le blob JSON __UNIVERSAL_DATA_FOR_REHYDRATION__ injecte dans le
    HTML par le SSR TikTok. Defensif : retourne [] si le blob change de nom
    ou si la structure JSON evolue.
    """
    sess = session or requests.Session()
    ua = os.environ.get("TIKTOK_USER_AGENT", USER_AGENT)
    sess.headers.update({"User-Agent": ua})

    url = TIKTOK_HASHTAG_URL.format(hashtag=urllib.parse.quote(hashtag))

    body = _bounded_get(sess, url, MAX_RESPONSE_BYTES_HTML)
    if body is None:
        # _bounded_get a deja logue le warning
        return []

    html_text = body.decode("utf-8", errors="replace")

    m = re.search(JSON_BLOB_PATTERN, html_text, flags=re.DOTALL)
    if m is None:
        logger.warning("[tiktok scrape] #%s : blob JSON introuvable dans le HTML", hashtag)
        return []

    try:
        data = json.loads(m.group(1))
    except ValueError as exc:
        logger.warning("[tiktok scrape] #%s : JSON parse error : %s", hashtag, exc)
        return []

    videos = _walk_video_list(data)[:MAX_ITEMS_PER_HASHTAG]

    items: list[SignalSource] = []
    for v in videos:
        try:
            video_id = str(v.get("id") or "").strip()
            if not video_id:
                continue

            desc = (v.get("desc") or "")[:200].strip()

            author_field = v.get("author", {})
            if isinstance(author_field, dict):
                author_id = (author_field.get("uniqueId") or "").strip()
            elif isinstance(author_field, str):
                author_id = author_field.strip()
            else:
                author_id = ""

            if author_id:
                source_url = f"https://www.tiktok.com/@{author_id}/video/{video_id}"
                source_name = f"TikTok @{author_id}"
            else:
                source_url = f"https://www.tiktok.com/video/{video_id}"
                source_name = f"TikTok #{hashtag}"

            create_time = v.get("createTime")
            try:
                detected_at = datetime.utcfromtimestamp(int(create_time))
            except (TypeError, ValueError, OSError):
                detected_at = datetime.utcnow()

            # Filtre view_count (defensif)
            stats = v.get("stats") or {}
            vc = _safe_int(stats.get("playCount"))
            if vc is not None and vc < min_view_count:
                continue

            contenu = (desc + "  #" + hashtag)[:2000] or None

            items.append(
                SignalSource(
                    source_type="tiktok",
                    source_name=source_name,
                    source_url=source_url,
                    titre=desc,
                    detected_at=detected_at,
                    contenu=contenu,
                )
            )
        except Exception as exc:
            logger.warning("[tiktok scrape] video skip : %s", exc)
            continue

    logger.info("[tiktok scrape] #%s -> %d items", hashtag, len(items))
    return items


# ---------------------------------------------------------------------------
# Orchestrateur — fallback tier 1 -> tier 2 -> tier 3 (degraded)
# ---------------------------------------------------------------------------

def fetch_all(
    hashtags: Optional[list[str]],
    bridge_base_url: Optional[str],
    min_view_count: int,
    bridge_users: Optional[list[str]] = None,
) -> Iterator[SignalSource]:
    """
    Itere sur les sources TikTok avec circuit breaker fallback-first.

    - Tier 1 bridge user : si `bridge_base_url` defini, recupere chaque compte
      de `bridge_users` (ou TIKTOK_BRIDGE_USERS par defaut). RSS-Bridge stock
      ne supporte pas hashtag, donc les hashtags sont reserves au tier 2.
    - Tier 2 scraping : pour chaque hashtag, scraping direct de la page
      tiktok.com/tag/<hashtag>.
    - Tier 3 degraded : aucun item pour la cible, on loggue et on continue.
    """
    hashtags = list(hashtags) if hashtags else TIKTOK_HASHTAGS
    users = list(bridge_users) if bridge_users else TIKTOK_BRIDGE_USERS

    session = requests.Session()
    session.headers.update({"User-Agent": os.environ.get("TIKTOK_USER_AGENT", USER_AGENT)})

    # Tier 1 : comptes verifies via bridge (mode user)
    if bridge_base_url:
        for user in users:
            items = fetch_via_bridge_user(user, bridge_base_url, session)
            if items:
                yield from items
            else:
                logger.warning("[tiktok] @%s : 0 item via bridge user", user)

    # Tier 2 : scraping hashtag direct
    for hashtag in hashtags:
        items = fetch_via_scraping(hashtag, min_view_count, session)
        if not items:
            logger.warning("[tiktok] #%s : source desactivee (degraded mode)", hashtag)
            continue
        yield from items


# ---------------------------------------------------------------------------
# Entree du registre
# ---------------------------------------------------------------------------

@register("tiktok")
def collect(cfg: SourceConfig) -> Iterator[SignalSource]:
    """Adaptateur registry. Delegue a fetch_all avec les params du cfg."""
    bridge_url = cfg.tiktok_bridge_base_url or os.environ.get("TIKTOK_BRIDGE_BASE_URL")
    yield from fetch_all(
        hashtags=cfg.tiktok_hashtags,
        bridge_base_url=bridge_url,
        min_view_count=cfg.tiktok_min_view_count,
        bridge_users=cfg.tiktok_bridge_users,
    )
