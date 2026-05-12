# Veilleur d'incidents — Agent 1 (POC)

Premier agent du système EverTrack. Récupère chaque matin les incidents produits publiés sur **RappelConso** (data.economie.gouv.fr), les normalise, les stocke, et exporte un JSON inspectable.

Pilote : filtrage sur la catégorie *Alimentation* (France).

## Structure

```
veilleur_incidents/
├── __init__.py
├── api_client.py      # Client Opendatasoft Explore v2.1
├── normalize.py       # Record brut -> Incident normalisé
├── models.py          # Dataclass Incident
├── storage.py         # Persistance SQLite (dédoublonnage automatique)
├── veilleur.py        # Orchestrateur du pipeline
├── cli.py             # Interface ligne de commande
├── requirements.txt
└── tests/
    └── test_pipeline.py
```

## Installation

Depuis `agents/` :

```bash
python -m venv .venv
source .venv/bin/activate          # (sous Windows : .venv\Scripts\activate)
pip install -r veilleur_incidents/requirements.txt
```

## Utilisation

```bash
# Récupérer les incidents alimentaires des 7 derniers jours
python -m veilleur_incidents.cli fetch

# Fenêtre personnalisée, max 20 incidents, tous secteurs
python -m veilleur_incidents.cli fetch --since-days 14 --categorie "" --max-records 20

# Lister les 10 plus récents en base
python -m veilleur_incidents.cli list --limit 10

# Lister au format JSON
python -m veilleur_incidents.cli list --format json
```

La base SQLite par défaut est `data/incidents.sqlite`, l'export JSON par défaut `data/incidents_last_fetch.json` — surchargeables via `--db` et `--export`.

## Tests

Sans accès réseau, on peut valider le pipeline avec des records fictifs :

```bash
python -m veilleur_incidents.tests.test_pipeline
```

## Comportement

- **Idempotent** : relancer `fetch` ne crée pas de doublons (clé composite `source, source_id`). Les incidents déjà vus voient leur `last_seen_at` rafraîchi.
- **Tolérant au schéma** : chaque record brut est conservé dans `raw_json`. Si RappelConso renomme un champ, seule la partie normalisation est à ajuster ; l'historique reste intact.
- **Filtres combinables** : fenêtre temporelle (via `date_de_publication`) + facette catégorie via `refine`.

## À valider côté Gautier (bloqué dans le sandbox Cowork)

L'API `data.economie.gouv.fr` n'est pas joignable depuis l'environnement où le code a été écrit. Donc **premier vrai test** à faire côté machine locale :

```bash
python -m veilleur_incidents.cli fetch --since-days 7 --max-records 5 -v
```

Trois choses à vérifier sur la sortie :

1. L'appel HTTP retourne 200. Si 404/400, vérifier le dataset id dans `api_client.py` — on cible `rappelconso-v2-gtin-espaces`.
2. Les champs normalisés sont corrects (marque, motif, date). Si plusieurs champs sont `None`, regarder `raw_json` et ajuster `FIELD_MAP` dans `normalize.py`.
3. `refine=categorie_de_produit:Alimentation` remonte bien des résultats. Le libellé exact peut différer (par exemple `Alimentation` vs `Aliments`) — tester sans filtre (`--categorie ""`) si zéro résultat.

## Dette assumée pour le POC

- Pas encore de connecteur RASFF (Europe). Prévu en v2 une fois le pilote validé.
- Logging basique (stdout). Pas de fichier de logs rotatif.
- Pas de configuration externe (YAML / `.env`). Tous les paramètres passent par la CLI.
- Pas encore packagé (`pyproject.toml`) — volontairement minimal tant qu'on itère.

## Prochaine étape

Agent 2 — Évaluateur de sévérité : score chaque incident fraîchement fetché sur des critères explicables (risque sanitaire, ampleur, médiatisation, taille de la société touchée). Sortie : un top N quotidien à présenter au commercial.
