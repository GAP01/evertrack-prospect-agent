# EverTrack — guide pour Claude Code

Contexte complet pour travailler sur ce projet lors des prochaines sessions.
Projet freelance de Gautier Prentout pour un client éditeur SaaS traçabilité.

**Objectif** : pipeline d'agents IA pour prospection commerciale post-rappel produit.

---

## 1. Architecture

Le projet est organisé comme un pipeline de 5 agents + 2 dashboards, dans
`agents/` à la racine.

```
agents/
├── veilleur_incidents/      # Agent 1 — Fetch RappelConso API
├── evaluateur_severite/     # Agent 2 — Scoring sanitaire (Claude Haiku)
├── enrichisseur_prospects/  # Agent 3 — SIRENE + Pappers (contact qualité/supply)
├── detecteur_signaux/       # Agent 4 — Signaux faibles (Google News + Reddit)
├── dashboard/               # Couche data_access + actions (lecture seule SQLite)
├── dashboard_reflex/        # Dashboard Reflex (React/Radix) avec 3 pages
├── data/                    # SQLite : incidents, scores, enrichissements, signaux
└── .env                     # Clés API (jamais commité — voir .gitignore)
```

### Pipeline

```
RappelConso API          Google News RSS + Reddit JSON
        │                       │
        ▼                       ▼
 ┌───────────┐          ┌──────────────┐
 │ veilleur  │          │  detecteur   │
 │ incidents │          │   signaux    │
 └─────┬─────┘          └──────┬───────┘
       │                       │
       ▼                       ▼
incidents.sqlite          signaux.sqlite
       │                       │
       ▼                       │
 ┌───────────┐                 │
 │evaluateur │                 │
 │ severite  │                 │
 └─────┬─────┘                 │
       │                       │
       ▼                       │
  scores.sqlite                │
       │                       │
       ▼                       │
 ┌───────────┐                 │
 │ enrichis. │                 │
 │ prospects │                 │
 └─────┬─────┘                 │
       │                       │
       ▼                       │
enrichissements.sqlite         │
       │                       │
       └───────────┬───────────┘
                   ▼
             dashboard_reflex
             (3 pages : Radar / Signaux / Prospects)
             + cross-référence signal ↔ incident
```

### Rôle de chaque agent

| Agent | Responsabilité | Entrée | Sortie |
|---|---|---|---|
| **veilleur_incidents** | Crawl RappelConso, normalise, dédup | API RappelConso | `incidents.sqlite` |
| **evaluateur_severite** | Score sanitaire 0-100 via Claude Haiku + règles fallback | `incidents.sqlite` | `scores.sqlite` |
| **enrichisseur_prospects** | Match marque → SIRENE + contact cible/dirigeant | `incidents.sqlite` | `enrichissements.sqlite` |
| **detecteur_signaux** | Détection presse/social + cross-ref avec incidents | Google News + Reddit | `signaux.sqlite` |
| **dashboard_reflex** | Visualisation + validation humaine | Les 4 SQLite | SPA web |

---

## 2. Conventions de code

### Pattern obligatoire pour tout nouvel agent

Chaque agent suit strictement cette structure :

```
agents/<nom_agent>/
├── __init__.py
├── README.md
├── requirements.txt
├── models.py           # dataclasses du domaine (Incident, Score, Enrichissement, Signal…)
├── storage.py          # SignalStorage/IncidentStorage etc. — SQLite avec migrations
├── <nom_agent>.py      # orchestrateur (ex: veilleur.py, enrichisseur.py, detecteur.py)
├── cli.py              # argparse avec subcommands
├── tests/
│   ├── __init__.py
│   └── test_*.py       # unittest (pas pytest) — avec MagicMock pour les APIs externes
└── <fichiers métier>.py  # api_client.py, normalize.py, rules.py, scorer.py…
```

### Règles de code

- **Python 3.12** — utilise `from __future__ import annotations`
- **Pas de dépendances lourdes** : stdlib en priorité, `requests`, `feedparser`,
  `anthropic`, `python-dotenv`. Évite pandas, numpy, sqlalchemy.
- **SQLite natif** (`import sqlite3`) — pas d'ORM
- **Migrations** : liste `_MIGRATIONS` avec ALTER TABLE, try/except OperationalError
  pour ignorer colonnes déjà présentes. Pattern :
  ```python
  _MIGRATIONS = ["ALTER TABLE ... ADD COLUMN ..."]
  def _migrate(self, conn):
      for stmt in _MIGRATIONS:
          try: conn.execute(stmt)
          except sqlite3.OperationalError: pass
  ```
