# Plan — ADR-006 : Enrichissement outreach par exemple stylistique + drawer KPI graphiques

**ADR source :** ADR-006
**Date :** 2026-05-12
**Complexite globale :** M (9 taches, ~8-11h focus, chemin critique T1 → T2 → T3 → T4 → T5 → T6 → T7)

---

## 1. Objectif

Ameliorer l'agent 5 (`redacteur_outreach`) sur deux axes independants.

**Axe 1 (backend)** : injecter un exemple stylistique real (fourni par Gautier) dans
le prompt LLM pour que les emails generes imitent le ton consultatif du template qui
convertit. Le fallback deterministe (`body_fallback`) et les garde-fous hallucination
restent strictement intacts. La version passe a `1.1` pour distinguer les nouvelles
generations en base.

**Axe 2 (dashboard)** : elargir le drawer outreach a 720px et y ajouter une zone
"INSIGHTS" avec 3 KPI visuels (score sanitaire gauge, couverture mediatique bar chart,
qualite prospect progress) alimentes exclusivement par le `context_json` deja stocke
en base — zero requete supplementaire.

---

## 2. Pre-requis

### Fichiers a verifier avant de commencer

- `agents/redacteur_outreach/llm_rewriter.py` — present, structure connue (lignes 44-355).
- `agents/redacteur_outreach/models.py` — `REDACTEUR_VERSION = "1.0"` ligne 9.
- `agents/redacteur_outreach/tests/test_llm_rewriter.py` — 13 tests passants, fixtures
  `_make_body_fallback`, `_make_context`, `_make_pitch`, `_make_clean_body_llm` a
  reutiliser ou adapter.
- `agents/dashboard_reflex/dashboard_reflex/components/outreach_drawer.py` — drawer
  actuel 480px, pas de section INSIGHTS.
- `agents/dashboard_reflex/dashboard_reflex/state.py` — `_normalize_outreach` ne
  passe pas `context_json`, `_OUTREACH_EMPTY` sans ce champ.

### Donnees / env vars necessaires

- Gautier doit fournir le contenu de `example_default.txt` (le mail qui convertit)
  avant T2. Bloquer T2 sur cette livraison.
