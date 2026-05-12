# Detecteur de signaux faibles — Agent 4

Detecte les alertes precoces dans la presse en ligne, sur Reddit et sur TikTok
— en amont ou en parallele des publications RappelConso officielles. Chaque
article / post est analyse, structure (marque + produit + symptome), score et
croise avec `incidents.sqlite` pour validation algorithmique.

## Structure

```
detecteur_signaux/
├── __init__.py
├── models.py              # SignalAlerte, SignalSource, SCORE_SEUIL_ALERTE
├── keywords.py            # Lexique symptomes, queries, SOURCE_WEIGHTS, TIKTOK_HASHTAGS
├── sources/
│   ├── config.py          # SourceConfig (dataclass parametres par source)
│   ├── registry.py        # @register decorator + _ensure_collectors_loaded
│   ├── google_news.py     # RSS Google News via feedparser
│   ├── reddit.py          # JSON API publique Reddit
│   ├── signalconso.py     # API SignalConso (source additionnelle)
│   └── tiktok.py          # RSS-bridge + scraping direct (voir ci-dessous)
├── extractor.py           # Claude Haiku extraction + fallback regex
├── deduplicator.py        # compute_signal_id (hash stable)
├── scorer.py              # 5 composantes scoring
├── cross_reference.py     # Match signal <-> incident (4 dimensions)
├── rappelconso_link.py    # Decode Google News + extrait URLs RappelConso
├── storage.py             # SignalStorage — 3 tables SQLite
├── detecteur.py           # run_detect orchestrateur
├── cli.py                 # fetch, list, show, stats, validate, promote, crossref
└── tests/
```

## Installation

Depuis `agents/` :

```bash
pip install -r detecteur_signaux/requirements.txt
```

Dependances : `requests`, `feedparser`, `python-dotenv`, `anthropic`,
`googlenewsdecoder`.

## Utilisation

```bash
# Fetch complet (toutes sources par defaut : google_news, reddit, signalconso)
python -m detecteur_signaux.cli fetch --max 100

# Sans LLM ni scrape HTML (rapide, fallback regex)
python -m detecteur_signaux.cli fetch --no-llm --no-scrape

# Sources specifiques
python -m detecteur_signaux.cli fetch --sources google_news
python -m detecteur_signaux.cli fetch --sources google_news,reddit,tiktok

# Liste, detail, stats
python -m detecteur_signaux.cli list --status a_valider --min-score 40
python -m detecteur_signaux.cli show <signal_id>
python -m detecteur_signaux.cli stats

# Validation humaine
python -m detecteur_signaux.cli validate <signal_id> --accept
python -m detecteur_signaux.cli validate <signal_id> --reject
python -m detecteur_signaux.cli promote <signal_id>

# Recalcul cross-ref sans refetch
python -m detecteur_signaux.cli crossref

# Scraper les URLs RappelConso dans les articles existants
python -m detecteur_signaux.cli scrape-links --sleep 0.3
```

## Sources

### Source Google News

Flux RSS public `news.google.com/rss/search`. Aucune authentification requise.
Queries definies dans `keywords.py::GOOGLE_NEWS_QUERIES`.

Les URLs sont encodees en base64 protobuf par Google — resolues via
`googlenewsdecoder` (appel a `news.google.com/_/DotsSplashUi/data/batchexecute`).
Sans ce decodage, le scraping HTML des articles est inutile.

Ponderation par defaut : varie selon la source (Marmiton 18, Le Monde 28,
LSA 30). Voir `SOURCE_WEIGHTS` dans `keywords.py`.

### Source Reddit

Endpoint JSON public `reddit.com/r/<sub>/search.json`. User-Agent custom
obligatoire. Rate limit respecte (1,5s entre requetes). Filtre posts avec
`score < 2`.

Subreddits : `r/france`, `r/Consommateurs`, `r/AskFrance`. Configurable via
`keywords.py::REDDIT_SUBREDDITS`.

### Source SignalConso

API SignalConso (signalconso.gouv.fr). Source additionnelle de plaintes
consommateurs.

### Source TikTok

**Statut** : optionnelle (non activee par defaut). Mode `degraded` automatique si aucun tier disponible.

Trois tiers en cascade :

