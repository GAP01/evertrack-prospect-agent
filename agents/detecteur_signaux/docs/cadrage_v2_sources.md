# Cadrage technique — Extension du détecteur de signaux faibles

**Date** : 2026-04-27
**Statut** : cadrage, pas d'implémentation
**Périmètre** : ajouter 3 sources officielles à `detecteur_signaux` :
SignalConso, RASFF, ARS régionales.

---

## 1. Contexte & objectif

L'agent 4 (`detecteur_signaux`) couvre aujourd'hui Google News RSS + Reddit
JSON. Ces sources captent des signaux **publics et tardifs** (la presse arrive
souvent après le rappel officiel). On veut ajouter trois sources **plus en
amont** :

| Source | Type | Avance estimée vs RappelConso | Volume FR/an |
|---|---|---|---|
| **SignalConso** | Plaintes consommateurs (DGCCRF) | -7 à -30 jours | ~200 000 signalements |
| **RASFF Window** | Notifications EU food/feed | -2 à -7 jours | ~300 notifs FR-related |
| **ARS régionales** | Communiqués TIAC locales | -1 à -10 jours | ~50-100 TIAC |

Hypothèse à valider : ces sources doivent **réduire le délai moyen entre
incident réel et création de prospect** dans le pipeline EverTrack.

---

## 2. Architecture cible — Registry des collectors

### 2.1 Problème actuel

`detecteur._iter_sources()` est un `if/elif` hardcodé :

```python
def _iter_sources(sources, subreddits, gn_queries, reddit_queries):
    if "google_news" in sources:
        yield from google_news.fetch_all(queries=gn_queries)
    if "reddit" in sources:
        yield from reddit.fetch_all(subreddits=subreddits, queries=reddit_queries)
```

Avec 5 sources, ça devient une signature de fonction monstrueuse (kwargs par
source) et chaque ajout touche `detecteur.py`. Coût marginal d'extension élevé.

### 2.2 Solution : registre + config typée

Pattern proposé (équivalent du registre Reflex / Flask blueprints) :

```
agents/detecteur_signaux/sources/
├── __init__.py          # expose register, get_collector, list_collectors
├── registry.py          # dict global + decorator @register
├── config.py            # SourceConfig dataclass (queries, since_days, max_items, …)
├── google_news.py       # @register("google_news") def fetch_all(cfg) → Iterator[SignalSource]
├── reddit.py            # @register("reddit") def fetch_all(cfg) → ...
├── signalconso.py       # NEW
├── rasff.py             # NEW
└── ars.py               # NEW
```

`registry.py` :

```python
from typing import Callable, Iterator
from ..models import SignalSource
from .config import SourceConfig

SourceCollector = Callable[[SourceConfig], Iterator[SignalSource]]
COLLECTORS: dict[str, SourceCollector] = {}

def register(name: str):
    def deco(fn: SourceCollector) -> SourceCollector:
        COLLECTORS[name] = fn
        return fn
    return deco

def get_collector(name: str) -> SourceCollector | None:
    # import differé pour déclencher les @register
    from . import google_news, reddit, signalconso, rasff, ars  # noqa
    return COLLECTORS.get(name)
```

`config.py` (dataclass unique avec champs optionnels par source) :

```python
@dataclass
class SourceConfig:
    # Communs
    max_items: int | None = None
    since_days: int = 7

    # Google News / Reddit
    queries: list[str] = field(default_factory=list)
    subreddits: list[str] = field(default_factory=list)

    # SignalConso
    signalconso_categories: list[str] | None = None
    # RASFF
    rasff_country_filter: list[str] | None = None  # ['FR', 'BE', 'DE', ...]
    # ARS
    ars_regions: list[str] | None = None  # ['idf', 'paca', ...] ; None = all
```

Le `detecteur._iter_sources()` devient générique :

```python
def _iter_sources(sources: list[str], cfg: SourceConfig) -> Iterator[SignalSource]:
    for name in sources:
        collector = get_collector(name)
        if collector is None:
            logger.warning("Source inconnue : %r — skip", name)
            continue
        yield from collector(cfg)
```

### 2.3 Migration

Étape 0 (refacto avant nouvelles sources) :
1. Créer `sources/registry.py` + `sources/config.py`
2. Décorer `google_news.fetch_all` et `reddit.fetch_all` avec `@register`
3. Adapter leur signature à `(cfg: SourceConfig)` (juste lire `cfg.queries` etc.)
4. Remplacer `_iter_sources` par la version générique
5. Tests existants passent → aucune régression fonctionnelle

Coût ~1 demi-journée. À faire avant les 3 nouvelles sources.

