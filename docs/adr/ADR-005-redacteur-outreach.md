# ADR 005 — Agent 5 : Rédacteur d'outreach personnalise

**Statut :** Propose
**Date :** 2026-05-12

## Contexte

Le pipeline EverTrack fournit aujourd'hui, par incident RappelConso :
- un score sanitaire 0-100 + justification LLM (`agents/evaluateur_severite/storage.py`),
- un enrichissement entreprise + contact (`agents/enrichisseur_prospects/storage.py` :
  `siren`, `raison_sociale`, `adresse`, `contact_nom`, `contact_titre`, `contact_type`,
  `confidence`),
- un ou plusieurs signaux faibles cross-references via
  `signal_incident_matches` (`agents/detecteur_signaux/storage.py`).

L'etape commerciale manque : transformer ce contexte en **email d'accroche**
adresse nommement au contact qualite / supply / dirigeant, en mentionnant
l'incident et eventuellement les signaux presse associes. La sortie doit
alimenter (a) le dashboard pour validation humaine, (b) plus tard un push CRM
Sellsy (cf. roadmap §7 de `CLAUDE.md`).

Contraintes EverTrack a respecter :
- pattern agent autonome `agents/<nom_agent>/` (models, storage, orchestrateur, cli, tests),
- LLM **fallback-first** (utilisable sans `ANTHROPIC_API_KEY`),
- SQLite natif, migrations via `_MIGRATIONS` + try/except,
- stdlib en priorite (pas de Jinja, FastAPI, Celery, ORM),
- ASCII-only CLI, `unittest`, `load_dotenv(override=True)`.

Point a noter : la doc projet evoque `contact_email` / `contact_phone` mais ces
colonnes **n'existent pas encore** dans `enrichissements` (cf. SCHEMA reel). L'Agent 5
doit donc fonctionner **sans email connu** dans 100% des cas a date, et le canal
sera resolu en aval (recherche manuelle / Apollo / Hunter / LinkedIn).

## Decision

Creer `agents/redacteur_outreach/` avec :
1. **Generation hybride** : un template deterministe (stdlib `string.Template`)
   produit un brouillon structure ; Claude Haiku **reecrit** le corps pour le rendre
   naturel et personnalise. Sans cle, on stocke directement le brouillon template.
2. **Une base dediee** `outreach.sqlite`, table `messages` indexee sur
   `(source, source_id)` de l'incident, avec workflow `brouillon` -> `a_valider`
   -> `valide` -> `envoye` -> `rejete` (calque du pattern Agent 4).
3. **Format de sortie** : objet + corps Markdown, plus un export `.eml` a la
   demande via la CLI (`redacteur_outreach.cli export <message_id>`).
4. **Config produit** dans `agents/redacteur_outreach/pitch.yaml` (cle/valeur
   simple, parse stdlib) : nom editeur, signature, pitch court, CTA, opt-out.
   Permet la reutilisation par d'autres clients sans toucher au code.
5. **Integration dashboard** : drawer "Message d'accroche" dans la page Prospects
   (pas de nouvelle page : 1 incident = 1 prospect = 1 message). Boutons
   Generer / Editer / Valider / Copier / Marquer envoye.

## Alternatives considerees

### Option A — Full LLM, prompt unique
- Approche : on injecte tout le contexte (incident + score + enrich + signaux)
  dans un prompt unique, Claude renvoie objet + corps.
- Pour : flexibilite maximale, ton naturel.
- Contre : non utilisable sans cle ; risque d'hallucination chiffree (score,
  dates, raison sociale) ; difficile a tester ; sensibilite forte aux changements
  de prompt.

### Option B — Full template deterministe (stdlib `string.Template`)
- Approche : un template fige avec variables `${marque}`, `${date_publication}`,
  `${contact_nom}`, etc. Pas de LLM du tout.
- Pour : zero cout, deterministe, testable trivialement, conforme RGPD/audit.
- Contre : tonalite robotique, mauvaise impression en B2B, difficile a varier
  d'un email a l'autre (risque de pattern detecte si volume).

### Option C — Hybride template + LLM (**retenue**)
- Approche : etape 1, on assemble un brouillon factuel via template
  (`string.Template`). Etape 2, Claude Haiku **reecrit** ce brouillon pour le
  rendre naturel, sous contrainte stricte (interdiction d'ajouter des faits non
  presents dans le contexte). Le brouillon template est conserve comme
  `body_fallback` en colonne separee.