1. **RSS-bridge auto-heberge** (recommande) — instance auto-hebergee de
   https://github.com/RSS-Bridge/rss-bridge. Reutilise `feedparser`, deja
   en dependance. Configurer via :
   ```
   TIKTOK_BRIDGE_BASE_URL=https://bridge.example.com
   ```
2. **Scraping direct** `tiktok.com/tag/<hashtag>` — fallback automatique si le
   tier 1 echoue ou retourne 0 item. Parser le blob JSON
   `__UNIVERSAL_DATA_FOR_REHYDRATION__`. Optionnel :
   ```
   TIKTOK_USER_AGENT="Mozilla/5.0 ..."
   ```
3. **Degraded mode** — si les deux tiers retournent 0 item, la source loggue
   un WARNING et n'emet rien. L'agent continue normalement avec les autres
   sources.

**Hashtags par defaut** : voir `TIKTOK_HASHTAGS` dans `keywords.py` (8 hashtags
rappel produit / intoxication / salmonelle / listeria, etc). Pour les overrider,
passer `tiktok_hashtags=["rappelproduit"]` dans `SourceConfig`.

**Commande CLI** :
```bash
python -m detecteur_signaux.cli fetch --sources tiktok --max 50
python -m detecteur_signaux.cli fetch --sources google_news,reddit,tiktok
```

**Filtre view_count** : `SourceConfig.tiktok_min_view_count` (defaut 1000).
Si le champ n'est pas disponible dans la source, l'item passe (comportement
defensif).

**Statut legal et limites** :

- Best-effort, zone grise vis-a-vis des ToS TikTok. Pas de SLA. La casse est
  attendue tous les 3-6 mois si TikTok modifie son markup ou la structure JSON.
- Aucun scraping de commentaires (RGPD).
- En cas de rupture du tier 2, evaluer l'option Apify ou Bright Data (cf.
  ADR-006 pour le rationale).

**Securite SSRF** :

La validation `_is_safe_bridge_url` rejette par defaut les URLs dont l'IP
resolue est privee, loopback, link-local ou reservee (ex: 127.0.0.1, 192.168.x.x,
169.254.169.254). Seule une URL pointant vers une IP publique est acceptee pour
les appels vers le bridge RSS-bridge. Override pour les reseaux prives (LAN) :
poser `TIKTOK_ALLOW_INSECURE_BRIDGE=1` dans l'environnement.

**Caps de protection (CWE-400)** :

- `MAX_RESPONSE_BYTES_ATOM = 2 MB` — taille maximale du flux Atom RSS-bridge.
- `MAX_RESPONSE_BYTES_HTML = 10 MB` — taille maximale de la page HTML tier 2.
- `MAX_ITEMS_PER_HASHTAG = 200` — nombre maximal d'items traites par hashtag et par run.

Au-dela de ces limites, la reponse est abandonnee et le tier suivant prend le relais.

## Variables d'environnement

| Variable | Obligatoire ? | Usage |
|---|---|---|
| `ANTHROPIC_API_KEY` | Recommandee | Extraction marque/produit/symptome via Claude Haiku. Fallback regex sinon. |
| `TIKTOK_BRIDGE_BASE_URL` | Recommandee (si TikTok actif) | URL de l'instance RSS-bridge auto-hebergee. Vide = fallback scraping direct. |
| `TIKTOK_USER_AGENT` | Optionnelle | UA custom pour le scraping direct TikTok. |
| `TIKTOK_ALLOW_INSECURE_BRIDGE=1` | Optionnelle | Bypass de la validation SSRF pour un bridge auto-heberge en reseau prive (LAN). NE PAS activer en production exposee. |

## Tests

```bash
cd agents
python -m unittest discover detecteur_signaux/tests
```

## Comportement

- **Fallback-first** : sans `ANTHROPIC_API_KEY`, l'extraction bascule sur le
  regex. Agent fonctionnel sans cle.
- **Idempotent** : `signal_id = sha1(marque + symptome + jour)[:16]`. Re-fetcher
  une source ne duplique pas les signaux.
- **`detected_at`** = date de publication de l'article source (pas la date de
  crawl). Alimente `recency` et `lead_time_days`.
- **Isolation d'erreurs** : un article qui plante l'extraction est logue et
  skippe. L'agent continue.
