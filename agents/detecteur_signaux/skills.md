# Compétences — Détecteur de signaux faibles

Ce que l'agent **sait faire** concrètement, du crawling à la cross-référence.

## 1. Crawl multi-sources

### Google News RSS (gratuit, sans auth)

**URL pattern** :
```
https://news.google.com/rss/search?q={query}&hl=fr&gl=FR&ceid=FR:fr
```

**Queries configurées** (`GOOGLE_NEWS_QUERIES` dans `keywords.py`) :
```
'"rappel produit" OR "rappel alimentaire"'
'"listeria" OR "listeriose"'
'"salmonelle" OR "salmonellose"'
'"intoxication alimentaire"'
'"corps étranger" aliment'
'"allergène non déclaré" OR "allergène non mentionné"'
'"e.coli" produit alimentaire'
'"moisissure" rappel'
```

**Parsing** : XML via `xml.etree.ElementTree`, extraction de chaque `<item>` :
- `title`, `link`, `description` (HTML stripped via regex)
- `pubDate` parsé via `email.utils.parsedate_to_datetime`
- `<source>` enfant pour le nom de l'éditeur (Marmiton, TF1 Info, …)

**Rate limiting** : aucun imposé par Google (tolérant).

### Reddit JSON public

**URL pattern** :
```
https://www.reddit.com/r/{sub}/search.json?q={q}&restrict_sr=1&sort=new&t=week&limit=25
```

**Subreddits** : `france`, `Consommateurs`, `AskFrance`

**Auth** : aucune — juste un **User-Agent custom obligatoire** :
```
User-Agent: EverTrackDetecteurSignaux/0.1 (by /u/evertrack_bot)
```

**Rate limiting** : `time.sleep(1.5)` entre queries (conservateur, Reddit bloque agressif).

**Filtrage qualité** : drop les posts avec `score < 2` (évite le bruit).

## 2. Extraction structurée LLM (Claude Haiku)

### Modèle
- `claude-haiku-4-5-20251001`
- `max_tokens=400`
- Prompt système concis, réponse JSON strict

### Sortie attendue
```json
{
  "marque": "Carrefour",         // ou null
  "produit": "fromage italien",  // ou null
  "symptome": "contamination bactérienne",  // ou null
  "is_alim": true,               // faux positif auto/jouet/médicament
  "resume": "Rappel urgent d'un fromage italien contaminé…"  // <= 180 chars
}
```

### Parsing défensif
1. Regex `\{.*\}` (DOTALL) sur la réponse
2. `json.loads` avec catch
3. Clean des champs : strip, cap à 80/100/180 chars selon

### Fallback regex (sans clé)
`_fallback_extract()` utilise :
- `NEGATIVE_FILTERS` pour rejeter les `rappel auto`, `rappel chiens`, etc.
- `_MARQUE_PATTERNS` : regex pour `"de la marque X"`, `"marque X"`, `"chez X"`
- `_SYMPTOME_MAP` : mapping texte → label standard (listeria, salmonelle, …)

**Taux de réussite LLM vs regex** (observé sur 100 articles) :
- LLM : ~70% de signaux extraits
- Regex : ~30% (perd tous les articles sans mention explicite "marque X")

## 3. Déduplication stable multi-niveaux

### `compute_signal_id(marque, symptome, titre, detected_at, produit)`

Hash sha1[:16] sur 4 niveaux de granularité décroissante :

```python
if marque and symptome:   key = f"brand|{marque_norm}|{symptome_norm}|{day}"
elif produit and symptome: key = f"prod|{produit_norm}|{symptome_norm}|{day}"
elif symptome:             key = f"sympt|{symptome_norm}|{day}"
else:                      key = f"title|{titre_norm[:80]}|{day}"
```

### Normalisation avant hash
- Strip accents via `unicodedata.NFD`
- Lower
- Regex `[^a-z0-9]+` → `" "`
- Collapse whitespace

### Cap au jour
Le `day = YYYY-MM-DD` évite de créer un nouveau signal par refetch
intrajournalier. Deux articles sur "Listeria Nestlé" publiés le même jour →
même `signal_id` → agrégation des sources.

### Robustesse
Le même signal détecté via Marmiton puis via Femme Actuelle → **2 sources**
rattachées au **même `signal_id`** → booste `recurrence` dans le scoring.

## 4. Scoring de crédibilité (0-100)

### 5 composantes pondérées

