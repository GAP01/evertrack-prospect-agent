# Plan — Source TikTok pour l'Agent 4 (detecteur_signaux)

**ADR source :** ADR-006
**Date :** 2026-05-12
**Complexite globale :** M-L (5 taches, ~5h total)

---

## Pre-requis

- [ ] L'ADR-006 est lu et accepte (statut "Propose" → valider avec le client
  avant de commencer).
- [ ] L'instance RSS-bridge n'est **pas** requise pour implementer ou tester :
  les tests utilisent uniquement des fixtures statiques et des mocks
  `requests.get`. L'URL de prod sera fournie dans `.env` apres deploiement.
- [ ] Aucune dependance Python nouvelle : `feedparser` et `requests` sont deja
  dans `agents/detecteur_signaux/requirements.txt`.

---

## Taches

### T1 — Ajouter les constantes TikTok dans keywords.py [XS]

**Fichiers touches :**
- `agents/detecteur_signaux/keywords.py`

**Depend de :** —

**Critere d'acceptation :**

1. La liste `TIKTOK_HASHTAGS` existe dans `keywords.py` et contient exactement
   les 8 valeurs de l'ADR :
   `["rappelproduit", "rappelconso", "intoxalimentaire", "salmonelle",
   "listeria", "alertealimentaire", "produitcontamine", "alimentdangereux"]`.
2. `SOURCE_WEIGHTS["tiktok"] == 10`.
3. `SOURCE_WEIGHTS["tiktok @60millions"] == 25` et
   `SOURCE_WEIGHTS["tiktok @dgccrf"] == 30`.
4. Test de non-regression : `python -m unittest detecteur_signaux.tests.test_scorer`
   passe sans modification (les nouvelles entrees ne cassent aucun test existant
   car `score_source_weight` fait un match substring case-insensitive).

**Description :**

Dans `keywords.py`, ajouter apres le bloc `SOURCE_WEIGHTS` :

```python
TIKTOK_HASHTAGS = [
    "rappelproduit", "rappelconso", "intoxalimentaire",
    "salmonelle", "listeria", "alertealimentaire",
    "produitcontamine", "alimentdangereux",
]
```

Dans le dict `SOURCE_WEIGHTS`, ajouter les trois entrees TikTok. L'ordre dans
le dict importe peu ; le scorer fait un `source_name.lower() in key` donc la
cle `"tiktok @60millions"` matchera `source_name="TikTok @60millions"`.

Aucun autre fichier a toucher dans cette tache.

---

### T2 — Etendre SourceConfig avec les champs TikTok [XS]

**Fichiers touches :**
- `agents/detecteur_signaux/sources/config.py`

**Depend de :** —

**Critere d'acceptation :**

1. `SourceConfig` possede trois nouveaux champs :
   - `tiktok_hashtags: Optional[list[str]] = None`
   - `tiktok_bridge_base_url: Optional[str] = None`
   - `tiktok_min_view_count: int = 1000`
2. `SourceConfig()` instanciable sans arguments (defaults conserves).
3. `python -m unittest detecteur_signaux.tests.test_sources_registry` passe :
   `test_defaults_safe` ne casse pas (les nouveaux champs ont des defaults).

**Description :**

Ajouter un bloc `# --- TikTok` dans la dataclass `SourceConfig` de
`sources/config.py`, apres le bloc `# --- RASFF`. Suivre exactement le
style des blocs existants (commentaire de section + champ annote + valeur
par defaut). Importer `Optional` deja present.

---

### T3 — Implementer sources/tiktok.py avec les 3 tiers [M]

**Fichiers touches :**
- `agents/detecteur_signaux/sources/tiktok.py` *(a creer)*

**Depend de :** T1, T2

**Critere d'acceptation :**

1. Le module expose une fonction `collect(cfg: SourceConfig) -> Iterator[SignalSource]`
   decoree `@register("tiktok")`.
