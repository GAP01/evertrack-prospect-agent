# Agent — Évaluateur de sévérité

## Identité

- **Nom** : `evaluateur_severite`
- **Position** : Agent 2 (deuxième étage du pipeline)
- **Version** : v0.1 (`SCORER_VERSION`)
- **Type** : Agent d'analyse (batch, stateful, LLM-augmenté)

## Objectif

Attribuer à chaque incident RappelConso un **score de priorité 0-100** et un
**tier** (critique / eleve / modere / faible), pour permettre au dashboard et
aux agents aval de concentrer les efforts commerciaux sur les cas à plus fort
impact potentiel.

Le score combine 4 dimensions pondérées, dont la principale (risque sanitaire
50%) est évaluée par **Claude Haiku** avec fallback déterministe sur table
de mots-clés.

## Inputs

| Input | Source | Format |
|---|---|---|
| Incidents à scorer | `data/incidents.sqlite` | Table `incidents` complète |
| Choix LLM | CLI `--no-llm` pour désactiver | Flag |
| Mode rescore | CLI `--rescore` | Force le recalcul |
| Limite | CLI `--max N` | Plafond (debug / coût) |
| `ANTHROPIC_API_KEY` | `.env` | Optionnelle (fallback sinon) |

### Champs d'incident utilisés pour le scoring

| Champ | Utilisé par |
|---|---|
| `motif` | LLM + fallback keywords + population_vulnerable |
| `risques` | LLM + fallback keywords + population_vulnerable |
| `categorie`, `sous_categorie` | LLM (contexte) + population_vulnerable |
| `zone_geographique` | `score_ampleur_geo` (règles) |
| `distributeurs` | `score_ampleur_geo` + `score_volume_distributeurs` |

## Outputs

| Output | Format | Consommateurs |
|---|---|---|
| `data/scores.sqlite` | SQLite, table `scores` | dashboard_reflex (page Radar), `dashboard/data_access.top_incidents` |
| Rapport CLI | JSON stdout | Humain / monitoring |

### Structure d'une ligne `scores`
```
source           : rappelconso
source_id        : 2026-04-0257
score            : 84.0              (somme pondérée 0-100)
tier             : critique          (≥80)
dimensions_json  : [{...}, {...}, {...}, {...}]
scored_at        : 2026-04-23T12:45:12
scorer_version   : v0.1
llm_used         : 1                 (0 si fallback utilisé)
```

### Exemple de rapport CLI

```json
{
  "incidents_total": 127,
  "skipped_already_scored": 85,
  "scored_now": 42,
  "llm_used_count": 40,
  "by_tier": {"critique": 5, "eleve": 18, "modere": 15, "faible": 4},
  "scorer_version": "v0.1"
}
```

## Déclencheurs

1. **Manuel** : `python -m evaluateur_severite.cli score [--rescore] [--no-llm]`
2. **Dashboard Reflex** : bouton "Scorer les incidents" dans la sidebar
   (via `dashboard/actions.py::trigger_score`)
3. **Après chaque fetch** (pattern recommandé) : chaîner manuellement ou via script

Pas d'auto-trigger interne.

## Dépendances vers les autres agents

| Agent | Type | Pourquoi |
|---|---|---|
| `veilleur_incidents` (Agent 1) | **Amont bloquant** | Lit `incidents.sqlite`, erreur si absente |
| Aucun agent aval obligatoire | — | Les consommateurs de `scores.sqlite` peuvent tourner sans lui |

L'agent **ne bloque pas** Agent 3 (enrichisseur) qui n'a pas besoin du score
— ils sont indépendants en parallèle.

## Dépendances externes

| Système | Criticité | Comportement si KO |
|---|---|---|
| `ANTHROPIC_API_KEY` configurée | **Non bloquant** | Fallback sur table `SANITARY_KEYWORDS` |
| SDK `anthropic` installé | **Non bloquant** | Fallback idem |
| API Claude joignable | **Non bloquant** | Fallback par incident si l'appel échoue |
| `incidents.sqlite` existant | **Bloquant** | `FileNotFoundError` explicite |

**Point clé** : l'agent est 100% fonctionnel sans clé LLM grâce au fallback.

## Comportement attendu

### Mode par défaut : `only_new=True`
- Saute les incidents déjà scorés avec le même `SCORER_VERSION`
- Permet de relancer sans coût LLM après un fetch

### Mode `--rescore`
- Force le scoring de tous les incidents
- Coût LLM proportionnel au volume

