# ADR 006 — Source TikTok pour l'Agent 4 (detecteur_signaux)

**Statut :** Propose
**Date :** 2026-05-12

## Contexte

L'Agent 4 `detecteur_signaux` agrege aujourd'hui deux sources (`google_news`
RSS et `reddit` JSON public) via le pattern collector pluggable defini dans
`agents/detecteur_signaux/sources/registry.py`. Chaque collector retourne des
`SignalSource` (`source_type`, `source_name`, `source_url`, `titre`,
`detected_at`, `contenu`) consommes ensuite par `extractor.py` (LLM Haiku +
fallback regex), `deduplicator.py`, `scorer.py` et `cross_reference.py`.

Le client veut etendre la detection aux **plaintes consommateurs sur TikTok**
(intoxications publiques, hashtags du type `#rappelproduit`, videos virales
sur un lot defectueux). Le rationale metier : un signal TikTok precede souvent
de plusieurs jours la publication RappelConso (videos d'intox personnelles,
mise en cause publique d'une marque), ce qui ameliore directement le
`lead_time_days` calcule par `cross_reference.py`.

Probleme : contrairement a Google News et Reddit, **TikTok ne propose pas de
flux public stable**. Les contenus sont des **videos** (pas du texte), avec
des sous-titres dynamiques, audio franc et OCR a l'ecran. Toute la valeur
extractive (marque, produit, symptome) est dans le pixel et l'audio, pas
dans la description textuelle (souvent vide ou genre "regardez ca lol").

Contraintes EverTrack a respecter :
- pattern `sources/<nom>.py` + `@register("nom")` + `SourceConfig`,
- stdlib + `requests` + `feedparser` en priorite,
- LLM **fallback-first** (la source doit retourner *quelque chose* sans cle
  API ni binaire ffmpeg),
- ASCII-only CLI, tests `unittest` avec mocks,
- conformite RGPD (donnees personnelles dans les videos : visages, voix,
  pseudos),
- contrat de sortie : `SignalSource` immuable (extractor downstream).

## Decision drivers

1. **Cout** : zero ou marginal a date (le projet tourne sur API gratuites + Haiku).
2. **Legalite** : ToS TikTok + RGPD France (videos = donnees personnelles).
3. **Fiabilite** : TikTok casse regulierement les endpoints non officiels.
4. **Complexite** : eviter l'usine a gaz (ffmpeg, Whisper, OCR) si retour faible.
5. **Coherence pipeline** : la source doit produire un `SignalSource` consommable
   par l'extractor existant, **avec du texte exploitable**.
6. **Fallback-first** : si TikTok bloque ou retire un endpoint, l'agent doit
   continuer a fonctionner.

## Options considerees

Les options se rangent en deux familles : **acces aux metadonnees** (titre,
description, hashtags, auteur) — extractible directement par le pipeline
existant — et **acces au contenu video** (audio + frames) — necessite un
pre-traitement LLM avant d'entrer dans `extractor.py`.

### Sans LLM (acces metadonnees uniquement)

#### Option 1 — TikTok Research API (officielle)

- **Approche** : endpoints REST officiels `open.tiktokapis.com/v2/research/video/query/`
  filtrant par hashtag, mot-cle, region (FR), date. Renvoie JSON :
  `id`, `video_description`, `create_time`, `hashtag_names`, `view_count`,
  `username`.
- **Auth** : OAuth 2.0 client credentials (`TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`).
- **Eligibilite** : reserve aux **chercheurs academiques** (universite, journaliste
  accredite). Application formelle, delai ~4-8 semaines, refus frequent pour
  usage commercial. Disponibilite UE elargie depuis le DSA (2024), mais la
  qualification "chercheur" reste exigee.
- **Cout** : gratuit si accepte.
- **Quota** : 1000 requetes/jour, 100 videos/requete = ~100k videos/jour.
- **Legalite** : 100% conforme ToS.
- **Fiabilite** : haute (API versionnee, deprecation annoncee).
- **Complexite** : moyenne (OAuth, pagination, gestion token).
- **Dependances** : `requests` seul.
- **Bloquant** : **non eligible** pour un editeur SaaS commercial.

#### Option 2 — TikTok Display API (officielle, sans recherche par mot-cle)

- **Approche** : API publique limitee a la **lecture du contenu d'un user
  authentifie** (login OAuth). Pas de search par hashtag global.
- **Inutilisable** pour une veille externe : il faudrait que les consommateurs
  loggent leur compte TikTok dans EverTrack. Disqualifie d'emblee.

#### Option 3 — Scraping web non authentifie (`https://www.tiktok.com/tag/<hashtag>`)

- **Approche** : GET sur la page hashtag, extraction du blob
  `__UNIVERSAL_DATA_FOR_REHYDRATION__` (JSON inline dans le HTML) qui contient
  la liste des videos.
- **Auth** : aucune ; cookies anti-bot (`tt_webid`, `msToken`) generes a la
  premiere visite.
- **Cout** : zero.
- **Legalite** : zone grise. Le `robots.txt` autorise `/`. Les ToS interdisent
  le scraping automatise — non-respect = risque de blacklist IP, pas
  d'action legale en pratique pour de la veille a faible volume FR.
- **Fiabilite** : **basse**. TikTok modifie regulierement la cle JSON
  (`__UNIVERSAL_DATA_*` → autres noms), bloque les IP datacenter, exige du JS
  via challenge `ttwid`. Casse observee a 3-6 mois.
- **Complexite** : moyenne a haute (gestion cookies, retry, parseur JSON
  defensif).
- **Dependances** : `requests` + selecteur HTML (`re` stdlib suffit pour
  extraire le blob).
- **Limite donnees** : pas de pagination publique propre (~30 videos par hit
  hashtag), recence limitee.

#### Option 4 — Librairies tierces non officielles (`TikTokApi` davidteather, `tiktok-scraper`)

- **Approche** : wrappers Python qui automatisent la generation de tokens
  (`msToken`, `ttwid`) via un navigateur headless (`playwright`).
- **Auth** : aucune cote utilisateur, mais cookies generes par browser.
- **Cout** : zero.
- **Legalite** : enfreint les ToS comme Option 3.
- **Fiabilite** : tres basse. `TikTokApi` (10k stars GitHub) a connu **plusieurs
  mois de panne** en 2024 et 2025 entre deux versions, communaute reactive
  mais pas de SLA.
- **Complexite** : faible cote code (3-4 appels), **haute** cote runtime :
  necessite `playwright` (Chromium 200+ Mo) + un proces navigateur en background.
- **Dependances** : `TikTokApi>=6`, `playwright`, Chromium installe.
- **Incompatible** avec la regle EverTrack "stdlib + requests + feedparser,
  pas de dependances lourdes".

#### Option 5 — RSS-bridge (instance auto-hebergee ou publique)

- **Approche** : `rss-bridge` est un projet PHP open source qui expose des
  pages publiques sous forme de flux RSS. Bridge `TikTokBridge` existe.
- **Auth** : aucune.
- **Cout** : zero (auto-heberge) ou aleatoire (instances publiques).
- **Legalite** : meme zone grise qu'Option 3 (RSS-bridge scrape en interne).
- **Fiabilite** : depend de la maintenance du bridge — historiquement
  `TikTokBridge` casse souvent. **Instances publiques** souvent rate-limitees,
  pas de SLA.
- **Complexite** : faible cote integration (`feedparser`, deja en deps !),
  haute cote ops (auto-heberger PHP).
- **Dependances** : `feedparser` (deja la).
- **Avantage majeur** : code de collection cote EverTrack identique a
  `google_news.py` (RSS → SignalSource). C'est l'option qui s'integre le **plus
  proprement** dans le pipeline existant.

#### Option 6 — Services tiers payants (Apify, Bright Data, ScrapingBee, EnsembleData)

- **Approche** : API hostees qui s'occupent du scraping + rotation IP + tokens.
- **Auth** : cle API.
- **Cout** :
  - Apify : ~0,30 USD pour 1000 videos (acteur `clockworks/tiktok-scraper`).
  - Bright Data : ~3 USD / 1000 enregistrements.
  - EnsembleData : ~0,001 USD / requete, plan starter 50 USD/mois.
- **Legalite** : le fournisseur prend a sa charge la conformite ToS (cf. Hi-Q
  vs LinkedIn et la jurisprudence post-Van Buren).
- **Fiabilite** : haute (SLA, ils maintiennent en cas de casse TikTok).
- **Complexite** : tres faible (1 appel REST).
- **Dependances** : `requests` seul.
- **Bemol** : cout recurrent et dependance commerciale.

### Avec LLM (acces au contenu video)

Necessaires uniquement si les **metadonnees ne suffisent pas** (titre vide ou
non descriptif, infos visuelles uniquement dans la video). A combiner avec
l'une des options 1-6 pour acceder a l'URL de la video.

#### Option 7 — Transcription audio (Whisper local ou API OpenAI)

- **Approche** : telecharger le `.mp4` (URL CDN publique sortie par les
  Options 3-6), extraire l'audio (ffmpeg), transcrire avec
  `whisper.cpp` (local) ou `openai/whisper-1` (API).
- **Cout** : Whisper local = CPU/GPU ; OpenAI API = ~0,006 USD/minute.
  Une video TikTok = 30s = 0,003 USD.
- **Complexite** : haute. Dependance binaire **ffmpeg** + Whisper installe,
  ou cle API supplementaire. Pipeline asynchrone (telechargement + queue).
- **Bemol majeur** : impose ffmpeg en dependance systeme — incompatible avec
  la regle stdlib-first et le deploiement Windows actuel.

#### Option 8 — OCR sur frames cles (texte affiche a l'ecran)

- **Approche** : extraction de 3-5 frames de la video, OCR via `tesseract` ou
  Vision API Claude.
- **Cout** : tesseract local = gratuit ; Claude Vision = ~0,003 USD par frame
  Haiku.
- **Complexite** : haute (ffmpeg pour frames + OCR).
- **Pertinence** : 80% des videos TikTok "intox" sont legendees en texte
  incruste — fort potentiel **mais** infrastructure lourde.

#### Option 9 — Synthese Claude sur metadonnees enrichies

- **Approche** : pas de traitement video, mais Claude Haiku synthese
  description + hashtags + commentaires top-5 pour produire un `contenu`
  exploitable par `extractor.py`. C'est **redondant** avec ce que fait deja
  `extractor.py`.
- **Disqualifie** : double appel LLM sans valeur ajoutee, hors scope ADR.

## Tableau comparatif (options finalistes)

| Critere | Opt 1 Research API | Opt 5 RSS-bridge | Opt 6 Apify | Opt 3 Scraping direct |
|---|---|---|---|---|
| Cout | Gratuit (si eligible) | Gratuit | ~0,30 USD/1000 | Gratuit |
| Eligibilite | Reservee chercheurs | Tous | Tous | Tous |
| Conformite ToS | Oui | Non (gris) | Externalise | Non (gris) |
| Fiabilite | Haute | Basse-moyenne | Haute | Basse |
| Complexite code | Moyenne | **Faible** (RSS) | **Tres faible** | Moyenne-haute |
| Dependances ajoutees | `requests` | aucune (feedparser deja la) | `requests` | `requests` + regex |
| Quota | 1000 req/j | aucun | budget cap | non documente |
| Maintenance | Faible | Forte | Faible (sous-traitee) | Forte |
| Fallback-first compat | Oui | Oui | Non (cle obligatoire) | Oui |

## Decision

Adopter une approche **multi-tier, fallback-first**, sans appel LLM video
au stade 1 :

1. **Tier prefere : Option 5 — RSS-bridge auto-heberge** sur le meme VPS qui
   hebergera plus tard EverTrack. Endpoint expose
   `https://rssbridge.evertrack.internal/?action=display&bridge=TikTok&context=...&format=Atom`.
   La source EverTrack reutilise `feedparser` (deja en deps), code calque sur
   `google_news.py`.
2. **Tier degrade : Option 3 — scraping direct** `tiktok.com/tag/<hashtag>` via
   `requests`, parse defensif du blob JSON inline. Active si RSS-bridge KO
   pendant > 1h (circuit breaker).
3. **Tier disable : aucune source TikTok** si les deux precedents echouent.
   L'agent continue avec Google News + Reddit seuls (fallback-first respecte).

**Pas de transcription video ni d'OCR au stade 1.** On extrait uniquement :
`video_description`, `hashtag_names`, `author_username`, `create_time`,
`view_count`. Les hashtags ciblee fournissent deja un fort signal taxonomique
(`#rappelproduit`, `#intoxalimentaire`, `#salmonellose`, `<marque>`).

**Si le ROI metier le justifie au stade 2** (~3 mois apres mise en prod, sur
mesure du `lead_time_days` median), instruire un ADR suivant pour ajouter
Option 7 (transcription Whisper API) **conditionnellement** aux videos
`view_count > N` et hashtag fort, pour limiter le cout.

### Pourquoi pas les autres

- **Option 1** : non eligible (commercial).
- **Option 4** (TikTokApi davidteather) : impose Chromium en deps, viole la
  regle stdlib-first, instabilite documentee.
- **Option 6** (Apify/Bright Data) : excellent en fiabilite mais cree une
  dependance commerciale payante recurrente alors que le pipeline est
  encore en validation. A reevaluer si RSS-bridge casse trop souvent.
- **Options 7-9** (video LLM) : ratio cout/complexite eleve avant d'avoir
  mesure que les metadonnees ne suffisent pas.

## Contrat d'integration dans le pipeline

### Fichier : `agents/detecteur_signaux/sources/tiktok.py`

Squelette aligne sur `google_news.py` :

```python
@register("tiktok")
def collect(cfg: SourceConfig) -> Iterator[SignalSource]:
    yield from fetch_all(
        hashtags=cfg.tiktok_hashtags,
        bridge_base_url=cfg.tiktok_bridge_base_url,
    )
```

Retourne des `SignalSource` :
- `source_type = "tiktok"`
- `source_name = "TikTok @<username>"` (visible dans les drawers dashboard)
- `source_url = "https://www.tiktok.com/@user/video/<id>"`
- `titre` = video_description tronquee a 200 chars (le titre n'existe pas en
  tant que tel sur TikTok)
- `detected_at` = `create_time` (date publication video, **pas** crawl —
  cf. regle `detected_at` du CLAUDE.md)
- `contenu` = description complete + hashtags concatenes (alimentera
  `extractor.py` pour marque/produit/symptome)

### Fichier : `agents/detecteur_signaux/sources/config.py`

Ajout des champs :

```python
# --- TikTok ---------------------------------------------------------
tiktok_hashtags: Optional[list[str]] = None    # default = TIKTOK_HASHTAGS
tiktok_bridge_base_url: Optional[str] = None   # ex: http://localhost:3500
tiktok_min_view_count: int = 1000              # filtre bruit
```

### Fichier : `agents/detecteur_signaux/keywords.py`

Ajouts :

```python
TIKTOK_HASHTAGS = [
    "rappelproduit", "rappelconso", "intoxalimentaire",
    "salmonelle", "listeria", "alertealimentaire",
    "produitcontamine", "alimentdangereux",
]

# Pondere bas par defaut : TikTok = signal grand public, faible verifiabilite
SOURCE_WEIGHTS["tiktok"] = 10
# Override si compte verifie / journaliste / autorite sanitaire :
SOURCE_WEIGHTS["tiktok @60millions"] = 25
SOURCE_WEIGHTS["tiktok @dgccrf"] = 30
```

Logique de poids : un `source_name = "TikTok @<user>"` matche d'abord la cle
specifique (`"tiktok @60millions"`) sinon retombe sur la cle generique
(`"tiktok"`). Pattern deja en place pour `r/<sub>` vs default reddit.

### Impact sur `deduplicator.py`

Aucun changement de schema. `compute_signal_id` continue de hasher
`marque + symptome + jour` quand l'extractor LLM remplit ces champs depuis
la description + hashtags. Un meme incident remonte par Google News + TikTok
fusionne automatiquement (meme signal_id) — le `recurrence` score grimpe de
+10 points → comportement souhaite.

Edge case : si la video TikTok n'expose ni marque ni symptome (description
vide), `compute_signal_id` retombe sur le niveau `title|titre|jour` → risque
de doublons faibles. Acceptable au stade 1 ; ces signaux seront filtres
par le seuil 40 (poids TikTok 10 + recency 15 + sentiment 5 = 30, sous seuil).

