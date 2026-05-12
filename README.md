# EverTrack

Pipeline d'agents IA pour la prospection commerciale post-rappel produit.
Détecte les incidents alimentaires (RappelConso + signaux faibles presse/social),
qualifie leur sévérité, enrichit les contacts opérationnels cibles, et expose le
tout dans un dashboard.

> Projet freelance pour un client éditeur SaaS spécialisé en traçabilité agroalimentaire.

---

## Architecture

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
       (Radar / Signaux / Prospects)
```

## Les agents

| Agent | Rôle | Entrée | Sortie |
|---|---|---|---|
| **veilleur_incidents** | Crawl RappelConso, normalisation, déduplication | API RappelConso | `incidents.sqlite` |
| **evaluateur_severite** | Score sanitaire 0–100 via Claude Haiku (fallback règles) | `incidents.sqlite` | `scores.sqlite` |
| **enrichisseur_prospects** | Match marque → SIRENE + Pappers, ciblage qualité/supply chain | `incidents.sqlite` | `enrichissements.sqlite` |
| **detecteur_signaux** | Signaux faibles Google News + Reddit, cross-ref avec incidents | RSS + JSON publics | `signaux.sqlite` |
| **dashboard_reflex** | SPA Reflex (3 pages) avec validation humaine | Les 4 SQLite | UI web |

## Stack

- **Python 3.12** — stdlib en priorité, peu de dépendances (`requests`, `feedparser`, `anthropic`, `python-dotenv`)
- **SQLite natif** — pas d'ORM, migrations via `ALTER TABLE` idempotents
- **Claude Haiku 4.5** — scoring sanitaire + extraction signaux, toujours avec fallback déterministe
- **Reflex 0.9** — dashboard (React Router 7 + Radix Themes en sortie)
- **APIs externes** — RappelConso, SIRENE (recherche-entreprises.api.gouv.fr), Pappers, Google News RSS, Reddit JSON

## Démarrage rapide

### Pré-requis

- Python 3.12
- Clé `ANTHROPIC_API_KEY` (recommandée — sinon les agents basculent sur leur fallback règles)
- Clé `PAPPERS_API_KEY` (optionnelle — enrichit le contact dirigeant)

### Installation

```bash
cd agents
python -m venv .venv
.venv/Scripts/pip install -r veilleur_incidents/requirements.txt
.venv/Scripts/pip install -r evaluateur_severite/requirements.txt
.venv/Scripts/pip install -r enrichisseur_prospects/requirements.txt
.venv/Scripts/pip install -r detecteur_signaux/requirements.txt
```

Créer `agents/.env` :

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
PAPPERS_API_KEY=...
```

### Exécution du pipeline

Depuis `agents/` :

```bash
# 1. Récupérer les rappels récents
python -m veilleur_incidents.cli fetch --since-days 7

# 2. Scorer la sévérité sanitaire
python -m evaluateur_severite.cli score

# 3. Enrichir les prospects (SIRENE + Pappers)
python -m enrichisseur_prospects.cli enrich

# 4. Détecter les signaux faibles
python -m detecteur_signaux.cli fetch --max 100
```

### Dashboard

```bash
cd agents/dashboard_reflex
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt

FRONTEND_PORT=3000 BACKEND_PORT=8000 .venv/Scripts/reflex run
```

Puis ouvrir [http://localhost:3000](http://localhost:3000).

### Tests

```bash
cd agents
python -m unittest discover
```

## Décisions techniques notables

- **LLM = fallback-first** : chaque intégration Claude a un fallback règles déterministe, le pipeline fonctionne entièrement sans clé API.
- **Cross-référence signal ↔ incident** : 4 dimensions pondérées (marque 40 %, symptôme 30 %, produit 20 %, proximité date 10 %). Auto-confirmation quand l'article contient un lien direct `rappel.conso.gouv.fr/fiche-rappel/...`.
- **Targeting contacts opérationnels** : profils qualité / QHSE / supply chain / conformité priorisés sur les dirigeants légaux (fallback uniquement).
- **Dédup signaux** : `sha1(marque + symptome + jour)[:16]` pour stabilité.

## Structure du dépôt

```
agents/
├── veilleur_incidents/      # Agent 1
├── evaluateur_severite/     # Agent 2
├── enrichisseur_prospects/  # Agent 3
├── detecteur_signaux/       # Agent 4
├── dashboard/               # Data access (lecture seule SQLite)
├── dashboard_reflex/        # SPA Reflex
└── data/                    # SQLite (gitignored)
```

Chaque agent suit le même pattern : `models.py` (dataclasses), `storage.py` (SQLite + migrations), `cli.py` (argparse), `tests/`.

## Statut

| Composant | État |
|---|---|
| Agents 1–4 | Livrés, testés |
| Dashboard Reflex | Livré (3 pages, drawers, validation, mobile) |
| Cross-ref signal↔incident | Livré (auto-confirm par lien) |
| Agent 5 — Rédaction outreach | À faire |
| Intégration CRM (Sellsy) | À faire |

## Licence

Code propriétaire — projet freelance sous contrat client. Tous droits réservés.
