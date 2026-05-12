# Sous-cadrage — SignalConso comme détecteur de volumes anormaux

**Date** : 2026-04-27
**Statut** : sous-cadrage, complète `cadrage_v2_sources.md`
**Périmètre** : pivot du collector SignalConso après découverte du schéma réel
de l'API ODS publique.

---

## 1. Pourquoi un pivot

Le cadrage initial (cf. `cadrage_v2_sources.md` §3) supposait que l'API ODS
publique de SignalConso exposait le **texte libre du signalement**, le **nom
de l'entreprise** et le **SIRET**. Le `discover_schema()` du 2026-04-27
révèle que c'est faux.

Champs réellement publiés (15 colonnes, voir `fields_from_meta`) :

| Champ | Type | Utilité |
|---|---|---|
| `id` | text | UUID du signalement |
| `category` | text (array) | Catégorie en CamelCase compact (ex: `BanqueAssuranceMutuelle`) |
| `subcategories` | text (array) | Sous-catégories |
| `creationdate` | date | Date du signalement |
| `tags` | text (array) | Tags libres (ex: `Internet`) |
| `dep_code` / `dep_name` | text | Département |
| `reg_code` / `reg_name` | text | Région |
| `signalement_transmis` | int | 0/1 — flag workflow |
| `signalement_lu` | int | 0/1 — flag workflow |
| `signalement_reponse` | int | 0/1 — flag workflow |
| `status` | text | État du dossier |
| `forwardtoreponseconso` | text | Routage interne |
| `contactagreement` | text | Consentement contact |

**Aucun texte libre, aucun nom d'entreprise, aucun SIRET.**

Conséquence : la stratégie « 1 signalement → 1 `SignalSource` avec marque
extraite » est morte. Pas de marque → pas de cross-ref avec un incident →
pas de prospection commerciale derrière.

Mais la donnée garde de la valeur : `(catégorie, département, date)` permet
un **détecteur d'anomalies de volume**. Une TIAC locale ou un produit
alimentaire défectueux distribué dans une zone géo génère typiquement un
spike de signalements concentré sur 1-2 départements en quelques jours.

---

## 2. Nouveau modèle de signal

### Avant (modèle abandonné)

```
1 signalement individuel → 1 SignalSource avec marque/symptome/contenu textuel
```

### Après (modèle volumes)

```
N signalements agrégés sur (catégorie, département, fenêtre récente)
  → comparaison avec baseline historique sur même couple
  → 1 SignalSource si écart statistiquement significatif
```

### Caractéristiques du `SignalSource` produit

| Champ | Valeur |
|---|---|
| `source_type` | `"signalconso_volume"` (bucket distinct du source_type initial) |
| `source_name` | `"SignalConso/<Categorie>/<dep_name>"` |
| `source_url` | `"signalconso://stats/<cat>/<dep_code>/<YYYY-WW>"` (clé de dédup) |
| `titre` | `"Pic signalements <Categorie> en <dep_name> (N actuels, baseline ~M)"` |
| `detected_at` | début de la fenêtre récente (lundi de la semaine ISO) |
| `contenu` | JSON sérialisé avec : `count_actuel`, `baseline_median`, `baseline_mad`, `z_score_modifie`, `top_subcategories[]`, `top_tags[]` |

**Pas de champ marque/produit/symptôme natif** — ce sera reconstitué
artificiellement à la promotion en signal final (cf. §6).

---

## 3. Architecture du collector v2

### 3.1 Stratégie d'agrégation côté ODS

Plutôt que de fetcher tous les records et d'agréger en local (1.7M lignes
côté Python = inutile), on délègue l'agrégation à ODS via `group_by` +
`select` sur l'endpoint records :

```
GET /api/explore/v2.1/catalog/datasets/signalconso/records
    ?select=category, dep_code, dep_name, count(*) as n
    &where=category="<X>" AND creationdate>='YYYY-MM-DD' AND creationdate<'YYYY-MM-DD'
    &group_by=category, dep_code, dep_name, year(creationdate), week(creationdate)
    &limit=<assez grand>
```

Une seule requête par fenêtre temporelle ramène un tableau `(cat, dept, semaine, count)`.

À valider en POC : la syntaxe `year(...)`, `week(...)` exacte d'ODSQL — la
doc dit `date_format(creationdate, 'YYYY-WW')` ou similaire. Si KO, on
fait le bucketing temporel côté Python à partir des records bruts agrégés
par jour.

### 3.2 Calcul de la baseline

**Fenêtre courante** : 7 derniers jours (semaine ISO N).
**Fenêtre baseline** : 12 semaines précédentes (N-13 à N-1).
**Granularité** : 1 ligne par `(category, dep_code, semaine)`.

