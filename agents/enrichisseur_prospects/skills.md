# Compétences — Enrichisseur de prospects

Ce que l'agent **sait faire** pour transformer une marque en prospect qualifié.

## 1. Normalisation de marque (règles intelligentes)

### Suppression des formes juridiques
`normalizer.py` reconnaît et strip :
```
SAS, S.A.S, SASU, SARL, S.A.R.L, SA, S.A, EURL, SNC, SCS, SC, SCEA, SCS,
GIE, GAEC, SELARL, SEL, SCI, SCP, SCOP, EIRL, EI, Société (coopérative),
Holding, Groupe, Group
```

### Suppression des stop-words
```
France, International, Europe, Holdings, Industries, Distribution, Trading,
Services, Participations, Finance, Capital, Investissements, ...
```

### Strip d'accents + ponctuation
- `unicodedata.normalize("NFD")` + filter combining marks
- Regex `[^a-z0-9 ]+` → `" "`
- Collapse whitespace

### Détection de marques génériques (→ `None`)
Retourne `None` (skip) si la marque est :
- `"sans marque"`, `"sans marques"`, `"-"`, `"n/a"`, `"divers"`
- Vide ou < 2 caractères après normalisation

### Fallback sur distributeur
Si `marque` est inutilisable, tente `normalize_distributeur(distributeurs)` :
- Split sur `|`, `,`, `¤` (séparateurs rencontrés dans RappelConso V2)
- Prend la 1re valeur non-générique
- Applique la même normalisation

## 2. Appel API SIRENE (data.gouv.fr)

### API maîtrisée
- **URL** : `https://recherche-entreprises.api.gouv.fr/search`
- **Pas d'auth** requise
- **Timeout** : 10s
- **Limite raisonnable** : `nombre=5` (top 5 candidats)

### Données extraites (`extract_company_fields`)
| Champ sortie | Source API |
|---|---|
| `siren` | `result.siren` |
| `siret_siege` | `result.siege.siret` |
| `raison_sociale` | `result.nom_complet` \|\| `result.nom_raison_sociale` |
| `forme_juridique` | `result.libelle_nature_juridique` |
| `code_naf` | `result.activite_principale` |
| `libelle_naf` | `result.libelle_activite_principale` |
| `adresse` | concat `numero_voie + type_voie + libelle_voie + code_postal + libelle_commune` |
| `effectif_tranche` | `result.tranche_effectif_salarie` → libellé via `TRANCHE_EFFECTIF` dict |
| `categorie_entreprise` | `result.categorie_entreprise` (PME / ETI / GE) |
| `dirigeants` | liste bruts pour `select_best_contact` |

### Lookup par SIREN (`get_by_siren`)
Utilisé pour re-vérifier après match ambiguous ou pour enrichissement différé.
Renvoie le résultat unique ou `None` si pas trouvé exact.

## 3. Fuzzy matching marque → raison sociale

### Algorithme
```python
ratio = difflib.SequenceMatcher(
    None,
    strip_accents(query.lower()),
    strip_accents(raison.lower()),
).ratio()

if strip_accents(query.lower()) in strip_accents(raison.lower()):
    ratio = min(1.0, ratio + 0.15)  # bonus substring
```

### Sélection du meilleur candidat
Sur les 5 résultats SIRENE, prend celui avec le `ratio` maximal (après bonus).
Pas de filtrage minimum à ce stade — le filtrage se fait sur la confidence
finale.

### Seuils de décision
| Seuil | Statut |
|---|---|
| ≥ 0.72 | `found` |
| 0.40-0.72 | `ambiguous` (à valider humain) |
| < 0.40 | `not_found` |

## 4. Classification de contact (profil métier)

### Règles d'extraction des mots-clés cibles
```python
_TARGET_KEYWORDS = [
    "qualit", "qhse", "hse",
    "supply chain", "supply-chain", "chaine d appro", "approvisionnement", "logistique",
    "conformit", "reglementaire", "regulatory", "compliance",
    "securite alimentaire", "food safety", "securite des produits",
    "rappel", "tracabilit", "traçabilit",
]
```

### Fonction `classify_contact_type(titre)`
Normalise le titre (lower + strip accents) et vérifie présence d'un mot-clé
cible. Retourne :
- `"cible"` → match trouvé
- `"fallback_dirigeant"` → pas de match (ou `titre` vide)

### Sélection dans une liste de dirigeants (`select_best_contact`)

3 passes ordonnées :

**Passe 1 — profil cible**
```python
for d in dirigeants:
    if classify_contact_type(d.qualite) == "cible":
        return d, "cible"
```

**Passe 2 — priorité exécutifs**
```python
priority_order = ["directeur general", "president", "pdg", "gerant", "dg "]
for kw in priority_order:
    for d in dirigeants:
        if kw in normalize(d.qualite):
            return d, "fallback_dirigeant"
```

**Passe 3 — premier de la liste** (garantit un résultat)
```python
return dirigeants[0], "fallback_dirigeant"
```

### Compétence clé : robustesse aux sources
Le `select_best_contact` fonctionne sur n'importe quelle liste de dirigeants
qui expose `qualite` ou `titre` → réutilisable pour SIRENE **et** Pappers.

