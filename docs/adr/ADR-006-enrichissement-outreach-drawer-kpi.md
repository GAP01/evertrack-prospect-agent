# ADR 006 — Enrichissement du contenu outreach par exemple + drawer KPI graphiques

**Statut :** Propose
**Date :** 2026-05-12
**Remplace / etend :** ADR-005 (Redacteur outreach) — extension stylistique + UX

---

## 1. Contexte

Deux composants livres et stabilises sont aujourd'hui en service :

### Agent 5 — `redacteur_outreach`
- `agents/redacteur_outreach/template_renderer.py` (l.170-212) rend un brouillon
  deterministe a partir de `templates/email_fr.txt` (template `string.Template`
  de 16 lignes, structure fixe : salutation, contexte rappel, motif, bloc signaux
  optionnel, pitch_court, valeur_immediate, cta, signature, opt_out).
- `agents/redacteur_outreach/llm_rewriter.py` (l.44-85, l.250-355) reecrit ce
  brouillon via 2 appels Claude Haiku (corps puis objet) avec deux garde-fous :
  - hallucination numerique (`_build_allowed_tokens` l.153-170 + check l.336-342),
  - ASCII strict (l.328-330).
- Le statut resultant est `a_valider` si LLM OK, `brouillon` si LLM skip
  (`redacteur.py` l.152-173).
- Config editeur : `pitch.json` charge par `pitch_loader.py` (clefs
  `pitch_court`, `valeur_immediate`, `cta`, `signature`, `opt_out_placeholder`).

Aujourd'hui le LLM recoit **uniquement** le `body_fallback` + un resume de contexte
formel (`_summarize_context` l.91-145). Le ton produit est sobre mais generique,
sans aucune trace du style commercial reel de Gautier (le client final).

### Dashboard — drawer outreach
- `agents/dashboard_reflex/dashboard_reflex/components/outreach_drawer.py`
  (l.250-392) : drawer lateral droit `width="480px"`, `max_width="95vw"`,
  `position="fixed"`, `right="0"`, `left="auto"` (vaul anti-injection).
- Contenu actuel : badge statut, tracabilite (LLM utilise, dates), objet, corps
  monospace en lecture seule + boutons (Generer, Valider, Rejeter, Regenerer,
  Marquer envoye, Copier).
- **Aucune visualisation graphique**. Le commercial qui valide doit basculer vers
  les drawers Incident / Signal / Prospect pour voir score, signaux croises,
  enrichissement — coupant son flux de decision.

### Donnees deja disponibles cote dashboard
- `services/data.py` expose deja get_stats, get_signaux, get_match_stats,
  enrichissements (lecture des 4 SQLite).
- Le `context_json` est fige a la generation dans `messages.context_json`
  (`redacteur.py` l.111) : contient incident + score + enrichissement + signaux_summary.

---

## 2. Problematique

### Axe 1 — Style d'email peu personnalise

Le client a un **exemple de mail reel** qui convertit bien (ton consultatif,
phrasage particulier, ordre rhetorique custom). Il veut que l'agent s'inspire
de ce style sans le copier mot pour mot, et sans casser :
- le **fallback deterministe** sans cle (statut `brouillon` doit rester
  utilisable tel quel) ;
- les **garde-fous hallucination** (set de tokens numeriques autorises) — un
  exemple riche en chiffres peut polluer ce set ;
- la **compatibilite ascendante** : ~N messages en base avec
  `redacteur_version="1.0"` ne doivent pas devenir invalides ; on doit pouvoir
  les regenerer ou les laisser tels quels ;
- le **budget token** : un exemple de 500 mots double les input tokens des
  2 appels Haiku, acceptable mais a mesurer ;
- la **contrainte ASCII** (Windows cp1252) — l'exemple humain contiendra
  certainement des accents, il faudra les normaliser **a l'ingestion**
  (`unicodedata.normalize`) pas en sortie.

### Axe 2 — Drawer outreach aveugle