- `ANTHROPIC_API_KEY` configuree dans `agents/.env` pour tester T3 manuellement
  (les tests unitaires mockent l'API, pas besoin de cle pour CI).
- Dashboard Reflex fonctionnel sur port 3000 pour T8 (smoke test).

### Donnees de test existantes

- Fixtures de `test_llm_rewriter.py` : reutilisables telles quelles pour T3/T4.
- Au moins 1 message en base (`outreach.sqlite`) avec `context_json` non vide
  pour que T8 puisse verifier les charts. Sinon : generer via CLI
  `python -m redacteur_outreach.cli generate-batch --no-llm --max 1` depuis
  `agents/`.

---

## 3. Taches

---

### T1 — Bump REDACTEUR_VERSION vers 1.1 [XS]

**Fichiers touches :**
- `agents/redacteur_outreach/models.py`

**Depend de :** —

**Description :**
Changer la constante `REDACTEUR_VERSION = "1.0"` en `"1.1"` dans `models.py`.
Ce bump est le signal d'audit : tout message genere apres ce changement a
beneficie du nouveau style (axe 1). Les messages existants en base conservent
leur `redacteur_version="1.0"` et restent valides.

**Critere d'acceptation :**
`from redacteur_outreach.models import REDACTEUR_VERSION; assert REDACTEUR_VERSION == "1.1"`
passe sans erreur.

**Tests :**
Ajouter `test_redacteur_version_is_1_1` dans
`agents/redacteur_outreach/tests/test_redacteur.py` (ou creer un test minimal
dans un nouveau `test_models.py`) qui verifie la valeur de la constante.

**Risques :** Aucun — changement purement symbolique, pas d'impact runtime.

---

### T2 — Creer style_loader.py + example_default.txt [S]

**Fichiers touches :**
- `agents/redacteur_outreach/style_examples/example_default.txt` (NOUVEAU — fourni par Gautier)
- `agents/redacteur_outreach/style_loader.py` (NOUVEAU)

**Depend de :** T1 (la version doit etre bumped avant qu'on ajoute la mecanique)

**Description :**
Creer le module `style_loader.py` qui expose une fonction `load_style_example(name: str = "example_default") -> str`.
Comportement :
- Cherche `<package_dir>/style_examples/<name>.txt`.
- Lit le fichier en UTF-8.
- Normalise vers ASCII via `unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()`.
- Cache le resultat dans un dict module-level pour eviter des I/O repetitifs.
- Si le fichier est absent ou illisible, retourne `""` (silencieux — le rewriter
  ignorera le bloc exemple si vide).

Creer aussi `style_examples/` avec un fichier `example_default.txt` (contenu
fourni par Gautier). Si Gautier n'a pas encore fourni le fichier au moment du
codage, creer un placeholder ASCII non-vide (`"[exemple stylistique a remplir]"`)
pour que les tests passent.

**Critere d'acceptation :**
```python
from redacteur_outreach.style_loader import load_style_example
ex = load_style_example()
assert isinstance(ex, str)
assert ex.isascii()   # normalisation appliquee
```

**Tests :**
Creer `agents/redacteur_outreach/tests/test_style_loader.py` avec :
- `test_load_returns_string` : le retour est une str.
- `test_load_is_ascii` : le retour est entierement ASCII (meme si le fichier
  source contient des accents).
- `test_load_missing_file_returns_empty` : appeler `load_style_example("inexistant")`
  retourne `""` sans lever d'exception.
- `test_cache_same_object` : deux appels successifs retournent le meme objet.

**Risques :**
- Si Gautier fournit un fichier tres long (>1000 mots), le `style_loader` doit
  tronquer a ~500 mots pour controler le budget token. Ajouter un parametre
  `max_chars: int = 2000` avec troncature au dernier saut de ligne avant la limite.

---

### T3 — Injecter l'exemple dans llm_rewriter.py [S]

**Fichiers touches :**
- `agents/redacteur_outreach/llm_rewriter.py`

**Depend de :** T2

**Description :**
Modifier `llm_rewriter.py` pour integrer l'exemple stylistique dans les prompts :

1. Importer `load_style_example` depuis `style_loader`.
2. Modifier `_SYSTEM_BODY` (constante str) pour ajouter les regles :
   - "Imite UNIQUEMENT le ton, la structure narrative et les tournures de l'exemple."
   - "N'utilise AUCUN chiffre present uniquement dans l'exemple — n'utilise que les
     chiffres du brouillon et du contexte fournis."
   - "N'invente aucun fait, nom, date ou reference de l'exemple."
3. Modifier `_USER_BODY_TMPL` pour injecter un bloc `<STYLE_EXAMPLE>` conditionnel :
   si `load_style_example()` retourne une chaine non vide, ajouter le bloc apres
   la section contexte. Si vide, le template reste inchange (pas de bloc vide).
4. Adapter `_call_rewrite_body` pour passer l'exemple charge au moment de la
   construction du message user (appel `load_style_example()` une fois par appel
   `rewrite()`, pas en module-level, pour permettre le mock dans les tests).
5. **Ne pas modifier** `_build_allowed_tokens` — l'exemple n'est PAS ajoute au set
   de tokens autorises.

**Critere d'acceptation :**
- `rewrite(body_fallback, context, pitch)` avec mock retournant un body propre :
  `llm_used=True`, `reason=None`.
- Le user prompt envoye au mock contient la chaine `"<STYLE_EXAMPLE>"` quand
  `load_style_example()` retourne un texte non vide.
- Le user prompt ne contient PAS `"<STYLE_EXAMPLE>"` quand `load_style_example()`
  retourne `""`.
- Un chiffre present dans l'exemple mais absent du contexte/pitch/fallback
  n'est PAS dans `_build_allowed_tokens` (le set reste identique a l'existant).

**Tests :**
Dans `agents/redacteur_outreach/tests/test_llm_rewriter.py`, ajouter :
- `test_style_example_injected_in_user_prompt` : patcher `style_loader.load_style_example`
  pour retourner `"Voici un exemple."`, verifier que le contenu du `messages[0]["content"]`
  passe au mock contient `"<STYLE_EXAMPLE>"`.
- `test_style_example_absent_no_block` : patcher pour retourner `""`, verifier
  que le prompt ne contient pas `"<STYLE_EXAMPLE>"`.
- `test_chiffre_exemple_declenche_fallback` : patcher `load_style_example` pour
  retourner `"notre taux de conversion est de 87%"`, faire retourner au mock LLM
  un body contenant `"87"` mais avec `"87"` absent du contexte/pitch/fallback —
  verifier `reason="hallucination_detected"`.

**Risques :**
- La constante `_USER_BODY_TMPL` est une str immutable. Passer a une fonction
  `_build_user_body(body_fallback, context_summary, style_example)` est plus propre
  qu'un `.format()` avec champ optionnel. Choisir cette approche.
- Attention a la concatenation de Var dans les tests : utiliser uniquement
  `str` natif Python (pas Reflex Var) — OK ici car tests unitaires purs.

---

### T4 — Mettre a jour les fixtures et tests existants de test_llm_rewriter.py [XS]

**Fichiers touches :**
- `agents/redacteur_outreach/tests/test_llm_rewriter.py`

**Depend de :** T3

**Description :**
Apres T3, les tests existants qui verifient le contenu exact du user prompt
(notamment `test_normal_rewrite_success` et `test_model_param_override`) peuvent
avoir leurs assertions sur la structure du prompt brisees par l'ajout du bloc
`<STYLE_EXAMPLE>`. Verifier et adapter :
- S'assurer que tous les tests existants (13 actuellement) passent toujours.
- Patcher `style_loader.load_style_example` pour retourner `""` dans les tests
  qui ne testent pas l'injection (isoler le comportement).
- Ajouter le patch comme decorator `@patch("redacteur_outreach.style_loader.load_style_example", return_value="")`
  sur les tests existants qui pourraient etre impactes.

**Critere d'acceptation :**
`python -m unittest discover agents/redacteur_outreach/tests` : 0 erreur, 0 echec.
Le compte de tests augmente (13 existants + 3 nouveaux de T3 + 4 de T2 + 1 de T1 = 21 minimum).

**Tests :** Pas de nouveaux tests — adaptation des existants.

**Risques :** Faible. Si un test verifie le contenu exact du user_msg via
`call_args_list[0].args[1]["content"]` ou similaire, il faut soit patcher
`load_style_example`, soit assouplir l'assertion (contains plutot qu'equals).