2. **Tier 1 (RSS-bridge)** : si `cfg.tiktok_bridge_base_url` est defini,
   `fetch_via_bridge(hashtag, bridge_base_url)` est appele. Il construit l'URL
   `{bridge_base_url}/?action=display&bridge=TikTok&context=Hashtag&h={hashtag}&format=Atom`,
   fait un GET avec `feedparser.parse()`, et retourne une `list[SignalSource]`.
   - `source_type = "tiktok"`
   - `source_name = "TikTok @{author}"` si le champ `author` existe dans
     l'entree feedparser, sinon `"TikTok #{hashtag}"`.
   - `source_url` = lien de l'entree feedparser.
   - `titre` = `entry.title[:200]` (tronque).
   - `detected_at` = `entry.published_parsed` converti en `datetime` UTC,
     ou `datetime.utcnow()` si absent.
   - `contenu` = description de l'entree + hashtags concatenes, tronque a 2000 chars.
   - Les items avec `view_count < cfg.tiktok_min_view_count` sont filtres si
     le champ `view_count` est parseable ; sinon l'item passe (comportement
     defensif).
   - Si le GET echoue (timeout, HTTP != 2xx, exception), log un WARNING et
     retourner une liste vide (le tier 2 prend le relais dans `fetch_all`).
3. **Tier 2 (scraping direct)** : `fetch_via_scraping(hashtag, session)` fait
   un GET sur `https://www.tiktok.com/tag/{hashtag}` avec un User-Agent
   configurable (`cfg.tiktok_user_agent` ou `USER_AGENT` par defaut) et extrait
   le blob JSON `__UNIVERSAL_DATA_FOR_REHYDRATION__` via `re.search`. Parse
   defensif : si la cle JSON change ou si le blob n'est pas parseable, retourne
   `[]` avec un WARNING loggue.
   - Meme mapping `SignalSource` que le tier 1.
   - Filtre `view_count < cfg.tiktok_min_view_count` applique si disponible.
4. **Tier 3 (degraded mode)** : si les deux tiers echouent ou retournent `[]`,
   `collect` log un WARNING `"[tiktok] source desactivee (degraded mode)"` et
   ne yield rien. L'agent continue normalement avec les autres sources.
5. `fetch_all(hashtags, bridge_base_url, min_view_count)` itere sur les hashtags
   et applique le fallback tier 1 → tier 2 → tier 3 par hashtag.
6. Pas d'import de feedparser au niveau module — import local dans la fonction
   tier 1 pour isoler les erreurs d'import.
7. ASCII only dans les messages de log et les sorties (pas d'emoji, pas de
   caractere non-ASCII dans les f-strings de logging).

**Description :**

Modele le fichier sur `google_news.py` pour la structure generale
(`fetch_*`, `fetch_all`, `@register`). Le circuit breaker inter-tiers se fait
simplement : `fetch_via_bridge` retourne `[]` en cas d'echec → `fetch_all`
tente `fetch_via_scraping` → si encore `[]`, loggue le mode degrade.

Constantes a definir en haut du fichier :

```python
USER_AGENT = "Mozilla/5.0 (compatible; EverTrackDetecteurSignaux/0.1)"
REQUEST_TIMEOUT = 15
TIKTOK_BRIDGE_PATH = "/?action=display&bridge=TikTok&context=Hashtag&h={hashtag}&format=Atom"
TIKTOK_HASHTAG_URL = "https://www.tiktok.com/tag/{hashtag}"
JSON_BLOB_PATTERN = r'__UNIVERSAL_DATA_FOR_REHYDRATION__\s*=\s*(\{.+?\})\s*</script>'
```

Note sur `SourceConfig` : le champ `tiktok_user_agent` n'est **pas** ajoute a
`SourceConfig` (pas dans l'ADR) — utiliser directement la variable d'env via
`os.environ.get("TIKTOK_USER_AGENT", USER_AGENT)` dans la fonction de scraping.

---

### T4 — Enregistrer tiktok dans le registry et le CLI [S]

**Fichiers touches :**
- `agents/detecteur_signaux/sources/registry.py`
- `agents/detecteur_signaux/cli.py`

**Depend de :** T3

**Critere d'acceptation :**

1. `_ensure_collectors_loaded()` dans `registry.py` contient
   `from . import tiktok  # noqa: F401`.
2. `list_collectors()` retourne `"tiktok"` parmi les noms disponibles.
3. `python -m detecteur_signaux.cli fetch --sources tiktok --no-llm --no-scrape`
   ne leve pas d'erreur (meme si aucun item n'est remonte faute de bridge).
4. `python -m detecteur_signaux.cli fetch --sources google_news,reddit,tiktok --no-llm --no-scrape`
   ne leve pas d'erreur.
5. Le flag `--sources` dans `cli.py` documente `tiktok` comme valeur valide
   dans le help string (`help="Sources a utiliser : google_news, reddit, tiktok, ..."`).