---

## 3. Source 1 — SignalConso

### 3.1 Données disponibles

Deux endpoints publics complémentaires :

**a) Dataset data.gouv.fr** — `https://www.data.gouv.fr/datasets/signalconso`
- Format : CSV anonymisé, mis à jour mensuellement
- Latence : ~30 jours (pas idéal pour signaux faibles)
- Volume : 100 000+ lignes par fichier
- Champs typiques : `siret`, `categorie`, `sous_categorie`, `details`,
  `date_creation`, `code_postal_consommateur`, etc.

**b) API data.economie.gouv.fr** — `https://data.economie.gouv.fr/explore/dataset/signalconso/api/`
- Format : JSON via OpenDataSoft (ODS) Records API v1
- Latence annoncée : quotidienne
- Endpoint type : `GET /api/records/1.0/search/?dataset=signalconso&rows=100&sort=-date_creation`
- Auth : aucune (rate limit public ODS, ~5 req/s)

**Choix recommandé** : (b) pour le run quotidien, (a) en backfill historique.

### 3.2 Mapping vers `SignalSource`

Un signalement SignalConso n'est **pas un article** — pas d'URL publique
individuelle, pas de "titre". Il faut adapter :

| Champ `SignalSource` | Source SignalConso | Notes |
|---|---|---|
| `source_type` | `"signalconso"` | nouveau bucket |
| `source_name` | `"SignalConso"` ou `"SignalConso/<categorie>"` | pour le scoring |
| `source_url` | `"https://signal.conso.gouv.fr"` (générique) ou deeplink vers la fiche entreprise via SIRET | pas d'ID public exploitable |
| `titre` | concaténation `<sous_categorie> : <details_tronqués>` | reconstitué |
| `detected_at` | `date_creation` parsé en ISO-8601 | |
| `contenu` | champ `details` (texte libre du conso) | source de l'extraction LLM |

**Risque** : pas de SIRET marque → l'extracteur (LLM ou regex) doit retomber
sur le texte libre `details`. Souvent le conso écrit la marque, parfois non.
Prévoir un fallback "marque inconnue" → signal sans nom de marque mais avec
catégorie produit.

### 3.3 Filtrage

Le dataset couvre TOUT (assurance, télécom, banque…). Il faut filtrer sur
**les catégories alimentaires + cosmétiques + jouets** au minimum. Catégories
SignalConso pertinentes :

- `Alimentation` (et sous-catégories `Restaurant`, `Café/Bar`, `Magasin`,
  `Industrie agro-alimentaire`)
- `Cosmétiques`
- `Produits de soin` / `Hygiène`
- `Jouets` (selon scope client)

À paramétrer via `cfg.signalconso_categories`. Default = `["Alimentation",
"Cosmétiques", "Produits de soin"]` pour rester aligné scope EverTrack.

### 3.4 Dedup

`signalement_id` interne au dataset (UUID dans le schéma ODS). On peut soit :
- Utiliser ce UUID comme `source_id` côté `signaux_sources.url`
  (en stockant `signalconso://uuid/<id>`)
- Laisser `compute_signal_id` faire son boulot habituel (marque + symptôme + jour)

**Reco** : laisser le dedup global faire son travail (un signal peut agréger
plusieurs signalements SignalConso + un article presse). Mais empêcher la
re-ingestion d'un même signalement via `signaux_sources` dédoublonné par
URL — donc encoder l'UUID dans l'URL : `signalconso://uuid/<uuid>`.

### 3.5 Scoring — `source_weight`

Plaintes brutes anonymes → fiabilité moyenne **mais** plateforme officielle.
Proposition `SOURCE_WEIGHTS["signalconso"] = 18`.
Si on a ≥ 3 signalements distincts sur la même marque/produit, le bonus
`recurrence` (10 par source distincte, cap 30) suffit à monter le signal en
`a_valider` automatiquement, ce qui est l'effet recherché.

### 3.6 Limites & risques

- **Texte libre bruité** : fautes, langage parlé, parfois agressif
  → l'extracteur LLM doit être robuste, fallback regex pas suffisant
- **Volume** : sur 1 an, possiblement 50k signalements alim
  → throttling fetch (max_items, since_days), ne pas tout charger en mémoire
- **Anonymisation marque** : la DGCCRF caviarde parfois le nom commercial
  → accepter taux de "marque non extraite" élevé (~30% estimé)
- **Pas d'URL article** : le scrapping HTML n'a pas de sens ici, donc
  `find_rappelconso_url_for_source(scrape=False)` pour cette source

---

## 4. Source 2 — RASFF Window