---

### T5 — Etendre _normalize_outreach pour inclure context_json [XS]

**Fichiers touches :**
- `agents/dashboard_reflex/dashboard_reflex/state.py`

**Depend de :** T1 (independant des axes backend, mais doit preceder T6 et T7)

**Description :**
Ajouter `context_json` au dict `_OUTREACH_EMPTY` et au normalizer
`_normalize_outreach` pour que `selected_outreach["context_json"]` soit
accessible cote Reflex.

Modifications minimales :
1. Dans `_OUTREACH_EMPTY` : ajouter `"context_json": ""`.
2. Dans `_normalize_outreach` : ajouter `"context_json"` dans `str_fields`
   (on le traite comme str — c'est du JSON serialise).
3. Dans `get_outreach_message` de `services/data.py` : verifier que
   `dataclasses.asdict(msg)` inclut bien `context_json` (c'est un champ de
   `OutreachMessage` — oui, il est deja la). Aucune modification necessaire
   cote data.py si c'est le cas.

**Critere d'acceptation :**
```python
from dashboard_reflex.state import _normalize_outreach
result = _normalize_outreach({"context_json": '{"incident": {"marque": "ACME"}}'})
assert result["context_json"] == '{"incident": {"marque": "ACME"}}'

result_none = _normalize_outreach(None)
assert "context_json" in result_none
assert result_none["context_json"] == ""
```

**Tests :**
Test Python direct (pas de test Reflex automatise). Ajouter une assertion dans
le smoke test data layer documente dans `agents/dashboard_reflex/CLAUDE.md` :
```python
msg = data.get_outreach_message(source, source_id)
assert "context_json" in msg
```
Ce test est manuel (pas de fichier test unitaire pour le dashboard).

**Risques :**
- `_normalize_outreach` est utilise dans 5 endroits de `state.py` (lignes 673,
  675, 702, 727, 744, 756, 771). L'ajout du champ est additif — aucun breaking
  change sur les callers existants.

---

### T6 — Ajouter @rx.var outreach_kpi_payload dans state.py [S]

**Fichiers touches :**
- `agents/dashboard_reflex/dashboard_reflex/state.py`

**Depend de :** T5

**Description :**
Ajouter une var calculee `@rx.var` qui parse le `context_json` de
`selected_outreach` et expose 3 sous-dicts normalises, prets a alimenter les
charts du drawer sans nouvelle requete DB.

```python
@rx.var
def outreach_kpi_payload(self) -> dict[str, Any]:
    import json as _json
    raw = (self.selected_outreach or {}).get("context_json") or ""
    try:
        ctx = _json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        ctx = {}

    # --- score_dims ---
    score = ctx.get("score") or {}
    score_dims = {
        "score_total": float(score.get("score_total") or 0),
        "tier": str(score.get("tier") or "faible"),
        "dimensions": [
            {
                "name": str(d.get("name") or ""),
                "score": float(d.get("raw") or d.get("score") or 0),
                "weight": float(d.get("weight") or 0),
            }
            for d in (score.get("dimensions") or [])
            if isinstance(d, dict)
        ],
    }

    # --- sources_distribution ---
    signaux = ctx.get("signaux_summary") or []
    sources_dist = [
        {
            "source_name": str(s.get("source_name") or "")[:30],
            "count": int(s.get("count") or 1),
        }
        for s in signaux[:5]
        if isinstance(s, dict) and s.get("source_name")
    ]

    # --- contact_summary ---
    enrich = ctx.get("enrichissement") or {}
    contact_summary = {
        "confidence": float(enrich.get("confidence") or 0.0),
        "contact_type": str(enrich.get("contact_type") or ""),
        "contact_nom": str(enrich.get("contact_nom") or ""),
        "contact_titre": str(enrich.get("contact_titre") or ""),
    }

    return {
        "score_dims": score_dims,
        "sources_dist": sources_dist,
        "contact_summary": contact_summary,
    }
```

**Critere d'acceptation :**
- En Python pur (sans lancer Reflex) : `DashboardState().outreach_kpi_payload`
  retourne un dict avec les 3 cles `score_dims`, `sources_dist`, `contact_summary`.
- Avec `selected_outreach["context_json"] = ""` : les sous-dicts sont vides/defaut
  sans lever d'exception.
- Avec un `context_json` mal forme (JSON invalide) : retourne les sous-dicts vides
  sans lever d'exception.

**Tests :**
Test manuel (smoke test) ou test Python pur instanciant `DashboardState` directement.
Verifier les 3 cas : context_json vide, context_json valide, context_json invalide.

**Risques :**
- `@rx.var` est recalcule a chaque render. Le `json.loads` est O(1) sur le petit
  blob stocke — pas de probleme de perf.
- Reflex serialise les `@rx.var` vers le frontend via WebSocket. Le type de retour
  doit etre un `dict[str, Any]` — pas une dataclass, pas un objet custom. La
  definition ci-dessus respecte cette contrainte.
- Si `signaux_summary` est une liste de dicts avec un seul element par source
  (le `context_json` actuel), `count=1` est correct. Verifier la structure reelle
  d'un `context_json` existant avant de coder.

---

### T7 — Modifier outreach_drawer.py : largeur 720px + section INSIGHTS [M]

**Fichiers touches :**
- `agents/dashboard_reflex/dashboard_reflex/components/outreach_drawer.py`

**Depend de :** T6

**Description :**
Deux modifications dans ce fichier :

**A. Largeur** :
Passer `width="480px"` en `width="720px"` (ligne 381 actuelle).
`max_width="95vw"` reste inchange — protege le mobile.

**B. Section INSIGHTS** :
Ajouter une fonction `_insights_block()` qui retourne le composant INSIGHTS,
a inserer dans `outreach_drawer()` entre `_actions_row()` et la section
`TRACABILITE`.

La section contient 3 sous-blocs en `rx.grid` (3 colonnes desktop, 1 colonne
mobile via media query) :

1. **Score sanitaire** (`_kpi_score_gauge()`) :
   - `rx.recharts.radial_bar_chart` avec une seule barre representant
     `outreach_kpi_payload["score_dims"]["score_total"]` sur 100.
   - Hauteur fixe `height=120` (pas `"100%"` — cf piege recharts dans drawer).
   - Label central = tier (texte statique dans la legende ou via
     `rx.recharts.label`).
   - Sous la gauge : 4 lignes de sous-scores (`rx.foreach` sur
     `outreach_kpi_payload["score_dims"]["dimensions"]`).

2. **Couverture mediatique** (`_kpi_sources_bar()`) :
   - `rx.recharts.bar_chart` horizontal : `layout="vertical"`,
     `width=200`, `height=120`.
   - `rx.recharts.bar(data_key="count")`.
   - `rx.recharts.x_axis(type_="number")`.
   - `rx.recharts.y_axis(data_key="source_name", type_="category", width=80)`.
   - Donnees : `outreach_kpi_payload["sources_dist"]`.
   - Si liste vide : afficher un texte `"(aucun signal croise)"` a la place du chart.

3. **Qualite prospect** (`_kpi_contact_progress()`) :
   - Pas de chart — `rx.progress` Radix avec
     `value=outreach_kpi_payload["contact_summary"]["confidence"] * 100`.
   - Label au-dessus : contact_type (cible / fallback_dirigeant / non trouve).
   - Label en-dessous : contact_nom + contact_titre si non vides.
   - Couleur progress : `color_scheme="green"` si confidence > 0.72,
     `color_scheme="amber"` si > 0.40, `color_scheme="red"` sinon.

**Media query mobile** :
Le `rx.grid` doit avoir `style={"grid-template-columns": "1fr 1fr 1fr", "@media (max-width: 640px)": {"grid-template-columns": "1fr"}}`.

**Critere d'acceptation :**
- Le composant `outreach_drawer()` se compile sans erreur Python :
  ```
  python -c "from dashboard_reflex.components.outreach_drawer import outreach_drawer; print('OK')"
  ```
- La largeur du drawer est bien `720px` dans le code.
- Les 3 sous-fonctions `_kpi_score_gauge`, `_kpi_sources_bar`,
  `_kpi_contact_progress` existent et sont appelees depuis `_insights_block`.
- `rx.foreach` sur une liste vide ne provoque pas d'erreur Reflex (tester avec
  `sources_dist=[]`).

