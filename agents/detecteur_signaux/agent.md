# Agent — Détecteur de signaux faibles

## Identité

- **Nom** : `detecteur_signaux`
- **Position** : Agent 4 (en parallèle des Agents 2 et 3, utilise Agent 1 pour enrichissement)
- **Version** : v0.1 (`DETECTOR_VERSION`)
- **Type** : Agent de veille active multi-sources (batch, stateful, LLM-augmenté)

## Objectif

Détecter les **alertes précoces** dans la presse en ligne et sur Reddit —
en amont ou en parallèle des publications RappelConso officielles. Chaque
article / post est analysé, structuré (marque + produit + symptôme), scoré,
et **croisé** avec `incidents.sqlite` pour validation algorithmique (+
auto-confirmation via liens directs RappelConso cités).

Permet de :
- Détecter un rappel avant sa publication officielle (lead time positif)
- Mesurer la couverture presse d'un rappel connu
- Identifier des signaux faibles (plaintes consommateurs, bad buzz) qui
  n'arrivent pas dans RappelConso

## Inputs

| Input | Source | Notes |
|---|---|---|
| Sources configurées | CLI `--sources google_news,reddit` | Par défaut les 2 |
| Subreddits FR | `keywords.py::REDDIT_SUBREDDITS` | `["france","Consommateurs","AskFrance"]` |
| Queries Google News | `keywords.py::GOOGLE_NEWS_QUERIES` | Patterns `"rappel produit" OR "listeria"` |
| Queries Reddit | `keywords.py::REDDIT_QUERIES` | Plus simples que GN |
| `ANTHROPIC_API_KEY` | `.env` | Fallback regex sinon |
| `data/incidents.sqlite` | Agent 1 | Pour `brand_known` scoring + cross-ref |
| Limite items | CLI `--max N` | Budget / debug |
| Flags | `--no-llm`, `--no-scrape`, `--no-crossref` | Opt-outs |

## Outputs

### 1. `data/signaux.sqlite` (3 tables)

**Table `signaux`** — 1 ligne par signal dédupliqué
```
signal_id (PK)       : sha1(marque+symptome+jour)[:16]
marque, produit, symptome, titre, resume
source_type          : google_news | reddit
source_name          : Marmiton, r/france, …
source_url           : URL du 1er article
score (0-100)        : algorithmique
score_breakdown      : JSON des 5 composantes
status               : faible | a_valider | valide | rejete | promu
detected_at          : date de pub du + ancien article
last_seen_at         : dernier crawl
```

**Table `signaux_sources`** — N sources par signal
```
PRIMARY KEY (signal_id, source_url)
rappelconso_url      : URL fiche-rappel/NNN trouvée dans l'article (si existe)
```

**Table `signal_incident_matches`** — cross-ref signal ↔ incident
```
PK composite (signal_id, incident_source, incident_source_id)
score (0-1)          : match algorithmique
brand/symptom/product/date (breakdown)
lead_time_days       : positif = signal avant rappel officiel
user_confirmed       : 0 ou 1 (humain OU URL directe RappelConso)
```

### 2. Effet de bord : Agent 1

Si un signal est `promote`d : INSERT dans `incidents.sqlite` avec
`source = "signal_detecteur"`.

### 3. Rapport CLI exemple

```json
{
  "detector_version": "v0.1",
  "sources_fetched": 100,
  "signaux_new": 12,
  "signaux_updated": 5,
  "alerts": 3,
  "llm_used_count": 100,
  "skipped_not_alim": 15,
  "skipped_no_symptom": 20,
  "rappelconso_urls_found": 8,
  "crossref": {
    "matches_stored": 45,
    "strong_matches": 12,
    "url_auto_confirmed": 8
  }
}
```

## Déclencheurs

1. **Manuel** : `python -m detecteur_signaux.cli fetch --max 100`
2. **Cron recommandé** : toutes les 6h (presse/social évoluent vite)
3. **Pas de bouton dashboard** (lancement CLI — trop long pour un bouton UI)
4. **Post-fetch Veilleur** (pattern complémentaire) : `crossref` sans refetch
   pour recalculer les matches quand Agent 1 ajoute de nouveaux incidents

## Dépendances vers les autres agents

| Agent | Type | Pourquoi |
|---|---|---|
| `veilleur_incidents` (Agent 1) | **Amont non-bloquant** | Si `incidents.sqlite` absente, `brand_known = 0` et crossref ignoré |
| Aval : Agent 5 (outreach) | **Futur** | Consommera les signaux `valide` / `promu` |

L'agent tourne **même sans incidents.sqlite** (perd juste le bonus brand_known
+ la cross-référence).

## Dépendances externes

| Système | Criticité | Comportement si KO |
|---|---|---|
| Google News RSS | **Bloquant si activé** | Erreur fatale (peut skip avec `--sources reddit`) |
| Reddit JSON API | Non bloquant | Rate limit 1.5s respecté ; skip la query en erreur |
| `ANTHROPIC_API_KEY` | Non bloquant | Fallback regex (moins précis, ~40% des signaux skipped `no_symptom`) |
| `googlenewsdecoder` | Non bloquant | Si absent : URLs Google News opaques, pas de scraping d'articles |
| Internet | Bloquant pour fetch | — |

## Comportement attendu

### Pipeline par source

```
1. Fetch RSS ou JSON → SignalSource (titre, url, contenu, detected_at)
2. extract(titre, contenu, source_name, use_llm)
   ├─ LLM Claude Haiku : JSON strict {marque, produit, symptome, is_alim, resume}
   └─ Fallback regex si pas de clé ou erreur
3. Si is_alim=False → skipped_not_alim (fin)
4. Si pas de symptome → skipped_no_symptom (fin)
5. compute_signal_id(marque, symptome, titre, detected_at, produit)
6. find_rappelconso_url_for_source() → optionnel, résoud GN + scrape HTML
7. storage.attach_source(signal_id, src, rappelconso_url)
8. Tracking pour re-scoring final
```

