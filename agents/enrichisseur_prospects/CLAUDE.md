# Agent 3 — Enrichisseur de prospects

## 1. Rôle et responsabilité

Pour chaque incident de `incidents.sqlite`, matcher la **marque produit** à
une entreprise française via **SIRENE**, puis récupérer un **contact
opérationnel** (qualité / supply chain / conformité) — avec fallback sur le
dirigeant légal si pas de profil cible trouvé.

Résultat stocké dans `enrichissements.sqlite`, consommé par la page
**Prospects** du dashboard.

## 2. Fichiers principaux

```
enrichisseur_prospects/
├── models.py              # EnrichissementResult, seuils confidence, TRANCHE_EFFECTIF
├── normalizer.py          # normalize_marque (strip SAS/SARL/accents/génériques)
├── contact_profiles.py    # classify_contact_type, select_best_contact
├── api_sirene.py          # SireneClient + extract_company_fields
├── api_pappers.py         # PappersClient — contact dirigeant plus récent
├── api_societecom.py      # Stub (clé non disponible)
├── matcher.py             # match_incident — pipeline complet avec confidence
├── storage.py             # EnrichissementStorage — upsert, stats, list_found
├── enrichisseur.py        # run_enrich(incidents_db, enrichissements_db, ...)
├── cli.py                 # argparse : enrich, show, stats
└── tests/
```

| Fichier | Rôle |
|---|---|
| `normalizer.py` | "SAS Nestlé France" → "nestle" (requête SIRENE propre) |
| `contact_profiles.py` | Classifie titre → `"cible"` vs `"fallback_dirigeant"` |
| `matcher.py` | Orchestrateur par incident : normalize → SIRENE → Pappers → scoring |

## 3. Modèles de données

### Table SQLite `enrichissements`

```sql
CREATE TABLE enrichissements (
    source               TEXT NOT NULL,
    source_id            TEXT NOT NULL,
    enricher_version     TEXT NOT NULL,
    marque_input         TEXT,
    query_used           TEXT,                -- terme normalisé envoyé à SIRENE
    match_status         TEXT NOT NULL,       -- found | ambiguous | not_found | skipped
    confidence           REAL,                -- 0.0-1.0
    siren                TEXT,
    siret_siege          TEXT,
    raison_sociale       TEXT,
    forme_juridique      TEXT,
    code_naf             TEXT,
    libelle_naf          TEXT,
    adresse              TEXT,
    effectif_tranche     TEXT,                -- libellé via TRANCHE_EFFECTIF
    categorie_entreprise TEXT,                -- PME / ETI / GE
    contact_nom          TEXT,
    contact_titre        TEXT,
    contact_source       TEXT,                -- 'sirene' | 'pappers' | 'societecom'
    contact_type         TEXT,                -- 'cible' | 'fallback_dirigeant'
    ca_annuel            TEXT,                -- réservé futur
    api_used             TEXT,
    enriched_at          TEXT NOT NULL,
    raw_json             TEXT,
    PRIMARY KEY (source, source_id, enricher_version)
);
```

### Seuils confidence (`models.py`)

```python
CONFIDENCE_FOUND = 0.72       # au-dessus : match_status = "found"
CONFIDENCE_AMBIGUOUS = 0.40   # entre : "ambiguous"
# sinon "not_found"
```

### Contact type (`contact_profiles.py`)

**Profils cibles** (mots-clés dans le titre) :
```python
_TARGET_KEYWORDS = [
    "qualit",           # responsable qualité, directeur qualité
    "qhse", "hse",
    "supply chain",
    "conformit",
    "reglementaire",
    "tracabilit",
    "achats",           # acheteur matières
    "industriel", "production",
]
```

**Sélection** (3 passes, ordre de priorité) :
1. Passe cible : 1er dirigeant avec mot-clé cible → `contact_type="cible"`
2. Passe exécutif : DG > PDG > Gérant > Président → `contact_type="fallback_dirigeant"`
3. Fallback : 1er dirigeant de la liste

**⚠️ Important** : SIRENE ne renvoie que les **dirigeants légaux** (jamais de
responsables qualité). Pappers pourrait renvoyer plus de profils mais retourne
**401 actuellement** (à vérifier côté plan). Donc en pratique, 90% des contacts
actuels sont `fallback_dirigeant`.

## 4. Dépendances et APIs

### `requirements.txt`
```
requests>=2.31
python-dotenv>=1.0
```

### APIs externes

| API | URL | Auth | Statut |
|---|---|---|---|
| **SIRENE** | `recherche-entreprises.api.gouv.fr` | Aucune | ✅ Gratuit, stable, inclut dirigeants |
| **Pappers** | `api.pappers.fr/v2/entreprise` | `PAPPERS_API_KEY` | ⚠️ Retourne 401 actuellement |
| **societe.com** | — | `SOCIETECOM_API_KEY` | 🚧 Stub, non implémenté |

