# Plan — Agent 5 : Redacteur outreach

**ADR source :** ADR-005
**Date :** 2026-05-12
**Complexite globale :** M (10 taches, ~10-12h focus, chemin critique = T1 → T2 → T3 → T5 → T6 → T7 → T8)

## Vue d'ensemble

Creer `agents/redacteur_outreach/` : un 5e agent qui prend un `source_id`
d'incident, assemble le contexte cross-base, produit un brouillon email via
template deterministe puis le reecrit optionnellement via Claude Haiku.
Sortie : brouillon stocke dans `outreach.sqlite`, consultable et editable depuis
un drawer Prospects du dashboard. **Aucun envoi automatique** : le statut
`envoye` est manuel uniquement. **RGPD/opt-out hors scope V1** (emplacement
reserve dans le template). **Deblocage email source hors scope** : l'agent
fonctionne sans `contact_email`.

---

## Pre-requis

- [ ] Agents 1, 2, 3 fonctionnels avec donnees dans `incidents.sqlite`,
      `scores.sqlite`, `enrichissements.sqlite` (existant)
- [ ] `signal_incident_matches` presente dans `signaux.sqlite` (existant, Agent 4)
- [ ] `ANTHROPIC_API_KEY` dans `agents/.env` (optionnel — fallback sinon)

---

## Taches

### T1 — Scaffolding agent [XS]
**Type :** code (nouveau)
**Fichiers touches :** `agents/redacteur_outreach/__init__.py`,
`agents/redacteur_outreach/models.py`,
`agents/redacteur_outreach/tests/__init__.py`
**Depend de :** —
**Critere d'acceptation :** `from redacteur_outreach.models import OutreachMessage`
s'importe sans erreur depuis `agents/` ; dataclass `OutreachMessage` possede au
moins les champs `message_id`, `source`, `source_id`, `canal`, `objet`,
`body_md`, `body_fallback`, `llm_used`, `status`, `generated_at` ; enum-like
`STATUS_CHOICES = ("brouillon", "a_valider", "valide", "envoye", "rejete")`.
**Description :** Creer l'arborescence du dossier, `__init__.py` vide, et
`models.py` avec la dataclass `OutreachMessage` et les constantes de statut.
Pas de logique metier.

---

### T2 — Storage + schema outreach.sqlite + tests [S]
**Type :** code + test (nouveau)
**Fichiers touches :** `agents/redacteur_outreach/storage.py`,
`agents/redacteur_outreach/tests/test_storage.py`
**Depend de :** T1
**Critere d'acceptation :**
- `OutreachStorage.save(msg)` persiste une `OutreachMessage` ; `get(message_id)`
  la relit avec tous les champs identiques.
- `list_by_status("a_valider")` retourne uniquement les messages de ce statut.
- `set_status(message_id, "valide")` met a jour le statut et `validated_at`.
- `count_by_status()` retourne un dict `{status: int}`.
- Les migrations (`_MIGRATIONS`) passent sans erreur meme si la table existe deja
  (idempotence testee en appelant `__init__` deux fois sur la meme DB).
- Tests : `unittest`, DB SQLite en memoire (`:memory:`).
**Description :** Implementer `OutreachStorage` avec creation de table +
`_MIGRATIONS`, CRUD minimal et requetes de liste/stats. Pattern identique a
`detecteur_signaux/storage.py`.

---

### T3 — context_builder.py + tests avec fixtures [S]
**Type :** code + test (nouveau)
**Fichiers touches :** `agents/redacteur_outreach/context_builder.py`,
`agents/redacteur_outreach/tests/test_context_builder.py`
**Depend de :** T1
**Critere d'acceptation :**
- `build_context(source, source_id, data_dir)` retourne un dict avec les cles :
  `incident`, `score`, `enrichissement`, `signaux_summary` (liste 0-3 entrees).
- Si `scores.sqlite` ou `enrichissements.sqlite` ne contient pas l'incident, les
  cles correspondantes sont `None` sans lever d'exception.
- `signaux_summary` est peuple depuis `signal_incident_matches` JOIN `signaux`
  (lecture `signaux.sqlite`), limite a 3 entrees, champs : `source_name`, `titre`.
- Tests : bases SQLite temporaires (`tempfile.TemporaryDirectory`) avec fixtures
  minimalistes (1 incident, 1 score, 1 enrichissement, 1 signal matche).
