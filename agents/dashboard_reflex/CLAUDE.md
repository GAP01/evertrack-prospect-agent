# Dashboard Reflex — SPA web EverTrack

## 1. Rôle et responsabilité

Single-Page Application Reflex (Python → React Router 7 + Radix Themes) qui
visualise les données des 4 SQLite produites par les agents, permet la
validation humaine et le cross-référencement interactif.

3 pages routées par `DashboardState.current_page` :
- **Radar incidents** — liste des incidents RappelConso scorés
- **Signaux faibles** — liste des alertes presse/social avec matching rappels
- **Prospects** — enrichissements SIRENE des marques avec contacts cibles

## 2. Fichiers principaux

```
dashboard_reflex/
├── rxconfig.py              # Config Reflex (app_name = dashboard_reflex)
├── requirements.txt         # reflex>=0.9, dateutil, dotenv
├── .venv/                   # venv dédié — ne PAS mélanger avec Python système
├── .web/                    # Auto-généré (Vite + React) — régénère si stale
│   └── app/                 # routes.js, entry.client.js, root.jsx
│
└── dashboard_reflex/
    ├── dashboard_reflex.py  # index() + app + routing rx.match + mobile bottom nav
    ├── state.py             # DashboardState (toutes les vars + event handlers)
    ├── services/
    │   └── data.py          # Lecture 4 SQLite + handlers confirm_match / set_signal_status
    └── components/
        ├── sidebar.py              # Desktop nav (cachée <640px)
        ├── header.py               # Breadcrumb + toast + bouton Rafraîchir
        ├── kpi_cards.py            # 4 KPI du Radar
        ├── incident_table.py       # Table + filtres + click → drawer
        ├── incident_detail_drawer.py
        ├── prospects_table.py
        ├── prospect_detail_drawer.py
        ├── signaux_table.py        # Avec KPI lead time + matches rappels
        ├── signal_detail_drawer.py # Avec lien source prominent + matches auto-confirmés
        └── tier_badge.py
```

### Points d'entrée

| Fichier | Rôle |
|---|---|
| `dashboard_reflex.py` | `index()` : sidebar + `rx.match` sur current_page + 3 drawers + mobile nav |
| `state.py` | Source de vérité de tout l'état front (rx.State + @rx.var + handlers) |
| `services/data.py` | **Bridge** vers `../dashboard/data_access.py` + lectures directes signaux/enrichissements |

## 3. État Reflex (`state.py`)

### Vars par page

```python
class DashboardState(rx.State):
    current_page: str = "radar"   # "radar" | "prospects" | "signaux"

    # Radar (incidents)
    stats, rows, sous_categories, tier_filter, sous_cat_filter, limit
    drawer_open, selected_source, selected_source_id, selected_incident, selected_score

    # Prospects
    enrich_rows, enrich_stats, enrich_match_filter, enrich_limit
    prospect_drawer_open, selected_enrich

    # Signaux
    signal_rows, signal_stats, signal_status_filter, signal_limit
    signal_drawer_open, selected_signal

    # Cross-ref (matches signaux ↔ incidents)
    match_stats, selected_signal_matches, selected_incident_matches
```

### Event handlers principaux

```python
# Navigation
def nav_radar(self), nav_signaux(self), nav_prospects(self)

# Radar
def load_initial(self)      # on_load de la page
def _refresh(self)          # Recharge rows triés par date desc, score desc
def open_incident(self, source, source_id)
def action_fetch(self)      # Déclenche veilleur
def action_score(self)      # Déclenche evaluateur

# Signaux
def _load_signaux(self)     # Charge rows + stats + match_stats
def open_signal(self, signal_id)
def validate_signal(self, signal_id)   # → status=valide
def reject_signal(self, signal_id)     # → status=rejete
def confirm_signal_match(self, signal_id, inc_source, inc_source_id)
def unconfirm_signal_match(self, signal_id, inc_source, inc_source_id)

# Prospects
def _load_enrichissements(self)
def open_prospect(self, source, source_id)
```

### Normalizers (`state.py` top-level)

Convertissent les dicts SQLite en dicts "safe pour Reflex Var" (str forcé sur
champs texte, int/float forcés sur numériques) :

