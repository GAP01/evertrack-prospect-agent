# Agent 2 — Évaluateur de sévérité

## 1. Rôle et responsabilité

Calcule un **score de priorité 0-100** pour chaque incident de `incidents.sqlite`
et le range dans un **tier** (critique / eleve / modere / faible).

Le score résulte de 4 dimensions pondérées, dont le **risque sanitaire** est
évalué par **Claude Haiku** (LLM), avec fallback règles déterministe. Les 3
autres dimensions sont purement règles (pas de LLM).

## 2. Fichiers principaux

```
evaluateur_severite/
├── models.py         # IncidentScore, DimensionScore, SCORER_VERSION
├── rules.py          # 3 dimensions règles (ampleur_geo, population_vulnerable, volume_distributeurs)
├── llm_scorer.py     # risque_sanitaire — Claude Haiku + fallback table mots-clés
├── storage.py        # ScoreStorage — upsert + latest_score + stats
├── evaluateur.py     # run_score(incidents_db, scores_db, ...) — orchestrateur
├── cli.py            # argparse : score, stats, show
└── tests/
```

| Fichier | Rôle |
|---|---|
| `rules.py` | Heuristiques pures : zone, vulnérabilité (enfants/femmes enceintes), enseignes |
| `llm_scorer.py` | Prompt système pour Claude Haiku + fallback `SANITARY_KEYWORDS` |
| `evaluateur.py` | Charge incidents, score chaque dimension, combine pondéré, upsert |

## 3. Modèles de données

### Table SQLite `scores`

```sql
CREATE TABLE scores (
    source           TEXT NOT NULL,
    source_id        TEXT NOT NULL,
    score            REAL NOT NULL,          -- 0-100 pondéré
    tier             TEXT NOT NULL,          -- critique | eleve | modere | faible
    dimensions_json  TEXT NOT NULL,          -- 4 DimensionScore sérialisés
    scored_at        TEXT NOT NULL,
    scorer_version   TEXT NOT NULL,
    llm_used         INTEGER NOT NULL,
    PRIMARY KEY (source, source_id, scorer_version, scored_at)
);
CREATE INDEX idx_scores_score ON scores (score DESC);
CREATE INDEX idx_scores_incident ON scores (source, source_id);
```

### Dataclass `IncidentScore` (`models.py`)

```python
@dataclass
class DimensionScore:
    name: str                # "risque_sanitaire" | "ampleur_geo" | ...
    raw: float               # 0-100 brut
    weight: float            # 0-1
    rationale: str           # prefixe "[LLM]" ou "[regles]"

@dataclass
class IncidentScore:
    source: str
    source_id: str
    score: float             # 0-100 (somme pondérée)
    tier: str                # calculé depuis score
    dimensions: list[DimensionScore]
    scored_at: datetime
    scorer_version: str
    llm_used: bool
```

### Pondération fixe

| Dimension | Poids | Type |
|---|---|---|
| `risque_sanitaire` | **50%** | LLM + fallback règles |
| `ampleur_geo` | 25% | règles |
| `population_vulnerable` | 15% | règles |
| `volume_distributeurs` | 10% | règles |

### Seuils de tier

| Score | Tier |
|---|---|
| ≥ 80 | critique |
| ≥ 60 | eleve |
| ≥ 40 | modere |
| < 40 | faible |

## 4. Dépendances et APIs

### `requirements.txt`
```
anthropic>=0.30.0    # Optionnel : fallback si absent
```

### API Claude
- **Modèle** : `claude-haiku-4-5-20251001`
- **Prompt système** : expert sécurité sanitaire, barème 0-100 calibré sur pathogènes
- **Réponse** : JSON strict `{"score": int, "rationale": str, "label": str}`
- **Sans clé** : bascule automatique sur la table `SANITARY_KEYWORDS` (30+ entrées)

### Fallback table (extrait)