Pour decider "valider / rejeter / regenerer", le commercial veut voir d'un coup
d'oeil :
- le **score sanitaire** (tier, dimensions),
- la **couverture mediatique** (nb sources, recurrence),
- la **fraicheur** du dossier (delai rappel <> aujourd'hui),
- la **qualite du contact** (confidence enrichissement, type cible/dirigeant).

Sans quitter le drawer outreach et **sans charger un dashboard dans le dashboard**.

Contraintes techniques :
- `rx.recharts.*` deja inclus dans Reflex 0.9 — pas de nouvelle depend.
- Pas de N+1 query : tout doit venir du `context_json` deja stocke OU d'un seul
  fetch dashboard.
- Mobile <640px : le drawer occupe deja 95vw, les charts doivent stack ou se
  masquer proprement.
- Le `selected_outreach` Var Reflex doit etre etendu sans casser les
  normalizers existants.

---

## 3. Options

### Axe 1 — Injection d'un exemple stylistique

#### Option A — Fichier `style_examples/*.txt` + injection few-shot dans le system prompt

- **Approche** : creer `agents/redacteur_outreach/style_examples/` contenant
  1 a N fichiers texte (`example_default.txt`, eventuellement
  `example_severite_haute.txt`, `example_signal_only.txt`). Le `llm_rewriter`
  selectionne 1 exemple (selection par defaut = `example_default.txt`,
  selection avancee = matching sur tier/source — V2) et l'injecte dans
  `_SYSTEM_BODY` sous la forme :
  ```
  Voici un exemple du style attendu (ne pas recopier le contenu, seulement
  imiter le ton, la structure narrative et les tournures) :
  <STYLE_EXAMPLE>
  {exemple}
  </STYLE_EXAMPLE>
  ```
- **Tokens autorises** : on **n'ajoute pas** les chiffres de l'exemple au set
  autorise (sinon on autorise des hallucinations). L'instruction systeme dit
  explicitement "n'utilise aucun chiffre present uniquement dans l'exemple".
- **Normalisation** : `unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()`
  a l'ingestion -> fichier source peut etre UTF-8 avec accents.
- **Pour** :
  - Migration minime : 1 fichier ajoute + ~20 lignes dans `llm_rewriter.py`.
  - Le fallback deterministe est **strictement inchange** (template intact).
  - Selection multi-exemples reste extensible (tier-based, source-based).
  - Idempotence preservee : `message_id` ne change pas, `pitch_version` peut
    bumper a `1.1` pour distinguer les nouvelles generations a l'audit.
- **Contre** :
  - +400-800 tokens input par appel Haiku (cout marginal, ~1ct / msg).
  - Si l'exemple est tres specifique a un cas (ex: produit congele
    listeria), le LLM peut transferer le contexte de l'exemple — risque
    "leakage". Mitige par l'instruction "n'imite que la forme".

#### Option B — Fine-tuning leger via prompt caching Anthropic

- **Approche** : utiliser le prompt caching (cache_control) d'Anthropic sur le
  bloc `<STYLE_EXAMPLE>` + system prompt. Premier appel paye plein tarif,
  suivants paient 10% sur la partie cachee.
- **Pour** : cout reduit a l'echelle (>1000 msg/mois).
- **Contre** :
  - Volume actuel = quelques dizaines/mois -> economie negligeable.
  - Complexite supplementaire (TTL cache 5 min, beta header, requires SDK >=
    une version specifique). Sort du principe "stdlib first".
  - Pas de fine-tuning Anthropic disponible — l'option "vrai fine-tune" est hors
    perimetre.

#### Option C — Re-ecriture du template `email_fr.txt` pour matcher la structure de l'exemple, LLM uniquement pour fluidite