**Statistique** : médiane + MAD (Median Absolute Deviation) plutôt que
moyenne + stddev. Raisons :
- Comptages discrets souvent non-gaussiens
- Robuste aux outliers (un pic ancien ne fausse pas la baseline future)
- 12 points = peu, MAD plus stable que stddev avec peu de samples

**Score d'anomalie** : z-score modifié d'Iglewicz-Hoaglin :

```
z_mod = 0.6745 * (count_actuel - median(baseline)) / MAD(baseline)
```

**Seuil** : `z_mod >= 3.5` → signal émis. (Convention statistique standard.)

**Garde-fou volumes faibles** : si `median(baseline) < 5`, on n'émet pas
de signal — bruit trop élevé sur petits nombres. Ajustable.

### 3.3 Filtre catégories

Les catégories alimentaires/cosmétiques sur SignalConso sont en CamelCase
compact. Liste à confirmer via un facet sur `category` (à relancer car
le 1er essai a retourné `[]` — peut-être paramètre `facets` au pluriel ou
endpoint `/aggregates`).

Hypothèse à vérifier (catégories probables d'après la nomenclature DGCCRF) :

- `Alimentation`
- `IntoxicationAlimentaire`
- `ProduitsCosmetiques` ou `Cosmetiques`

À confirmer en relançant le `discover_schema` enrichi (un patch à venir
pour debugguer le facet vide).

### 3.4 Pseudo-code

```python
def collect(cfg):
    # 1. Fetch agrégés baseline (12 sem) + fenêtre actuelle (1 sem)
    baseline = fetch_aggregated(weeks=12, offset_weeks=1, categories=cfg.signalconso_categories)
    current  = fetch_aggregated(weeks=1,  offset_weeks=0, categories=cfg.signalconso_categories)

    # 2. Group by (category, dep_code)
    by_pair = group_by_cat_dept(baseline)
    actuals = group_by_cat_dept(current)

    # 3. Pour chaque pair présent dans actuals :
    for (cat, dept), count_actuel in actuals.items():
        history = by_pair.get((cat, dept), [])
        if len(history) < 6 or median(history) < 5:
            continue
        z = 0.6745 * (count_actuel - median(history)) / mad(history)
        if z >= 3.5:
            yield make_signal_source(cat, dept, count_actuel, history, z)
```

---

## 4. Bypass de l'extracteur LLM

Le pipeline actuel dans `detecteur.run_detect()` appelle `extract()` sur
chaque `SignalSource`, qui sort `is_alim`, `marque`, `symptome`, etc.

Pour `source_type == "signalconso_volume"` :

- L'extracteur n'a pas de texte exploitable
- Appeler le LLM = perte de tokens et résultats incohérents

**Patch à apporter dans `detecteur.run_detect()`** :

```python
if src.source_type == "signalconso_volume":
    # Bypass extracteur — on synthétise les champs depuis la donnée structurée.
    extracted = ExtractionResult(
        is_alim=True,                            # implicite si filtré côté collector
        marque=None,                             # pas de marque dispo
        produit=None,
        symptome=_derive_symptom_from_category(src.titre),  # mapping cat → label
        resume=src.titre,
        source="signalconso_volume",
    )
else:
    extracted = extract(...)  # comportement existant
```

Avec un mapping `category → symptome_label` dans `signalconso_volumes.py` :

```python
CATEGORY_TO_SYMPTOM = {
    "Alimentation": "anomalie_alimentaire_locale",
    "IntoxicationAlimentaire": "intoxication_alimentaire_collective",
    "Cosmetiques": "anomalie_cosmetique_locale",
    # ...
}
```

---

## 5. Dédup

Granularité naturelle : 1 signal unique par `(category, dep_code, YYYY-WW)`.
Si le pic dure 3 semaines consécutives, on a 3 signaux distincts (cohérent
avec la dédup actuelle qui est journalière → on étend mentalement à
hebdomadaire pour ce bucket).

`source_url` = `"signalconso://stats/<cat>/<dep_code>/<YYYY-WW>"` joue le
rôle de clé naturelle dans `signaux_sources` — empêche la double ingestion
si le collector tourne 2x dans la même semaine.

`signal_id` calculé par `compute_signal_id()` actuel : marque vide +
symptome (du mapping cat→symptome) + jour → ça produira des collisions
entre départements si on émet 5 signaux le même jour pour la même
catégorie. **Adaptation requise** : injecter `dep_code` dans la
construction du `signal_id` quand `source_type == "signalconso_volume"`.

À faire dans `deduplicator.py` :

```python
def compute_signal_id(*, marque, symptome, titre, detected_at, produit, dep_code=None):
    parts = [_norm(marque), _norm(symptome), date_bucket]
    if dep_code:
        parts.append(dep_code)
    return _hash("|".join(parts))[:16]
```

Et signaler depuis le collector (via un champ ajouté au `SignalSource` ?
ou via un override calculé côté `detecteur.run_detect`).

**Décision pragmatique** : le collector calcule lui-même un `signal_id`
custom et le stocke dans un champ `forced_signal_id` de `SignalSource`
(à ajouter au dataclass), et `run_detect` l'utilise s'il est présent.
Évite de complexifier `compute_signal_id`.

---

## 6. Scoring du signal volume

Le scoring actuel (`scorer.compute_score`) combine :
- `source_weight` (poids du média)
- `recurrence` (nombre de sources distinctes)
- `recency` (fraîcheur)
- `brand_known` (marque dans `incidents.sqlite`)
- `sentiment` (mots négatifs)

Pour le bucket `signalconso_volume`, plusieurs ne marchent pas :
- `recurrence` : 1 collector = 1 source par défaut → toujours 10
- `brand_known` : pas de marque
- `sentiment` : pas de texte libre

**Stratégie** : pour ce bucket, on remplace le scoring standard par un
score dérivé directement du `z_mod` :

```
score = clip(20 + 15 * (z_mod - 3.5), 20, 100)
```

- `z_mod = 3.5` → score 20 (juste au seuil)
- `z_mod = 5.0` → score 42
- `z_mod = 8.0` → score 87
- `z_mod >= 9.5` → cap à 100

`source_weight` reste à 12 (poids modeste = ce n'est pas un événement
confirmé), mais le score final fait foi via `status_for_score`.

`SOURCE_WEIGHTS["signalconso"] = 12` reste cohérent (on garde l'entrée).

---

## 7. Cross-référence avec incidents

Le crossref actuel (`cross_reference.py`) score sur 4 dimensions :
`brand_match` (40%), `symptom_match` (30%), `product_match` (20%),
`date_proximity` (10%).

Pour un signal `signalconso_volume`, `brand_match` et `product_match`
sortent KO d'office (champs vides). Si on garde le scoring tel quel, le
score max plafonne à 40% (`symptom` + `date`) → en dessous du seuil "Fort"
de 0.70.

**Adaptation** : pour les pairs où signal.source_type contient `volume`,
remplacer la pondération :

```python
WEIGHTS_VOLUME_VARIANT = {
    "geo_match":      0.40,  # nouveau : signal.dep_code ↔ incident.zone_geo
    "symptom_match":  0.30,
    "category_match": 0.20,  # signal.category ↔ incident.categorie
    "date_proximity": 0.10,
}
```

**Problème** : `incidents.sqlite` n'a pas de champ département stable.
Les colonnes utiles sont `distributeurs` (texte libre) et `geo` éventuel.
Plusieurs options :

a) **MVP V1** : on n'active pas le crossref pour `signalconso_volume`.
   Le signal apparaît côté dashboard mais sans match incident. Le commercial
   regarde le département et fait son propre lien manuellement.

b) **V2** : enrichir `incidents.sqlite` avec un champ `dep_codes` extrait
   du texte des distributeurs (Carrefour Rochefort 17 → `["17"]`). Lourd.

