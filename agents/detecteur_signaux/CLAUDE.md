# Agent 4 — Détecteur de signaux faibles

## 1. Rôle et responsabilité

Détecte les **alertes précoces** dans la presse et sur Reddit — en amont ou
en parallèle des publications RappelConso officielles. Extrait marque /
produit / symptôme via **Claude Haiku**, déduplique, score la crédibilité
(0-100), et **croise** avec `incidents.sqlite` pour valider ou pas chaque signal.

Le système calcule un **lead time** (délai entre signal détecté et rappel
officiel) — positif = early warning, négatif = couverture presse post-rappel.

## 2. Fichiers principaux

```
detecteur_signaux/
├── models.py              # SignalAlerte, SignalSource, SCORE_SEUIL_ALERTE
├── keywords.py            # Lexique symptômes, queries Google News/Reddit, SOURCE_WEIGHTS
├── sources/
│   ├── config.py          # SourceConfig — parametres par source
│   ├── registry.py        # @register decorator + _ensure_collectors_loaded
│   ├── google_news.py     # feedparser-based RSS fetcher
│   ├── reddit.py          # JSON API publique (User-Agent obligatoire)
│   ├── signalconso.py     # API SignalConso (plaintes DGCCRF)
│   └── tiktok.py          # 3 tiers : RSS-bridge / scraping direct / degraded mode
├── extractor.py           # Claude Haiku extraction + fallback regex
├── deduplicator.py        # compute_signal_id (hash stable marque/produit/symptome+jour)
├── scorer.py              # 5 composantes : source, recurrence, recency, brand_known, sentiment
├── cross_reference.py     # Match signal ↔ incident (4 dimensions pondérées)
├── rappelconso_link.py    # Décode Google News + extrait URLs RappelConso des articles
├── storage.py             # SignalStorage — 3 tables : signaux, signaux_sources, signal_incident_matches
├── detecteur.py           # run_detect orchestrateur + validate_signal + promote_signal
├── cli.py                 # fetch, list, show, stats, validate, promote, crossref, scrape-links
└── tests/                 # 82 tests unitaires
```

| Fichier | Rôle |
|---|---|
| `keywords.py` | **Config centrale** : lexique détection + pondérations sources |
| `extractor.py` | Prompt LLM structuré : is_alim, marque, produit, symptôme, resume |
| `cross_reference.py` | Scoring match signal↔incident + auto-confirm par URL |
| `rappelconso_link.py` | Découverte directe des fiches citées (via `googlenewsdecoder`) |

## 3. Modèles de données

### Table `signaux`

```sql
CREATE TABLE signaux (
    signal_id            TEXT PRIMARY KEY,        -- sha1(marque+symptome+jour)[:16]
    detector_version     TEXT NOT NULL,
    marque               TEXT,
    produit              TEXT,
    symptome             TEXT,
    titre                TEXT,
    resume               TEXT,
    source_type          TEXT,                    -- 'google_news' | 'reddit'
    source_name          TEXT,                    -- 'Marmiton', 'r/france', …
    source_url           TEXT,
    score                INTEGER,                 -- 0-100
    score_breakdown      TEXT,                    -- JSON 5 composantes
    status               TEXT NOT NULL,           -- faible | a_valider | valide | rejete | promu
    promu_vers_source    TEXT,                    -- "signal_detecteur" si promu
    promu_vers_source_id TEXT,
    detected_at          TEXT NOT NULL,           -- date de pub du + ancien article source
    last_seen_at         TEXT NOT NULL,           -- dernier crawl
    raw_json             TEXT
);
```

### Table `signaux_sources` (N sources par signal)

```sql
CREATE TABLE signaux_sources (
    signal_id        TEXT NOT NULL,
    source_type      TEXT NOT NULL,
    source_name      TEXT NOT NULL,
    source_url       TEXT NOT NULL,
    titre            TEXT,
    contenu          TEXT,
    detected_at      TEXT NOT NULL,
    rappelconso_url  TEXT,                        -- URL fiche-rappel/NNN trouvée dans l'article
    PRIMARY KEY (signal_id, source_url)
);
```

