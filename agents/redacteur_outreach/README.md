# Agent 5 -- Redacteur outreach

Genere des brouillons d emails d accroche personnalises a partir des donnees
collectees par les agents 1-4 (incidents RappelConso, scoring sanitaire,
enrichissement entreprise/contact, signaux faibles presse/social).

## Role

Prend un `source_id` d incident en entree, assemble le contexte depuis les
4 bases SQLite du pipeline, produit un brouillon email via template deterministe
(stdlib `string.Template`), puis le reecrit optionnellement via Claude Haiku pour
ameliorer le style sans inventer de faits.

Le brouillon resultant est stocke dans `outreach.sqlite`. Il est consultable et
editable depuis le drawer "Message" de la page Prospects du dashboard. **Aucun
envoi automatique** : le statut `envoye` est positionne manuellement uniquement.

## Pipeline

```
incidents.sqlite   scores.sqlite   enrichissements.sqlite   signaux.sqlite
       |                |                   |                      |
       +----------------+-------------------+----------------------+
                                    |
                           context_builder.py
                           (lecture seule multi-base)
                                    |
                         template_renderer.py
                         (string.Template, body_fallback garanti)
                                    |
                          llm_rewriter.py (optionnel)
                          (Claude Haiku -- style uniquement)
                                    |
                           outreach.sqlite
                           (table messages)
```

## Workflow

Les messages suivent ce cycle de vie :

```
brouillon --> a_valider --> valide --> envoye
                  |
                  v
               rejete
```

- `brouillon` : template seul (pas de cle API, ou `--no-llm`).
- `a_valider` : LLM utilise avec succes, ou anomalie detectee (hallucination,
  non-ASCII) -- dans les deux cas, relecture humaine obligatoire.
- `valide` : validé via CLI `validate --accept` ou bouton dashboard.
- `envoye` : marque manuellement via `mark-sent` ou bouton dashboard.
- `rejete` : marque via `validate --reject`.

## Pre-requis

- Python 3.12
- `incidents.sqlite` et `enrichissements.sqlite` presents dans `agents/data/`
  (produits par les agents 1 et 3)
- `scores.sqlite` et `signaux.sqlite` optionnels mais recommandes pour
  personnaliser le message
- `ANTHROPIC_API_KEY` dans `agents/.env` (optionnel -- fallback deterministe sinon)

## Installation

Depuis `agents/`, dans le venv des agents :

```bash
pip install -r redacteur_outreach/requirements.txt
```

Dependances : `anthropic`, `requests`, `python-dotenv` (pas de nouvelles
dependances lourdes).

## Commandes CLI

Toutes les commandes se lancent depuis `agents/`.

### Generer un message

```bash
# Generer pour un incident specifique (source par defaut : rappelconso)
python -m redacteur_outreach.cli generate 2026-04-0257

# Specifier la source explicitement
python -m redacteur_outreach.cli generate 2026-04-0257 --source rappelconso

# Sans LLM (template seul, statut brouillon)
python -m redacteur_outreach.cli generate 2026-04-0257 --no-llm

# Forcer la regeneration si un message existe deja
python -m redacteur_outreach.cli generate 2026-04-0257 --force
```

Sortie : `[ok] message_id=<id> status=<s> llm_used=<bool>`

### Generer en batch

```bash
# Tous les incidents enrichis (score quelconque)
python -m redacteur_outreach.cli generate-batch

# Filtrer par score minimal (jointure scores.sqlite)
python -m redacteur_outreach.cli generate-batch --min-score 60

# Limiter le nombre d incidents traites
python -m redacteur_outreach.cli generate-batch --min-score 60 --max 20

# Sans LLM
python -m redacteur_outreach.cli generate-batch --min-score 40 --no-llm
```

La batch est idempotente : les incidents deja traites sont ignores sauf avec
`--force`.

### Lister les messages

```bash
# Tous les messages (50 derniers par defaut)
python -m redacteur_outreach.cli list

# Filtrer par statut
python -m redacteur_outreach.cli list --status a_valider

# Changer la limite
python -m redacteur_outreach.cli list --limit 100
```

Colonnes : `message_id | source_id | status | generated_at | llm`

### Afficher un message

```bash
# Format texte (defaut)
python -m redacteur_outreach.cli show <message_id>

# Format JSON (tous les champs)
python -m redacteur_outreach.cli show <message_id> --format json

# Format .eml (headers RFC 2822 minimaux, sans envoi)
python -m redacteur_outreach.cli show <message_id> --format eml
```

### Valider ou rejeter

```bash
python -m redacteur_outreach.cli validate <message_id> --accept
python -m redacteur_outreach.cli validate <message_id> --reject
```

### Marquer comme envoye

```bash
python -m redacteur_outreach.cli mark-sent <message_id>
```

Positionne le statut a `envoye` et renseigne `sent_at` avec l horodatage courant.

### Transition de statut generique

```bash
python -m redacteur_outreach.cli set-status <message_id> --status valide
```

Valeurs acceptees : `brouillon`, `a_valider`, `valide`, `envoye`, `rejete`.

### Regenerer un message existant

```bash
python -m redacteur_outreach.cli regenerate <message_id>

# Sans LLM
python -m redacteur_outreach.cli regenerate <message_id> --no-llm
```

### Statistiques

