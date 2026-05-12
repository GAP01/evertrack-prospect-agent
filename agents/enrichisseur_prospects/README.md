# enrichisseur_prospects — Agent 3 EverTrack

Enrichit les incidents RappelConso avec les données d'entreprise (SIREN, contact dirigeant)
en matchant le nom de marque contre la base SIRENE/INSEE.

## Pipeline

```
incidents.sqlite
    └─► normalizer     marque brute → requête propre
    └─► api_sirene     recherche-entreprises.api.gouv.fr (gratuit, sans auth)
    └─► matcher        confidence + match_status
    └─► api_pappers    contact dirigeant (si PAPPERS_API_KEY définie)
    └─► storage        enrichissements.sqlite
```

## Installation

```bash
cd agents/
pip install -r enrichisseur_prospects/requirements.txt
```

## Variables d'environnement

Copiez `.env.example` en `.env` à la racine du dossier `agents/` :

```bash
# Optionnel — SIRENE fonctionne sans clé
SIRENE_API_TOKEN=

# Contact dirigeants (optionnel, freemium)
PAPPERS_API_KEY=your_key_here

# Contact dirigeants alternatif (optionnel, payant)
SOCIETECOM_API_KEY=your_key_here
```

## Usage

```bash
cd agents/

# Enrichir tous les incidents non encore traités
python -m enrichisseur_prospects.cli enrich

# Enrichir seulement 10 incidents (test)
python -m enrichisseur_prospects.cli enrich --max 10

# Forcer le ré-enrichissement complet
python -m enrichisseur_prospects.cli enrich --reenrich

# Détail d'un incident
python -m enrichisseur_prospects.cli show 2026-04-0196

# Stats de couverture
python -m enrichisseur_prospects.cli stats

# Options communes
python -m enrichisseur_prospects.cli enrich -v  # logs détaillés
python -m enrichisseur_prospects.cli stats --format json
```

## Match status

| Statut | Signification |
|---|---|
| `found` | Confidence ≥ 0.72 — entreprise identifiée avec confiance |
| `ambiguous` | 0.40 ≤ confidence < 0.72 — candidat probable, à vérifier |
| `not_found` | Aucun candidat suffisamment proche |
| `skipped` | Marque inutilisable ("sans marque", "-", trop courte) |

## Base de données

`data/enrichissements.sqlite` — table `enrichissements` :

- Clé primaire : `(source, source_id, enricher_version)`
- Versionné : un bump de version permet de ré-enrichir sans perte historique
- Champs SIRENE : siren, siret_siege, raison_sociale, forme_juridique, code_naf, adresse, effectif_tranche
- Champs contact : contact_nom, contact_titre, contact_source

## Ajouter societe.com ou Pappers

1. Définir `SOCIETECOM_API_KEY` ou `PAPPERS_API_KEY` dans `.env`
2. Implémenter la méthode `get_by_siren()` dans `api_societecom.py` / `api_pappers.py`
3. Le `matcher.py` branchera automatiquement la source configurée après SIRENE