### 4.1 Données disponibles

Portail officiel : `https://webgate.ec.europa.eu/rasff-window/screen/list`

**Pas d'API publique documentée** mais le portail est une SPA Angular qui
appelle un endpoint JSON interne. Reverse-engineering rapide (à confirmer
en phase POC) :

```
POST https://webgate.ec.europa.eu/rasff-window/api/public/notification/list
Body: { "filters": {...}, "pageSize": 100, "page": 0 }
```

Les notifications publiques sont accessibles sans auth. À tester en POC
avant de cadrer définitivement (l'endpoint peut nécessiter un cookie CSRF).

**Plan B** si l'API interne est instable : **scrapping HTML** sur la page
`/screen/list` avec pagination. Plus fragile mais bien documenté côté
projets de recherche universitaires.

**Plan C** : projet open source `rasff-scraper` (à vérifier sur GitHub) qui
fait le boulot et publie les données dans un format CSV — moins frais mais
sans dette technique.

### 4.2 Mapping vers `SignalSource`

Une notification RASFF a une structure riche :

| Champ `SignalSource` | Champ RASFF | Notes |
|---|---|---|
| `source_type` | `"rasff"` | |
| `source_name` | `"RASFF/<notification_type>"` (ex: `RASFF/alert`) | type ∈ {alert, info, border_rejection, news} |
| `source_url` | `https://webgate.ec.europa.eu/rasff-window/screen/notification/<ref>` | deeplink stable |
| `titre` | `subject` ou concat `<hazard> in <product> from <country>` | |
| `detected_at` | `notification_date` (ISO) | |
| `contenu` | concat `subject` + `hazard_description` + `distribution_status` | pour l'extraction |

**Champ `marque`** : RASFF identifie souvent le produit + l'établissement
expéditeur, mais le **nom commercial est souvent absent** (ils nomment le
fabricant ou l'importateur, pas le brand consumer-facing).
Conséquence : RASFF est très bon pour **détecter un risque amont** mais
insuffisant pour matcher une marque conso. À combiner avec d'autres sources
via `cross_reference`.

### 4.3 Filtrage

- **Pays** : ne garder que les notifs où la France apparaît dans
  `distribution_countries` OU `notifying_country`. Optionnel : étendre aux
  pays sources fréquents (DE, BE, NL, ES, IT) car le produit peut être
  distribué en France via importation.
- **Type de produit** : filtrer sur `product_category` ∈ {alimentaire,
  cosmétique, matériaux contact alimentaire}. RASFF couvre aussi feed (animaux)
  → exclure sauf demande client.
- **Date** : `since_days` configurable, par défaut 7.

### 4.4 Dedup

`notification_reference` (ex: `2024.1234`) est unique. Stocker en
`signaux_sources.url` via le deeplink. Pas de calcul de hash custom.

### 4.5 Scoring

Source officielle EU, très haute fiabilité technique mais signal souvent
abstrait pour le grand public.
Proposition `SOURCE_WEIGHTS["rasff"] = 30` (au niveau presse pro agro).

### 4.6 Limites & risques

- **API non documentée** : risque de changement silencieux de schéma
  → POC obligatoire avec cassette de test (snapshot d'une réponse JSON)
- **Marque souvent absente** : faiblesse intrinsèque de RASFF pour la
  prospection — utile pour l'early warning amont mais pas en isolation
- **Anglais** : tous les textes sont en EN → l'extracteur doit gérer EN
  (ou on traduit avant via Haiku)
- **Politique d'usage** : à vérifier dans les CGU du portail RASFF.
  Probablement OK car données publiques mais à confirmer.

---

## 5. Source 3 — ARS régionales

### 5.1 Données disponibles

**18 sites ARS régionaux** (`<region>.ars.sante.fr`), chacun avec sa
section "Salle de presse" / "Communiqués". Pas d'API, pas de RSS centralisé.

Approches possibles, par ordre de simplicité :

**a) RSS individuels** — certaines ARS publient un RSS de leurs communiqués
(à inventorier site par site). Simple et léger quand dispo.

**b) Crawl HTML** — page `/communiques-de-presse` paginée, scrapping classique
avec BeautifulSoup. Lourd mais marche partout.

**c) Agrégateur tiers** — Santé Publique France publie le bulletin
épidémiologique avec les TIAC déclarées. Cadence trimestrielle, donc trop
tardif pour un signal faible. À écarter en V1.

**d) Search Google site-restricted** — `site:*.ars.sante.fr "TIAC"
intoxication` via Google Search API ou via le pipeline Google News existant
en élargissant les queries. **C'est probablement la voie la plus rentable
en V1**.