- Pour : LLM utilise pour le style, pas pour les faits -> moins d'hallucination ;
  fallback exploitable directement si pas de cle (statut `brouillon` au lieu de
  `a_valider`) ; testable (mock LLM, on teste l'etape template) ; coherent avec
  Agents 2 et 4.
- Contre : 2 etapes a maintenir ; tokens un peu plus eleves (input + output dans
  reecriture). Cout reel estime ~0,002 EUR/email en Haiku.

**Pourquoi C plutot que A ou B** : A casse le principe fallback-first et la
defense anti-hallucination que le client va exiger sur des chiffres (score
sanitaire, dates de rappel). B donne un rendu pauvre qui sabote la valeur
commerciale du livrable. C est l'extension naturelle des choix Agents 2 et 4.

## Schema de stockage propose

Base : `agents/data/outreach.sqlite`.

```sql
CREATE TABLE messages (
    message_id          TEXT PRIMARY KEY,         -- sha1(source|source_id|version)[:16]
    source              TEXT NOT NULL,            -- "rappelconso" ou "signal_detecteur"
    source_id           TEXT NOT NULL,            -- FK logique vers incidents
    redacteur_version   TEXT NOT NULL,
    canal               TEXT NOT NULL,            -- 'email' | 'linkedin' | 'phone_script'
    destinataire_nom    TEXT,                     -- copie de enrichissements.contact_nom
    destinataire_titre  TEXT,
    destinataire_type   TEXT,                     -- 'cible' | 'fallback_dirigeant'
    objet               TEXT,                     -- sujet email
    body_md             TEXT,                     -- version finale (LLM ou template)
    body_fallback       TEXT,                     -- brouillon template, toujours rempli
    llm_used            INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL,            -- brouillon|a_valider|valide|envoye|rejete
    context_json        TEXT,                     -- snapshot incident+score+enrich+signaux
    generated_at        TEXT NOT NULL,
    validated_at        TEXT,
    sent_at             TEXT,
    raw_llm_response    TEXT
);
CREATE INDEX idx_outreach_status ON messages (status);
CREATE INDEX idx_outreach_incident ON messages (source, source_id);
```

Pas de FK SQL dure (coherent avec le reste du projet, les bases sont
independantes). `context_json` fige le contexte au moment de la generation pour
l'audit ulterieur (le score peut etre recalcule, le message envoye doit rester
explicable).

## Strategie de prompt Claude Haiku

Deux appels distincts pour limiter les hallucinations :