### Table `signal_incident_matches` (cross-ref)

```sql
CREATE TABLE signal_incident_matches (
    signal_id          TEXT NOT NULL,
    incident_source    TEXT NOT NULL,
    incident_source_id TEXT NOT NULL,
    score              REAL NOT NULL,            -- 0.0-1.0
    brand_match        REAL,
    symptom_match      REAL,
    product_match      REAL,
    date_proximity     REAL,
    lead_time_days     INTEGER,                  -- + = signal avant rappel
    computed_at        TEXT NOT NULL,
    user_confirmed     INTEGER NOT NULL DEFAULT 0,  -- humain OU lien direct RappelConso
    PRIMARY KEY (signal_id, incident_source, incident_source_id)
);
```

### Statuts d'un signal (`models.py`)

| Statut | Sens |
|---|---|
| `faible` | Score < seuil alerte (40) |
| `a_valider` | Score ≥ 40 mais pas encore qualifié humain |
| `valide` | Humain a cliqué "Valider" |
| `rejete` | Humain a cliqué "Rejeter" |
| `promu` | Signal converti en Incident dans `incidents.sqlite` |

## 4. Dépendances et APIs

### `requirements.txt`
```
requests>=2.31
feedparser>=6.0
python-dotenv>=1.0
anthropic>=0.30.0
googlenewsdecoder>=0.1.7
```

### Sources & APIs

| Source | URL | Auth | Notes |
|---|---|---|---|
| **Google News** | `news.google.com/rss/search?q=…&hl=fr&gl=FR` | Aucune | URLs masquées, résolues via `googlenewsdecoder` |
| **Reddit** | `reddit.com/r/<sub>/search.json` | User-Agent custom | Rate limit 1.5s, filtre `score ≥ 2` |
| **TikTok** | `tiktok.com/tag/<hashtag>` (tier 2) ou RSS-bridge auto-heberge (tier 1) | Aucune (tier 2) ou bridge auto-heberge (tier 1) | Fallback-first 3 tiers, cap 200 items/hashtag, 10 MB HTML / 2 MB Atom, validation SSRF sur URL bridge |
| **Claude API** | Haiku 4.5 | `ANTHROPIC_API_KEY` | Extraction marque/produit/symptôme + is_alim |

### Subreddits ciblés (`keywords.py`)
```python
REDDIT_SUBREDDITS = ["france", "Consommateurs", "AskFrance"]
```

### Pondération sources (`SOURCE_WEIGHTS`)
```python
# Presse pro agro : 25-30
"lsa": 30, "process alimentaire": 30, "60 millions de consommateurs": 25,
# Presse généraliste nationale : 20-28
"le monde": 28, "le figaro": 25, "tf1 info": 22,
# Cuisine / lifestyle fiables : 15-18
"marmiton": 18, "cuisine az": 17, "femme actuelle": 18,
# Reddit : 12-18 selon sub
"r/consommateurs": 18, "r/france": 15, "r/askfrance": 12,
# TikTok : poids conservateur (bruit elevé), comptes verifies surponderes
"tiktok": 10, "tiktok @60millions": 25, "tiktok @dgccrf": 30,
# Default inconnu : 12
```

## 5. Scoring

### Score signal (0-100)

| Composante | Max | Calcul |
|---|---|---|
| `source_weight` | 35 | Dict `SOURCE_WEIGHTS` avec match substring |
| `recurrence` | 30 | 10 points/source distincte, cap 30 |
| `recency` | 15 | 15 si < 24h, 10 si < 72h, 5 si < 7j, 0 sinon |
| `brand_known` | 10 | +10 si marque dans `incidents.sqlite` |
| `sentiment` | 10 | Mots négatifs FR : 1 hit = 5, ≥2 hits = 10 |

**Seuil alerte** : `SCORE_SEUIL_ALERTE = 40` dans `models.py`.

### Score cross-ref (0.0-1.0)