6. `python -m unittest detecteur_signaux.tests.test_sources_registry` passe :
   `test_default_collectors_registered` doit etre mis a jour pour verifier que
   `"tiktok"` est aussi dans `list_collectors()`.

**Description :**

Dans `registry.py`, ajouter `from . import tiktok  # noqa: F401` dans
`_ensure_collectors_loaded()`, apres `from . import signalconso`.

Dans `cli.py`, mettre a jour la valeur par defaut du flag `--sources` et son
`help`. La valeur par defaut actuelle est probablement `"google_news,reddit"` —
**ne pas ajouter `tiktok` par defaut** (source optionnelle, degraded mode sans
bridge). Mettre a jour uniquement le `help` pour mentionner `tiktok` comme
option valide.

Mettre a jour le test `test_default_collectors_registered` dans
`tests/test_sources_registry.py` pour ajouter `assertIn("tiktok", names)`.

---

### T5 — Ecrire tests/test_tiktok_source.py [S]

**Fichiers touches :**
- `agents/detecteur_signaux/tests/test_tiktok_source.py` *(a creer)*
- `agents/detecteur_signaux/tests/fixtures/tiktok_bridge_feed.xml` *(a creer)*
- `agents/detecteur_signaux/tests/fixtures/tiktok_hashtag_page.html` *(a creer)*

**Depend de :** T3, T4

**Critere d'acceptation :**

`python -m unittest detecteur_signaux.tests.test_tiktok_source` passe avec au
moins les cas suivants :

1. **`TestFetchViaBridge.test_parse_atom_feed`** : mock de `requests.get`
   retournant le contenu de `fixtures/tiktok_bridge_feed.xml` (flux Atom
   minimal avec 2 entrees). Verifier :
   - 2 `SignalSource` retournes.
   - `source_type == "tiktok"`.
   - `detected_at` est un `datetime` (pas `None`).
   - `titre` tronque a 200 chars max.
   - `contenu` contient la description de l'entree.

2. **`TestFetchViaBridge.test_bridge_502_returns_empty`** : mock `requests.get`
   levant `requests.exceptions.HTTPError` (simulant un 502). Verifier que
   `fetch_via_bridge` retourne `[]` sans exception.

3. **`TestFetchViaBridge.test_bridge_timeout_returns_empty`** : mock levant
   `requests.exceptions.Timeout`. Verifier `[]` retourne.

4. **`TestFetchViaBridge.test_view_count_filter`** : fixture avec 3 entrees dont
   1 avec `view_count < tiktok_min_view_count`. Verifier que seules 2 sont
   retournees. (Si le champ view_count n'est pas dans le flux Atom standard,
   ce test peut utiliser un champ custom ou verifier que les 3 passent —
   comportement defensif documente dans T3.)

5. **`TestFetchViaScraping.test_parse_json_blob`** : mock `requests.get`
   retournant le contenu de `fixtures/tiktok_hashtag_page.html` (HTML minimal
   avec le blob `__UNIVERSAL_DATA_FOR_REHYDRATION__` contenant 2 videos).
   Verifier que 2 `SignalSource` sont retournes avec `source_type == "tiktok"`.

6. **`TestFetchViaScraping.test_missing_blob_returns_empty`** : mock retournant
   du HTML sans le blob JSON. Verifier `[]` retourne sans exception.

7. **`TestFetchAll.test_tier1_preferred`** : `cfg.tiktok_bridge_base_url` defini,
   `fetch_via_bridge` retourne 2 items → `fetch_via_scraping` ne doit **pas**
   etre appele (verifier via `patch`). Verifier 2 items retournes.

8. **`TestFetchAll.test_tier2_fallback_when_bridge_fails`** : `cfg.tiktok_bridge_base_url`
   defini, `fetch_via_bridge` retourne `[]`, `fetch_via_scraping` retourne
   1 item. Verifier 1 item retourne.

9. **`TestFetchAll.test_tier3_degraded_no_items`** : `cfg.tiktok_bridge_base_url`
   non defini, `fetch_via_scraping` retourne `[]`. Verifier que `collect`
   ne yield rien et ne leve pas d'exception.

10. **`TestSignalSourceMapping.test_detected_at_is_datetime`** : verifier que
    `detected_at` est toujours un `datetime` (pas une string, pas `None`) pour
    une entree RSS valide et pour une entree sans `published_parsed`.

