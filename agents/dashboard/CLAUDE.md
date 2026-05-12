# Dashboard Streamlit (legacy / couche data_access)

## 1. Rôle et responsabilité

**Dashboard historique en Streamlit** — conservé pour son **`data_access.py`**
et **`actions.py`** qui sont réutilisés par le dashboard Reflex moderne.

En pratique, le `dashboard_reflex/` est la version à utiliser pour le front.
Ce dossier agit comme **bibliothèque de lecture/action** sur les SQLite.

## 2. Fichiers principaux

```
dashboard/
├── app.py            # UI Streamlit (legacy — pas maintenu activement)
├── data_access.py    # Lecteur SQLite : stats, top_incidents, get_incident_full…
├── actions.py        # Wrappers pour déclencher fetch/score depuis l'UI
└── requirements.txt
```

| Fichier | Rôle | Utilisé par |
|---|---|---|
| `app.py` | UI Streamlit complète (3 onglets) | Usage local legacy |
| `data_access.py` | Requêtes SQL sur incidents + scores | `dashboard_reflex/services/data.py` |
| `actions.py` | `trigger_fetch(...)`, `trigger_score(...)` | `dashboard_reflex/services/data.py` |

## 3. Fonctions clés de `data_access.py`

```python
def stats(incidents_db, scores_db) -> dict:
    # Renvoie incidents_total, scores_total, last_score_at, by_tier

def top_incidents(incidents_db, scores_db, limit=50, tier=None, sous_categorie=None) -> list[dict]:
    # Top N avec jointure score le plus récent, classé par score DESC

def get_incident_full(incidents_db, scores_db, source, source_id) -> dict:
    # Détail incident + score (dimensions unpacked) pour le drawer

def list_sous_categories(incidents_db) -> list[str]:
    # Pour le filtre du dashboard
```

Les clés retournées par `get_incident_full()` correspondent **exactement**
aux colonnes DB : `motif`, `risques`, `source_url` (pas `motif_rappel`, etc.).

## 4. Fonctions clés de `actions.py`

```python
def trigger_fetch(incidents_db, since_days=7, categorie="alimentation", max_records=None) -> dict:
    # Invoque veilleur_incidents.veilleur.run_fetch → renvoie {fetched, new, updated}

def trigger_score(incidents_db, scores_db, use_llm=True, rescore=False, max_incidents=None) -> dict:
    # Invoque evaluateur_severite.evaluateur.run_score → renvoie {scored_now, llm_used_count, ...}
```

Ces fonctions sont appelées par les boutons "Rafraîchir la veille" et "Scorer
les incidents" dans la sidebar du dashboard Reflex.

## 5. Lancement (legacy)

```bash
cd agents
streamlit run dashboard/app.py
```

**Non recommandé** — utiliser `dashboard_reflex/` à la place.

## 6. Décisions techniques

### Séparation data_access / UI

Le split `data_access.py` / `app.py` a permis de réutiliser la couche data
intacte quand on a migré vers Reflex. Cette séparation doit être **maintenue**.

Toute nouvelle requête SQL sur `incidents.sqlite` ou `scores.sqlite` doit aller
dans `data_access.py`, pas dans les composants frontend.

### PYTHONPATH injection

`app.py` ajoute `agents/` au `sys.path` pour que `veilleur_incidents` et
`evaluateur_severite` soient importables quand lancé via `streamlit run`.
Même pattern dans `dashboard_reflex/services/data.py`.

## 7. À savoir pour toute évolution

- **Ne pas ajouter de nouvelles dépendances Streamlit** : le legacy est stable,
  pas de dev actif prévu.
- **Nouvelles fonctions lecture** : ajoute dans `data_access.py` + expose via
  `dashboard_reflex/services/data.py`.
- **Signaux faibles** : les lectures sur `signaux.sqlite` ne passent **pas** par
  ce module — elles sont directement dans `dashboard_reflex/services/data.py`
  (decisions prise pour isoler les features récentes).