**Tests :** Pas de test unitaire automatise (Reflex frontend non testable
unitairement). Verification par compile check puis smoke test T8.

**Risques :**
- `rx.recharts.radial_bar_chart` : verifier le nom exact de la classe dans
  `reflex 0.9` (peut etre `rx.recharts.RadialBarChart` selon la version).
  Utiliser `import reflex as rx; dir(rx.recharts)` pour lister les composants
  disponibles.
- Concat Var + str dans les labels : utiliser `rx.hstack(rx.text(...), rx.text(var))`
  plutot que concatenation directe.
- La `@rx.var outreach_kpi_payload` retourne un `dict`. Pour acceder aux sous-dicts
  dans le composant, utiliser `DashboardState.outreach_kpi_payload["score_dims"]`
  — Reflex supporte l'indexation des Var dict.

---

### T8 — Smoke test manuel dashboard [XS]

**Fichiers touches :** Aucun — test uniquement.

**Depend de :** T7

**Description :**
Lancer le dashboard Reflex en dev mode et verifier manuellement le drawer
outreach sur desktop et mobile.

Procedure :
1. Depuis `agents/dashboard_reflex` :
   `FRONTEND_PORT=3000 BACKEND_PORT=8000 .venv/Scripts/reflex run`
2. Ouvrir `http://localhost:3000`, aller sur la page Prospects.
3. Cliquer sur un prospect enrichi → ouvrir le drawer Prospect → cliquer
   "Message" → ouvrir le drawer Outreach.