| Composante | Max | Calcul |
|---|---|---|
| `source_weight` | 35 | `SOURCE_WEIGHTS[source_name]` (fallback default 12) |
| `recurrence` | 30 | `min(n_sources × 10, 30)` |
| `recency` | 15 | 15 si < 24h, 10 si < 72h, 5 si < 7j, 0 sinon |
| `brand_known` | 10 | `+10` si marque ∈ `incidents.sqlite` (lookup substring) |
| `sentiment` | 10 | `10` si ≥2 mots négatifs, `5` si 1, `0` sinon |

### Dictionnaire `SOURCE_WEIGHTS` (extraits)

| Catégorie | Sources | Poids |
|---|---|---|
| Presse pro agro | LSA, Process Alimentaire | 30 |
| Presse nationale | Le Monde, Le Figaro, Les Échos | 22-28 |
| Conso / vulgarisation | 60M Consommateurs, Que Choisir | 25 |
| Cuisine / lifestyle | Marmiton, Cuisine AZ, Femme Actuelle | 15-18 |
| Reddit | r/consommateurs, r/france, r/AskFrance | 12-18 |
| Inconnu (défaut) | — | 12 |

### Détection négative pour sentiment
Mots négatifs FR (dans `scorer.py::_NEGATIVE_WORDS`) :
```
danger, dangereux, grave, mort, deces, hospitalisation, intoxique,
alerte, scandale, catastrophe, urgent, risque vital, empoisonne, malades, …
```

### Seuil d'alerte
`SCORE_SEUIL_ALERTE = 40` dans `models.py` → passe en `a_valider`.

## 5. Résolution et scraping d'articles

### Décodage Google News (opaque → URL réelle)

Google News masque les URLs cibles dans un protobuf base64. Résolution via
**googlenewsdecoder** (dépendance requirements.txt) :

```python
from googlenewsdecoder import new_decoderv1
result = new_decoderv1(google_news_url, interval=1)
real_url = result["decoded_url"]  # ex: https://www.marmiton.org/...
```

Nécessaire pour 100% des articles provenant de Google News RSS.

### Fetch HTTP de l'article

`fetch_article_html(url)` :
- Session `requests` avec User-Agent Chrome moderne
- Timeout 6s
- `allow_redirects=True`
- Cap à 500 KB (évite pages énormes)
- Content-Type filtrer sur `text` ou `html`
- Silent sur toutes les erreurs (`return None`)

### Extraction des URLs RappelConso

Regex sur le HTML ou le RSS description :
```python
_RAPPELCONSO_URL_RE = re.compile(
    r"https?://(?:www\.)?rappel\.conso\.gouv\.fr/fiche-rappel/(\d+)(?:/[\w-]+)?",
    re.IGNORECASE,
)
```

Stratégie 2 niveaux :
1. Chercher dans le RSS description (gratuit)
2. Si rien : HTTP GET + regex sur le HTML complet

**Taux réel observé** : ~65% des articles Google News contiennent un lien
direct. Marmiton et Femme Actuelle citent systématiquement, Melty et 750g
rarement.

## 6. Cross-référence signal ↔ incident

### 4 dimensions pondérées (somme = 1.0)

| Dimension | Poids | Calcul |
|---|---|---|
| `brand_match` | **0.40** | `brand_or_distributor_similarity(signal.marque, incident.marque, incident.distributeurs)` |
| `symptom_match` | **0.30** | `symptom_match` avec mapping `SYMPTOM_TO_KEYWORDS` (famille pathogènes) |
| `product_match` | **0.20** | Substring + hints `PRODUCT_CATEGORY_HINTS` |
| `date_proximity` | **0.10** | Gaussienne `exp(-(Δj / 30)²)` |

### Skill clé : brand OR distributeur

Un même patched function prend le MAX entre :
- similarité(signal.marque, incident.marque) — ex: Nestlé ↔ Nestlé
- similarité(signal.marque, incident.distributeurs) — ex: Carrefour ↔ "carrefour"

Crucial car la presse parle du distributeur, RappelConso de la marque fabricant.
Sans ce mécanisme, "Carrefour saumon listeria" ne matche jamais "océan délices
distrib=carrefour".

### Skill clé : familles de pathogènes

Quand le LLM renvoie un symptôme générique (`"contamination bactérienne"`),
le mapping pointe vers une liste de patterns spécifiques (`listeria`,
`salmonelle`, `e.coli`, …) cherchés dans `incident.motif + risques`.

Voir `SYMPTOM_TO_KEYWORDS` dans `cross_reference.py` (~20 entrées).

### Skill clé : hints produit → catégorie