- **LLM = fallback-first** : toute intégration Claude doit avoir un fallback règles
  déterministe. Pattern dans `evaluateur_severite/llm_scorer.py` et
  `detecteur_signaux/extractor.py`.
- **ASCII only dans CLI outputs** (Windows cp1252 casse sur `✓`, utiliser `[ok]`, `[~]`, `[x]`).
- **Pas d'emojis dans les fichiers** sauf demande explicite.
- **Noms de colonnes DB figés** — renommer nécessite migration ET update dashboard.
- **load_dotenv(override=True)** — obligatoire côté Windows (env vars vides du shell
  écrasent sinon les valeurs du `.env`).

### Nommage

- Classes : `PascalCase` (ex: `SignalStorage`, `EnrichissementResult`)
- Fonctions/variables : `snake_case`
- Constantes module-level : `UPPER_SNAKE_CASE`
- Fichiers : `snake_case.py`
- Dossiers agent : `snake_case` (ex: `detecteur_signaux`, pas `DetecteurSignaux`)
- Tests : `test_<module>.py`, classes `Test<Thing>`, méthodes `test_<condition>`

### Gestion des dates

- **ISO-8601 uniquement** en base (`YYYY-MM-DD` ou `YYYY-MM-DDTHH:MM:SS`)
- Parsing defensive : `datetime.fromisoformat(s[:10])` pour tolérer les formats
- Dans `detecteur_signaux`, `signal.detected_at` = **date de publication** du plus
  ancien article source (pas la date de crawl, qui est `last_seen_at`)

---

## 3. Commandes CLI principales

Toujours lancer depuis `agents/` (les paths relatifs pointent sur `data/`).

### Agent 1 — Veilleur incidents
```bash
python -m veilleur_incidents.cli fetch [--since-days 7] [--max N]
python -m veilleur_incidents.cli stats
python -m veilleur_incidents.cli show <source_id>
```

### Agent 2 — Évaluateur sévérité
```bash
python -m evaluateur_severite.cli score [--rescore] [--max N]  # avec LLM
python -m evaluateur_severite.cli score --no-llm               # fallback règles
python -m evaluateur_severite.cli stats
python -m evaluateur_severite.cli show <source_id>
```

### Agent 3 — Enrichisseur prospects
```bash
python -m enrichisseur_prospects.cli enrich [--reenrich] [--max N]
python -m enrichisseur_prospects.cli show <source_id>
python -m enrichisseur_prospects.cli stats
```

### Agent 4 — Détecteur signaux faibles
```bash
# Fetch + crossref + scrape (par défaut)
python -m detecteur_signaux.cli fetch --max 100

# Fetch sans LLM / sans scrape HTML
python -m detecteur_signaux.cli fetch --no-llm --no-scrape

# Uniquement Google News
python -m detecteur_signaux.cli fetch --sources google_news

# Liste signaux
python -m detecteur_signaux.cli list --status a_valider --min-score 40

# Détail signal
python -m detecteur_signaux.cli show <signal_id>

# Valider / rejeter / promouvoir en incident
python -m detecteur_signaux.cli validate <signal_id> --accept
python -m detecteur_signaux.cli validate <signal_id> --reject
python -m detecteur_signaux.cli promote <signal_id>

# Recalcul crossref signal↔incident sans refetch
python -m detecteur_signaux.cli crossref

# Scraper les articles existants pour détecter les liens RappelConso
python -m detecteur_signaux.cli scrape-links --sleep 0.3
```

### Tests
```bash
# Par agent
python -m unittest discover <agent>/tests

# Tout le projet
python -m unittest discover -s agents
```

---

## 4. Variables d'environnement

Fichier **`agents/.env`** (jamais commité — vérifié dans `.gitignore`).

| Variable | Obligatoire ? | Usage |
|---|---|---|
| `ANTHROPIC_API_KEY` | Recommandé | Agent 2 (scoring sanitaire) + Agent 4 (extraction LLM) |
| `PAPPERS_API_KEY` | Optionnel | Agent 3 (contact dirigeant) — peut retourner 401 selon plan |
| `SOCIETECOM_API_KEY` | Optionnel | Agent 3 (stub prêt, pas encore implémenté) |

Sans `ANTHROPIC_API_KEY` : les agents basculent sur leur fallback déterministe.
Sans `PAPPERS_API_KEY` : les contacts viennent uniquement de SIRENE (dirigeants légaux).

**Format .env** :
```
ANTHROPIC_API_KEY=sk-ant-api03-...
PAPPERS_API_KEY=...
```

