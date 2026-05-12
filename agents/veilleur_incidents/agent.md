# Agent — Veilleur d'incidents

## Identité

- **Nom** : `veilleur_incidents`
- **Position** : Agent 1 (entrée du pipeline EverTrack)
- **Version** : v0.1
- **Type** : Agent de veille périodique (batch, stateful)

## Objectif

Maintenir une base de vérité à jour des rappels produits alimentaires publiés
en France, en crawlant le dataset public RappelConso v2 de data.economie.gouv.fr.

C'est la **source canonique** de tout incident officiel dans le pipeline.
Aucun autre agent ne doit appeler directement cette API — ils consomment tous
`incidents.sqlite`.

## Inputs

| Input | Source | Contrôle |
|---|---|---|
| Fenêtre temporelle | CLI `--since-days N` (défaut 7) | Gautier / cron |
| Catégorie produit | CLI `--categorie X` (défaut "alimentation") | Gautier / cron |
| Limite records | CLI `--max-records N` (optionnel, debug) | Gautier |
| Dataset id | Hardcodé `rappelconso-v2-gtin-espaces` | Code |

L'agent **ne consomme aucune autre base EverTrack** — il est la racine du DAG.

## Outputs

| Output | Format | Consommateurs |
|---|---|---|
| `data/incidents.sqlite` | SQLite, table `incidents` | Agent 2, 3, 4, dashboards |
| `data/incidents_last_fetch.json` (optionnel) | JSON liste d'Incident | Debug / backup |
| Rapport CLI | JSON stdout | Humain / monitoring |

Schéma de sortie du rapport :
```json
{
  "fetched": 42,
  "new": 3,
  "updated": 39,
  "since": "2026-04-17",
  "categorie": "alimentation",
  "total_in_db": 127,
  "export_path": "data/incidents_last_fetch.json"
}
```

## Déclencheurs

1. **Manuel** : `python -m veilleur_incidents.cli fetch`
2. **Dashboard Reflex** : bouton "Rafraîchir la veille" dans la sidebar
   (appel via `dashboard/actions.py::trigger_fetch`)
3. **Cron** (à mettre en place) : idéal 1× par jour, `--since-days 2` pour
   couvrir le jour précédent avec marge

Aucun auto-trigger interne — l'agent ne se lance jamais seul.

## Dépendances vers les autres agents

**Aucune**. Premier agent du pipeline, sans dépendance amont.

## Dépendances externes

| Système | Criticité | Comportement si KO |
|---|---|---|
| API RappelConso (`data.economie.gouv.fr`) | Bloquant | Lève `RappelConsoError`, agent s'arrête |
| Réseau internet | Bloquant | Timeout (20s) → erreur |
| Filesystem `data/` | Bloquant | Création automatique du dossier |

## Comportement attendu

### Mode de fonctionnement
- **Batch idempotent** : chaque run est une photo du dataset à T
- **Pas de streaming** : paginate via offset, consomme jusqu'au bout
- **Pas de retry automatique** sur erreur API — remonte l'exception

### Idempotence
- PK composite `(source, source_id)` garantit l'absence de doublons
- Si un incident existe déjà : UPDATE `last_seen_at`, `first_seen_at` reste figé
- Si nouveau : INSERT complet
- Aucun incident n'est jamais supprimé (pour traçabilité)

### Gestion d'erreur
| Erreur | Action |
|---|---|
| HTTP 429/5xx sur une page | Exception propagée (pas de retry) |
| Record individuel non normalisable | Log `logger.exception`, continue |
| Timeout 20s | `requests.exceptions.Timeout` propagée |
| DB verrouillée (rare) | SQLite error propagée |

### Pas de rate-limiting client
L'API Opendatasoft est tolérante ; aucun sleep introduit. Si volume augmente
massivement, envisager un délai entre pages.

## Conditions de succès

L'agent réussit si :
1. La requête API a répondu (au moins une page)
2. Tous les records ont pu être normalisés OU les échecs individuels ont été loggés
3. Le upsert SQLite a renvoyé des compteurs cohérents

**Sortie** : code 0 avec rapport JSON.

## Conditions d'échec

Échec (sortie non-zero ou exception) si :
1. **API injoignable** : timeout, 5xx
2. **Schema brisé** : si `FIELD_MAP` ne trouve plus `source_id` (numero_fiche) →
   `source_id = "unknown"` → PK collision possible sur plusieurs records
3. **SQLite inaccessible** : permissions, disque plein

### Recovery
- API KO → relancer plus tard (l'agent est idempotent)
- Schema brisé → investiguer via `cli schema` pour voir les champs actuels,
  patcher `FIELD_MAP` dans `normalize.py`
- DB corrompue → restaurer depuis l'export JSON du dernier fetch

## Intégration dans le pipeline

```
  ┌─────────────────────────┐
  │  API RappelConso V2     │  ← source externe publique
  └───────────┬─────────────┘
              │ HTTP GET /records (paginé)
              ▼
  ┌─────────────────────────┐
  │  VEILLEUR_INCIDENTS     │
  │  (cet agent)            │
  │                         │
  │  fetch → normalize →    │
  │  upsert → export        │
  └───────────┬─────────────┘
              │ écrit
              ▼
       incidents.sqlite
              │
              ├────────────────► Agent 2 (evaluateur_severite)
              ├────────────────► Agent 3 (enrichisseur_prospects)
              ├────────────────► Agent 4 (detecteur_signaux — pour brand_known & crossref)
              └────────────────► dashboard_reflex (page Radar)
```

## Fréquence recommandée

| Contexte | Fréquence | Paramètres |
|---|---|---|
| Veille quotidienne (recommandé) | 1×/jour | `--since-days 2 --categorie alimentation` |
| Démo / rattrapage | 1 run | `--since-days 90 --categorie alimentation` |
| Debug | Au besoin | `--max-records 5 -v` |

## Non-objectifs explicites

- **Pas de scoring** : le rôle de l'Agent 2
- **Pas d'enrichissement entreprise** : le rôle de l'Agent 3
- **Pas de déduplication sémantique** : un "même" rappel reçu sur 2 IDs API
  différents crée 2 rows — c'est intentionnel (fidélité à la source)
- **Pas de filtrage métier** : tout record qui correspond à la requête ODSQL
  est stocké, sans interprétation
