# Changelog

Toutes les modifications notables de ce projet sont documentees ici.
Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Versioning : [SemVer](https://semver.org/lang/fr/).

---

## [Unreleased]

### Added

- **`redacteur_outreach/style_loader.py`** : charge un exemple stylistique
  optionnel depuis `style_examples/example_default.txt`. Normalise UTF-8
  vers ASCII pur (NFKD + ligatures explicites) au chargement. Cache
  module-level par chemin absolu. Troncature au dernier saut de ligne avant
  2000 caracteres. Retourne `None` si le fichier est absent (agent
  fonctionnel sans exemple).
- **Injection few-shot** dans `llm_rewriter.py` : quand un exemple est
  present, il est injecte dans le prompt systeme dans un bloc
  `<STYLE_EXAMPLE>`. Cela guide le ton du LLM sans modifier le fallback
  deterministe ni le set de tokens autorises.
- **Garde-fou `link_injection`** dans `llm_rewriter.py` : declenche le
  fallback vers `body_fallback` si la sortie LLM contient une URL, une
  adresse email ou un numero de telephone absents de `pitch.json` et du
  `body_fallback`. Vise la fuite de coordonnees depuis l exemple stylistique.
  `notes` = `link_injection`, statut = `a_valider`.
- **Template `style_examples/example_default.example.txt`** : email anonymise
  (Jean Dupont / contact@example.com / www.example.com) versionne en depot
  comme point de depart. Le fichier reel `example_default.txt` est gitigore.
- **Section INSIGHTS dans le drawer outreach** (`outreach_drawer.py`) avec
  3 KPI graphiques : score sanitaire (radial bar chart recharts), sources
  mediatiques (bar chart horizontal recharts), confidence prospect (barre
  CSS `rx.progress`). Affichage conditionnel sur presence de `context_json`.
- **Vars `@rx.var` KPI outreach** dans `state.py` :
  `outreach_kpi_score_value`, `outreach_kpi_score_label`,
  `outreach_kpi_score_color`, `outreach_kpi_sources_total`,
  `outreach_kpi_sources_data`, `outreach_kpi_confidence_value`,
  `outreach_kpi_confidence_percent`, `outreach_kpi_confidence_status`,
  `outreach_kpi_has_data`.
- **`services/normalize.py`** (dashboard_reflex) : couche pure sans import
  Reflex contenant `normalize_outreach_pure` et `build_outreach_kpi_pure`.
  Permet les tests unitaires dans le venv standard des agents.
- **Nouveaux modules de test** : `test_style_loader.py`,
  `test_backward_compat.py`, `test_state_kpi_vars.py`, `test_data_kpi.py`.
  Total : redacteur_outreach 204 OK, dashboard_reflex/services 78 OK
  (10 skip Reflex venv).

### Changed

- **`REDACTEUR_VERSION` passe de `1.0` a `1.1`** (`models.py`). Nouveau
  champ `redacteur_version` en base distingue les messages generes avec
  injection few-shot de ceux generes sans. Les messages existants ne sont
  pas touches.
- **`pitch.json` version passe de `1.0` a `1.1`**. Champ `pitch_version`
  en base trace la config editeur utilisee a la generation.
- **Set de tokens numeriques autorises restreint** dans
  `llm_rewriter._build_allowed_tokens` : le dump `json.dumps(context)`
  complet est remplace par un sous-set explicite (marque, dates,
  score_total, sources, raison_sociale, contact_nom/titre). Les champs
  `siren`, `siret`, `email`, `telephone` sont exclus pour eviter qu ils
  apparaissent dans le corps genere.
- **Drawer outreach elargi de 480 px a 720 px** (bureau). Mobile (<768 px)
  : largeur 100 %. La taille `max_width="95vw"` reste inchangee.
- **`outreach_kpi_has_data`** evalue la presence de `context_json` non
  vide plutot que les valeurs KPI > 0, pour ne pas masquer les incidents
  avec score = 0.

### Fixed

- **`_OUTREACH_EMPTY` shallow copy** dans `state.py` : remplacement par
  `copy.deepcopy` pour eviter le partage de dicts imbriques entre instances
  de state.
- **Tests `test_backward_compat.py`** : les cas de figures avec messages
  v1.0 manquant la cle `kpi` ne levaient pas d exception mais loggaient une
  alerte silencieuse. Corriges pour retourner le payload vide de reference.

### Security

- **Garde-fou `link_injection`** : empeche toute URL, adresse email ou
  numero de telephone present dans l exemple stylistique de fuiter dans les
  emails generes. Le set autorise est construit a partir de `pitch.json` et
  `body_fallback` uniquement.
- **Cap 64 Ko sur `context_json`** avant `json.loads` dans
  `services/data.build_outreach_kpi` et `services/normalize.build_outreach_kpi_pure`
  : protege contre l injection de contenu volumineux en base locale.
- **`style_examples/example_default.txt` gitigore** : l email reel fourni
  par le client (peut contenir des donnees personnelles) n est jamais commite.
  Seul le template anonymise `example_default.example.txt` est versionne.

---

## [1.1.0] - 2026-05-12

### Added

- Agent 5 `redacteur_outreach` : generation de brouillons email hybride
  (template deterministe + reecriture Claude Haiku). Workflow complet
  `brouillon -> a_valider -> valide -> envoye / rejete`.
- Drawer "Message" dans la page Prospects du dashboard (ouverture depuis
  le drawer Prospect). Boutons Generer, Valider, Rejeter, Regenerer,
  Marquer envoye, Copier.
- CLI `redacteur_outreach.cli` : sous-commandes `generate`, `generate-batch`,
  `list`, `show`, `validate`, `mark-sent`, `set-status`, `regenerate`,
  `stats`.
- `outreach.sqlite` : table `messages` avec idempotence par
  `sha1(source|source_id)[:16]`.

---

## [1.0.0] - 2026-04-15

### Added

- Agent 1 `veilleur_incidents` : crawl RappelConso, normalisation, dedup.
- Agent 2 `evaluateur_severite` : score sanitaire 0-100 via Claude Haiku
  avec fallback table de mots-cles.
- Agent 3 `enrichisseur_prospects` : match marque vers SIRENE + Pappers,
  ciblage contacts operationnels (qualite / supply chain / conformite).
- Agent 4 `detecteur_signaux` : signaux faibles Google News + Reddit,
  cross-reference avec incidents (4 dimensions ponderees).
- Dashboard Reflex 3 pages (Radar / Signaux / Prospects) avec drawers,
  validation humaine et navigation mobile responsive.
- Cross-reference signal-incident avec auto-confirmation par lien direct
  `rappel.conso.gouv.fr/fiche-rappel/...`.
- Tunnel Cloudflare pour acces externe.
