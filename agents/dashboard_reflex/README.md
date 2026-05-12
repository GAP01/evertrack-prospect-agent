# Dashboard Reflex — EverTrack

Dashboard SaaS B2B (style Linear / Stripe) construit avec **Reflex**
(Python → Next.js/React). Il lit la meme base SQLite que le dashboard
Streamlit et reutilise les memes modules `dashboard/data_access.py` et
`dashboard/actions.py`.

## Structure

```
dashboard_reflex/
├── rxconfig.py                 # config Reflex (ports, nom de l'app)
├── requirements.txt
├── README.md
└── dashboard_reflex/
    ├── __init__.py
    ├── dashboard_reflex.py     # point d'entree — routing + theme
    ├── state.py                # DashboardState (Reflex) + @rx.var KPI outreach
    ├── services/
    │   ├── data.py             # bridge vers dashboard.data_access / actions
    │   │                       # + build_outreach_kpi (parse context_json)
    │   ├── normalize.py        # couche pure (sans import Reflex) — testable
    │   │                       # hors venv dashboard
    │   └── tests/              # tests unitaires services (78 tests)
    └── components/
        ├── tier_badge.py
        ├── sidebar.py
        ├── header.py
        ├── kpi_cards.py
        ├── incident_table.py
        ├── incident_detail_drawer.py
        ├── prospects_table.py
        ├── prospect_detail_drawer.py
        ├── signaux_table.py
        ├── signal_detail_drawer.py
        └── outreach_drawer.py  # drawer 720px + section INSIGHTS (KPI graphiques)
```

## Installation

Depuis la racine `agents/dashboard_reflex/` :

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Reflex tire tout le reste (Node + bun) la premiere fois qu'on lance
`reflex init`.

## Initialisation

```powershell
reflex init
```

Quand il demande un template : **blank**. Reflex generera les dossiers
`.web/` et `assets/` manquants. Le code de l'app est deja en place.

## Lancement

```powershell
# Depuis agents/dashboard_reflex/
reflex run
```

- Frontend : http://localhost:3000
- Backend (API Reflex interne) : http://localhost:8000

La premiere compilation Next.js prend ~30 s.

## Variables d'environnement

| Variable | Defaut | Role |
|----------|--------|------|
| `EVERTRACK_DATA_DIR` | `agents/data` | Dossier des SQLite |
| `EVERTRACK_DEMO_MODE` | (vide) | `1`/`true` → desactive fetch + score (protege la cle Anthropic) |
| `ANTHROPIC_API_KEY` | — | Requis uniquement si tu declenches un score depuis l'UI |

Exemple en mode demo (PowerShell) :

```powershell
$env:EVERTRACK_DEMO_MODE = "1"
reflex run
```

## Expose en HTTPS pour un demo

Avec `cloudflared` deja installe (cf. `install_cloudflared.ps1` a la racine
du projet) :

```powershell
cloudflared tunnel --url http://localhost:3000
```

Cloudflare renvoie une URL `https://xxx.trycloudflare.com` a partager.
Rappel : le backend Reflex tourne sur `:8000`, le front sur `:3000`, et le
front appelle le back par WebSocket. En mode quick-tunnel, seule l'URL 3000
est exposee — Reflex gere automatiquement le chemin `_event` cote backend
via sa configuration `api_url`. Si besoin, configurer `api_url` dans
`rxconfig.py` pour pointer vers la meme origine publique.

## Drawer outreach (page Prospects)

Le drawer "Message" (`outreach_drawer.py`) s ouvre depuis la page Prospects.

- **Largeur** : 720 px (bureau), 100 % largeur en dessous de 768 px.
- **Section INSIGHTS** : affichee quand `context_json` est present, masquee
  sinon (placeholder "Donnees KPI insuffisantes").
  - KPI 1 Score sanitaire : radial bar chart (`rx.recharts`, 160x100 px).
  - KPI 2 Sources mediatiques : bar chart horizontal par source
    (`rx.recharts`), alimente par `signaux_summary` du `context_json`.
  - KPI 3 Confidence prospect : barre CSS (`rx.progress`) + label texte
    ("Contact cible 0.82" / "Fallback dirigeant" / "Non trouve").
- **Zero requete supplementaire** : toutes les donnees KPI viennent du
  `context_json` deja stocke en base a la generation du message.
- **Vars `@rx.var` exposes** dans `state.py` :
  `outreach_kpi_score_value`, `outreach_kpi_score_label`,
  `outreach_kpi_score_color`, `outreach_kpi_sources_total`,
  `outreach_kpi_sources_data`, `outreach_kpi_confidence_value`,
  `outreach_kpi_confidence_percent`, `outreach_kpi_confidence_status`,
  `outreach_kpi_has_data`.

## services/normalize.py

Module pur sans import Reflex. Contient `normalize_outreach_pure` et
`build_outreach_kpi_pure` — memes regles que `state._normalize_outreach` et
`data.build_outreach_kpi`, mais utilisables dans le venv standard des agents
(sans installer Reflex). Sert de base aux tests de compatibilite ascendante
(`test_backward_compat.py`, `test_state_kpi_vars.py`, `test_data_kpi.py`).

## Design

- Palette : fond `#f9fafb`, cartes blanches, bordures `#e5e7eb`, accent
  `indigo` (#4f46e5), texte principal `#111827`.
- Typographie : Inter (chargee via Google Fonts).
- Sidebar fixe 260 px + contenu principal fluide.
- Drawer droit 560 px pour le detail d incident, 720 px pour le drawer
  outreach.

## Mode demo

Quand `EVERTRACK_DEMO_MODE=1` :

- Les boutons "Rafraichir la veille" et "Scorer les incidents" sont
  desactives et un badge "Mode demo" s'affiche dans la sidebar.
- Aucun appel Anthropic n'est emis depuis l'UI.
- Toutes les lectures restent actives (donnees, filtres, drawer).

## Notes

- L'app reutilise le meme SQLite que Streamlit — pas de duplication de
  donnees. Tu peux laisser Streamlit tourner en parallele si tu veux
  comparer.
- Le bridge `services/data.py` ajoute `agents/` au `sys.path` pour
  permettre l'import des modules voisins (`veilleur_incidents`,
  `evaluateur_severite`, `dashboard`).