**Description :** Requetes SQLite en lecture seule sur les 4 bases existantes.
Aucune ecriture. Retourner un dict serialisable JSON (pour `context_json`).
Note : ce module est independant de T2 (pas de dependency sur storage outreach).

---

### T4 — pitch.yaml + loader stdlib [XS]
**Type :** code + test (nouveau)
**Fichiers touches :** `agents/redacteur_outreach/pitch.yaml`,
`agents/redacteur_outreach/pitch_loader.py`,
`agents/redacteur_outreach/tests/test_pitch_loader.py`
**Depend de :** T1
**Critere d'acceptation :**
- `load_pitch(path)` retourne un dict avec au minimum les cles `editeur_nom`,
  `pitch_court`, `cta`, `signature`, `opt_out_placeholder` (chaine vide ou
  commentaire TODO).
- Le parsing utilise uniquement la stdlib (`re` + split ligne par ligne ou
  `json` si on pivote vers JSON) — **pas de PyYAML**. Si la syntaxe YAML
  choisie est trop complexe pour la stdlib, pivoter vers un fichier `.cfg`
  (INI via `configparser`) ou `.json`. Trancher dans la tache.
- `load_pitch` accepte un fichier absent et retourne les valeurs par defaut
  sans exception (cas fallback).
- Test : verifier parsing d'un fichier minimal + cas fichier absent.
**Description :** Config editeur versionnable sans secret commercial. Format
a trancher (YAML simple → stdlib suffisante si cles plates ; sinon `.json` ou
`.cfg`). L'emplacement `opt_out_placeholder` satisfait le pre-requis RGPD V1
(reserve, non fonctionnel).

---

### T5 — template_renderer.py + tests ton/variables [S]
**Type :** code + test (nouveau)
**Fichiers touches :** `agents/redacteur_outreach/template_renderer.py`,
`agents/redacteur_outreach/templates/email_fr.txt`,
`agents/redacteur_outreach/tests/test_template_renderer.py`
**Depend de :** T3, T4
**Critere d'acceptation :**
- `render(context_dict, pitch_dict)` retourne `{"objet": str, "body": str}`.
- `body` contient les valeurs de `context_dict` interpolees (`string.Template.safe_substitute`).
- Si `contact_nom` est absent du contexte, `body` utilise "Madame/Monsieur" (valeur par defaut).
- Le bloc `${bloc_signaux_optionnel}` est vide si `signaux_summary` est vide, rempli sinon.
- L'emplacement `${opt_out}` est present dans le template mais rendu avec la
  valeur de `pitch_dict["opt_out_placeholder"]` (chaine vide acceptable).
- Tests : 3 scenarios (contexte complet, contexte sans enrichissement, contexte
  sans signaux).
**Description :** Fallback deterministe pur. `safe_substitute` tolerant aux
variables manquantes. Le fichier `templates/email_fr.txt` contient le template
du fallback ADR.

---

### T6 — llm_rewriter.py + tests MagicMock [S]
**Type :** code + test (nouveau)
**Fichiers touches :** `agents/redacteur_outreach/llm_rewriter.py`,
`agents/redacteur_outreach/tests/test_llm_rewriter.py`
**Depend de :** T5
**Critere d'acceptation :**
- `rewrite(body_fallback, context_dict, pitch_dict)` retourne
  `{"body_md": str, "objet": str, "llm_used": bool}`.
- Sans `ANTHROPIC_API_KEY`, retourne `body_fallback` avec `llm_used=False` sans
  lever d'exception.
- Appel LLM : 2 appels Haiku (reecriture corps + generation objet), modele
  `claude-haiku-4-5-20251001`.
- Garde-fou hallucination : si la reponse contient un chiffre absent du
  `context_dict` (regex `\b\d{2,}\b`), on degrade vers `body_fallback` et
  `llm_used=False`.
- Tests : `MagicMock` pour `anthropic.Anthropic` ; tester (a) succes normal,
  (b) absence de cle, (c) exception API, (d) declenchement garde-fou.
**Description :** Pattern identique a `evaluateur_severite/llm_scorer.py` et
`detecteur_signaux/extractor.py`. `load_dotenv(override=True)` en entete.

---