4. Si aucun message n'existe : cliquer "Generer" et attendre.
5. Verifier :
   - Le drawer est bien a droite (pas a gauche — piege vaul `left="auto"`).
   - La largeur est ~720px sur un ecran 1440p.
   - La section INSIGHTS apparait avec les 3 blocs.
   - Le gauge score affiche une valeur numerique (meme 0 si pas de score).
   - Le bar chart sources s'affiche ou le texte fallback "(aucun signal croise)".
   - Le progress contact affiche une barre coloree.
6. Redimensionner le navigateur a <640px (ou ouvrir DevTools → mobile) :
   les 3 blocs INSIGHTS stackent verticalement (grid 1 colonne).
7. Si des artefacts visuels sur recharts (flickering, taille 0px) : fixer
   `height` en pixels dans les composants concernes et relancer.

**Critere d'acceptation :**
Les 5 verifications ci-dessus passent sans erreur console JS ni traceback Python.
Le drawer s'ouvre a droite a 720px, les INSIGHTS sont visibles, le mobile stacks
correctement.

**Tests :** Manuel uniquement — pas de test automatise pour Reflex frontend.

**Risques :**
- Build stale si `.web/` n'est pas regenere apres les changements Python.
  Remediation : `rm -rf .web/app .web/build` puis relancer.
