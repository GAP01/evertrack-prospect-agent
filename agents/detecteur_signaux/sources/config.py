"""
Configuration commune passée à tous les collectors.

Les collectors lisent uniquement les champs qui les concernent et ignorent
les autres. None = utilise les defaults définis dans le module source
(ex: GOOGLE_NEWS_QUERIES dans keywords.py).

Préfixe par source pour éviter les collisions entre champs spécifiques :
    google_news_*    pour Google News
    reddit_*         pour Reddit
    signalconso_*    pour SignalConso (Phase 1)
    rasff_*          pour RASFF (Phase 2)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SourceConfig:
    # --- Communs ---------------------------------------------------------
    max_items: Optional[int] = None
    since_days: int = 7

    # --- Google News -----------------------------------------------------
    # None => utilise GOOGLE_NEWS_QUERIES depuis keywords.py
    google_news_queries: Optional[list[str]] = None

    # --- Reddit ----------------------------------------------------------
    # None => utilise REDDIT_SUBREDDITS / REDDIT_QUERIES depuis keywords.py
    reddit_subreddits: Optional[list[str]] = None
    reddit_queries: Optional[list[str]] = None

    # --- SignalConso (Phase 1, slot prêt) --------------------------------
    # Catégories DGCCRF à ingérer.
    # Default actuel : Alimentation + Cosmétiques + Produits de soin
    signalconso_categories: Optional[list[str]] = None

    # --- RASFF (Phase 2, slot pret) --------------------------------------
    # Filtre pays (codes ISO) -- None = FR seul.
    rasff_country_filter: Optional[list[str]] = None
    # Inclure les notifications feed (alimentation animale)
    rasff_include_feed: bool = False

    # --- TikTok ----------------------------------------------------------
    # None => utilise TIKTOK_HASHTAGS depuis keywords.py
    tiktok_hashtags: Optional[list[str]] = None
    # None => utilise TIKTOK_BRIDGE_USERS depuis keywords.py
    # Mode user du RSS-Bridge (le bridge stock ne supporte pas hashtag).
    tiktok_bridge_users: Optional[list[str]] = None
    # URL d'instance RSS-bridge auto-hebergee (tier 1).
    # None => tier 1 desactive, fallback direct sur le scraping tier 2.
    tiktok_bridge_base_url: Optional[str] = None
    # Filtre minimal sur view_count si dispo dans la source. Defensive :
    # si view_count non parseable, l'item passe.
    tiktok_min_view_count: int = 1000