| Dimension | Poids | Calcul |
|---|---|---|
| `brand_match` | **0.40** | signal.marque vs incident.marque **OU** distributeurs (SequenceMatcher + bonus substring 0.85) |
| `symptom_match` | **0.30** | Mapping `SYMPTOM_TO_KEYWORDS` avec familles pathogènes (bactérien/viral) |
| `product_match` | **0.20** | Substring + hints `PRODUCT_CATEGORY_HINTS` (fromage→lait, jambon→charcuterie…) |
| `date_proximity` | **0.10** | Gaussienne `exp(-(Δjours/30)²)` |

Seuils : `MATCH_THRESHOLD_STRONG = 0.70`, `MATCH_THRESHOLD_POSSIBLE = 0.50`.

### Dédup (`signal_id`)

Hash sha1[:16] sur 4 niveaux de granularité décroissante :

```python
if marque and symptome:   key = "brand|marque|sympt|jour"
elif produit and symptome: key = "prod|produit|sympt|jour"
elif symptome:             key = "sympt|sympt|jour"
else:                      key = "title|titre|jour"
```

Cap au **jour** → un signal ne se duplique pas en refetch intrajournaliers.

## 6. Commandes CLI

```bash
# Fetch complet (LLM + scrape articles activés par défaut)
python -m detecteur_signaux.cli fetch --max 100

# Options
python -m detecteur_signaux.cli fetch --no-llm --no-scrape --sources google_news

# Liste
python -m detecteur_signaux.cli list --status a_valider --min-score 40 --limit 30
python -m detecteur_signaux.cli list --format json

# Détail (affiche sources multi + breakdown score)
python -m detecteur_signaux.cli show <signal_id>

# Stats globales
python -m detecteur_signaux.cli stats

# Validation humaine
python -m detecteur_signaux.cli validate <signal_id> --accept
python -m detecteur_signaux.cli validate <signal_id> --reject

# Promotion en incident (crée row dans incidents.sqlite avec source=signal_detecteur)
python -m detecteur_signaux.cli promote <signal_id>

# Recalcul cross-ref sans refetch (utile après ajout d'incidents)
python -m detecteur_signaux.cli crossref --min-score 0.5 --window-days 30

# Scraper les articles existants pour détecter les URLs RappelConso a posteriori
python -m detecteur_signaux.cli scrape-links --sleep 0.3
python -m detecteur_signaux.cli scrape-links --all  # re-scan même ceux qui ont déjà une URL
```

## 7. Tests

```bash
cd agents
python -m unittest discover detecteur_signaux/tests
```

**82 tests** répartis :
- `test_scorer.py` — source_weight, recurrence, recency, brand_known, sentiment, status_for_score
- `test_deduplicator.py` — compute_signal_id sur les 4 niveaux, accents, case-insensitive
- `test_extractor.py` — fallback regex (is_alim, négatif filters, symptômes)
- `test_cross_reference.py` — brand/symptom/product/date, strong/possible/no match

LLM jamais appelé en test (fallback regex uniquement).

## 8. Décisions techniques

### Approche fallback-first (comme Agent 2)

Si `ANTHROPIC_API_KEY` absente → bascule regex. Agent fonctionnel gratuit.

### Google News URLs masquées

Depuis 2023, Google News encode les URLs cibles en protobuf base64. Impossible
de les résoudre sans lib dédiée → dépendance `googlenewsdecoder` qui fait un
appel à `news.google.com/_/DotsSplashUi/data/batchexecute` pour récupérer
l'URL réelle.

Sans ce décodage, le scraping des articles est inutile (on ne peut GET que
`news.google.com` qui redirige sur un consent RGPD).

### `detected_at` = date de publication article, pas crawl

C'est ce qui alimente le scoring `recency` et le `lead_time_days`. Bug
historique : on utilisait `datetime.utcnow()` à la création → tous les signaux
paraissaient récents. Fixé avec `earliest_source_date(signal_id)` qui prend
le MIN des dates de sources.

### Validation humaine préservée entre runs

Le champ `user_confirmed` survit à `recompute_all_matches()` :

```python
storage.clear_matches(keep_confirmed=True)
```

Un match confirmé reste en 1er rang même si le score algorithmique devient
< seuil. Pour retirer la validation, UI bouton "Retirer la validation" ou
`storage.unconfirm_match()`.