1. **Reecriture corps** — input : brouillon template + contexte structure JSON
   (incident, score, enrich, signaux). Instructions :
   - ne pas inventer de chiffres, dates, noms,
   - ton FR pro, tutoiement bannit, 120-180 mots,
   - reprendre la justification sanitaire du score sans la copier mot pour mot,
   - si signaux faibles presents, glisser une mention courte ("la presse evoque
     egalement..."),
   - terminer par un CTA unique (15 min de demo).
2. **Generation objet** — appel court, prompt minimal : "Genere un objet
   d'email <= 70 caracteres, factuel, mentionnant la marque et le mot rappel."

Variables injectees (depuis `context_json`) : `marque`, `produit`,
`date_publication`, `motif`, `score_global`, `score_tier`, `score_justification`,
`raison_sociale`, `contact_prenom`, `contact_nom`, `contact_titre`,
`signaux_summary` (liste de 0-3 entrees : `source_name` + `titre`),
`pitch_produit`, `signature`, `cta`.

Garde-fous post-generation : si la reponse contient un chiffre absent du
contexte (regex simple), on degrade vers `body_fallback` et on marque
`status='brouillon'` pour relecture.

## Fallback deterministe

Sans `ANTHROPIC_API_KEY` ou en cas d'erreur LLM :

```
Objet: Rappel ${marque} du ${date_publication} - echange traçabilite ?

Bonjour ${contact_civilite} ${contact_nom},

Nous avons note la publication du rappel ${source_id} concernant ${produit}
(motif : ${motif_court}). Notre score sanitaire interne classe cet incident
en tier "${score_tier}" (${score_global}/100).

${bloc_signaux_optionnel}

${pitch_produit_court}

Seriez-vous disponible pour un echange de 15 minutes la semaine prochaine ?

${signature}
${opt_out}
```

Implementation : `string.Template.safe_substitute()` sur stdlib, aucun template
engine. Le fallback est **toujours** genere et stocke dans `body_fallback`,
LLM ou pas — ce qui simplifie les tests et garantit un livrable degrade
fonctionnel.

## Integration dashboard Reflex

- **Pas de nouvelle page** : extension de la page Prospects existante.
- Nouveau drawer "Message" declenche depuis `prospects_table.py`.
- Etats UI : Generer (POST -> `redacteur_outreach.generate(source_id)`),
  Editer (textarea sur `body_md`), Valider (transition status),
  Copier dans presse-papier, Exporter `.eml`.
- Service backend : `dashboard_reflex/dashboard_reflex/services/data.py` gagne
  `get_outreach_message(source, source_id)` et `list_outreach(status)`.
- KPI sur page Radar : "Messages en attente de validation" (count
  `status='a_valider'`).

## CLI prevue

```bash
python -m redacteur_outreach.cli generate <source_id> [--no-llm] [--canal email]
python -m redacteur_outreach.cli generate-batch [--min-score 60] [--max N]
python -m redacteur_outreach.cli list [--status a_valider]
python -m redacteur_outreach.cli show <message_id> [--format md|json|eml]
python -m redacteur_outreach.cli validate <message_id> --accept|--reject
python -m redacteur_outreach.cli mark-sent <message_id>
python -m redacteur_outreach.cli export <message_id> --out fichier.eml
python -m redacteur_outreach.cli stats
```

## Consequences

**Positives**
- Boucle commerciale complete : detection -> qualification -> contact.
- Pattern coherent : 5e agent qui ressemble aux 4 autres (CLI, SQLite, fallback).
- Decouplage canal : le schema accepte `email`/`linkedin`/`phone_script`, on
  pourra cibler le canal selon dispo contact sans changer la table.
- `context_json` fige l'etat -> audit reproductible meme apres rescoring.
- Preparation push CRM : on aura `objet` + `body_md` + `destinataire_nom` deja
  structures pour Sellsy.

**Negatives / dette**
- Le contact mail n'existe pas en base (`enrichissements` n'a pas `contact_email`).
  Tant que l'enrichissement contact ne fournit pas d'email, l'envoi reel reste
  manuel. A traiter en parallele (Apollo / Hunter / Pappers contacts API).
- Deux etapes LLM -> tokens ~2x un appel direct. A surveiller cote cout.
- Le fallback template peut paraitre generique si utilise tel quel.

**A surveiller**
- Taux de regeneration humaine (proxy qualite LLM) — exposer dans `stats`.
- Detection d'hallucinations par regex chiffree : tester sur 50 messages reels
  avant d'industrialiser.
- Volume de mots-cles "rappel produit" dans les filtres anti-spam des MX
  destinataires — le client peut vouloir un wording moins frontal.

## Points ouverts a valider avec l'humain (avant planning)

1. **RGPD / opt-out** : mention obligatoire en pied de mail ? Quelle base
   legale (interet legitime B2B vs consentement) ? Qui gere les desabonnements ?
2. **Ton** : formel (vouvoiement + Madame/Monsieur) ou direct (prenom + tutoiement) ?
   Defaut propose : formel.
3. **Longueur cible** : 120-180 mots ou plus court (4 lignes type Predictable
   Revenue) ? Defaut propose : 120-180 mots.
4. **Pieces jointes / liens** : on joint la fiche RappelConso (`source_url`) ?
   Risque de spam si lien gouvernemental + mention "rappel".
5. **Signature & pitch** : qui fournit le bloc final ? Fait-il partie de `pitch.yaml`
   versionne ou doit-il rester hors repo (secret commercial) ?
6. **Multi-canal** : prioriser email > LinkedIn > phone-script, ou generer les 3
   systematiquement ? Impact direct sur le volume d'appels LLM.
7. **Seuil de declenchement auto** : on genere tous les messages, ou seulement
   `score >= 60` + `enrichissement.confidence >= 0.72` ? Defaut propose : seuil
   automatique pour la batch, generation manuelle dispo dans tous les cas.