## 5. Appel API Pappers (v2, freemium)

### API maîtrisée
- **URL** : `https://api.pappers.fr/v2/entreprise`
- **Auth** : `api_token` en query param (ex: `?siren=123&api_token=...`)
- **Clé** : `PAPPERS_API_KEY` dans `.env`
- **Statut actuel** : ⚠️ renvoie 401, à investiguer (plan / activation)

### Graceful degradation
Si Pappers KO (401, timeout, erreur parsing) :
- `PappersAPIError` → caught dans `_enrich_contact_pappers`
- Contact SIRENE conservé (pas d'erreur propagée)
- Warning loggé

### Bénéfice quand ça marche
- Liste de contacts plus fraîche (Pappers se met à jour plus souvent que SIRENE)
- **Potentiellement** des profils non-dirigeants (responsables fonctionnels)
- Permet de passer `contact_type = "cible"` plus souvent

## 6. Assemblage `EnrichissementResult`

### Source de vérité finale
| Champ | Source prioritaire | Fallback |
|---|---|---|
| Identité entreprise | SIRENE | — |
| Effectif, catégorie | SIRENE | — |
| Contact nom/titre | Pappers si dispo ET contact trouvé | SIRENE dirigeants |
| `contact_source` | `"pappers"` ou `"sirene"` | — |
| `contact_type` | calculé via `classify_contact_type` | `"fallback_dirigeant"` |
| `api_used` | `"sirene+pappers"` ou `"sirene"` | `"none"` si skipped |

### Sérialisation `raw_json`
Le résultat SIRENE brut (`best` candidat) est stocké en JSON → audit
ultérieur possible sans re-requête.

## 7. Persistance SQLite avec historique de version

### PK composite
`(source, source_id, enricher_version)` → permet de garder l'historique si on
change la logique d'enrichissement (bump `ENRICHER_VERSION`).

### Migrations maîtrisées
`_MIGRATIONS` gère les `ALTER TABLE ADD COLUMN` idempotents (catch
`OperationalError`) — pattern utilisé pour l'ajout de `contact_type` a
posteriori.

### Index
- `idx_enrich_siren` — lookup par SIREN
- `idx_enrich_status` — filtre par `match_status`
- `idx_enrich_contact_type` — filtre cible vs fallback (pour KPI dashboard)

## 8. Statistiques de couverture (`storage.stats()`)

Agrège pour monitoring :
| Métrique | Calcul |
|---|---|
| `total_enrichis` | `COUNT(DISTINCT source\|\|source_id)` |
| `by_status` | `GROUP BY match_status` |
| `with_contact` | `COUNT WHERE contact_nom IS NOT NULL` |
| (ajouté dashboard) `with_cible` | `COUNT WHERE contact_type = 'cible'` |

Le taux de couverture affiché : `(found + ambiguous) / total * 100` %.

## 9. CLI structurée

| Commande | Capacité |
|---|---|
| `enrich` | Pipeline complet (only_new par défaut) |
| `enrich --reenrich` | Force ré-enrichissement |
| `enrich --max N` | Limite (debug / budget API) |
| `show <source_id>` | Affiche le dernier enrichissement, format texte ou JSON |
| `stats` | Stats globales : total, par statut, coverage |

### Format `show` humain
```
=== Enrichissement : 2026-04-0257 ===
  Marque input   : leclerc
  Match status   : found  (confidence=0.89)
  Raison sociale : E.LECLERC SA
  SIREN          : 642050199
  NAF            : Commerce de détail non alimentaire spécialisé
  Adresse        : 26 Quai Marcel Boyer 94200 Ivry-sur-Seine
  Effectif       : 10 000+
  Contact        : DUPONT Jean — Directeur Supply Chain
  Contact type   : cible
  API utilisee   : sirene+pappers
```

## 10. API societe.com (stub prêt)

Le fichier `api_societecom.py` expose la même interface que Pappers :
- `SocieteComClient(api_key)` lève `SocieteComNotConfiguredError` si pas de clé
- `get_by_siren()` → `NotImplementedError`
- `extract_contact()` → `NotImplementedError`

Pour activer : compléter les 3 méthodes, structure identique à `api_pappers.py`.
L'intégration dans `matcher.py` se fera en parallèle de Pappers.

## Ce que l'agent ne sait PAS faire

- **Pas de web scraping** : que des APIs JSON
- **Pas de resolve email/téléphone** : pas dans SIRENE, pas dans Pappers v2 public
- **Pas de cross-match pays** : SIRENE = France only
- **Pas de scoring du prospect** (CA, taille, potentiel commercial)
- **Pas de notification** des nouveaux enrichissements
- **Pas de déduplication inter-incidents** : si 3 incidents ont la même marque,
  on fait 3 requêtes SIRENE (cache serait une optim future)
- **Pas de correction manuelle** via CLI : pour corriger un enrichissement,
  il faut éditer directement la DB ou relancer avec `--reenrich`
- **Pas de LLM** : 100% règles + APIs structurées (volontaire pour la reproductibilité)