c) **V2 alternatif** : crossref sur la catégorie produit + date seulement,
   ignorer la géo. Score plus faible mais signal "à investiguer" reste utile.

**Reco V1 : option (a)** — pas de crossref auto pour ce bucket. Section
ouverte pour V2.

---

## 8. Impact sur les autres composants

### `models.py`
- Ajouter `forced_signal_id: Optional[str] = None` au dataclass `SignalSource`
- `source_type` accepte `"signalconso_volume"`

### `detecteur.run_detect()`
- Bypass extracteur si `src.source_type == "signalconso_volume"`
- Utiliser `src.forced_signal_id` si présent (avant `compute_signal_id`)
- Bypass scoring standard, utiliser `_score_volume_signal()` à la place

### `keywords.py`
- `SOURCE_WEIGHTS["signalconso"]` reste à 12 (utilisé pour les rares cas
  où le scoring standard tourne quand même)

### `sources/signalconso.py`
- **Réécrire intégralement** le collector — l'actuel produit 1 signal/record,
  le nouveau produit 1 signal/anomalie
- Helpers : `_fetch_aggregated`, `_compute_baseline_stats`, `_make_volume_signal`
- Garder `discover_schema()` tel quel (utile pour debug futur)

### `cross_reference.py`
- Skip `signalconso_volume` en V1 (early return dans la fonction de match)
- Slot prévu pour la variante de pondération en V2