**IMPORTANT Windows** : toujours utiliser `load_dotenv(override=True)` dans le code,
car Claude Code et certains tools injectent des vars vides dans l'env shell.

---

## 5. Dashboard Reflex

### Stack technique

- **Reflex 0.9** (Python → React Router 7 + Radix Themes + vaul)
- **Port** : 3000 (frontend) + 8000 (backend WebSocket)
- **Lecture directe** des SQLite via `services/data.py`
- **3 pages** routées par `DashboardState.current_page` ("radar" / "signaux" / "prospects")

### Architecture dashboard

```
dashboard_reflex/dashboard_reflex/
├── dashboard_reflex.py    # index() + routing rx.match + mobile bottom nav
├── state.py               # DashboardState (vars + event handlers)
├── services/
│   └── data.py            # Lecture des 4 SQLite + get_matches pour cross-ref
├── components/
│   ├── sidebar.py         # Navigation desktop (cachée <640px)
│   ├── header.py          # Breadcrumb + toast + Rafraîchir
│   ├── kpi_cards.py       # 4 KPI du Radar
│   ├── incident_table.py  # Tableau + filtres + drawer trigger
│   ├── incident_detail_drawer.py
│   ├── prospects_table.py
│   ├── prospect_detail_drawer.py
│   ├── signaux_table.py   # Avec KPI lead time
│   ├── signal_detail_drawer.py
│   └── tier_badge.py
└── assets/
```

### Lancer le dashboard

```bash
cd agents/dashboard_reflex

# Dev mode (hot-reload)
FRONTEND_PORT=3000 BACKEND_PORT=8000 .venv/Scripts/reflex run

# Production build (recommandé pour test)
FRONTEND_PORT=3000 BACKEND_PORT=8000 .venv/Scripts/reflex run --env prod
```

**Dépendances** : venv dédié dans `dashboard_reflex/.venv/`. Ne pas confondre
avec le Python système utilisé pour les agents.

### Pièges courants

- **Drawer à gauche au lieu de droite** : `rx.drawer.content` doit avoir
  `position="fixed"`, `right="0"`, `bottom="0"`, **`left="auto"`** (vaul injecte
  `left:0` par défaut qui gagne sur `right:0`).
- **Concat Var + str** : `"texte" + sig["champ"]` échoue — utiliser deux `rx.text`
  séparés ou `sig["champ"].to(str) + "suffix"` (Var à gauche).
- **CSS media queries** : passer via `style={"@media (max-width: 640px)": {...}}`,
  pas via props directes.
- **Champs DB dashboard** : les colonnes `incidents.sqlite` sont `motif`, `risques`,
  `source_url` (pas `motif_rappel`, `risques_encourus`, `lien_fiche` — noms hérités).
- **Process fantômes** : sur Windows, tuer via PowerShell `Stop-Process` en filtrant
  `python.exe`, `bun.exe`, `node.exe`. Les PIDs WSL ne meurent pas avec `taskkill`.
- **Regen `.web`** : si le dashboard sert un vieux build, `rm -rf .web/app .web/build`
  puis relancer (Reflex régénère).

### Tunnel Cloudflare (accès mobile / partage)

```bash
cd agents
cloudflared tunnel --url http://localhost:3000
```

Génère une URL `https://*.trycloudflare.com` valide tant que le process tourne.
Utile pour tester sur mobile ou envoyer un lien au client.

---

## 6. Décisions techniques structurantes

### Agent 2 — Scoring sanitaire
- **Claude Haiku** (`claude-haiku-4-5-20251001`) — prompt court, JSON strict
- **Fallback table mots-clés** (`SANITARY_KEYWORDS`) — agent fonctionnel sans clé
- **Poids** : `risque_sanitaire` 50%, `ampleur_geo` 25%, `population_vulnerable` 15%,
  `volume_distributeurs` 10%

### Agent 3 — Enrichissement
- **SIRENE toujours en 1re source** (`recherche-entreprises.api.gouv.fr`) — gratuit,
  sans auth, retourne aussi les dirigeants légaux
- **Pappers en complément** (si clé configurée) — contact dirigeant plus récent
- **societe.com** — stub prêt, non implémenté
- **Targeting contacts** : profils **opérationnels** (qualité / supply chain / conformité)
  via `contact_profiles.py` avec mots-clés (qualit, qhse, hse, supply chain, conformit,
  reglementaire, tracabilit…)
- **Contact type** :
  - `"cible"` = profil opérationnel trouvé
  - `"fallback_dirigeant"` = pas de profil cible, on retombe sur gérant/PDG