### Impact sur `scorer.py` et `cross_reference.py`

Aucun changement structurel. Les 5 composantes scoring + les 4 dimensions
cross-ref s'appliquent telles quelles.

### Impact CLI

```bash
python -m detecteur_signaux.cli fetch --sources tiktok
python -m detecteur_signaux.cli fetch --sources google_news,reddit,tiktok
```

Pas de nouvelle commande. La liste `--sources` accepte tout nom du registry.

### Tests

`tests/test_tiktok.py` (`unittest`, MagicMock sur `requests.get`) :
- parse d'un feed RSS-bridge fixture (XML statique embarque dans le test),
- fallback scraping direct quand RSS-bridge renvoie 502,
- mapping correct `create_time` ISO → `datetime`,
- `contenu` concatene description + hashtags,
- skip des videos `view_count < tiktok_min_view_count`.

LLM jamais appele (extractor mocke comme pour les autres sources).

## Variables d'environnement

| Variable | Obligatoire ? | Usage |
|---|---|---|
| `TIKTOK_BRIDGE_BASE_URL` | Recommandee | URL de l'instance RSS-bridge auto-hebergee. Vide → fallback scraping direct. |
| `TIKTOK_USER_AGENT` | Optionnelle | UA custom pour le scraping direct. Default = celui de google_news.py. |

