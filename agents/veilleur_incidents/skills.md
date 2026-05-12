# Compétences — Veilleur d'incidents

Ce que l'agent **sait faire** concrètement, au-delà de son rôle.

## 1. Appel d'API externe : RappelConso V2

### API maîtrisée
- **Fournisseur** : data.economie.gouv.fr (Opendatasoft Explore v2.1)
- **Dataset** : `rappelconso-v2-gtin-espaces` (V1 désactivée fin 2025)
- **Base URL** : `https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets`
- **Pas d'auth** requise

### Endpoints appelés
| Endpoint | Usage |
|---|---|
| `GET /{dataset}` | `get_dataset_metadata()` — schéma des champs (pour CLI `schema`) |
| `GET /{dataset}/records` | `fetch_page()` — paginé par 100 max |

### Pagination maîtrisée
- `limit` max 100 par requête (borné côté API)
- `offset` incrémental jusqu'à résultats vides
- Itération via `iter_records()` (generator) pour ne pas tout charger en mémoire

### Filtres supportés
| Paramètre | Syntaxe | Exemple |
|---|---|---|
| `where` | ODSQL | `date_publication >= date'2026-04-17'` |
| `refine` | `facet:value` | `categorie_produit:alimentation` |
| `order_by` | champ + direction | `date_publication DESC` |

⚠️ Les valeurs des facettes RappelConso V2 sont **toutes en minuscules** —
`"alimentation"` et pas `"Alimentation"`.

## 2. Parsing de formats

### Records Opendatasoft
L'agent sait consommer les deux formats possibles :
- **V2 plat** : `{"numero_fiche": "...", "marque_produit": "..."}`
- **V1 imbriqué** (fallback défensif) : `{"record": {"fields": {...}}}`

Cas V1 déballé automatiquement dans `normalize_record()`.

### Dates tolérantes
Utilise `dateutil.parser.parse(value, dayfirst=True)` → accepte :
- ISO 8601 (`2026-04-17T10:30:00`)
- Date européenne (`17/04/2026`, `17 avril 2026`)
- Date US (`2026-04-17`)

Retourne `None` silencieusement si invalide.

## 3. Mapping de schéma tolérant aux changements

### `FIELD_MAP` — noms de champs candidats

L'agent tente **plusieurs clés** par champ cible, dans l'ordre. Permet de
survivre aux renommages entre versions du dataset :

| Champ cible | Clés tentées (ordre) |
|---|---|
| `source_id` | `numero_fiche`, `ndeg_de_la_fiche`, `reference_fiche`, `rappel_guid` |
| `source_url` | `lien_vers_la_fiche_rappel` |
| `categorie` | `categorie_produit`, `categorie_de_produit` |
| `motif` | `motif_rappel`, `motif_du_rappel` |
| `risques` | `risques_encourus`, `risques_encourus_par_le_consommateur` |
| `date_publication` | `date_publication`, `date_de_publication` |
| (tous les autres dans `normalize.py::FIELD_MAP`) |

### Fallback `"unknown"`
Si aucune clé ne matche pour `source_id` → `source_id = "unknown"` (évite de
crasher, permet de détecter le problème via PK collision en base).

## 4. Coercion de types

### `_coerce_str()` — texte nettoyé
- Listes/tuples concaténés avec ", "
- Trim des espaces
- `""` → `None`

### `_parse_date()` — date/datetime/str → `date`
- `date` passe tel quel
- `datetime` → `.date()`
- `str` → parse via dateutil avec `dayfirst=True`

### `raw` intact
Le record brut entier est conservé dans `Incident.raw` (dict) — permet
l'inspection a posteriori de champs non mappés.

## 5. Persistance SQLite

### Opérations maîtrisées
- **CREATE TABLE IF NOT EXISTS** (`SCHEMA` dans `storage.py`)
- **Upsert différentiel** : SELECT 1 avant INSERT/UPDATE pour compter
  `new_count` vs `updated_count`
- **Sérialisation JSON** du record brut dans `raw_json`
- **Auto-timestamps** : `first_seen_at DEFAULT datetime('now')`, `last_seen_at`
  updaté au re-fetch

### Index créés
- `idx_incidents_date` sur `date_publication DESC` (pour top liste)
- `idx_incidents_categorie` sur `categorie` (pour filtres)

## 6. CLI argparse avec flags globaux

L'agent accepte `-v` et `--db` avant OU après la sous-commande :

```bash
python -m veilleur_incidents.cli -v fetch --max-records 5
python -m veilleur_incidents.cli fetch --max-records 5 -v   # équivalent
```

Pattern réutilisable, implémenté via `_add_common_flags()` sur parent + subs.

### Sous-commandes
| Commande | Capacité |
|---|---|
| `fetch` | Pipeline complet |
| `list` | Lit les N derniers depuis SQLite (sans appel API) |
| `schema` | Interroge l'API pour lister les champs actuels (diagnostic) |

## 7. Export JSON pour debug/backup

Si `--export <path>` fourni : le batch courant est sérialisé en JSON
(UTF-8, indent 2) sous `incidents_last_fetch.json` par défaut.

Permet :
- Backup ponctuel avant une migration
- Inspection hors-ligne
- Partage avec le client

## 8. Logging structuré

- Niveau contrôlé par `-v` (DEBUG) ou défaut (INFO)
- Format : `%(asctime)s %(levelname)s %(name)s - %(message)s`
- `logger.exception()` sur les records individuels qui plantent (stack trace)

## Ce que l'agent ne sait PAS faire

- **Pas de LLM** : zero appel Claude/OpenAI. 100% règles.
- **Pas de retry** automatique sur erreur API.
- **Pas de déduplication sémantique** — identique PK = identique record.
- **Pas de scoring** — pas son rôle.
- **Pas de notifications** — ne push rien (pas d'email, pas de webhook).
- **Pas d'historique des versions** d'un même `source_id` — on garde le dernier état seulement.