- **Approche** : Gautier extrait la **structure narrative** de son exemple
  (ex: "accroche-question / constat factuel / contexte regulatoire / pitch /
  CTA doux"), on ecrit un nouveau `email_fr.txt` qui reflete cette structure,
  et le LLM ne fait que polir. Pas de fichier d'exemple distinct.
- **Pour** :
  - Le fallback deterministe **profite directement** du nouveau style
    (les statuts `brouillon` deviennent immediatement meilleurs).
  - Aucune surface LLM ajoutee, donc aucun risque d'hallucination supplementaire.
- **Contre** :
  - Demande a Gautier un **travail d'abstraction** (passer du texte plein au
    template parametre) qu'il pourrait ne pas vouloir faire.
  - Moins de flexibilite : changer le style necessite editer le template
    (vs ajouter un .txt).
  - Mono-style : pas de variation tier / source possible sans dupliquer le
    template.
  - Risque d'**uniformite** : tous les messages auront EXACTEMENT la meme
    structure, le LLM ne pourra plus varier les tournures.

---

### Axe 2 — Drawer KPI graphique

#### Option D — Drawer reste a droite, elargi a 720px desktop, layout vertical KPI -> corps

- **Approche** : passer `width="720px"` (vs 480px actuellement), ajouter en
  haut sous "ACTIONS" une zone "INSIGHTS" avec 3 charts en grid 3-col desktop,
  stack-vertical mobile (`@media (max-width: 640px)`).
- KPI proposes (3 max, focus decision) :
  1. **Score sanitaire** — `rx.recharts.radial_bar_chart` (gauge 0-100) avec
     les 4 dimensions en sous-barres horizontales (risque, ampleur,
     vulnerabilite, volume).
  2. **Signaux croises** — `rx.recharts.bar_chart` horizontal des sources
     mediatiques (axe Y = source_name, axe X = nb articles, max 5 sources).
     Lit `signaux_summary` du `context_json`.
  3. **Confidence prospect** — pastille colorée + label (gauge simple en
     `rx.progress` Radix, pas un chart) : "Contact cible 0.82" /
     "Fallback dirigeant 0.55" / "Non trouve".
- **Pour** :
  - Continuite UX : drawer reste a droite, le commercial garde son repere
    spatial.
  - 720px = ~50% d'un ecran 1440p, le contenu derriere reste visible (table
    prospects).
  - Mobile : `max_width="95vw"` deja en place -> stack vertical auto.
  - Toutes les donnees viennent du `context_json` **deja stocke** (zero
    requete supplementaire) -> aucun N+1.
- **Contre** :
  - 3 charts dans un drawer de 720px = densite forte, risque "petit ecran
    desktop 1280x800" (charts ecrases).
  - Reflex `rx.recharts` a parfois des soucis de redimensionnement en drawer
    (height fixe necessaire, pas `100%`).

#### Option E — Drawer plein ecran (modal) avec split layout 60/40

- **Approche** : `width="100vw"` (ou 90vw), 2 colonnes — gauche 60% =
  KPI graphiques + meta, droite 40% = objet + corps + actions. Direction
  vaul peut rester right ou passer en bottom-sheet sur mobile.
- **Pour** : place pour 4-5 KPI bien aerés, lecture confortable du corps en
  parallele.
- **Contre** :
  - Rupture UX : tous les autres drawers du dashboard (incident, signal,
    prospect) sont a 560-640px a droite -> incoherence visuelle.
  - Le commercial perd le contexte de la table prospects derriere.
  - Mobile : pas d'amelioration vs option D (deja 95vw).
  - Complexite layout : split + media queries + drawer plein = plus de bugs
    CSS (cf piege `left="auto"` vaul deja rencontre dans ADR-005-bis non
    formalise).

#### Option F — Pas de chart dans le drawer, ajout d'une **strip KPI compacte** (badges + sparklines inline)

- **Approche** : conserver drawer 480px, ajouter une zone "INSIGHTS" de
  60-80px de haut juste sous actions, contenant 4 petits "chips" :
  - badge tier (Critique/Haut/Moyen/Bas, deja colore),
  - chip score (texte "82/100" + barre fine 4px sous le chiffre),
  - chip signaux ("3 signaux / 2 sources" + dot par source),
  - chip contact ("Cible 0.82" ou "Dirigeant 0.55", couleur green/amber).