### Phase 2 — Scoring et upsert

```
Pour chaque signal touché dans ce run :
1. n_sources = storage.count_sources(signal_id)
2. pub_date = storage.earliest_source_date(signal_id)
3. score, breakdown = compute_score(source, n_sources, pub_date, marque, titre, contenu, incidents_db)
4. status = "a_valider" si score >= 40 sinon "faible"
5. Préserver statuts humains (valide/rejete/promu) s'ils existent
6. Préserver promu_vers_source_* si déjà promu
7. storage.upsert_signal(signal)
```

### Phase 3 — Cross-référence auto (si non `--no-crossref`)

```
1. recompute_all_matches()
   a. clear_matches(keep_confirmed=True)  ← préserve validations humaines
   b. Pour chaque (signal × incident) : compute_match() → upsert si score >= 0.5
   c. Parcourir signaux avec rappelconso_url → auto-confirm le match correspondant
2. Retour : n_matches, n_strong, n_url_auto_confirmed
```

### Idempotence
- `signal_id` stable : ré-exécuter un fetch ne dédouble pas
- Le même article re-fetché → `attach_source` retourne False (déjà là), met à
  jour `rappelconso_url` si nouvelle info
- `last_seen_at` bump à chaque détection

### Isolation d'erreurs
- Un article qui fait crasher l'extraction : log `logger.exception`, skip,
  continue
- Une source en panne (Google News KO) : log, bascule sur Reddit si activé

## Conditions de succès

1. Au moins une source a répondu
2. Les articles pertinents ont été extraits (LLM ou regex)
3. Les signaux ont été dédupés et stockés
4. (si activé) Le crossref a tourné sans erreur bloquante

## Conditions d'échec

| Cas | Traitement |
|---|---|
| Google News RSS inaccessible et activé seul | Exception fatale |
| Tous les articles filtrés (not_alim / no_symptom) | Succès vide (`signaux_new=0`) |
| `ANTHROPIC_API_KEY` absente | Fallback regex, warning |
| Crash sur un article | Log + continue |
| `incidents.sqlite` absente | Crossref skip, `brand_known = 0` partout |

### Recovery
- Reset complet : `rm data/signaux.sqlite` puis `fetch` — attention, perd les
  validations humaines
- Réparer matches seulement : `crossref` sans refetch
- Enrichir URLs a posteriori : `scrape-links` parcourt les sources existantes

## Intégration dans le pipeline

```
                                Google News RSS      Reddit JSON
                                      │                   │
                                      ▼                   ▼
                                  ┌────────────────────────────┐
                                  │  DETECTEUR_SIGNAUX         │
                                  │                            │
                                  │  ┌─────────────────────┐   │
  ┌──────────────────┐            │  │ extractor (LLM)     │   │
  │ incidents.sqlite │─── lu ────►│  │ scorer              │   │
  └──────────────────┘            │  │ dedup               │   │
                                  │  │ rappelconso_link    │   │
                                  │  │   (scrape+decode)   │   │
                                  │  └─────────────────────┘   │
                                  │            │               │
                                  │            ▼               │
                                  │      signaux.sqlite        │
                                  │            │               │
                                  │  ┌─────────▼────────────┐  │
                                  │  │ cross_reference      │  │
  ┌──────────────────┐            │  │ (auto-confirm URL)   │  │
  │ incidents.sqlite │◄─── lu ────┤  └──────────────────────┘  │
  └──────────────────┘            │                            │
                                  │  signal_incident_matches   │
                                  │       (dans signaux.sqlite)│
                                  └──────────────┬─────────────┘
                                                 │
                                                 ▼
                                    ┌──────────────────────┐
                                    │  dashboard_reflex    │
                                    │  page Signaux +      │
                                    │  drawer Incident     │
                                    │  (cross-ref visible) │
                                    └──────────────────────┘
```

## Workflow statuts d'un signal

```
[fetch initial]
     │
     ▼
  ┌──────────┐        ┌──────────┐
  │  faible  │ ───┐   │ a_valider│
  │ (< 40)   │    │   │ (>= 40)  │
  └──────────┘    │   └────┬─────┘
                  │        │
            [humain clique]│
                  │        │
            ┌─────┴────────┴─────┐
            ▼                    ▼
        ┌────────┐          ┌──────┐
        │ valide │          │rejete│
        └───┬────┘          └──────┘
            │
            │ [humain clique promote]
            ▼
        ┌───────┐          + création d'un Incident dans incidents.sqlite
        │ promu │            avec source="signal_detecteur"
        └───────┘
```

## Fréquence recommandée

| Contexte | Fréquence | Paramètres |
|---|---|---|
| Veille opérationnelle | Toutes les 6h | `fetch --max 80` |
| Recalibration seuils | À la demande | `fetch --no-scrape` (rapide) + `crossref` |
| Rattrapage d'URLs RappelConso | 1 run | `scrape-links --sleep 0.3` |
| Recalcul matches après Agent 1 | Automatique après fetch | `crossref` |

## Non-objectifs explicites

- **Pas de crawling direct de sites presse** : passe par Google News RSS (agrège
  et normalise)
- **Pas de X/Twitter** : API payante depuis 2023
- **Pas de LinkedIn** : pas d'API, scraping risqué
- **Pas de traduction** : FR uniquement (queries + LLM prompt)
- **Pas de génération d'email** : c'est le rôle d'Agent 5 (futur)
- **Pas de qualification business** (CA, taille) : Agent 3 s'en charge pour les
  marques promues
- **Pas de propagation temps-réel** — mode batch uniquement