```python
_normalize_incident, _normalize_score, _normalize_dimension
_normalize_enrich_row, _normalize_enrich_detail
_normalize_signal_row, _normalize_signal_detail
_normalize_signal_match, _normalize_incident_match
```

⚠️ **Tout ajout de colonne DB doit passer par un normalizer** — Reflex ne gère
pas les `None` → affichage cassé.

## 4. Composants clés

### Drawers (pattern commun)

```python
rx.drawer.root(
    rx.drawer.overlay(z_index="10"),
    rx.drawer.portal(
        rx.drawer.content(
            rx.box(...),
            # CSS CRUCIAL :
            position="fixed",
            top="0", right="0", bottom="0",
            left="auto",              # ← ANNULE le left:0 injecté par vaul
            height="100vh", width="560px", max_width="95vw",
            z_index="50",
        ),
    ),
    open=...,
    on_open_change=...,
    direction="right",
)
```

### Layout responsive

```python
# Sidebar : cachée <640px
style={"@media (max-width: 640px)": {"display": "none"}}

# Main content : padding réduit + plus de margin-left sur mobile
style={
    "padding": "32px 40px",
    "margin-left": "260px",
    "@media (max-width: 640px)": {
        "margin-left": "0px",
        "padding": "16px 12px 80px",   # 80px bottom pour mobile nav
    },
}

# Mobile bottom nav : fixed z-index 9999 + translateZ(0) pour forcer stacking
```

### Tables responsive (incidents/signaux/prospects)

```python
rx.box(
    rx.cond(
        count > 0,
        rx.box(
            rx.table.root(..., min_width="640px"),  # force scroll sur mobile
            overflow_x="auto",
            width="100%",
        ),
        _empty_state(),
    ),
    border_radius="12px",
    overflow="hidden",
)
```

## 5. Lancer le dashboard

### Prérequis

Venv dédié avec Reflex 0.9 installé dans `dashboard_reflex/.venv/`.

### Dev mode (hot-reload)
```bash
cd agents/dashboard_reflex
FRONTEND_PORT=3000 BACKEND_PORT=8000 .venv/Scripts/reflex run
```

### Prod mode (build optimisé — recommandé pour usage)
```bash
cd agents/dashboard_reflex
FRONTEND_PORT=3000 BACKEND_PORT=8000 .venv/Scripts/reflex run --env prod
```

### Tunnel Cloudflare (accès externe/mobile)
```bash
cd agents
cloudflared tunnel --url http://localhost:3000
```
Génère `https://<random>.trycloudflare.com` valide tant que le process tourne.

## 6. Dépendances

### `requirements.txt`
```
reflex>=0.9
python-dateutil
python-dotenv
```

### Stack technique complet
- **Reflex 0.9** (transcompile Python → React + Vite)
- **Radix Themes** (composants UI de base)
- **vaul** (drawer side panel) — via `rx.drawer.*`
- **Lucide Icons** (via `rx.icon()`)
- **React Router 7** (routing interne, SPA mode `ssr: false`)
- **Bun** (bundler JS, remplace npm)

## 7. Tests

**Pas de tests automatisés pour le front** (Reflex ne fournit pas de framework
de test). Les tests sont manuels :

```bash
# Compile check (détecte erreurs Python + Var manipulation)
cd agents/dashboard_reflex
.venv/Scripts/python -c "
import sys; sys.path.insert(0, '.')
from dashboard_reflex.dashboard_reflex import app
print('COMPILE OK')
"

# Smoke test data layer
.venv/Scripts/python -c "
import sys; sys.path.insert(0, '.')
from dashboard_reflex.services import data
print('Stats incidents :', data.get_stats())
print('Signaux :', len(data.get_signaux()))
print('Matches :', data.get_match_stats())
"
```

## 8. Décisions techniques

### Reflex 0.9 + React Router 7

Migration de Streamlit → Reflex fin 2026 pour :
- UI beaucoup plus riche (drawers, animations, responsive mobile)
- Code 100% Python (pas de JSX à maintenir)
- Déploiement simple (Python + static build)

### Pas d'API REST — accès SQLite direct

Le backend Reflex lit directement les 4 SQLite via `services/data.py`. Pas
d'abstraction API, pas de serveur séparé. Simple et suffisant pour l'usage.