### Tests
- Suite de tests réécrite : pas de `_FAKE_PAYLOAD_PAGE_1` typé "1 record =
  1 signal" mais des fixtures agrégées
- Couverture : calcul z-score, seuil, dedup par dep_code, bypass extracteur

---

## 9. Plan d'implémentation phasé

### Étape 1 — Re-discover catégories (1h)
- Patch `discover_schema` pour utiliser le bon paramètre facet (probable
  `facets[]=category` au pluriel, ou endpoint dédié `/aggregates`)
- Lancer côté Windows, identifier les vraies valeurs CamelCase pour
  Alimentation / Cosmétiques / IntoxicationAlimentaire

### Étape 2 — Réécriture collector (1.5j)
- `signalconso_volumes.py` (rename ou nouveau fichier ; je propose nouveau
  pour garder `signalconso.py` en historique au cas où l'API privée
  débloquerait du textuel plus tard)
- `_fetch_aggregated()` avec `group_by` ODS
- `_compute_baseline_stats()` median + MAD
- `_make_volume_signal()` qui produit le `SignalSource`
- `@register("signalconso_volume")`

### Étape 3 — Adaptations pipeline (0.5j)
- Patch `models.py` (ajout `forced_signal_id`)
- Patch `detecteur.run_detect()` (bypass extracteur + scoring)
- Patch `cross_reference.py` (skip ce bucket)

### Étape 4 — Tests (0.5j)
- Cassettes JSON simulant des données agrégées avec / sans pic
- Tests calcul z-score, seuils, dedup
- Tests intégration end-to-end via mock session

### Étape 5 — Validation prod (1h)
- Run réel sur 12 semaines historique + dernière semaine
- Inspection manuelle des signaux émis
- Calibration éventuelle du seuil `z_mod` (3.5 → 4.0 si trop bruyant)

**Total : ~3 jours**

---

## 10. Décisions actées (2026-04-27)

1. **Granularité temporelle** : hebdo ISO. Fenêtre courante = 7 derniers
   jours, baseline = 12 semaines précédentes.
2. **Seuil** : `z_mod = 3.5` (standard), recalibrage après observation.
3. **Crossref V1** : skip total. Le commercial voit le pic au dashboard
   et fait son lien manuel. Pas de match auto pour ce bucket.
4. **Nom du bucket** : `signalconso_volume`.
5. **Module** : on **réécrit `signalconso.py` en place**. La fonction
   `discover_schema()` reste dans le même fichier (utile pour
   diagnostic futur). L'ancien collector record-by-record est supprimé.

---

## 11. Risques

- **Volumétrie API** : 1.7M records globaux mais agrégation côté serveur
  via `group_by` → quelques requêtes max. Faible risque si ODS supporte
  `group_by` correctement, à valider en POC.
- **Stabilité de la baseline** : 12 semaines pour des couples `(cat, dept)`
  rares peuvent donner des baselines bruitées. Le garde-fou
  `median >= 5` les écarte mais réduit le rappel.
- **Saisonnalité ignorée** : un pic réel l'été (vacances, intoxications
  estivales) peut produire des faux positifs si la baseline tombe sur des
  semaines hors-saison. Solution V2 : baseline saisonnière (mêmes semaines
  l'an dernier).
- **Faux positifs sur dept à faible population** : un dept qui passe de
  2 à 8 signalements donne un gros z-score mais pas de TIAC réelle. Le
  garde-fou `median >= 5` mitige mais ne supprime pas.

---

## 12. Décisions techniques actées (2026-04-27)

1. Choix §10 validés (cf. ci-dessus).
2. **`SignalSource.forced_signal_id`** ajouté (champ `Optional[str]` avec
   default `None`). Le collector volume injecte son id custom incluant
   `dep_code`. `detecteur.run_detect` lit ce champ s'il est présent et
   bypass `compute_signal_id`.
3. **Statistique** : médiane + MAD (Median Absolute Deviation), avec
   z-score modifié d'Iglewicz-Hoaglin. Robuste aux outliers historiques.
4. **Score de signal volume** : calculé côté collector et stocké dans
   `contenu` JSON (clé `z_mod`). `detecteur.run_detect` détecte
   `source_type == "signalconso_volume"` et applique
   `score = clip(20 + 15*(z_mod - 3.5), 20, 100)` au lieu du scoring
   standard. Pas besoin d'ajouter `forced_score` au dataclass.
