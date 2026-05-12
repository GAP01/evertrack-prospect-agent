# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Agent 4 (`detecteur_signaux`) : source TikTok optionnelle via 3 tiers
  fallback-first : RSS-bridge auto-heberge (tier 1, `feedparser`), scraping
  direct `tiktok.com/tag/<hashtag>` avec parse du blob JSON
  `__UNIVERSAL_DATA_FOR_REHYDRATION__` (tier 2), degraded mode silencieux
  si les deux tiers echouent (tier 3). Voir `docs/adr/ADR-006-tiktok-source-signaux.md`.
- Variables d'environnement `TIKTOK_BRIDGE_BASE_URL`, `TIKTOK_USER_AGENT`,
  `TIKTOK_ALLOW_INSECURE_BRIDGE` pour configurer la source TikTok.
- Constante `TIKTOK_HASHTAGS` dans `agents/detecteur_signaux/keywords.py`
  (8 hashtags par defaut : rappelproduit, rappelconso, intoxalimentaire,
  salmonelle, listeria, alertealimentaire, produitcontamine, alimentdangereux).
- Champs `tiktok_hashtags`, `tiktok_bridge_base_url`, `tiktok_min_view_count`
  dans `SourceConfig` (`agents/detecteur_signaux/sources/config.py`).
- Entrees `SOURCE_WEIGHTS` pour TikTok dans `keywords.py` :
  `"tiktok"` = 10, `"tiktok @60millions"` = 25, `"tiktok @dgccrf"` = 30.
- 22 tests unitaires + 10 tests de securite dans
  `agents/detecteur_signaux/tests/test_tiktok_source.py`
  (couverture : parse RSS-bridge, fallback scraping direct, filtre view_count,
  SSRF, caps taille/items, fallback inter-tiers, defensive parsing item malforme).

### Security
- Validation SSRF sur l'URL du bridge TikTok (`_is_safe_bridge_url`) : schemas
  non http/https et IPs privees, loopback, link-local, reservees, multicast et
  non-specifiees sont rejetes. Override via `TIKTOK_ALLOW_INSECURE_BRIDGE=1`
  pour les deployments LAN (ne pas activer en production exposee).
- Cap taille reponse HTTP : 2 MB pour le flux Atom RSS-bridge, 10 MB pour la
  page HTML du scraping direct. Abort et fallback au dela de la limite.
- Cap nombre d'items par hashtag : 200 items maximum traites par run et par
  hashtag (protection contre les flux anormalement volumineux).
- Defensive catch par item dans les boucles de parsing des deux tiers : un item
  malforme est logue et saute sans interrompre le traitement des suivants.