- Pas de `rx.recharts` du tout — uniquement composants Radix + box CSS.
- **Pour** :
  - Aucune nouvelle depend / aucun risque de redim.
  - Taille drawer inchangee -> aucun risque regression.
  - Pas de N+1 : tout depuis `context_json`.
- **Contre** :
  - "KPI graphiques" demande par l'utilisateur est interprete au minimum
    (pas de vrais charts).
  - Difficile de visualiser une **timeline** ou une **distribution** sans
    chart.

---

## 4. Recommandation

### Axe 1 : **Option A — fichier `style_examples/example_default.txt` + injection few-shot**

Justification :
- Le fallback deterministe doit **rester intact** (statut `brouillon` doit
  fonctionner sans cle, c'est un invariant de l'agent). Option C casse ce
  decouplage en couplant style et fallback.
- L'exemple humain peut etre fourni tel quel par Gautier (copie-colle du mail
  qui fonctionne) — pas de travail d'abstraction prealable (vs C).
- Le risque hallucination est borne : on **ne touche pas** au set de tokens
  autorises, l'instruction systeme explicite la regle, et le garde-fou
  existant continue de filtrer. Si un chiffre de l'exemple fuit, le message
  bascule `body_fallback` automatiquement.
- Extension future facile (1 fichier par tier / segment) sans toucher au code.

Bump : `REDACTEUR_VERSION = "1.1"` et `pitch_version` bumpe en consequence
pour tracer en base quelle generation a beneficie du nouveau style.
Les messages existants ne sont pas touches (statut conserve, body conserve) ;
ils peuvent etre regeneres a la demande via `regenerate <message_id>`.

### Axe 2 : **Option D — drawer elargi 720px + zone INSIGHTS verticale**

Justification :
- Coherence avec les autres drawers (a droite, taille comparable a
  incident_detail_drawer qui est aussi a 560-640px ; 720 est dans la meme
  famille).
- Aucun N+1 : 100% des donnees viennent du `context_json` deja en base.
- `rx.recharts` deja disponible, pas de dependance nouvelle.
- Mobile degrade proprement via stack vertical (pattern deja utilise dans
  les autres drawers).
- Le radial gauge sanitaire + bar chart sources + progress contact couvrent
  les 3 axes de decision principaux **sans** dupliquer le dashboard.

KPI retenus (3) — **pas plus**, pour border le scope :
1. Score sanitaire — `rx.recharts.radial_bar_chart` (gauge unique 0-100 +
   tier en label central).
2. Couverture mediatique — `rx.recharts.bar_chart` horizontal des sources
   (lit `signaux_summary` du `context_json`).
3. Qualite prospect — pastille `rx.progress` + label texte (pas de chart).

Le **4e KPI candidat** (timeline incident/signaux) est ecarte : peu de points
par incident, lisibilite faible dans un drawer, complexite recharts elevee
pour le gain.

---

## 5. Impact

### Fichiers a modifier

#### Axe 1
- **Nouveau** : `agents/redacteur_outreach/style_examples/example_default.txt`
  (fichier UTF-8, fourni par Gautier).
- **Nouveau** : `agents/redacteur_outreach/style_loader.py` (~30 lignes :
  load + normalisation ASCII + cache module).