- Process fantômes sur Windows : tuer via PowerShell avant de relancer
  (`Stop-Process` sur `python.exe`, `bun.exe`, `node.exe`).
- Si recharts ne s'affiche pas du tout : verifier dans `rxconfig.py` que
  `tailwind=None` n'entre pas en conflit, et que la version de Reflex inclut
  bien `rx.recharts` (disponible dans 0.9+).

---

### T9 — Verification compatibilite ascendante messages existants [XS]

**Fichiers touches :** Aucun — verification uniquement.

**Depend de :** T7

**Description :**
Verifier que les messages `redacteur_version="1.0"` deja en base s'affichent
correctement dans le drawer elargi sans regression.

Procedure :
1. Identifier un message existant en base avec `context_json` non vide :
   `python -m redacteur_outreach.cli list --limit 5` (depuis `agents/`).
2. L'ouvrir dans le dashboard. Verifier que le corps et l'objet s'affichent
   normalement.
3. Verifier que les KPI INSIGHTS s'affichent (meme partiellement) ou affichent
   un etat "vide" gracieux si le `context_json` manque certaines cles.
4. Cliquer "Regenerer" sur un message existant : verifier que le message genere
   porte bien `redacteur_version="1.1"` dans le CLI :
   `python -m redacteur_outreach.cli show <message_id> --format json`

**Critere d'acceptation :**
- Le message existant s'affiche sans erreur dans le drawer elargi.
- Apres regeneration, `redacteur_version` vaut `"1.1"`.
- Les charts INSIGHTS ne lèvent pas d'erreur JS si certaines cles de
  `context_json` sont absentes (dict vides retournes par `outreach_kpi_payload`).

**Tests :** Manuel.