### T7 — redacteur.py orchestrateur + tests [S]
**Type :** code + test (nouveau)
**Fichiers touches :** `agents/redacteur_outreach/redacteur.py`,
`agents/redacteur_outreach/tests/test_redacteur.py`
**Depend de :** T2, T3, T5, T6
**Critere d'acceptation :**
- `Redacteur.generate(source, source_id, canal, no_llm, data_dir)` :
  1. Appelle `build_context` — si incident inconnu, leve `IncidentNotFoundError`.
  2. Rend le template fallback.
  3. Si `no_llm=False` et cle presente, appelle `rewrite`.
  4. Calcule `message_id = sha1(source|source_id|version)[:16]`.
  5. Persiste en `outreach.sqlite` avec statut `a_valider` (LLM ok) ou
     `brouillon` (fallback).
  6. Retourne l'`OutreachMessage` persiste.
- Si un message existe deja pour `(source, source_id)`, retourne l'existant sans
  regenerer (comportement idempotent par defaut).
- `Redacteur.regenerate(message_id)` force une nouvelle generation.
- Tests : MagicMock sur `context_builder`, `template_renderer`, `llm_rewriter` ;
  base SQLite en memoire.
**Description :** Orchestre les 4 modules precedents. Calcule le `message_id`
et le `redacteur_version` (constante de module `REDACTEUR_VERSION = "1.0"`).

---

### T8 — cli.py subcommands + tests [S]
**Type :** code + test (nouveau)
**Fichiers touches :** `agents/redacteur_outreach/cli.py`,
`agents/redacteur_outreach/requirements.txt`,
`agents/redacteur_outreach/tests/test_cli.py`
**Depend de :** T7
**Critere d'acceptation :**
- `generate <source_id>` cree un message et affiche `[ok] message_id=<id> status=<s>`.
- `generate-batch [--min-score 60] [--max N]` itere sur les incidents enrichis
  filtres par score, appelle `generate` pour chacun, affiche un recap ASCII.
- `list [--status a_valider]` liste les messages avec colonnes
  `message_id | source_id | status | generated_at`.
- `show <message_id> [--format md|json|eml]` affiche le contenu.
  Format `eml` = headers RFC 2822 minimaux (To, Subject, body) sans envoi.
- `validate <message_id> --accept|--reject` change le statut.
- `mark-sent <message_id>` passe a `envoye` + renseigne `sent_at`.
- `set-status <message_id> --status <s>` transition generique.
- `regenerate <message_id>` appelle `Redacteur.regenerate`.
- `stats` affiche `count_by_status()`.
- Tous les outputs : ASCII-only.
- Tests : `unittest.mock.patch` sur `sys.argv` + `Redacteur`.
**Description :** `argparse` avec subparsers. `requirements.txt` : `anthropic`,
`requests`, `python-dotenv` (pas de nouvelles dependances lourdes).

---

### T9 — Integration dashboard Reflex [M]
**Type :** code (modifie du code existant + nouveau)
**Fichiers touches :**
- `agents/dashboard_reflex/dashboard_reflex/services/data.py` **(modifie)**
- `agents/dashboard_reflex/dashboard_reflex/state.py` **(modifie)**
- `agents/dashboard_reflex/dashboard_reflex/components/outreach_drawer.py` **(nouveau)**
- `agents/dashboard_reflex/dashboard_reflex/components/prospect_detail_drawer.py` **(modifie)**
- `agents/dashboard_reflex/dashboard_reflex/components/kpi_cards.py` **(modifie)**
**Depend de :** T8 (schema DB stabilise)
**Critere d'acceptation :**
- `data.get_outreach_message(source, source_id)` retourne le dict message ou
  `None` si absent.
- `data.set_outreach_status(message_id, status)` met a jour le statut dans
  `outreach.sqlite`.
- `DashboardState` gagne `outreach_drawer_open: bool`, `selected_outreach: dict`,
  + handlers `open_outreach(source, source_id)`, `generate_outreach(source, source_id)`,
  `validate_outreach(message_id)`, `reject_outreach(message_id)`,
  `mark_outreach_sent(message_id)`.
- Le drawer `outreach_drawer` affiche : objet, body_md (zone texte lisible),
  statut, boutons Generer / Valider / Marquer envoye / Copier (clipboard via
  `rx.set_clipboard`). Bouton Generer appelle `Redacteur.generate` via le
  handler.