### Auto-confirm par lien direct RappelConso

Si un article cite `rappel.conso.gouv.fr/fiche-rappel/NNN`, c'est une preuve
formelle du lien. Le système :
1. Scrape le HTML à l'ingest
2. Extrait les URLs `fiche-rappel/NNN` via regex
3. Stocke dans `signaux_sources.rappelconso_url`
4. Pendant `recompute_all_matches`, match NNN ↔ incidents.source_url
5. Si match : `user_confirmed = 1` (automatique, même UI que validation humaine)

Taux réel sur les tests : **~65% des articles Google News** (Marmiton et Femme
Actuelle citent systématiquement).

### Brand match étendu aux distributeurs

Sans ça, "Carrefour saumon listeria" ne matchait pas le rappel "océan délices
distributeurs: carrefour" (la presse parle du distributeur, RappelConso de la
marque fabricant). `brand_or_distributor_similarity` prend le MAX des deux.

### Familles de pathogènes

Le LLM renvoie parfois "contamination bactérienne" (générique) alors que
l'incident dit "listeria monocytogenes" (spécifique). Le mapping
`SYMPTOM_TO_KEYWORDS` contient des clés **génériques** qui pointent vers
une liste de patterns spécifiques :

```python
"contamination bacterienne": _BACTERIAL_PATHOGENS,  # listeria, salmonelle, e.coli, …
"intoxication alimentaire": _BACTERIAL_PATHOGENS + toxines,
```

## 9. À savoir pour toute évolution

- **Ajouter une source** : crée un module dans `sources/`, expose `fetch_all()`
  qui yield `SignalSource`, ajoute au `_iter_sources` dans `detecteur.py`.
  Pense à ajouter une entrée dans `SOURCE_WEIGHTS` (`keywords.py`).
- **Ajouter des symptômes** : édite `SYMPTOM_KEYWORDS`, `SYMPTOM_TO_KEYWORDS`,
  et mets à jour les tests (`test_extractor.py`, `test_cross_reference.py`).
- **Calibrer les poids scoring** : édite constantes en haut de `scorer.py`
  (MAX_SOURCE_WEIGHT, etc.) OU `SCORE_SEUIL_ALERTE` dans `models.py`.
- **Calibrer les poids cross-ref** : édite `WEIGHT_BRAND/SYMPTOM/PRODUCT/DATE`
  en haut de `cross_reference.py`. Rerun `cli crossref` après.
- **Coût LLM** : ~0,0005 €/article en Haiku. Pour 100 articles = 0,05 €.
  Scalable.
- **Scraping articles** : ~2-5s par article (décodage Google News + HTTP GET).
  100 articles ≈ 5min. Utilise `--no-scrape` pour debug sans délai.
- **Reddit rate limit** : respecté via `RATE_LIMIT_SLEEP = 1.5`s entre requêtes.
  Ne pas descendre en dessous, Reddit bloque l'IP.
- **Regen DB** : `rm data/signaux.sqlite` puis `python -m detecteur_signaux.cli stats`
  recrée la base vide via la migration. Attention : perd l'historique des
  validations humaines.
- **TikTok — fragilite du regex JSON_BLOB_PATTERN** : la constante
  `JSON_BLOB_PATTERN = r"__UNIVERSAL_DATA_FOR_REHYDRATION__\s*=\s*(\{.+?\})\s*</script>"`
  dans `sources/tiktok.py` cible une clé HTML injected par le SSR TikTok.
  TikTok renomme ou restructure cette clé tous les 3-6 mois. Si le tier 2
  (scraping direct) retourne systematiquement 0 item alors que des videos
  existent, verifier d'abord le regex sur un dump HTML frais (curl ou devtools)
  avant de diagnostiquer un blocage IP. La fonction `_walk_video_list` teste
  deux paths alternatifs dans le blob — en ajouter un troisieme si la structure
  a change. Prevoir une alerte monitoring sur le taux de succes tier 2 (< 5
  items sur un hashtag actif = signal de casse probable).