### Stratégie multi-sources

```
normalize_marque(marque_input) → query
          │
          ▼
     SIRENE (gratuit)
          │
          ├── found (≥ 0.72) : retourne entreprise + dirigeants SIRENE
          │         │
          │         ▼
          │    Pappers.get_by_siren()  (si clé dispo)
          │         │
          │         ├── success : remplace contact par profil plus récent / cible
          │         └── 401/erreur : garde contact SIRENE
          │
          ├── ambiguous (0.40-0.72) : stocke quand même pour review humain
          └── not_found : stocke ligne vide (marque_input + query_used pour audit)
```

## 5. Commandes CLI

```bash
# Enrichit tous les incidents non encore enrichis
python -m enrichisseur_prospects.cli enrich

# Limite à N (debug)
python -m enrichisseur_prospects.cli enrich --max 10

# Force le ré-enrichissement (change enricher_version ou override)
python -m enrichisseur_prospects.cli enrich --reenrich

# Détail d'un enrichissement (format texte lisible)
python -m enrichisseur_prospects.cli show 2026-04-0257

# Détail en JSON
python -m enrichisseur_prospects.cli show 2026-04-0257 --format json

# Stats : total, by_status, with_contact, taux de couverture
python -m enrichisseur_prospects.cli stats
```

## 6. Tests

```bash
cd agents
python -m unittest discover enrichisseur_prospects/tests
```

**Deux fichiers de test** :
- `test_normalizer.py` (15 tests) — strip accents, formes juridiques, génériques
- `test_matcher.py` (20 tests) — MagicMock sur SireneClient, vérifie confidence
  et contact_type dans tous les cas limites

Tous mockés, pas d'appel réseau.

## 7. Décisions techniques

### SIRENE en source primaire gratuite

- Accessible sans clé, sans quota bloquant
- Inclut les dirigeants légaux (pas les fonctionnels)
- Permet un premier enrichissement gratuit pour 100% des incidents

### Pappers en complément optionnel

- Ajoute la possibilité d'avoir un contact **cible** (responsable qualité, etc.)
- Freemium avec limite d'appels
- Si pas de clé ou 401 : on garde SIRENE, pas d'exception

### Matching fuzzy avec bonus substring

```python
def _similarity(a, b) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()

def _best_candidate(query, results):
    scored = [(_similarity(query, r["nom_complet"]), r) for r in results]
    # Bonus +0.15 si query est substring de la raison sociale
    for score, r in scored:
        if query.lower() in r["nom_complet"].lower():
            score = min(1.0, score + 0.15)
    return max by score
```

### Normalisation marque agressive

Le `normalize_marque` supprime :
- Formes juridiques (SAS, SARL, SA, SASU, SNC…)
- Accents (via `unicodedata.normalize("NFD")`)
- Stop words (France, International, Group, etc.)
- Ponctuation

Si le résultat est générique ("sans marque", "-", "sans marques"), renvoie
`None` → `match_status = "skipped"`.

### Upsert avec historique via `enricher_version`

PK composite `(source, source_id, enricher_version)` permet de garder plusieurs
versions. Bump `ENRICHER_VERSION` dans `matcher.py` quand tu changes la logique
de matching.

### Pas de cache API

Même raison qu'Agent 2 : chaque requête est sur une marque différente, cache
peu utile. Si jamais : Redis serait l'option, mais pas pour le MVP.

## 8. À savoir pour toute évolution

- **Débloquer Pappers** : vérifier le plan côté compte Pappers, endpoint peut
  avoir changé. La clé dans `.env` est bonne mais le code renvoie 401. À
  investiguer côté compte.
- **Implémenter societe.com** : le stub `api_societecom.py` est prêt, même
  interface que `api_pappers.py`. Remplacer `NotImplementedError` par l'appel
  HTTP quand la clé est dispo.
- **Changer les mots-clés cibles** : édite `_TARGET_KEYWORDS` dans
  `contact_profiles.py`. Couvre les fonctions exigées par le client (qualité,
  supply, conformité). Si le client veut cibler "achats" ou "R&D", ajoute-les.
- **Calibrer les seuils** : `CONFIDENCE_FOUND` / `CONFIDENCE_AMBIGUOUS` dans
  `models.py`. Observe les résultats via `list_found` puis ajuste si trop de
  faux positifs / négatifs.
- **Ajouter une dimension CA / effectif exploitable** : `ca_annuel` est réservé
  mais jamais rempli. À faire quand on aura une source (Pappers ou societe.com).
