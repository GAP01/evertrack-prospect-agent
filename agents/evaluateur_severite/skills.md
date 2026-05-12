# Compétences — Évaluateur de sévérité

Ce que l'agent **sait faire** pour scorer un incident produit.

## 1. Scoring par règles déterministes (3 dimensions)

### Dimension A : `ampleur_geo` (poids 25%)

Parse `zone_geographique` + `distributeurs` (concaténés) et attribue un score
selon des patterns textuels :

| Score | Règle déclenchante |
|---|---|
| 100 | Mot-clé national : `"france entiere"`, `"national"`, `"tout le territoire"` |
| 70 | ≥ 3 codes département détectés (pattern `(\d{2,3})`) |
| 45 | 1-2 codes département |
| 15 | Mots-clés locaux : `"magasin"`, `"uniquement"`, `"exclusivement"`, `"ville de"`, `"commune de"` |
| 30 | Aucune info (défaut prudent) |

**Pattern regex des départements** : `\((\d{2,3})\)` — capture `(75)`, `(971)`, etc.

### Dimension B : `population_vulnerable` (poids 15%)

Scanne `sous_categorie` + `motif` + `risques` pour des mots-clés de vulnérabilité.

**Niveaux de criticité** :
| Catégorie | Exemples de mots-clés | Score |
|---|---|---|
| Très vulnérable (nourrisson, SHU, botulisme) | `"lait infantile"`, `"premier age"`, `"shu"`, `"clostridium botulinum"` | 100 |
| Sensible (listeria, salmonelle, enfant) | `"listeria"`, `"salmonel"`, `"e. coli"`, `"etouffement"` | 60 |
| Rien détecté | — | 0 |

Liste complète dans `VULNERABLE_KEYWORDS` (`rules.py`).

### Dimension C : `volume_distributeurs` (poids 10%)

Compte les grandes enseignes nationales dans `distributeurs`.

**Liste** : `carrefour, leclerc, auchan, intermarche, lidl, aldi, casino,
monoprix, franprix, super u, hyper u, cora, match, naturalia, biocoop, amazon, …`

| Score | Règle |
|---|---|
| 100 | ≥ 3 enseignes nationales distinctes |
| 60 | 1-2 enseignes nationales |
| 30 | Distributeurs listés, aucun national |
| 10 | `distributeurs` vide ou null |

## 2. Scoring LLM avec fallback (risque sanitaire, poids 50%)

### Modèle utilisé
- **Claude Haiku** : `claude-haiku-4-5-20251001`
- **max_tokens** : 300
- **Prompt système** : expert sécurité sanitaire, barème 0-100 calibré sur les
  pathogènes classiques (cf `llm_scorer.py::SYSTEM_PROMPT`)

### Format de réponse attendu
```json
{
  "score": 92,
  "rationale": "Listeria monocytogenes cause une infection grave potentiellement mortelle chez les populations à risque...",
  "label": "Listeriose"
}
```

### Barème LLM (indicatif)
| Score | Exemple |
|---|---|
| 90-100 | Botulisme, listeria femme enceinte, allergène non déclaré grave |
| 70-89 | Salmonelle, E. coli pathogène, intoxication aiguë |
| 50-69 | Histamine élevée, corps étranger tranchant |
| 30-49 | Résidus phytosanitaires légers, étiquetage allergène mineur |
| 0-29 | Défauts cosmétiques, étiquetage non sanitaire |

### Parsing défensif de la réponse
1. Extraction JSON via regex `\{.*\}` (DOTALL)
2. `json.loads` avec catch `JSONDecodeError`
3. Validation `score` ∈ [0, 100] et type `int/float`
4. Cap `rationale` à 300 chars, `label` à 60 chars

Si l'une de ces étapes échoue → bascule fallback.

### Fallback déterministe : table `SANITARY_KEYWORDS`

30+ entrées structurées en `(score, label, [keywords])` :

```python
(95, "Botulisme - risque vital", ["botulisme", "clostridium botulinum"]),
(92, "Listeria - risque grave", ["listeria", "listeriose", "monocytogenes"]),
(90, "Allergene non declare - risque anaphylactique", [...]),
(85, "E. coli pathogene - risque SHU enfant", [...]),
(80, "Salmonellose - risque eleve", [...]),
# ... jusqu'à 20 pour défauts cosmétiques
```

**Logique** : scanne `motif + risques`, score = max des matches trouvés.
Si aucun match → 30 (défaut prudent).

### Déclencheurs du fallback
| Condition | Fallback |
|---|---|
| `ANTHROPIC_API_KEY` absente | Oui |
| SDK `anthropic` non installé | Oui |
| Timeout / erreur API | Oui |
| JSON invalide | Oui |
| Score hors bornes | Oui |

