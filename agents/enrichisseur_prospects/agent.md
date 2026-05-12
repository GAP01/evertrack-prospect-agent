# Agent — Enrichisseur de prospects

## Identité

- **Nom** : `enrichisseur_prospects`
- **Position** : Agent 3 (en parallèle d'Agent 2, consomme Agent 1)
- **Version** : v0.1 (`ENRICHER_VERSION`)
- **Type** : Agent d'enrichissement (batch, stateful, API-bound)

## Objectif

Transformer une marque produit brute (ex: `"Carrefour"`, `"Lustucru"`) en
**entreprise française identifiée** (SIREN + raison sociale + activité NAF +
contact opérationnel), pour permettre la prospection commerciale ciblée
post-rappel.

Le **contact** ciblé n'est pas le dirigeant légal mais un profil
**opérationnel** (qualité, supply chain, conformité). Fallback sur dirigeant
si pas de profil cible trouvé.

## Inputs

| Input | Source | Notes |
|---|---|---|
| Incidents à enrichir | `data/incidents.sqlite` | Table `incidents` |
| Mode rescore | CLI `--reenrich` | Force recalcul même si déjà enrichi |
| Limite | CLI `--max N` | Budget API / debug |
| `PAPPERS_API_KEY` | `.env` | Optionnelle (améliore le contact si dispo) |
| `SOCIETECOM_API_KEY` | `.env` | Optionnelle (stub, non implémenté) |

### Champs d'incident utilisés

| Champ | Usage |
|---|---|
| `marque` | Requête principale SIRENE (après normalisation) |
| `distributeurs` | Fallback si `marque` est inutilisable (générique ou vide) |
| `source`, `source_id` | Clé de sortie |

## Outputs

| Output | Format | Consommateurs |
|---|---|---|
| `data/enrichissements.sqlite` | SQLite, table `enrichissements` | dashboard_reflex (page Prospects), futur Agent 5 (outreach) |
| Rapport CLI | JSON stdout | Humain |

### Ligne type d'`enrichissements`
```
source, source_id, enricher_version  : clé composite
marque_input                         : "Lustucru" (brut)
query_used                           : "lustucru" (normalisé)
match_status                         : found | ambiguous | not_found | skipped
confidence                           : 0.87
siren, siret_siege, raison_sociale   : "572091158" / "..." / "Lustucru Sélection SAS"
forme_juridique, code_naf, libelle_naf, adresse
effectif_tranche, categorie_entreprise : "500-999" / "ETI"
contact_nom, contact_titre           : "Dupont Jean" / "Directeur Supply Chain"
contact_source                       : sirene | pappers | societecom
contact_type                         : cible | fallback_dirigeant
api_used                             : "sirene" | "sirene+pappers"
enriched_at, raw_json
```

### Rapport CLI exemple
```json
{
  "incidents_total": 127,
  "to_enrich": 42,
  "enriched": 42,
  "by_status": {"found": 21, "ambiguous": 8, "not_found": 10, "skipped": 3},
  "with_contact": 25,
  "with_cible": 2,
  "enricher_version": "v0.1"
}
```

## Déclencheurs

1. **Manuel** : `python -m enrichisseur_prospects.cli enrich [--reenrich] [--max N]`
2. **Pas de bouton dashboard** (pour l'instant) — lancement CLI uniquement
3. **Post-fetch Veilleur** (pattern recommandé) : chaîner manuellement

Pas d'auto-trigger.

## Dépendances vers les autres agents

| Agent | Type | Pourquoi |
|---|---|---|
| `veilleur_incidents` (Agent 1) | **Amont bloquant** | Lit `incidents.sqlite` |
| Aucun amont optionnel | — | — |
| Aucun aval obligatoire | — | Agent 5 (outreach) pourra consommer si créé |

L'agent **ne dépend pas** de Agent 2 (scoring) — les deux tournent en parallèle.

## Dépendances externes

| Système | Criticité | Comportement si KO |
|---|---|---|
| API SIRENE (`recherche-entreprises.api.gouv.fr`) | **Bloquant** (source primaire) | `SireneAPIError` → match_status `not_found` |
| API Pappers (`api.pappers.fr/v2`) | **Non bloquant** | Warning + contact SIRENE conservé |
| API societe.com | **Non bloquant** | Stub, lève `NotImplementedError` |
| `incidents.sqlite` existant | **Bloquant** | Erreur SQLite propagée |
| Réseau internet | **Bloquant** pour SIRENE | — |

### Statut actuel des APIs
- **SIRENE** : ✅ opérationnelle, gratuite, sans auth
- **Pappers** : ⚠️ retourne 401 avec la clé actuelle (à investiguer côté compte)
- **societe.com** : 🚧 stub prêt, pas de clé

## Comportement attendu

### Mode par défaut : `only_new=True`
- Saute les incidents déjà enrichis pour la `enricher_version` courante
- Évite le re-scraping SIRENE (quotas, courtoisie)

### Mode `--reenrich`
- Ré-enrichit tous les incidents (pas de skip)
- Utile après changement de seuils ou ajout de source

### Pipeline par incident (`match_incident`)

```
1. normalize_marque(marque)
   └─► None (générique ou vide)
       ↓
2. normalize_distributeur(distributeurs)  ← fallback
   └─► None (rien d'exploitable)
       ↓
       → match_status = "skipped" (fin)

3. SireneClient.search(query, nombre=5)
   └─► Exception → match_status = "not_found" (avec api_used="sirene")

4. _best_candidate(query, results) → (best, confidence 0-1)
   └─► confidence >= 0.72 → "found"
       confidence >= 0.40 → "ambiguous"
       sinon               → "not_found"

5. Si found|ambiguous + Pappers dispo :
       pappers.get_by_siren(siren) → override du contact si succès
```

### Conservation "not_found"
Même si SIRENE ne trouve rien, une ligne est persistée avec `marque_input` et
`query_used` → permet l'audit et évite de re-requêter inutilement.

### Isolation d'erreurs
Une exception sur un incident est loggée (`logger.exception`) et n'arrête
pas le batch.

## Conditions de succès

L'agent réussit si :
1. `incidents.sqlite` est lisible
2. Chaque incident a été traité (même si `skipped` ou `not_found`)
3. La base `enrichissements.sqlite` contient une ligne par incident traité

## Conditions d'échec

| Cas | Traitement |
|---|---|
| `incidents.sqlite` absente | Erreur SQLite propagée |
| `enrichissements.sqlite` verrouillée | Exception propagée |
| API SIRENE KO réseau | Incident marqué `not_found`, batch continue |
| API Pappers 401 | Warning, contact SIRENE conservé |
| Crash inattendu sur un incident | Log + continue |

## Intégration dans le pipeline

```
  ┌───────────────────────┐
  │  incidents.sqlite     │  ← Agent 1
  └──────────┬────────────┘
             │ SELECT (filtrage only_new)
             ▼
  ┌──────────────────────────┐
  │  ENRICHISSEUR_PROSPECTS  │  ← cet agent
  │                          │
  │  normalize → SIRENE →    │
  │    confidence scoring →  │
  │    Pappers (optionnel)   │
  └──────────┬───────────────┘
             │ upsert
             ▼
    enrichissements.sqlite
             │
             ├──► dashboard_reflex (page Prospects)
             └──► futur Agent 5 outreach
```

### Position relative
- **Parallèle** avec Agent 2 (scoring) — pas de dépendance
- **Amont futur** d'Agent 5 (rédaction outreach) — fournit le contact à personaliser

## Seuils de décision

### Confidence (matching marque ↔ raison sociale)

| Seuil | `match_status` | Action |
|---|---|---|
| ≥ 0.72 (`CONFIDENCE_FOUND`) | `found` | Contact extrait, affiché comme match fort |
| 0.40-0.72 (`CONFIDENCE_AMBIGUOUS`) | `ambiguous` | Contact extrait, affiché en jaune pour review humain |
| < 0.40 | `not_found` | Pas de contact, ligne vide |

### Bonus substring
`+0.15` si la query normalisée est un sous-ensemble strict de la raison sociale
(ex: query=`"lustucru"` ⊂ `"lustucru sélection sas"`). Capé à 1.0.

## Fréquence recommandée

| Contexte | Fréquence | Paramètres |
|---|---|---|
| Après chaque fetch Veilleur | Automatique | `enrich` (only_new) |
| Nouveau corpus de marques (import client) | À la demande | `enrich --reenrich` |
| Debug single incident | À la demande | modifier `--max 1` + `show` |

## Non-objectifs explicites

- **Pas de scraping web** : uniquement APIs JSON structurées
- **Pas de téléphone ni email** : juste nom + titre du contact (pour l'instant)
- **Pas de scoring du prospect** : agent d'identification seul, pas d'évaluation
  commerciale (chiffre d'affaires, taille…)
- **Pas d'enrichissement à l'étranger** : SIRENE = France uniquement
- **Pas de création de compte CRM** : push vers Sellsy = agent séparé à créer
- **Pas de fuzzy matching cross-marques** : chaque marque est traitée isolément
  (pas de "marques proches de X")