### 5.2 Recommandation V1

Plutôt que de scraper 18 sites différents, **ajouter une query Google News
ciblée ARS** :

```python
GOOGLE_NEWS_QUERIES.append('site:ars.sante.fr OR site:santepubliquefrance.fr "TIAC" OR "intoxication"')
```

Avantage : zéro nouveau code, le pipeline existe.
Inconvénient : Google News échantillonne, on rate des communiqués.

**V2 : scrapper réellement** une fois la V1 stabilisée et qu'on sait
quelles ARS produisent vraiment des communiqués actionables (probablement
3-5 ARS sur les 18 — IDF, AURA, PACA, Hauts-de-France, Occitanie).

### 5.3 Si on fait quand même un collector dédié (V2)

Architecture par "sous-collector" régional :

```python
# sources/ars.py
ARS_SITES = {
    "idf": "https://www.iledefrance.ars.sante.fr/communiques-de-presse",
    "aura": "https://www.auvergne-rhone-alpes.ars.sante.fr/...",
    # ...
}

@register("ars")
def fetch_all(cfg: SourceConfig) -> Iterator[SignalSource]:
    regions = cfg.ars_regions or list(ARS_SITES.keys())
    for region in regions:
        yield from _scrape_one_region(region, ARS_SITES[region], cfg.since_days)
```

Avec `_scrape_one_region` qui parse le listing HTML, suit les liens vers le
détail, et yield des `SignalSource`. Throttle 1 req/s par site (politesse).

### 5.4 Mapping vers `SignalSource`

| Champ | ARS |
|---|---|
| `source_type` | `"ars"` |
| `source_name` | `"ARS <region>"` (ex: `"ARS Île-de-France"`) |
| `source_url` | URL du communiqué |
| `titre` | titre du communiqué |
| `detected_at` | date de publication |
| `contenu` | corps du communiqué (HTML stripped) |

### 5.5 Scoring

`SOURCE_WEIGHTS["ars île-de-france"] = 30`, etc. — cohérent avec presse pro
agro (autorité officielle).
Pour la V1 (via Google News), pas de nouvelle entrée nécessaire : la
détection passe par le `source_name` du résultat Google News qui sera
déjà `ars.sante.fr` ou similaire.

### 5.6 Limites & risques

- **Inhomogénéité des sites ARS** : chaque site a son CMS, son template
  → 18 parsers spécifiques si on va jusqu'au bout, ROI questionnable
- **Volume faible** : 50-100 TIAC publiées/an, donc effort > rendement V1
- **Communiqués génériques** : beaucoup d'ARS publient des CP sur autre
  chose (vaccination, hôpitaux), filtrage mots-clés requis

---

## 6. Impact sur les autres composants

### 6.1 `models.py`
- `SignalSource.source_type` accepte 3 nouvelles valeurs :
  `"signalconso"`, `"rasff"`, `"ars"`
- Pas de breaking change (champ str libre)

### 6.2 `keywords.py` — `SOURCE_WEIGHTS`
- Ajouter entrées pour les 3 sources (cf §3.5, §4.5, §5.5)
- Recalibrer après quelques semaines d'observation (comme on a fait pour
  Marmiton/TF1)

### 6.3 `extractor.py`
- SignalConso : tester sur texte libre conso (orthographe, langage parlé)
- RASFF : ajouter capacité multilingue FR/EN au prompt LLM
  ou traduire avant via un appel Haiku séparé
- ARS : prose institutionnelle FR, devrait bien fonctionner sans modif

### 6.4 `cross_reference.py`
- Aucune modif côté logique — le crossref signal↔incident continue de
  marcher car il opère sur les champs agrégés (`signal.marque`,
  `signal.symptome`) indépendamment de la source d'origine
- **Bonus possible** : un match signal-RASFF↔incident ↔ signal-Presse↔incident
  donne un degré de confirmation supplémentaire. À explorer en V2 via
  une métrique "n_source_types" (combien de buckets différents pointent
  sur le même signal).

### 6.5 `cli.py`
- Le flag `--sources` accepte déjà une liste : `--sources google_news,reddit,signalconso,rasff,ars`
- Ajouter validation : warn si nom inconnu (le registre le fait déjà)

### 6.6 `requirements.txt`
- SignalConso : juste `requests` (déjà là)
- RASFF : `requests` + éventuellement `beautifulsoup4` si on tombe sur le
  Plan B HTML (déjà dans le projet pour `rappelconso_link.py`)
- ARS V1 : zéro nouvelle dépendance (passe par Google News existant)