**Risques :** Faible. Le `context_json` est un champ optionnel (peut etre `None`)
et T6 (`outreach_kpi_payload`) gere ce cas avec `try/except` et valeurs par defaut.

---

## 4. Estimation totale

| Tache | Complexite | Heures estimees |
|---|---|---|
| T1 — Bump REDACTEUR_VERSION | XS | 0.25h |
| T2 — style_loader.py + example_default.txt | S | 1h |
| T3 — Injection exemple dans llm_rewriter | S | 1.5h |
| T4 — Mise a jour fixtures tests existants | XS | 0.5h |
| T5 — Etendre _normalize_outreach context_json | XS | 0.5h |
| T6 — @rx.var outreach_kpi_payload | S | 1h |
| T7 — outreach_drawer.py 720px + INSIGHTS | M | 3h |
| T8 — Smoke test dashboard | XS | 0.5h |
| T9 — Compatibilite ascendante messages 1.0 | XS | 0.25h |
| **Total** | **M** | **~8.5h** |

**Chemin critique** : T1 → T2 → T3 → T4 (axe backend, ~3.25h)
en parallele de : T5 → T6 → T7 → T8 (axe dashboard, ~5.25h)
puis T9 (validation finale, ~0.25h).

Les deux axes sont independants a partir de T1/T5 et peuvent etre travailles
en parallele si deux devs disponibles.

---

## 5. Points d'attention transverses

### ASCII / Windows cp1252
- `style_loader.py` doit normaliser vers ASCII a l'ingestion du fichier exemple
  (`unicodedata.normalize("NFKD", ...)`) — Gautier fournira un fichier UTF-8 avec
  accents. La normalisation se fait UNE SEULE FOIS a la lecture, pas a chaque
  generation.
- Les tests de `test_style_loader.py` doivent tester explicitement un fichier
  contenant des accents (ex: `"cafe"` avec accent) et verifier `result.isascii()`.
- Les CLI outputs existants restent ASCII (pas touche).

### Fallback LLM
- Le fallback deterministe (`body_fallback`) est **strictement inchange** :
  `template_renderer.py` et `email_fr.txt` ne sont pas modifies.
- Si `load_style_example()` retourne `""` (fichier absent, erreur I/O), le
  `llm_rewriter` doit se comporter exactement comme avant T3 — le bloc
  `<STYLE_EXAMPLE>` n'est simplement pas injecte.
- Le garde-fou hallucination (set de tokens numeriques autorises) n'est PAS
  elargi aux chiffres de l'exemple. C'est un invariant documente dans l'ADR
  et doit etre explicitement verifie dans T3.

### Mobile (drawer INSIGHTS)
- `max_width="95vw"` est deja en place sur le drawer — le passage a 720px
  n'affecte pas le mobile (le `max_width` prend le dessus sous 720px d'ecran).
- Le `rx.grid` INSIGHTS doit passer a 1 colonne sous 640px via media query
  style dict (pas de prop directe Reflex — cf CLAUDE.md section "CSS media queries").
- Les heights recharts doivent etre en pixels fixes (`height=120`) — `"100%"` ne
  fonctionne pas dans un vaul drawer (recharts calcule la hauteur avant que le drawer
  soit pleinement rendu, il obtient 0).

### Idempotence
- `message_id = sha1(source|source_id)[:16]` : inchange. Un message deja genere
  reste le meme message, seul `--force` force la regeneration.
- T9 verifie que la regeneration via `--force` ou le bouton "Regenerer" dans le
  drawer met bien `redacteur_version="1.1"` et beneficie de l'exemple stylistique.

### Hors scope (explicit)
- Selection multi-exemples par tier/source (V2 — dossier `style_examples/` extensible
  mais routing non implemente).
- A/B testing style.
- Edition du corps dans le drawer (reste read-only).
- Timeline incident/signaux dans le drawer.
- Export PDF/EML depuis le drawer.
- Push CRM Sellsy.
- Prompt caching Anthropic.
- Modification de `email_fr.txt`.
- Refonte de `pitch.json`.
