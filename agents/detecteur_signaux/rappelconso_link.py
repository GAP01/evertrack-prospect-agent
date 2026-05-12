"""
Détection de liens directs vers RappelConso dans les articles de signaux.

Stratégie 2 niveaux :
1. Regex sur le contenu RSS déjà téléchargé (gratuit)
2. Si pas trouvé : HTTP GET de l'article + regex sur le HTML

Les URLs trouvées permettent de fermer le match signal ↔ incident sans
ambiguïté : un article qui CITE une fiche RappelConso est une preuve
directe du lien.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# URL canonique RappelConso : /fiche-rappel/<num>/<type>
# Le type peut être 'interne', 'externe', 'consommateur', etc.
_RAPPELCONSO_URL_RE = re.compile(
    r"https?://(?:www\.)?rappel\.conso\.gouv\.fr/fiche-rappel/(\d+)(?:/[\w-]+)?",
    re.IGNORECASE,
)

# Si un article référence la fiche sous une autre forme (lien partagé)
_RAPPELCONSO_SHORT_RE = re.compile(
    r"rappel\.conso\.gouv\.fr/fiche-rappel/(\d+)",
    re.IGNORECASE,
)


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 6  # secondes — court pour ne pas bloquer le pipeline


def extract_rappelconso_urls(text: Optional[str]) -> list[str]:
    """Retourne la liste DÉDUPLIQUÉE des URLs RappelConso trouvées dans text."""
    if not text:
        return []
    urls: set[str] = set()
    for m in _RAPPELCONSO_URL_RE.finditer(text):
        # Canonise : garde juste /fiche-rappel/NNN/interne (type par défaut interne)
        # On stocke ce que l'article contient effectivement pour traçabilité
        urls.add(m.group(0))
    # Si on n'a rien trouvé avec le schéma complet, tente la forme courte
    if not urls:
        for m in _RAPPELCONSO_SHORT_RE.finditer(text):
            num = m.group(1)
            urls.add(f"https://rappel.conso.gouv.fr/fiche-rappel/{num}/interne")
    return sorted(urls)


def extract_fiche_number(url: str) -> Optional[str]:
    """Extrait le numéro de fiche depuis une URL. Ex: '22094'."""
    m = _RAPPELCONSO_SHORT_RE.search(url)
    return m.group(1) if m else None


def resolve_google_news_url(url: str) -> Optional[str]:
    """
    Décode l'URL Google News masquée vers l'URL cible de l'article.
    Google News encode l'URL réelle dans un protobuf base64 → il faut
    passer par leur API de résolution.

    Retourne l'URL résolue, ou None si échec.
    """
    if "news.google.com" not in url:
        return url  # déjà une URL directe
    try:
        from googlenewsdecoder import new_decoderv1  # type: ignore
    except ImportError:
        logger.warning("googlenewsdecoder non installé → URLs Google News opaques")
        return None
    try:
        result = new_decoderv1(url, interval=1)
        if result and result.get("status") and result.get("decoded_url"):
            return str(result["decoded_url"])
    except Exception as exc:
        logger.debug("resolve_google_news_url KO (%s) : %s", url[:60], exc)
    return None


def fetch_article_html(
    url: str,
    timeout: float = REQUEST_TIMEOUT,
    session: Optional[requests.Session] = None,
) -> Optional[str]:
    """
    GET de l'URL de l'article. Retourne le HTML ou None en cas d'échec.
    Résout les URLs Google News automatiquement.
    Silencieux sur les erreurs — c'est du best-effort.
    """
    # Résout les URLs Google News masquées vers l'URL directe de l'article
    if "news.google.com" in url:
        resolved = resolve_google_news_url(url)
        if not resolved:
            return None
        url = resolved

    sess = session or requests.Session()
    try:
        resp = sess.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        ctype = resp.headers.get("Content-Type", "").lower()
        if "html" not in ctype and "text" not in ctype:
            return None
        # Cap à 500 KB pour éviter les pages énormes
        if len(resp.content) > 500_000:
            return resp.text[:500_000]
        return resp.text
    except requests.RequestException as exc:
        logger.debug("fetch_article_html KO (%s) : %s", url, exc)
        return None
    except Exception as exc:
        logger.debug("fetch_article_html erreur inattendue (%s) : %s", url, exc)
        return None


def find_rappelconso_url_for_source(
    content_rss: Optional[str],
    source_url: Optional[str],
    scrape: bool = True,
    session: Optional[requests.Session] = None,
) -> Optional[str]:
    """
    Cherche une URL RappelConso liée à cet article.

    1. D'abord dans le contenu RSS (rapide)
    2. Puis dans le HTML de l'article (si scrape=True et URL fournie)

    Retourne la 1re URL trouvée ou None.
    """
    # Niveau 1 : RSS
    urls = extract_rappelconso_urls(content_rss)
    if urls:
        return urls[0]

    # Niveau 2 : fetch HTML
    if not scrape or not source_url:
        return None
    html = fetch_article_html(source_url, session=session)
    if not html:
        return None
    urls = extract_rappelconso_urls(html)
    return urls[0] if urls else None