- **Seuils confidence** : found ≥ 0.72, ambiguous ≥ 0.40, sinon not_found
  (scoring via `difflib.SequenceMatcher` + bonus +0.15 si marque ⊂ raison sociale)

### Agent 4 — Signaux faibles
- **Sources** : Google News RSS (gratuit, pas d'auth) + Reddit JSON public
  (subreddits `r/france`, `r/Consommateurs`, `r/AskFrance`)
- **Extraction LLM** : Claude Haiku via `extractor.py` — retourne marque, produit,
  symptôme, is_alim, resume. Fallback regex + `SYMPTOM_TO_KEYWORDS`.
- **Dedup stable** : `signal_id = sha1(marque + symptome + day)[:16]` — ordre de
  priorité brand → produit → symptome seul → titre (fallback)
- **Scoring crédibilité (0-100)** :
  - `source_weight` (0-35) — dict `SOURCE_WEIGHTS` dans `keywords.py`,
    default 12. Marmiton/TF1 Info en tête après usage réel.
  - `recurrence` (0-30) — 10 points par source distincte, cap à 30
  - `recency` (0-15) — basé sur `detected_at` (= date de pub article, pas crawl)
  - `brand_known` (0-10) — marque déjà dans `incidents.sqlite`
  - `sentiment` (0-10) — mots négatifs FR (heuristique simple)
- **Seuil alerte** : 40 (calibré sur les vrais scores observés, ajustable dans
  `models.py` → `SCORE_SEUIL_ALERTE`)
- **Google News URL masquées** : `googlenewsdecoder` (dépendance requirements.txt)
  décode les URLs base64 vers l'URL cible réelle (Marmiton, Femme Actuelle…)
- **Validation workflow** : `faible` → `a_valider` (auto si score ≥ 40) →
  `valide` (humain) → `promu` (incident créé dans `incidents.sqlite` avec
  `source="signal_detecteur"`)

### Cross-référence signaux ↔ incidents
- **4 dimensions** pondérées (somme = 1.0) :
  - `brand_match` 0.40 — signal.marque vs **incident.marque OR incident.distributeurs**
    (crucial car la presse mentionne le distributeur, RappelConso la marque fabricant)
  - `symptom_match` 0.30 — mapping `SYMPTOM_TO_KEYWORDS` avec **familles
    pathogènes** (terme générique "contamination bactérienne" → listeria,
    salmonelle, e.coli, etc.)
  - `product_match` 0.20 — hints `PRODUCT_CATEGORY_HINTS` (fromage → lait,
    jambon → charcuterie, poisson → pêche…)
  - `date_proximity` 0.10 — gaussienne sur fenêtre ±30j
- **Seuils** : ≥ 0.70 "Fort", ≥ 0.50 "Possible", < 0.50 ignoré
- **Auto-confirm via URL directe** : si le HTML de l'article contient un lien
  `rappel.conso.gouv.fr/fiche-rappel/NNN`, le match correspondant est automatiquement
  validé (`user_confirmed=1`)
- **Validation humaine** : bouton "Confirmer ce lien" dans les drawers — les
  matches confirmés remontent en tête et survivent aux recomputes (`clear_matches(keep_confirmed=True)`)
- **Table** : `signal_incident_matches` (PRIMARY KEY composite signal_id + incident_source + incident_source_id)

---

## 7. État courant & prochaines étapes

### Livrés
- Agents 1, 2, 3, 4 complets avec tests
- Dashboard Reflex 3 pages avec drawers + validation humaine + mobile responsive
- Cross-référence signal↔incident avec auto-confirm par lien RappelConso
- Tunnel Cloudflare pour accès externe

### À faire
- **Agent 5 — Rédaction outreach** : email personnalisé depuis contexte incident
  + enrichissement prospect (prompt Claude + template)
- **Intégration CRM** : push leads vers Sellsy
- **Pappers 401** : vérifier plan/activation de la clé
- **Déploiement continu** : serveur dédié (actuellement local + cloudflared)
- **Calibration continue** des poids scoring (SOURCE_WEIGHTS, seuils, etc.)

---

## 8. Fichiers à ne JAMAIS toucher

- `.env` — secrets
- `data/*.sqlite` — données live, backup avant toute modif schéma
- `dashboard_reflex/.web/` — auto-généré par Reflex, régen si stale
- `dashboard_reflex/.venv/` — venv dédié, ne pas mélanger avec Python système

## 9. Références mémoire Claude

- `project_evertrack.md` dans `~/.claude/.../memory/` — à garder synchronisé
  quand l'architecture évolue (agents ajoutés, colonnes DB changées, seuils
  recalibrés). À mettre à jour manuellement après chaque session structurante.
