# Agent 1 — Veilleur d'incidents (RappelConso)

## 1. Rôle et responsabilité

Crawl le dataset public **RappelConso** (data.economie.gouv.fr), normalise les
records en dataclass `Incident`, déduplique, et stocke dans `incidents.sqlite`.

C'est la **porte d'entrée** du pipeline : toutes les analyses aval (scoring,
enrichissement, cross-référence) s'appuient sur cette table.

## 2. Fichiers principaux

```
veilleur_incidents/
├── api_client.py     # RappelConsoClient — requêtes HTTP vers l'API data.gouv
├── models.py         # @dataclass Incident (18 champs + raw)
├── normalize.py      # Mapping record API brut → Incident
├── storage.py        # class Storage (SQLite, upsert_many, stats)
├── veilleur.py       # run_fetch(db_path, export_json_path, ...) — orchestrateur
├── cli.py            # argparse : fetch, list, schema
└── tests/
```

| Fichier | Rôle |
|---|---|
| `api_client.py` | Wrapper requests + pagination + retry sur 429/5xx |
| `normalize.py` | Convertit les champs API (parfois changeants) vers `Incident` stable |
| `storage.py` | Gère la table `incidents` + dédup via `(source, source_id)` |
| `veilleur.py` | Pipeline complet : fetch → normalize → upsert → export JSON |

## 3. Modèles de données

### Table SQLite `incidents`

```sql
CREATE TABLE incidents (
    source            TEXT NOT NULL,
    source_id         TEXT NOT NULL,
    source_url        TEXT,
    categorie         TEXT,
    sous_categorie    TEXT,
    marque            TEXT,
    modeles           TEXT,
    nature_juridique  TEXT,
    motif             TEXT,
    risques           TEXT,
    zone_geographique TEXT,
    distributeurs     TEXT,
    date_publication  TEXT,
    raw_json          TEXT,
    first_seen_at     TEXT DEFAULT (datetime('now')),
    last_seen_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (source, source_id)
);
CREATE INDEX idx_incidents_date ON incidents (date_publication DESC);
CREATE INDEX idx_incidents_categorie ON incidents (categorie);
```

### Dataclass `Incident` (`models.py`)

```python
@dataclass
class Incident:
    source: str                          # "rappelconso"
    source_id: str                       # ex: "2026-04-0257"
    source_url: Optional[str]            # https://rappel.conso.gouv.fr/fiche-rappel/22094/interne
    categorie: Optional[str]             # "Alimentation"
    sous_categorie: Optional[str]
    marque: Optional[str]
    modeles: Optional[str]               # noms/références concaténés
    nature_juridique: Optional[str]      # Rappel / Retrait
    motif: Optional[str]
    risques: Optional[str]
    zone_geographique: Optional[str]
    distributeurs: Optional[str]         # liste concaténée
    date_publication: Optional[date]
    raw: dict[str, Any]                  # record brut pour inspection
```

**⚠️ Important** : les colonnes sont `motif` et `risques` (pas `motif_rappel` /
`risques_encourus` — c'est l'ancienne nomenclature de l'API qui a été abandonnée).

## 4. Dépendances et APIs

### Packages Python (`requirements.txt`)
```
requests>=2.31
```

Juste `requests` — agent volontairement léger.

### API externe
- **RappelConso** via `data.economie.gouv.fr` (ODS API)
- **Pas d'auth** requise — open data gouvernementale
- **Dataset** : `rappelconso0/records` (paginé, max 100 records/page)
- **Filtrage** : query ODQL (Open Data Query Language), ex `categorie_produit:"Alimentation"`
- **Date** : filtre sur `date_de_publication` relatif (`now() - Xd`)

## 5. Commandes CLI

Toutes depuis `agents/` (paths relatifs vers `data/`).

```bash
# Fetch des 7 derniers jours, catégorie Alimentation
python -m veilleur_incidents.cli fetch --since-days 7 --categorie Alimentation

# Fetch limité à N records (debug)
python -m veilleur_incidents.cli fetch --max-records 10

# Verbose (DEBUG logging)
python -m veilleur_incidents.cli -v fetch --since-days 30

# Liste les derniers incidents en base
python -m veilleur_incidents.cli list --limit 10

# Inspecte le schéma actuel du dataset API (utile si les champs changent)
python -m veilleur_incidents.cli schema
```

## 6. Tests

```bash
cd agents
python -m unittest discover veilleur_incidents/tests
```

Tests unitaires sur :
- `normalize.py` — mapping record API → Incident
- `storage.py` — upsert idempotent, dédup

Les tests API sont mockés (pas d'appels réseau en CI).

## 7. Décisions techniques

### Idempotence par `(source, source_id)`
- Même incident re-fetché → UPDATE `last_seen_at`, pas d'INSERT doublé
- Permet des refresh quotidiens sans duplications
- `first_seen_at` figé à la 1re détection (utile pour Agent 4 lead time)

### Pas d'ORM, SQL brut
- Cohérent avec le reste du projet
- Perf suffisante (< 100k records attendus)

### Export JSON optionnel
- `--export data/incidents_last_fetch.json` pour debug / backup
- Dump complet du dernier batch fetché

### Tolérance aux évolutions du dataset
- `normalize.py` utilise `.get()` partout avec defaults
- Les champs non reconnus atterrissent dans `Incident.raw`
- `cli.py schema` permet d'inspecter le dataset en cas de changement API

### `nature_juridique` n'impacte pas le pipeline
- Que ce soit "Rappel" ou "Retrait", on traite pareil
- Stocké pour info mais pas filtre métier

## 8. À savoir pour toute évolution

- **Si tu ajoutes une colonne** : modifie `SCHEMA`, ajoute une entrée dans la liste
  `_MIGRATIONS` (pattern ALTER TABLE try/except OperationalError) — et surtout
  propage dans `_INCIDENT_KEYS` du dashboard `state.py` si la colonne doit être
  affichée.
- **Si l'API change** : le mapping se fait dans `normalize.py`. Utilise
  `cli.py schema` pour voir les champs actuels.
- **Performance** : le fetch est paginé par 100, tourne en quelques secondes pour
  un mois de données. Pas besoin d'optim pour l'instant.
- **Source autre que RappelConso** : l'archi permet d'ajouter d'autres `source`
  (ex: `"signal_detecteur"` quand Agent 4 promeut un signal). Respecter la PK
  composite `(source, source_id)`.