## 3. Agrégation pondérée

### Formule
```
score_global = Σ (dimension.raw × dimension.weight)
             = risque_sanitaire × 0.50
             + ampleur_geo × 0.25
             + population_vulnerable × 0.15
             + volume_distributeurs × 0.10
```

### Validation des poids
`IncidentScore.from_dimensions()` vérifie `|sum_weights - 1.0| < 0.01` et
lève `ValueError` sinon. Évite les erreurs silencieuses de pondération.

### Tier depuis score
```python
def score_to_tier(score):
    if score >= 80: return "critique"
    if score >= 60: return "eleve"
    if score >= 40: return "modere"
    return "faible"
```

Seuils dans `models.py::TIER_BOUNDS`.

## 4. Persistance SQLite avec historique

### Structure
PK composite `(source, source_id, scorer_version, scored_at)` permet :
- Plusieurs scores pour un même incident (historique)
- Plusieurs versions de scoring (avant/après recalibration)
- Récupération du plus récent via `latest_score()` (ORDER BY scored_at DESC LIMIT 1)

### Sérialisation des dimensions
La liste de `DimensionScore` est stockée dans `dimensions_json` (JSON text).
Format :
```json
[
  {"name": "risque_sanitaire", "raw": 92.0, "weight": 0.5, "rationale": "[LLM] ..."},
  {"name": "ampleur_geo", "raw": 100.0, "weight": 0.25, "rationale": "Diffusion nationale"},
  {"name": "population_vulnerable", "raw": 60.0, "weight": 0.15, "rationale": "Listeriose - ..."},
  {"name": "volume_distributeurs", "raw": 60.0, "weight": 0.10, "rationale": "Enseigne(s) nationale(s) touchee(s) : carrefour"}
]
```

### Déduplication `already_scored_ids`
Pour `only_new=True`, retourne le `set` des `source_id` déjà scorés avec la
version courante. Permet de ne relancer le LLM que sur les nouveaux.

## 5. Traçabilité via `rationale`

Chaque `DimensionScore` contient un `rationale` humain court (1-2 lignes) :
- Règles : message explicite ex `"Enseigne(s) nationale(s) touchee(s) : carrefour"`
- LLM : `"[LLM] " + rationale renvoyé par Claude`
- Fallback LLM : `"[regles] " + label de la table des mots-clés`

Affiché tel quel dans le drawer du dashboard → explicable par Gautier.

## 6. CLI structurée

| Commande | Capacité |
|---|---|
| `score` | Pipeline complet (LLM ou fallback selon flags et clé) |
| `score --rescore` | Force recalcul (utile après changement de règles) |
| `score --no-llm` | Règles uniquement (pas de coût API) |
| `score --max N` | Limite (debug / budget LLM) |
| `stats` | Affiche total, répartition par tier, `llm_used_count`, dernier scoring |
| `show <source_id>` | Dernière version d'un score, avec breakdown 4 dimensions |

## 7. Configuration tolérante aux évolutions

### Bump `SCORER_VERSION` pour invalider l'historique
Si tu changes les règles (ex: ajout d'une dimension, nouveau barème), modifie
`SCORER_VERSION = "v0.2"` dans `evaluateur.py`. Les anciens scores restent en
base (historique), les nouveaux sont recalculés.

### Constantes modifiables
- `TIER_BOUNDS` (`models.py`) — seuils critique/eleve/modere/faible
- Poids des dimensions (dans chaque fonction `score_*` de `rules.py`)
- `VULNERABLE_KEYWORDS`, `ENSEIGNES_NATIONALES`, `GEO_*_PATTERNS` (`rules.py`)
- `SANITARY_KEYWORDS` (`llm_scorer.py`) — fallback
- Prompt système LLM (`llm_scorer.py::SYSTEM_PROMPT`)

## Ce que l'agent ne sait PAS faire

- **Pas de scoring multi-incidents groupés** (ex: « tous les rappels Carrefour
  cette semaine ») — chaque incident est scoré isolément
- **Pas de scoring temporel** (pas de décroissance du score avec le temps)
- **Pas de propagation aux signaux** — l'Agent 4 gère ses propres scores
- **Pas de retry LLM** — une seule tentative, puis fallback
- **Pas de parallélisation** — scoring séquentiel, ~1-2 s/incident avec LLM
- **Pas de métrique de confiance sur les règles** — le score raw est final
- **Pas d'auto-recalibration** — les seuils sont en dur, ajustés manuellement