### Architecture 3 pages via `rx.match`

Plutôt que 3 routes React Router, on a **1 seule route `/`** et `current_page`
comme var. Switch entre les 3 vues via `rx.match(current_page, ...)` dans
`index()`. Raison : Reflex gère mal les routes multiples avec états partagés.

### CSS responsive via `style={"@media ..."}`

Reflex passe `style` comme inline CSS dans React. Les media queries Radix ne
sont pas accessibles directement → on passe par style dict + @media.

### Drawers toujours à droite

`direction="right"` + `left="auto"` explicite pour neutraliser vaul qui injecte
`left: 0` par défaut et brise le `right: 0`. Pattern répété dans les 3 drawers.

### Mobile bottom nav avec z-index 9999

Pour échapper au stacking context créé par Radix Theme, on utilise
`position="fixed"` + `z_index="9999"` + `transform="translateZ(0)"` (crée un
nouveau stacking context isolé).

### Pas de rebuild automatique sur changement DB

Le dashboard lit les SQLite **à chaque navigation/refresh** via `_load_*()`.
Pas de cache → données toujours fraîches, mais coûteux si SQLite énorme
(pas encore un problème à notre échelle).

## 9. Pièges courants (bugs déjà rencontrés et résolus)

### Var + string concat
```python
# ❌ CASSE
rx.text("Préfixe " + sig["field"], ...)

# ✅ OK (deux composants)
rx.hstack(rx.text("Préfixe"), rx.text(sig["field"]))

# ✅ OK (Var à gauche)
rx.text(sig["field"].to(str) + " suffix", ...)
```

### Build stale après changement
Symptôme : le dashboard sert une vieille version.
```bash
cd agents/dashboard_reflex
rm -rf .web/app .web/build .web/.react-router
# Puis relancer reflex run
```

### `routes.js` manquant après cleanup
Si `.web/app` est supprimé complètement, Reflex ne régénère pas certains
fichiers statiques. Les recréer depuis les templates :
```bash
ls .venv/Lib/site-packages/reflex_base/.templates/web/app/
# Contient routes.js + entry.client.js à copier dans .web/app/
```

### Process fantômes sur Windows
`taskkill` et `kill` ne tuent pas les PIDs WSL/Git Bash. Utiliser PowerShell :
```powershell
Get-WmiObject Win32_Process | Where-Object {
    $_.Name -in @("python.exe","bun.exe","node.exe")
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### Ports 3000/3001/3002 pris par fantômes
Parfois Reflex bind sur un port autre si 3000 occupé. Pour forcer un port
précis :
```bash
FRONTEND_PORT=3000 BACKEND_PORT=8000 .venv/Scripts/reflex run --env prod
```
Si ça échoue : kill les processes comme ci-dessus puis relancer.

### Noms de colonnes DB
Le code utilisait historiquement `motif_rappel`, `risques_encourus`,
`lien_fiche` (noms de l'ancienne API RappelConso). Les colonnes actuelles sont
`motif`, `risques`, `source_url`. Si tu vois des boxes grises vides dans le
drawer incident, c'est sûrement ça.

## 10. À savoir pour toute évolution

- **Ajouter une page** : ajoute "X" dans `current_page` literal, crée les
  vars/handlers dans `state.py`, crée `components/x_table.py` + éventuellement
  `x_detail_drawer.py`, branche dans `dashboard_reflex.py index()` via
  `rx.match`, ajoute l'item dans sidebar + mobile bottom nav.
- **Ajouter un KPI** : composant `_kpi_card(label, value, icon, color)` réutilisable
  dans `kpi_cards.py` / `signaux_table.py`. Branche la var depuis `state.py`
  avec `@rx.var`.
- **Icônes** : via `rx.icon("nom")` — liste sur https://reflex.dev/docs/library/data-display/icon/
  Attention : certains noms ne sont pas supportés (ex: `check_circle` → utiliser
  `check_check`).
- **Debug CSS** : Reflex sérialise `style={}` en CSS inline React. Inspecter
  `.web/app/routes/_index.jsx` (fichier généré) pour voir exactement ce que
  reçoit le navigateur. Utile pour comprendre pourquoi un style n'est pas
  appliqué.