11. **`TestKeywords.test_tiktok_hashtags_defined`** : importer `TIKTOK_HASHTAGS`
    depuis `detecteur_signaux.keywords` et verifier `len(TIKTOK_HASHTAGS) >= 8`.

12. **`TestKeywords.test_source_weights_tiktok`** : verifier
    `SOURCE_WEIGHTS["tiktok"] == 10`,
    `SOURCE_WEIGHTS["tiktok @60millions"] == 25`,
    `SOURCE_WEIGHTS["tiktok @dgccrf"] == 30`.

**Fixtures a creer :**

`tiktok_bridge_feed.xml` : flux Atom minimal avec 2 `<entry>` valides,
incluant `<title>`, `<link>`, `<published>`, `<summary>`, `<author><name>`.
Les valeurs doivent etre en ASCII pur (contrainte CLI).

`tiktok_hashtag_page.html` : page HTML minimale avec le script contenant
`__UNIVERSAL_DATA_FOR_REHYDRATION__ = {"VideoFeedPage":{"videoList":[...]}}`.
2 videos avec les champs `id`, `desc`, `createTime`, `author.uniqueId`,
`stats.playCount`. Utiliser des valeurs ASCII uniquement.

---

### T6 — Mettre a jour le README de l'agent [XS]

**Fichiers touches :**
- `agents/detecteur_signaux/README.md`

**Depend de :** T4

**Critere d'acceptation :**

1. La section "Sources" (ou equivalente) mentionne TikTok avec les variables
   d'env `TIKTOK_BRIDGE_BASE_URL` et `TIKTOK_USER_AGENT`.
2. La commande CLI `--sources tiktok` apparait dans un exemple.
3. Une note sur le statut legal (zone grise ToS, best-effort, pas de SLA) est
   presente — reprendre la formulation de l'ADR §Risques.
4. La liste des hashtags par defaut (`TIKTOK_HASHTAGS`) est mentionnee avec le
   pointeur vers `keywords.py`.

**Description :**

Ajouter une section `### Source TikTok` dans le README existant. Pas de
documentation de design — uniquement ops : comment configurer, quoi attendre
en production, et la mention legale obligatoire pour le client.

---

## Risques identifies

- **Blob JSON `__UNIVERSAL_DATA_FOR_REHYDRATION__` peut changer de nom** :
  le parseur du tier 2 doit etre defensif (retourner `[]` silencieusement).
  Prevoir un test snapshot commite dans `tests/fixtures/` pour detecter les
  regressions.
- **feedparser et les flux Atom TikTok non standard** : le bridge RSS peut
  produire des champs non conventionnels (pas de `author` standard, `view_count`
  dans un namespace custom). Le mapping doit rester defensif (`.get()` partout,
  pas d'acces direct a des attributs potentiellement absents).
- **Import circulaire** : `sources/tiktok.py` importe de `keywords.py` et
  `models.py`, comme les autres sources. Respecter exactement le meme schema
  d'imports que `google_news.py` pour eviter tout cycle.
- **Windows cp1252** : `TIKTOK_HASHTAGS` contient uniquement des caracteres
  ASCII (pas d'accents, pas d'emoji) → aucun risque. Les descriptions TikTok
  peuvent contenir de l'UTF-8 — tronquer a 2000 chars et encoder en ASCII
  `errors="replace"` dans les sorties CLI si necessaire.

---

## Hors scope (explicitement)

- **Transcription audio (Whisper, ffmpeg)** : stade 2 uniquement, conditionne
  a un ADR suivant. Ne pas creer de stub ou de placeholder.
- **OCR sur frames video** : stade 2.
- **Option 6 (Apify/Bright Data)** : reevaluation si RSS-bridge casse > 2x/an.
  Pas de code prevu maintenant.
- **Deploiement RSS-bridge** : hors scope Python — operations VPS a specifier
  separement.
- **Scraping des commentaires TikTok** : interdit RGPD (cf. ADR §RGPD).
- **Purge RGPD 30 jours** : a specifier dans un ADR ops dedie (hors scope T1-T6).
- **Modification du schema SQLite** : aucune migration necessaire — `source_type`
  accepte deja toute string.
- **Modification de `extractor.py`, `scorer.py`, `cross_reference.py`,
  `deduplicator.py`** : aucun changement structural requis (cf. ADR §Consequences).
- **Calibration des poids `SOURCE_WEIGHTS`** : T1 pose les valeurs initiales de
  l'ADR. La recalibration apres observation est hors scope de ce plan.
