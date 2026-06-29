# SignalConso — API, données ouvertes et référentiels

*Synthèse à destination métier (non technique) — recherche vérifiée sur sources officielles `.gouv.fr` et dépôts GitHub de l'État.*
*Document de référence EverTrack. Dernière mise à jour : 2026-06-29.*

> **Méthode** : recherche multi-sources avec vérification adversariale (11 sources officielles, 25 affirmations testées en triple-vote, 23 confirmées) ; les référentiels de valeurs sont extraits **en direct de l'API d'exploration** (valeurs réelles + volumes, mai 2026).

---

## 1. En une phrase

SignalConso met ses données à disposition de façon **ouverte, gratuite et réutilisable commercialement** — mais ces données sont **anonymisées** : on voit les *types* de problèmes, les *volumes*, la *géographie* et la *réactivité des entreprises*, **sans jamais voir le nom de l'entreprise signalée**. C'est une mine pour comprendre un marché ; ce n'est pas un annuaire de prospects.

---

## 2. SignalConso ≠ RappelConso

Deux dispositifs **distincts** de la même administration (la DGCCRF) :

| | **SignalConso** | **RappelConso** |
|---|---|---|
| Objet | Signalements / litiges de **consommateurs** envers des entreprises | **Rappels de produits** dangereux (alimentaires et non-alimentaires) |
| Question posée | « Tel commerçant / produit / service m'a posé problème » | « Tel produit précis est retiré du marché » |
| Nomme l'entreprise ? | **Non** (données ouvertes anonymisées) | **Oui** (marque, fabricant, produit identifiés) |
| Usage pour EverTrack | Comprendre les **tendances de risque** par secteur | Cibler **nominativement** une marque/fabricant |

➜ **RappelConso reste la source de ciblage nominatif** (déjà l'Agent 1 du pipeline). SignalConso vient en **complément stratégique**, pas en remplacement.

---

## 3. Deux « API » — une seule est utile

**a) L'API applicative interne** (`signal-api.conso.gouv.fr`)
Moteur du site (code open source MIT, `github.com/betagouv/signalement-api`, stack Scala/Play + PostgreSQL). Accès **cloisonné** : réservé aux administrateurs, agents DGCCRF et professionnels concernés. Pas de documentation publique exploitable. **À écarter pour un usage tiers.**

**b) L'API de données ouvertes** (portail `data.economie.gouv.fr`) — **celle qui compte**
Le jeu de données « signalconso » :
- **Interrogeable sans authentification** (lecture seule)
- Téléchargeable en **CSV / JSON / ZIP** (~5,5 Mo)
- Interrogeable via une **API d'exploration** standard (technologie OpenDataSoft)
- Accompagné de **visualisations et d'une carte** par région/département et par type de problème

---

## 4. Contenu des données

Volume : **~1,73 million de signalements** anonymisés (depuis nov. 2018). Pour chaque signalement :

- **Catégorie et sous-catégories** du problème
- **Date de création**
- **Statut de traitement** (voir référentiel §6)
- **Cycle de réponse de l'entreprise** : informée → lue → répondu
- **Géographie** : département et région (codes + noms)

**Absent** (volontairement, RGPD) : nom de l'entreprise, SIRET nominatif, identité du consommateur, texte libre détaillé.

### Indicateur métier phare : la « promesse d'action »
L'entreprise reconnaît l'erreur, s'engage à corriger, répare le préjudice. Parcours national observé :
- **~58 %** des signalements sont *transmis* à l'entreprise ;
- parmi eux **~75 %** sont *lus* ;
- parmi les lus, **~89 %** reçoivent une *réponse*.

---

## 5. Cadre légal

- **Licence Ouverte 2.0 (Etalab)** : réutilisation autorisée **y compris à des fins commerciales** ; seule obligation = **citer la source**.
- **RGPD** : risque traité à la source par l'anonymisation. Données agrégées/anonymes = pas de données personnelles → l'essentiel des contraintes de réutilisation tombe.

---

## 6. Référentiels de valeurs (extraits en direct de l'API)

> Il n'existe **pas de "dictionnaire de codes" séparé**. Le référentiel est porté par (1) les **descriptions de champs** du schéma et (2) les **facettes** de l'API (liste exhaustive des valeurs réellement présentes + fréquence).
> Récupération autonome : `https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/signalconso/facets?facet=<champ>`

### `category` — type de problème
Codes officiels (CamelCase), par volume :

| Code | Volume | Code | Volume |
|---|---|---|---|
| AchatInternet | 445 k | DemarchesAdministratives | 21 k |
| DemarchageAbusif | 286 k | **IntoxicationAlimentaire** | **15 k** |
| AchatMagasinInternet | 174 k | Coronavirus | 8 k |
| TravauxRenovations | 114 k | Sante | 8 k |
| AchatMagasin | 110 k | Animaux | 4 k |
| VoyageLoisirs | 91 k | RecouvrementAmiable | 3 k |
| TelephonieFaiMedias | 90 k | VoitureVehicule | 2 k |
| BanqueAssuranceMutuelle | 75 k | TelEauGazElec | 2 k |
| CafeRestaurant | 72 k | Internet | 30 k |
| VoitureVehiculeVelo | 70 k | EauGazElectricite | 24 k |
| ServicesAuxParticuliers | 47 k | RetraitRappelSpecifique | 44 |
| Immobilier | 38 k | | |

⚠️ **Qualité de donnée** : ce champ contient aussi une traîne de ~20 valeurs « parasites » à faible volume (`Téléphonie / Internet / médias`, `Produit alimentaire`, `Pratique d'hygiène`, `Autre`…) = résidus d'anciennes versions du formulaire / fuites de sous-catégorie. **Se baser sur les codes CamelCase** et regrouper/ignorer la traîne.