### 6.7 Tests
Pour chaque nouvelle source, dans `tests/test_sources_<name>.py` :
- 1 fixture JSON/HTML représentative (cassette)
- Test du parser → vérifie le mapping `SignalSource`
- Test du filtrage (catégorie, pays, date)
- Test du dedup (même UUID/référence ne crée pas de doublon)
- Aucun appel réseau réel dans la suite de tests (MagicMock)

---

## 7. Plan d'implémentation phasé

### Phase 0 — Refacto registre (prérequis)
- Créer `sources/registry.py`, `sources/config.py`
- Décorer les 2 sources existantes
- Adapter `_iter_sources` et `cli.py`
- Vérifier que la suite de tests passe
- **Estimation : 0.5 jour**

### Phase 1 — SignalConso (le plus rentable)
- POC sur l'API ODS (1-2h pour valider la fraîcheur réelle des données)
- Implémenter `sources/signalconso.py` (collector + filtrage catégories)
- Adapter `extractor.py` pour texte libre conso
- Tests + ajout au CLI
- **Estimation : 1.5 jour**

### Phase 2 — RASFF
- POC sur l'endpoint interne (vérifier stabilité, schéma)
- Si OK : `sources/rasff.py` avec API JSON
- Si KO : fallback HTML scrapping
- Gestion FR/EN dans l'extracteur
- Tests + CLI
- **Estimation : 1-2 jours selon plan A/B**

### Phase 3 — ARS V1
- Ajouter une query Google News ciblée ARS dans `keywords.py`
- Ajuster `SOURCE_WEIGHTS` pour `ars.sante.fr`
- Test sur 1-2 semaines de production
- Décision V2 (scrapping dédié) selon volume utile remonté
- **Estimation : 0.5 jour**

### Total V1 (Phases 0-3) : 3.5 à 4.5 jours

---

## 8. Décisions actées (2026-04-27)

1. **Scope SignalConso** : Alim + Cosmétiques + Produits de soin.
   Jouets reportés à un V2 si demande client.
2. **Scope RASFF** : Food only. Feed exclu.
3. **ARS V1** : query Google News `site:*.ars.sante.fr OR
   site:santepubliquefrance.fr` ajoutée au pipeline existant. Pas de
   collector dédié en V1. Scrapping multi-sites reporté en V2 selon
   volume utile remonté.
4. **Source weights initiaux** : approche conservative à la Marmiton —
   `SOURCE_WEIGHTS["signalconso"] = 12`, `SOURCE_WEIGHTS["rasff"] = 20`.
   Pas d'entrée ARS dédiée (passe par Google News). Recalibrage après
   2-3 semaines d'observation.
5. **Backfill SignalConso** : `since_days=30` au premier run via API ODS.
   Pas de chargement du CSV mensuel data.gouv.
6. **Versioning** : `DETECTOR_VERSION = "v0.2"` bump en fin de Phase 3,
   après intégration des 3 sources. Phase 0 (refacto registre) reste en
   `v0.1` puisque la surface de détection ne change pas.

---

## 9. Risques transverses

- **Ratio bruit/signal SignalConso** : le volume brut peut noyer les
  vraies alertes. Mitigation : seuil `recurrence` plus exigeant
  (au moins 2 signalements distincts sur la même marque) avant de remonter.
- **Stabilité RASFF API** : si l'endpoint privé change, le collector casse
  silencieusement. Mitigation : monitoring du compteur `sources_fetched`
  par source dans le rapport, alerte si tombe à 0.
- **Conformité RGPD SignalConso** : les données sont anonymisées par la
  DGCCRF, donc pas d'enjeu côté données. Mais vérifier les CGU de réutilisation
  data.gouv.fr (licence ouverte v2 normalement).

---

## 10. Sources

- [SignalConso dataset data.gouv.fr](https://www.data.gouv.fr/datasets/signalconso)
- [SignalConso API ODS data.economie.gouv.fr](https://data.economie.gouv.fr/explore/dataset/signalconso/api/?flg=en-us)
- [RASFF Window — listing](https://webgate.ec.europa.eu/rasff-window/screen/list)
- [RASFF Window — consumers](https://webgate.ec.europa.eu/rasff-window/screen/consumers)
- [ARS Centre-Val de Loire — TIAC](https://www.centre-val-de-loire.ars.sante.fr/toxi-infections-alimentaires-collectives-tiac)
- [Santé Publique France — TIAC 2022](https://www.santepubliquefrance.fr/les-actualites/2024/pres-de-2-000-toxi-infections-alimentaires-collectives-declarees-en-france-en-2022)
- [betagouv/signalement-api (GitHub)](https://github.com/betagouv/signalement-api)