Pas de cle API, pas de secret a stocker (RSS-bridge interne).

## Risques et points d'attention

### ToS et legalite

- Le scraping de TikTok et l'utilisation d'un RSS-bridge violent
  techniquement les **Terms of Service** TikTok (clause anti-automatisation).
  Aucun cas connu de poursuite civile en France pour de la veille a faible
  volume (< 1000 requetes/jour). Le risque concret est le **blocage IP**,
  pas un proces.
- L'editeur SaaS client doit etre informe par ecrit : la source TikTok est
  **best-effort**, sans SLA, et peut etre coupee a tout moment.

### RGPD

- Les videos TikTok publiques sont des **donnees personnelles** (image,
  voix, pseudo). Base legale : interet legitime B2B (article 6.1.f RGPD)
  pour la prevention d'incidents sanitaires.
- **A ne pas faire** : stocker la `.mp4` en local, faire de la
  reconnaissance faciale, retenir le contenu apres rejet humain du signal.
- **Mesure** : ajouter dans `storage.py` un job de purge des `signaux_sources`
  TikTok rejetes apres 30 jours (`status='rejete' AND source_type='tiktok'`).
  A specifier dans un ADR ops dedie.
- Pas de scraping des **commentaires** (donnees personnelles de tiers
  non-publics au sens du DSA).

