# Évaluateur de sévérité — Agent 2

Score chaque incident récupéré par le **Veilleur** (agent 1) sur une échelle 0-100, avec un tier human-readable (faible/modéré/élevé/critique). Sortie pensée pour produire un *top N quotidien* à présenter au commercial.

## Approche

Hybride règles + LLM, avec quatre dimensions pondérées :

| Dimension | Poids | Source |
|---|---|---|
| Risque sanitaire | 50% | Claude Haiku (avec fallback table de mots-clés) |
| Ampleur géographique | 25% | Règles sur `zone_geographique` + `distributeurs` |
| Population vulnérable | 15% | Mots-clés (lait infantile, listeria, botulisme, SHU…) |
| Volume distributeurs | 10% | Détection des grandes enseignes nationales |

Le LLM ne juge **que** la gravité intrinsèque du risque — il ne voit ni l'ampleur ni le volume. C'est un choix : on garde une décomposition explicable et auditable, ce qui rassure le client face à une boîte qui paraîtrait "noire".

### Tiers

| Tier | Borne |
|---|---|
| critique | ≥ 80 |
| élevé | 60-79 |
| modéré | 40-59 |
| faible | < 40 |

## Structure

```
evaluateur_severite/
├── __init__.py
├── models.py            # IncidentScore, DimensionScore, score_to_tier
├── rules.py             # 3 dimensions structurées (déterministes)
├── llm_scorer.py        # Risque sanitaire — Claude Haiku ou fallback
├── storage.py           # Persistance SQLite (table scores, historique versionné)
├── evaluateur.py        # Orchestrateur
├── cli.py               # CLI : score, top
├── requirements.txt
└── tests/
    └── test_evaluateur.py
```

## Installation

Depuis `agents/`, dans le même venv que le veilleur :

```bash
pip install -r evaluateur_severite/requirements.txt
```

Le SDK `anthropic` est requis si on veut utiliser le LLM. Sans lui, l'agent bascule automatiquement sur la table de mots-clés.

## Configuration

Pour activer le scoring LLM, exporter la clé Anthropic :

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Sans clé : pas d'erreur, on bascule sur le fallback déterministe (et `llm_used: false` dans le rapport).

## Utilisation

```bash
# Scorer tous les incidents non encore scorés (avec LLM si dispo)
python -m evaluateur_severite.cli score

# Scorer sans LLM (table mots-clés uniquement, gratuit, offline)
python -m evaluateur_severite.cli score --no-llm

# Forcer le rescoring de TOUS les incidents (utile si on change la version du scorer)
python -m evaluateur_severite.cli score --rescore

# Limite à 5 incidents (utile pour tester / contrôler le coût LLM)
python -m evaluateur_severite.cli score --max 5

# Top 10 par sévérité
python -m evaluateur_severite.cli top --limit 10

# Filtrer par tier
python -m evaluateur_severite.cli top --tier critique

# Top en JSON (avec breakdown par dimension)
python -m evaluateur_severite.cli top --format json --limit 5
```

Bases par défaut : `data/incidents.sqlite` (lecture, base du veilleur), `data/scores.sqlite` (écriture, base de l'évaluateur). Surchargeables via `--incidents-db` et `--scores-db`.

## Tests

```bash
python -m evaluateur_severite.tests.test_evaluateur
```

15 tests, sans dépendance réseau. Les fixtures sont les 4 vrais incidents récupérés sur RappelConso le 2026-04-22 — donc on valide le scoring sur des données qu'on a vraiment vues.

## Comportement

- **Idempotent par défaut** : `score` ne re-évalue pas un incident déjà scoré avec la même `scorer_version`. Pour forcer, utiliser `--rescore`.
- **Versionné** : `IncidentScore.scorer_version = "v0.1"`. Quand on changera la pondération ou le prompt, on incrémente — l'historique reste en base.
- **Robuste au LLM** : timeout, erreur réseau, JSON malformé → log warning + fallback. Jamais d'exception qui remonte.
- **Coût** : ~150 tokens out / incident sur Haiku, ~0,001 €/incident. Pour ~30 incidents/jour côté France, ça fait < 1 €/mois.

## Calibration sur les 4 incidents observés

Sans LLM (avec fallback), on s'attend à peu près à :

| Incident | Sanitaire | Ampleur | Vulnér. | Distrib. | **Total** | Tier |
|---|---|---|---|---|---|---|
| Listéria (Carrefour Laventie) | 92 | 15 | 60 | 60 | **~65** | élevé |
| Histamine (france entière) | 60 | 100 | 0 | 60 | **~61** | élevé |
| Histamine (Intermarché St Médard) | 60 | 15 | 0 | 60 | **~40** | modéré |
| Phyto (10 dépt, épicerie) | 40 | 70 | 0 | 30 | **~41** | modéré |

Le bug volontaire est qu'**une listéria locale prime sur une histamine nationale** — c'est ce qu'on veut, le risque sanitaire pèse 50%. Si le client préfère privilégier l'ampleur (volume de prospects à toucher), on passera l'ampleur de 25 à 40% et le sanitaire de 50 à 35%.

## Dette assumée pour le POC

- Médiatisation pas évaluée (rôle de l'agent 3 — enrichisseur).
- Pas encore de seuil "nouveau vs déjà scoré il y a X jours" — pour rescorer un incident dont la fiche RappelConso a été enrichie après publication.
- Pas de cache LLM. Si on rescore sans `--rescore`, on n'appelle pas le LLM ; mais si on force, on rejoue tous les appels.
- Pas de calibration empirique — la pondération est un choix d'expert, à ajuster après retours du commercial.

## Prochaine étape

Agent 3 — Enrichisseur : aller chercher la **société fabricante** (souvent absente quand `marque = "sans"`), sa **taille** (Pappers/Sirene), sa **médiatisation** (Google News). Sortie : un dossier prospect par incident, prêt pour l'agent 4 (identificateur de contact LinkedIn).