### Pas de retry LLM
Si l'appel Claude échoue (timeout, rate limit, erreur parsing JSON), l'agent
log un warning et bascule sur le fallback règles pour **cet incident
uniquement**. Les autres continuent.

### Historique préservé
PK composite `(source, source_id, scorer_version, scored_at)` permet plusieurs
versions d'un même score. Le dashboard lit toujours la plus récente via
`latest_score()` (ORDER BY scored_at DESC LIMIT 1).

### Isolation d'erreurs
Un incident qui plante pendant le scoring n'arrête pas le batch — log
`logger.exception` et continue.

## Conditions de succès

L'agent réussit si :
1. `incidents.sqlite` est lisible
2. Au moins 0 incidents sont à scorer (= pas de nouveaux = succès trivial)
3. Les incidents scorés ont tous une `IncidentScore` cohérente
   (somme pondérée des dimensions, `tier` déduit du score)

**Sortie** : code 0 avec rapport JSON.

## Conditions d'échec

Échec (exception remontée) si :
1. **`incidents.sqlite` absente** → `FileNotFoundError` explicite avec message
   "Lance d'abord `python -m veilleur_incidents.cli fetch`"
2. **Poids des dimensions incohérents** (somme ≠ 1.0 ±0.01) → `ValueError` dans
   `IncidentScore.from_dimensions` (garde-fou pour détecter les mauvaises
   configurations)
3. **SQLite corrompue** → propagé

### Recovery
- Base incidents absente → lancer Agent 1 d'abord
- Poids incohérents → bug de code, corriger dans `rules.py` / `llm_scorer.py`
- Si LLM coûteux : désactiver via `--no-llm`, utiliser que les règles

## Intégration dans le pipeline

```
  ┌─────────────────────┐
  │  incidents.sqlite   │  ← produit par Agent 1
  └──────────┬──────────┘
             │ SELECT * FROM incidents
             ▼
  ┌─────────────────────┐
  │ EVALUATEUR_SEVERITE │  ← cet agent
  │                     │
  │  pour chaque inc :  │
  │   ┌───────────────┐ │
  │   │ 3 dimensions  │ │
  │   │ règles        │ │  ← rules.py (ampleur_geo, pop_vulnerable, volume)
  │   └───────────────┘ │
  │   ┌───────────────┐ │
  │   │ 1 dimension   │ │
  │   │ LLM + fallback│ │  ← llm_scorer.py (risque_sanitaire)
  │   └───────────────┘ │
  │   ↓                 │
  │ Score pondéré 0-100 │
  │ + tier (4 classes)  │
  └──────────┬──────────┘
             │ upsert
             ▼
      scores.sqlite
             │
             └──────► dashboard_reflex (tri par score DESC sur page Radar)
```

## Pondération des dimensions (fixe)

| Dimension | Poids | Plage possible | Pondérée max |
|---|---|---|---|
| `risque_sanitaire` | **0.50** | 0-100 | 50 |
| `ampleur_geo` | 0.25 | 0-100 | 25 |
| `population_vulnerable` | 0.15 | 0-100 | 15 |
| `volume_distributeurs` | 0.10 | 0-100 | 10 |

**Somme** = 1.00 (garde-fou dans `from_dimensions`).

## Seuils de tier (fixes)

| Score ≥ | Tier |
|---|---|
| 80 | `critique` |
| 60 | `eleve` |
| 40 | `modere` |
| < 40 | `faible` |

Cf `TIER_BOUNDS` dans `models.py`. Toute modification impacte les couleurs
du dashboard (`tier_badge.py`).

## Fréquence recommandée

| Contexte | Fréquence | Paramètres |
|---|---|---|
| Après chaque fetch Veilleur | Automatique | `score` (sans flag, only_new=True) |
| Recalibration des règles / poids | 1× après chaque changement | `--rescore` (bump `SCORER_VERSION` si gros changement) |
| Debug LLM KO | À la demande | `--no-llm --max 5` |

## Non-objectifs explicites

- **Pas de fetching** : ne lit que `incidents.sqlite`, jamais l'API RappelConso
- **Pas de filtrage métier** : tous les incidents sont scorés (même "faibles")
- **Pas de notifications** — ne réagit pas aux tiers "critique" (à ajouter hors agent)
- **Pas de machine learning supervisé** : on n'apprend pas, on applique des règles +
  un LLM zero-shot
- **Pas de score individuel par distributeur** : le score est par incident entier