Mapping `PRODUCT_CATEGORY_HINTS` (~40 entrées) :
- `fromage, yaourt, lait` → `lait et produits laitiers`
- `jambon, saucisson, coppa, terrine` → `viandes, charcuterie`
- `poisson, saumon, huitre` → `pêche, aquaculture`
- etc.

Bonus fixé à 0.85 si hint matche la `sous_categorie` de l'incident.

### Seuils de qualification
| Seuil | Label | Affichage UI |
|---|---|---|
| ≥ 0.70 | Fort | Pastille verte |
| 0.50-0.70 | Possible | Pastille jaune |
| < 0.50 | Ignoré | Non affiché |

### Auto-confirm via URL directe
Parcours des signaux avec `rappelconso_url` non null :
- Extrait le numéro de fiche depuis l'URL
- Cherche dans `incidents` via `source_url LIKE '%fiche-rappel/NNN%'`
- Si match : `storage.confirm_match()` → `user_confirmed = 1`

### Validation humaine préservée
`clear_matches(keep_confirmed=True)` → les matches `user_confirmed=1`
survivent aux recomputes.

## 7. Calcul du lead time

```python
lead_time_days = (incident.date_publication - signal.detected_at).days
```

- **Positif** : signal AVANT rappel officiel (early warning) — objectif idéal
- **Négatif** : couverture presse APRÈS le rappel (cas le plus fréquent)
- **Zéro** : même jour

Affiché dans le dashboard avec badge coloré (bleu = ahead, orange = after).

## 8. Workflow de validation humaine

### Statuts et transitions
```
faible ─── score >= 40 ──► a_valider ──[click valider]──► valide
                                       └─[click rejeter]─► rejete
                                                            │
                                             [click promote]│
                                                            ▼
                                                          promu
                                                     + crée row dans
                                                     incidents.sqlite
                                                     (source="signal_detecteur")
```

### Promotion en incident (`promote_signal`)
Construit un dict compatible schema `incidents` :
- `source = "signal_detecteur"`
- `source_id = signal_id` (hash 16 chars)
- `marque`, `motif = resume`, `risques = symptome`, `date_publication = today`
- `raw = {signal_id, origin}`

INSERT OR REPLACE dans `incidents.sqlite`. L'incident créé est alors visible
dans le Radar et peut lui-même être enrichi par Agent 3.

## 9. CLI maîtrisée

| Commande | Capacité |
|---|---|
| `fetch` | Pipeline complet (fetch + extract + score + crossref + scrape URLs) |
| `fetch --no-llm` | Fallback regex |
| `fetch --no-scrape` | Skip l'HTTP GET des articles (plus rapide) |
| `fetch --no-crossref` | Skip le recalcul des matches après |
| `fetch --sources google_news` | Limite aux sources indiquées |
| `crossref` | Recalcul matches seul, sans refetch |
| `scrape-links` | Enrichit `rappelconso_url` sur sources existantes |
| `list --status a_valider --min-score 40` | Liste filtrée |
| `show <signal_id>` | Détail + sources + breakdown score |
| `stats` | Compteurs par statut + dernier scan |
| `validate <id> --accept / --reject` | Validation CLI |
| `promote <id>` | Promotion en incident |

## 10. Persistance SQLite avec 3 tables liées

### Migrations maîtrisées
Pattern `_MIGRATIONS` (ALTER TABLE idempotents) pour :
- Ajout `user_confirmed` (table matches)
- Ajout `rappelconso_url` (table signaux_sources)
- Création d'index a posteriori

### `attach_source` tolère l'update du `rappelconso_url`
Si une source est déjà en base mais qu'on découvre maintenant une URL
RappelConso via scraping : UPDATE sélectif (ne réécrase pas une URL existante).

## Ce que l'agent ne sait PAS faire

- **Pas de X/Twitter/LinkedIn** : API payantes ou scraping risqué
- **Pas de traduction** : FR uniquement
- **Pas de parallélisation** : fetch séquentiel (Reddit rate-limited de toute façon)
- **Pas de streaming** / temps-réel : batch toutes les 6h max
- **Pas de LLM pour le cross-ref** : 100% règles (pour reproductibilité)
- **Pas de self-learning** : pas de feedback loop utilisant les validations
  humaines pour tuner les poids (futur possible)
- **Pas de détection de "contradiction"** : si deux articles disent des choses
  différentes sur un même signal, on ne le détecte pas
- **Pas d'OCR d'images** : si un article a un screenshot de fiche RappelConso,
  on ne le lit pas
- **Pas de recherche sémantique** : regex + substring, pas d'embeddings