```python
SANITARY_KEYWORDS = [
    (95, "Botulisme", ["botulisme", "clostridium botulinum"]),
    (92, "Listeria", ["listeria", "listeriose", "monocytogenes"]),
    (90, "Allergene non declare", ["allergene non declare", ...]),
    (85, "E. coli pathogene", ["escherichia coli", "stec", ...]),
    (80, "Salmonelle", ["salmonel", "salmonella"]),
    ...
]
```

Priorité : le score max des mots-clés trouvés gagne.

## 5. Commandes CLI

```bash
# Score tous les incidents non encore scorés (utilise LLM par défaut)
python -m evaluateur_severite.cli score

# Force le rescoring de tout
python -m evaluateur_severite.cli score --rescore

# Limite à N incidents (debug coûts LLM)
python -m evaluateur_severite.cli score --max 10

# Sans LLM (fallback règles uniquement)
python -m evaluateur_severite.cli score --no-llm

# Stats globales (total, par tier, llm_used_count, dernier scoring)
python -m evaluateur_severite.cli stats

# Détail d'un incident scoré (avec breakdown 4 dimensions)
python -m evaluateur_severite.cli show 2026-04-0257
```

## 6. Tests

```bash
cd agents
python -m unittest discover evaluateur_severite/tests
```

Tests unitaires sur :
- `rules.py` — cas limites zone/vulnerable/volume
- `llm_scorer.py` — **fallback uniquement** (le LLM est mocké, jamais appelé en test)
- `evaluateur.py` — combinaison pondérée des 4 dimensions

## 7. Décisions techniques

### LLM fallback-first

C'est le pattern de référence du projet, reproduit dans Agent 4.

```python
def _call_claude_api(...) -> Optional[dict]:
    try:
        import anthropic
    except ImportError:
        return None  # fallback
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None  # fallback
    try:
        msg = client.messages.create(...)
    except Exception:
        return None  # fallback
    # parse JSON defensively
    ...
```

Agent fonctionnel sans clé, sans dépendance réseau, sans coût. Coût réel avec
LLM : ~0,003 €/incident (Haiku).

### Historique préservé via PRIMARY KEY composite

`(source, source_id, scorer_version, scored_at)` permet de conserver plusieurs
versions d'un même score. Le dashboard lit toujours le **plus récent** via
`latest_score()` avec `ORDER BY scored_at DESC LIMIT 1`.

Utile pour :
- Recalibrer (nouveau `scorer_version`) sans perdre l'ancien
- Comparer "score à t0 vs score à t1"
- Audit

### Risque sanitaire = 50% du score global

Le plus gros levier. C'est le seul justifiant le LLM. Les 3 autres dimensions
sont facilement règles :
- `ampleur_geo` : mots-clés dans `zone_geographique` (national > régional > local)
- `population_vulnerable` : mots-clés dans `motif+risques` (enfant, femme enceinte, immunodéprimé)
- `volume_distributeurs` : nombre d'enseignes dans `distributeurs`

### Pas de retry automatique sur LLM

Si Claude API échoue (rate limit, timeout), on log un warning et on bascule sur
le fallback. Pas de retry parce que :
- Le scoring n'est pas temps réel
- Un rescoring ultérieur (`--rescore`) capture les cas manqués
- Simplifie le code

### Pas de cache LLM

Chaque incident a une signature unique (motif + risques spécifiques). La
probabilité de réutiliser exactement le même prompt est quasi-nulle. Cache
inutile.

## 8. À savoir pour toute évolution

- **Ajouter une dimension** : ajoute une fonction dans `rules.py`, référence-la
  dans `evaluateur.py`, recalcule les poids (somme = 1.0), bump `SCORER_VERSION`
  pour ne pas mélanger avec l'historique.
- **Calibrer les seuils tier** : édite `tier_from_score()` dans `models.py`.
  Attention : le dashboard Reflex utilise ces tiers (badge couleur).
- **Changer de modèle LLM** : param `model=` dans `score_risque_sanitaire()`. Haiku
  reste le bon choix (ratio perf/coût). Opus si besoin de nuance fine.
- **Dépendance au Veilleur** : si `Incident.motif` ou `Incident.risques`
  sont renommés, le prompt LLM doit être mis à jour (variables `{motif}`,
  `{risques}`).