- **Modifie** : `agents/redacteur_outreach/llm_rewriter.py`
  - import + appel `load_style_example()`,
  - augmentation `_SYSTEM_BODY` (~10 lignes de regle "imite forme pas contenu"),
  - augmentation `_USER_BODY_TMPL` (injection bloc `<STYLE_EXAMPLE>`),
  - aucun changement au garde-fou hallucination (le set autorise reste
    `body_fallback + context + pitch`, **pas** l'exemple).
- **Modifie** : `agents/redacteur_outreach/models.py` -> `REDACTEUR_VERSION = "1.1"`.
- **Modifie** : `agents/redacteur_outreach/tests/test_llm_rewriter.py`
  - test "exemple charge depuis fichier injecte dans le user prompt",
  - test "un chiffre present dans exemple mais absent du contexte declenche fallback".

#### Axe 2
- **Modifie** : `agents/dashboard_reflex/dashboard_reflex/components/outreach_drawer.py`
  - passage `width="720px"`,
  - ajout section `_insights_block()` avec 3 sous-composants (gauge,
    bar chart, progress),
  - import `rx.recharts`,
  - media query stack vertical sous 768px.
- **Modifie** : `agents/dashboard_reflex/dashboard_reflex/state.py`
  - ajout var calculee `@rx.var outreach_kpi_payload` qui parse
    `selected_outreach["context_json"]` (deja Var) et expose 3 sous-dicts
    pretes a feeder les charts (score_dims, sources_distribution,
    contact_summary).
  - Normalisation defensive (json.loads + try/except, dict vides si absent).
- Pas de modification `services/data.py` (zero requete additionnelle).
- Pas de modification de schema SQLite, pas de migration.

### Pas de migration DB
Le `context_json` contient deja toutes les donnees necessaires aux KPI.
Aucun ALTER TABLE.

### Compatibilite ascendante
- Messages existants : `body_md` et `body_fallback` conserves. Affichage drawer
  fonctionne — les charts auront simplement moins de finesse si l'ancien
  `context_json` manque certaines cles (gere par defaut via dict vides cote
  state).
- Tests existants : `test_llm_rewriter.py` doit etre mis a jour (les fixtures
  de prompt vont changer). Pas de breaking change runtime.

### Breaking changes
Aucun. Bump `REDACTEUR_VERSION` -> `1.1` est purement informatif (champ
`redacteur_version` deja en base, valeur libre).

### Surveiller
- **Cout LLM** : mesurer le delta de tokens input apres ajout exemple
  (Anthropic Console). Si depassement, tronquer exemple a N caracteres dans
  `style_loader`.
- **Taux de fallback hallucination** : tracker `notes` des messages generes
  apres deploiement. Si forte hausse de `hallucination_detected`, c'est que
  des chiffres de l'exemple fuitent -> revoir l'instruction systeme ou
  expurger les chiffres de l'exemple a l'ingestion.
- **Largeur drawer sur ecrans 1280** : valider manuellement. Si trop serre,
  abaisser a 640px (le contenu doit rester lisible).
- **Performance recharts dans vaul** : le redimensionnement initial peut
  flicker. Fixer `height` en pixels (pas `100%`).

---

## 6. Hors scope

Ce qui n'est **PAS** fait dans cette ADR :
- **Selection multi-exemples par tier/source** : la mecanique est laissee
  ouverte (`style_examples/` est un dossier extensible), mais V1 = 1 seul
  fichier `example_default.txt`. Le routing tier->fichier sera une V2.
- **A/B testing du style** : pas d'instrumentation pour comparer
  taux de validation des messages avec/sans exemple. A faire si
  necessaire dans un autre ADR.
- **Edition du corps dans le drawer** : reste read-only. Pas de
  rich-text editor.
- **Timeline incident/signaux** dans le drawer : ecarte (cf justif Axe 2).
- **Export PDF / EML depuis le drawer** : la commande CLI
  `show <message_id> --format eml` existe deja, pas de duplication UI.
- **Push CRM (Sellsy)** : roadmap §7 EverTrack, autre ADR.
- **Refonte du `pitch.json`** : la config editeur reste identique, c'est
  la couche stylistique qui est ajoutee en complement (pitch = contenu,
  exemple = ton).
- **Prompt caching Anthropic** : ecarte tant que volume < 1000 msg/mois.
- **Modification du template deterministe `email_fr.txt`** : intact.
  Le brouillon `body_fallback` reste identique pour preserver l'invariant
  fallback-first.