### Perennite

- L'instance RSS-bridge peut casser a chaque mise a jour TikTok. Plan :
  monitoring simple (`/healthz` sur le bridge, alerte si > 0 video remontee
  dans les dernieres 24h alors qu'on en avait 50+ avant). Bascule manuelle
  vers Option 6 (Apify) si la casse dure > 1 semaine.
- Le scraping direct (tier 2) est encore plus fragile : prevoir des
  asserts defensifs dans le parseur JSON inline et un test snapshot sur
  un fichier HTML reel committee dans `tests/fixtures/`.

### Cout cache

- Volume estime : 8 hashtags x 30 videos = ~240 items/run, 1-2 runs/jour =
  ~500 items/jour. Negligeable cote bande passante et cout LLM
  (`extractor.py` = 500 * 0,0005 EUR ≈ 0,25 EUR/jour, en ligne avec
  l'estimation Agent 4 actuelle).

## Consequences

**Positives**
- 3e source qui augmente le `recurrence` score sur les vrais incidents
  (Google News + Reddit + TikTok), donc plus de signaux dans la zone
  `score >= 40` → meilleure couverture pour le dashboard.
- Reutilisation maximale du pipeline existant : aucun changement de schema
  SQLite, ni des modules `scorer`, `cross_reference`, `deduplicator`,
  `extractor`. Seul `sources/tiktok.py` + 1 entree `keywords.py` +
  3 lignes dans `config.py` + tests.
- Tier RSS-bridge permet une transition douce vers Apify (Option 6) si la
  fiabilite devient insuffisante — meme contrat de sortie `SignalSource`.
- Pas de ffmpeg, pas de Chromium, pas de cle API additionnelle au stade 1.

**Negatives / dette**
- Operationnel : un VPS doit faire tourner RSS-bridge (~50 Mo RAM, PHP-FPM).
  Hors stack Python du projet — premier service non-Python a maintenir.
- Fiabilite intrinseque basse : casse attendue tous les 3-6 mois cote
  bridge ou scraping direct. Necessite un mainteneur reactif.
- Signal TikTok intrinsequement bruite (memes, troll, plaintes non sourcees).
  Poids 10 par defaut est un parti pris **conservateur**, mais sous-evalue
  potentiellement les comptes verifies (DGCCRF, 60M consommateurs). A
  recalibrer apres 50-100 signaux observes.
- Pas de transcription video → on rate les videos sans description
  textuelle. Estime a 30-50% du volume "intox" sur TikTok (a confirmer
  par echantillonnage manuel).

**A surveiller**
- Taux de casse mensuel du bridge (alerte healthz).
- Distribution des scores TikTok vs Google News / Reddit (dashboard stats).
  Si median TikTok < 25, le seuil 40 elimine 90%+ → reflechir a un seuil
  par source ou a un boost `view_count`.
- ROI lead_time : si les signaux TikTok n'ameliorent pas le `lead_time_days`
  median > 1 jour vs Google News + Reddit seuls, retirer la source.
- Volume RGPD : taux de signaux TikTok rejetes par l'humain (proxy bruit).
  Si > 70%, repenser la liste des hashtags ou le poids.

## Points ouverts a valider

1. **Hashtags cibles** : la liste proposee (`rappelproduit`, `intoxalimentaire`,
   etc.) est un point de depart. Le client a-t-il une liste de marques
   prioritaires a inclure comme hashtags (`#carrefour`, `#lactalis`) ?
2. **Hebergement RSS-bridge** : meme VPS qu'EverTrack ou service dedie ?
   Impacte le scope ops du projet.
3. **Strategie escalade payante** : si RSS-bridge casse plus de 2x/an, on
   bascule sur Apify (cout ~5 EUR/mois). Le client valide ce budget par
   anticipation ?
4. **Stade 2 video LLM** : critere de declenchement (lead_time median trop
   bas ? volume de signaux TikTok exploitables trop bas ?). A trancher dans
   un ADR suivant.
5. **Purge RGPD** : 30 jours apres rejet humain, ou plus court ? Aligner sur
   la politique de conservation generale d'EverTrack quand elle sera ecrite.