- Le bouton "Message" dans `prospect_detail_drawer` ouvre `outreach_drawer`.
- KPI "Messages en attente" dans `kpi_cards.py` affiche
  `count status='a_valider'`.
- Smoke test : `python -c "from dashboard_reflex.dashboard_reflex import app; print('OK')"`.
**Description :** Tache la plus large — pattern drawer identique aux drawers
existants (`position="fixed"`, `right="0"`, `left="auto"`). Normalizer
`_normalize_outreach` a ajouter dans `state.py` (pattern existant). Pas de
nouvelle page : extension de la vue Prospects.
Note : T9 est la seule tache M car elle touche 5 fichiers existants/nouveaux
avec des contraintes Reflex Var specifiques (concat, None-safety).

---

### T10 — Documentation + mise a jour CLAUDE.md [XS]
**Type :** doc (modifie + nouveau)
**Fichiers touches :**
- `agents/redacteur_outreach/README.md` **(nouveau)**
- `CLAUDE.md` **(modifie)** — §7 : deplacer Agent 5 de "A faire" vers "Livres" +
  ajouter les commandes CLI section §3
**Depend de :** T8 (CLI stabilisee), T9 (dashboard stabilise)
**Critere d'acceptation :**
- `README.md` contient : role de l'agent, commandes CLI avec exemples, variables
  d'environnement requises, schema de la table `messages`.
- `CLAUDE.md` §3 liste les 8 sous-commandes CLI de `redacteur_outreach.cli`.
- `CLAUDE.md` §7 "Livres" inclut l'Agent 5 avec une ligne de description.
- Pas d'emojis, ASCII-only.

---

## Ordre d'execution

```
T1 (scaffolding)
 ├── T2 (storage)      ──────────────────────────────┐
 ├── T3 (context)      ─────────────────────────┐    │
 └── T4 (pitch loader) ───┐                     │    │
                          ▼                     │    │
                      T5 (template) ────────────┤    │
                          │                     ▼    ▼
                          ▼                    T7 (orchestrateur)
                      T6 (llm_rewriter) ────────┘    │
                                                      ▼
                                                  T8 (cli)
                                                      │
                                                      ▼
                                                  T9 (dashboard)
                                                      │
                                                      ▼
                                                 T10 (docs)
```

**Parallelisable :** T2, T3, T4 peuvent etre faites en parallele apres T1.
T5 necessite T3 et T4. T6 necessite T5.

---

## Risques identifies

- **Reflex Var + None** : `outreach_drawer` doit normaliser tous les champs du
  message (pattern `_normalize_outreach` obligatoire) — un `None` non trape
  fait crasher le frontend silencieusement.
- **Format pitch.yaml** : si le contenu devient multi-ligne (signature), la
  stdlib ne parse pas YAML complet. Trancher en T4 (JSON ou configparser
  recommande pour eviter une dependance PyYAML).
- **Garde-fou hallucination** : la regex `\b\d{2,}\b` peut rejeter des messages
  valides contenant des scores (ex: "score 75/100"). Affiner la regex en
  comparant les chiffres trouves avec ceux du `context_dict` plutot qu'un
  simple detect-any.
- **Idempotence `generate-batch`** : si la batch est relancee, l'orchestrateur
  doit retourner l'existant sans appel LLM supplementaire — tester explicitement
  en T7.
- **Fixtures test T3** : creer des bases SQLite temporaires avec le bon schema
  (inclure les colonnes `signal_incident_matches`) necessite de copier/adapter
  les schemas des agents 1-4 en dur dans les fixtures — prevoir ~30 min de
  setup fixture avant le code metier.

---

## Hors scope (explicitement)

- Envoi SMTP ou API mail (aucune tache d'envoi automatique).
- RGPD / logique opt-out / consentement (emplacement reserve dans template, pas de code).
- Deblocage ou recherche d'adresse email (`contact_email` absent de la DB — hors scope).
- Integration CRM Sellsy (roadmap post-V1).
- Canal LinkedIn et phone_script (schema prevu, generation email uniquement en V1).
- Generation automatique a 3 canaux simultanement.
- Tests automatises du front Reflex (pas de framework de test Reflex — smoke test Python suffit).