```bash
python -m redacteur_outreach.cli stats
```

Affiche le compte par statut et le total.

## Configuration pitch

Le fichier `agents/redacteur_outreach/pitch.json` contient les informations
editeur injectees dans chaque message genere. Editez-le avec un editeur texte.
ASCII uniquement. Les sauts de ligne dans `signature` s expriment via `\n`.

```json
{
  "version": "1.0",
  "editeur_nom": "EverTrack",
  "pitch_court": "EverTrack securise la tracabilite produit ...",
  "valeur_immediate": "Identifier les lots affectes en quelques minutes ...",
  "cta": "Auriez-vous 20 minutes la semaine prochaine ?",
  "signature": "Cordialement,\nEquipe EverTrack",
  "opt_out_placeholder": ""
}
```

Cles disponibles :

| Cle | Obligatoire | Description |
|---|---|---|
| `version` | non | Versionne le pitch pour l audit (stocke en DB) |
| `editeur_nom` | oui | Nom de l editeur injecte dans la salutation |
| `pitch_court` | oui | Proposition de valeur (1-2 phrases) |
| `valeur_immediate` | non | Benefice concret mis en avant |
| `cta` | oui | Appel a l action unique |
| `signature` | oui | Bloc signature, `\n` pour les sauts de ligne |
| `opt_out_placeholder` | non | Reserve RGPD V1 -- laisser vide ou remplir |

Si `pitch.json` est absent, des valeurs par defaut neutres sont utilisees
(l agent ne leve pas d exception).

## Schema de la table messages

Base : `agents/data/outreach.sqlite`, table `messages`.

| Colonne | Type | Description |
|---|---|---|
| `message_id` | TEXT PK | sha1(source\|source_id)[:16] -- stable, idempotent |
| `source` | TEXT | Origine de l incident (ex. `rappelconso`) |
| `source_id` | TEXT | Identifiant de l incident |
| `canal` | TEXT | `email` en V1 (extensible : `linkedin`, `phone_script`) |
| `objet` | TEXT | Sujet de l email |
| `body_md` | TEXT | Corps final (version LLM si disponible, sinon template) |
| `body_fallback` | TEXT | Corps template deterministe, toujours rempli |
| `llm_used` | INTEGER | 1 si Claude Haiku a reecrit le corps, 0 sinon |
| `redacteur_version` | TEXT | Version de l orchestrateur (`REDACTEUR_VERSION`) |
| `status` | TEXT | `brouillon`, `a_valider`, `valide`, `envoye`, `rejete` |
| `context_json` | TEXT | Snapshot JSON du contexte a la generation (audit) |
| `pitch_version` | TEXT | Version du `pitch.json` utilise |
| `generated_at` | TEXT | ISO-8601 UTC |
| `validated_at` | TEXT | ISO-8601 UTC, rempli par `validate` |
| `sent_at` | TEXT | ISO-8601 UTC, rempli par `mark-sent` |
| `notes` | TEXT | Raison du fallback LLM ou notes humaines |

Index : `(source, source_id)` et `(status)`.

## Garde-fous LLM

Trois situations declenchent le fallback vers `body_fallback` :

| Situation | `notes` (colonne DB) | Statut resultant |
|---|---|---|
| Pas de `ANTHROPIC_API_KEY` | `no_api_key` | `brouillon` |
| SDK `anthropic` absent | `anthropic_not_installed` | `brouillon` |
| Flag `--no-llm` | `no_llm_requested` | `brouillon` |
| Exception API (timeout, rate limit) | `api_error` | `a_valider` |
| Chiffre invente detecte (regex) | `hallucination_detected` | `a_valider` |
| Caractere non-ASCII en sortie LLM | `non_ascii_detected` | `a_valider` |

La detection d hallucination compare les tokens numeriques (suite de 2+ chiffres)
presents dans la reponse LLM avec ceux du `body_fallback` + contexte + pitch. Tout
chiffre absent de ces sources est considere comme invente.

Les statuts `a_valider` pour anomalie (3 derniers cas) signalent qu un humain doit
inspecter avant usage -- le `body_fallback` est toujours disponible en colonne
separee comme reference.

## Variables d environnement

| Variable | Obligatoire | Usage |
|---|---|---|
| `ANTHROPIC_API_KEY` | Non | Reecriture LLM via Claude Haiku -- sans elle, statut `brouillon` |

Configurer dans `agents/.env`. Le module appelle `load_dotenv(override=True)`
au chargement (obligatoire sur Windows).

## Tests

Depuis `agents/` :

```bash
python -m unittest discover redacteur_outreach/tests -v
```

Couverture : storage (CRUD + migrations), context_builder (fixtures SQLite
temporaires), template_renderer (3 scenarios), llm_rewriter (MagicMock --
succes / sans cle / exception / hallucination), orchestrateur (MagicMock modules),
CLI (patch sys.argv).

## Hors scope V1

- Envoi SMTP ou API mail (aucun envoi automatique, jamais)
- Logique RGPD / opt-out / consentement (emplacement reserve dans `opt_out_placeholder`)
- Recherche d adresse email (`contact_email` absent de `enrichissements.sqlite`)
- Integration CRM Sellsy (roadmap post-V1)
- Canaux LinkedIn et phone_script (schema prevu, generation email uniquement)