### `status` — état de traitement (référentiel le plus précieux)

| Valeur | Signification | Volume |
|---|---|---|
| **PromesseAction** | Le pro s'engage à une action corrective/préventive *(indicateur phare)* | 380 k |
| NonConsulte | Le pro n'a pas créé de compte pour lire le signalement | 232 k |
| Infonde | Le pro déclare le signalement non fondé | 228 k |
| ConsulteIgnore | Lu mais resté sans réponse malgré relances | 75 k |
| MalAttribue | Mauvais établissement sélectionné par le consommateur | 58 k |
| SuppressionRGPD | Donnée supprimée (droit à l'effacement) | 93 k |
| InformateurInterne | Signalement d'un lanceur d'alerte interne | 21 k |
| TraitementEnCours | En cours | 19 k |
| Transmis | Transmis, pas encore d'issue | 6 k |
| NA | Hors flux classique (lié à une URL, ou hors périmètre géo. de l'expé.) | 621 k |

### `reg_name` / `reg_code` — région
Les **18 régions INSEE** (13 métropole + 5 DROM). Île-de-France domine (740 k, ~43 %). `reg_code` suit le COG INSEE, avec 2 regroupements documentés (31 = Nord+Pas-de-Calais ; 94 = Corse).

### `dep_name` / `dep_code` — département
Référentiel standard des **101 départements** (codes INSEE).

### Champs binaires (1/0)

| Champ | Sens |
|---|---|
| `signalement_transmis` | transmis au professionnel |
| `signalement_lu` | lu par l'entreprise |
| `signalement_reponse` | a reçu une réponse |
| `contactagreement` | identité du consommateur visible par le pro |
| `forwardtoreponseconso` | transmis au service ReponseConso |

### `tags` — thématiques transverses (multi-valeur)
~28 étiquettes croisant les catégories. Les plus utiles pour EverTrack :
**`Produit alimentaire` (68 k)**, **`Produit dangereux` (48 k)**, **`hygiène` (43 k)**, **`Produit industriel` (35 k)**, `Produit périmé`, `Quantité non conforme`, `Shrinkflation`, et — point de jonction officiel — **`RappelConso` (532)** et `OpenFoodFacts` (1 146).

### Champs SANS référentiel fermé (texte semi-libre)
- **`subcategories`** : arborescence très large et **bruitée** (mélange de langues et de versions de formulaire : `Apres_avoir_mange_sur_place`, `A_emporter`, `En_livraison`, mais aussi doublons EN `On_site`/`Takeaway`/`Yes`, et `Oui`). **À normaliser soi-même** avant exploitation.
- **`id`**, **`creationdate`** : identifiant technique et date — pas de référentiel.

---

## 7. Valeur business pour EverTrack

1. **Argumentaire de marché chiffré** : « Dans le secteur X, les signalements consommateurs liés à la qualité/traçabilité ont augmenté de Y % » — narratif factuel issu d'une source d'État.
2. **Segmentation secteur × territoire** : repérer où la pression consommateur est la plus forte.
3. **Qualification de maturité** : le champ `status` est le meilleur signal — beaucoup de `NonConsulte` + `ConsulteIgnore` sur un secteur/territoire = entreprises qui ne traitent pas leurs réclamations → cible idéale pour un SaaS de traçabilité/qualité.
4. **Filtres directs** : `refine=category:IntoxicationAlimentaire` ou `refine=tags:Produit dangereux` isolent le périmètre alimentaire/qualité sans téléchargement.
5. **Pont avec RappelConso** : `tags:RappelConso` relie signalements consommateurs et rappels.

**Limite majeure** : l'anonymisation **interdit le ciblage nominatif** d'une entreprise via SignalConso seul. La voie nominative reste **RappelConso** (qui nomme marques et fabricants) — mécanique de cross-référence déjà présente dans le pipeline.

**À prévoir côté code** : une couche de normalisation pour `category` (codes propres vs traîne legacy) et surtout `subcategories` (FR/EN, versions de formulaire) — même logique que `services/normalize.py`.

---

## 8. Points de vigilance (vérifiés)

- **Fraîcheur réelle** : « mise à jour quotidienne » annoncée, mais dernière mise à jour constatée du fichier ouvert = **10 mai 2026** (recherche fin juin) → rafraîchissement réel probablement plus espacé. À valider avant tout usage temps réel.
- **Chiffres = instantanés** : volumes et taux sont des compteurs temps réel, donc datés.
- **Limites d'usage de l'API d'exploration** (quotas/débit pour usage commercial intensif) : **non documentées** — à tester ou demander au support `data.economie.gouv.fr`.
- **Affirmations rejetées** par la vérification (à ne pas reprendre) : (1) une prétendue migration d'authentification JWT→cookie HttpOnly ; (2) l'idée d'une alimentation « en continu » du jeu.

---

## 9. Sources principales (officielles)

- Jeu de données ouvert : `data.economie.gouv.fr/explore/dataset/signalconso/` · `data.gouv.fr/datasets/signalconso`
- API d'exploration : `data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/signalconso`
- Tableau de bord officiel : `economie.gouv.fr/dgccrf/laction-de-la-dgccrf/le-tableau-de-bord-de-signalconso`
- Statistiques temps réel : `signal.conso.gouv.fr/fr/stats`
- Code source (transparence) : `github.com/betagouv/signalement-api`

---

## 10. Questions ouvertes

- Quotas/limites exacts de l'API d'exploration pour un usage commercial intensif ?
- Granularité sectorielle suffisante (alimentaire/traçabilité) pour le ciblage d'EverTrack ?
- Voie légale pour relier signalements anonymisés ↔ entreprises nommées (croisement RappelConso), et conditions RGPD ?
