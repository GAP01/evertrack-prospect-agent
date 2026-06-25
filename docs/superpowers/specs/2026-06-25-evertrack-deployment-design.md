# EverTrack — Déploiement en ligne (démo partagée)

> Spec de déploiement validée le 2026-06-25. Objectif : mettre le dashboard
> Reflex en ligne pour une démo à accès partagé, avec un pipeline GitHub propre.

## 1. Contexte & contraintes

EverTrack est un pipeline d'agents IA (crawl RappelConso, scoring sanitaire,
enrichissement prospects, signaux faibles, rédaction outreach) qui alimente un
**dashboard Reflex** (frontend React + backend WebSocket Python). Les données
vivent dans plusieurs fichiers **SQLite locaux** (`incidents`, `scores`,
`enrichissements`, `signaux`, `outreach`…), gitignorés car ils contiennent des
données prospects (RGPD).

Aujourd'hui le dashboard n'est accessible qu'en local + tunnel cloudflared
éphémère. Pas de Dockerfile, pas de CI. Remote : `GAP01/evertrack-prospect-agent`.

### Décisions de cadrage (validées en brainstorming)

| Axe | Choix | Conséquence |
|---|---|---|
| Audience | Démo / accès partagé | Pas de multi-tenant, pas d'inscription, pas de SLA 24/7 |
| Production des données | **Snapshot manuel** | Les agents tournent en local ; le dashboard en ligne est lecture seule |
| Hébergement | **Railway** (PaaS conteneur) | Deploy GitHub natif, HTTPS auto, pas de spin-down |
| Protection d'accès | **Basic Auth** (mot de passe partagé) | Injecté dans le reverse proxy Caddy |
| Transfert des snapshots | **GitHub Releases** (asset privé) | Zéro service externe ; tout reste dans GitHub |

### Non-objectifs (YAGNI)

- Pas d'auth par utilisateur, pas de comptes, pas de billing.
- Pas de crawl planifié en ligne (les agents ne tournent pas sur le serveur).
- Pas de base Postgres : on garde SQLite (lecture seule en prod).
- Pas de haute dispo / autoscaling : une seule instance suffit pour une démo.

## 2. Architecture cible

Un **seul conteneur** déployé sur Railway :

```
┌─────────────────────── conteneur Railway ───────────────────────┐
│                                                                   │
│   Caddy (écoute $PORT public fourni par Railway)                  │
│    ├── Basic Auth (BASIC_AUTH_USER / BASIC_AUTH_HASH via env)     │
│    ├── sert le frontend Reflex (export statique)                  │
│    └── proxy WebSocket /_event, /ping, /_upload ──► backend :8000 │
│                                                       │           │
│                                            lit les SQLite depuis  │
│                                            $EVERTRACK_DATA_DIR     │
│                                            (= /data, éphémère)     │
│                                                                   │
│   entrypoint.sh : au boot, télécharge le snapshot depuis          │
│   l'asset GitHub Release "data-snapshot" → /data, puis lance      │
│   `reflex run --env prod` + Caddy.                                │
└───────────────────────────────────────────────────────────────────┘
```

**Pourquoi un seul conteneur + Caddy** : Reflex sert un frontend statique **et**
un backend WebSocket sur deux ports (3000/8000). Railway n'expose qu'un port
public. Caddy unifie tout derrière une seule URL HTTPS et porte la Basic Auth.
C'est le pattern self-host canonique documenté par Reflex.

**Pourquoi pas de volume persistant** : en mode snapshot manuel, `/data` est
ré-hydraté depuis GitHub Release à chaque boot. Rafraîchir = `make push-snapshot`
puis redémarrer le service. Cela supprime la gestion d'un volume Railway.

## 3. Flux de données (snapshot manuel)

```
   LOCAL (poste de Gautier)                      EN LIGNE (Railway)
   ─────────────────────────                     ──────────────────
   python -m <agent>.cli ...   produit les
        │                      SQLite dans
        ▼                      agents/data/
   make push-snapshot
        │  tar.gz des *.sqlite (hors secrets)
        ▼
   gh release upload data-snapshot
        data-snapshot.tar.gz --clobber
        │ (asset privé, tag fixe "data-snapshot")
        ▼
   ┌──── GitHub Release "data-snapshot" ────┐
   │     data-snapshot.tar.gz               │
   └────────────────┬───────────────────────┘
                    │  au boot / au restart
                    ▼
        entrypoint.sh télécharge l'asset
        (GitHub API + GITHUB_SNAPSHOT_TOKEN)
        → extrait dans /data
                    ▼
        dashboard Reflex lit /data (lecture seule)
```

### Détail du transfert GitHub Release

- **Tag fixe** `data-snapshot` (pré-release), un seul asset `data-snapshot.tar.gz`
  écrasé à chaque push (`gh release upload ... --clobber`).
- **Contenu du tar.gz** : uniquement les `agents/data/*.sqlite` nécessaires au
  dashboard. **Exclus** : `.sellsy_token.json`, `*.json` de cache, tout secret.
- **Téléchargement côté conteneur** (repo privé → token requis) :
  1. `GET /repos/GAP01/evertrack-prospect-agent/releases/tags/data-snapshot`
     → récupère l'`id` de l'asset.
  2. `GET /repos/.../releases/assets/{id}` avec `Accept: application/octet-stream`
     et `Authorization: Bearer $GITHUB_SNAPSHOT_TOKEN` → télécharge le tar.gz.
  3. Extraction dans `$EVERTRACK_DATA_DIR`.
- **Token** : PAT fine-grained en lecture seule sur ce repo (`contents: read`),
  stocké en variable Railway `GITHUB_SNAPSHOT_TOKEN`. Jamais commité.
- **Démarrage à froid** : si l'asset est absent, le conteneur démarre quand même
  avec un `/data` vide et logge un WARNING (dashboard vide mais pas de crash).

## 4. Modifications de code applicatif (minimales)

1. **`agents/dashboard_reflex/.../services/data.py`** — rendre le répertoire des
   SQLite configurable :
   ```python
   DATA_DIR = Path(os.environ.get("EVERTRACK_DATA_DIR", <défaut local agents/data>))
   ```
   Aujourd'hui les chemins sont relatifs en dur ; c'est le seul vrai changement.
   Couvert par un test (env var → chemin résolu).
2. **`rxconfig.py`** — config prod : `api_url` depuis `API_URL` env, exécution en
   `--env prod`. Garder le comportement local par défaut.
3. **`requirements.txt` du conteneur** — compléter avec les deps réellement
   importées au boot. Le dashboard importe plusieurs agents au niveau module
   (via `dashboard.actions` / `services/data.py`) : auditer la chaîne d'import
   complète (`requests`, `anthropic`, `feedparser`, `python-dateutil`,
   `googlenewsdecoder`…) pour éviter un `ImportError` au démarrage du conteneur.

Aucune logique métier modifiée. Aucun comportement du dashboard changé.

## 5. Fichiers de déploiement ajoutés

```
deploy/
├── Dockerfile          # multi-stage : base Python 3.12 + Node (build frontend) + Caddy
├── Caddyfile           # reverse proxy + Basic Auth, écoute :$PORT
└── entrypoint.sh       # fetch snapshot GitHub Release → /data, puis reflex prod + caddy
Makefile                # cibles : push-snapshot, deploy-check
railway.json            # build via deploy/Dockerfile
.github/workflows/ci.yml # tests unittest (gate PR)
.env.example            # documente les variables (sans valeurs)
```

### Dockerfile (esquisse)

- Stage 1 : `python:3.12-slim`, install des requirements, `reflex init`,
  `reflex export --frontend-only --no-zip` pour produire le build statique
  (nécessite Node — installé dans le stage).
- Stage final : Python slim + Caddy (binaire), copie du backend + frontend
  exporté, `entrypoint.sh` comme `CMD`.
- Le build se fait **sans données** (snapshot injecté au runtime, pas au build).

### Caddyfile (esquisse)

```
:{$PORT} {
    basicauth {
        {$BASIC_AUTH_USER} {$BASIC_AUTH_HASH}   # hash bcrypt via `caddy hash-password`
    }
    @ws path /_event* /ping*
    reverse_proxy @ws localhost:8000
    reverse_proxy /_upload* localhost:8000
    root * /srv/frontend
    file_server
}
```
(Le découpage exact frontend/backend sera calé sur le pattern Reflex officiel
lors de l'implémentation.)

## 6. Pipeline GitHub « clean »

```
   branche feature ──► Pull Request
                          │
                          ▼
              GitHub Actions  ci.yml
              python -m unittest discover -s agents   (~280 tests)
              + lint léger (ruff si dispo)
                          │ doit passer
                          ▼  (branch protection sur main)
              merge sur main
                          │
                          ▼
              Railway détecte le push sur main
              build deploy/Dockerfile ──► deploy auto
```

- **CI** (`.github/workflows/ci.yml`) : lance la suite unittest des agents + du
  dashboard sur chaque PR. Sert de gate qualité.
- **Branch protection** sur `main` : CI verte obligatoire avant merge (+ revue si
  souhaité).
- **Deploy** : natif Railway (connexion du repo, auto-deploy sur push `main`).
  Aucun secret de déploiement à stocker dans GitHub → surface d'attaque réduite.
- **Rollback** : Railway garde l'historique des déploiements (redeploy d'une
  version précédente en un clic).

## 7. Secrets & variables d'environnement

| Variable | Où | Rôle |
|---|---|---|
| `EVERTRACK_DATA_DIR` | Railway | `/data` en prod |
| `GITHUB_SNAPSHOT_TOKEN` | Railway | PAT lecture seule pour télécharger l'asset snapshot |
| `BASIC_AUTH_USER` | Railway | Login de la démo |
| `BASIC_AUTH_HASH` | Railway | Hash bcrypt du mot de passe (jamais en clair) |
| `API_URL` | Railway | URL publique pour `rxconfig` |
| `ANTHROPIC_API_KEY` | Railway (optionnel) | Inutile en lecture seule ; à fournir seulement si une action LLM est déclenchée |
| `PORT` | Railway (auto) | Port public écouté par Caddy |

Côté CI GitHub, aucun secret applicatif n'est requis (les tests utilisent les
fallbacks déterministes). `.env.example` documente toutes les clés.

## 8. Tests & vérification

- **Test unitaire** : `data.py` lit bien `EVERTRACK_DATA_DIR` (résolution chemin).
- **CI** : la suite unittest existante passe en environnement GitHub Actions
  (sans clés API → chemins fallback).
- **Smoke test déploiement** : après le premier deploy Railway, vérifier
  (a) la Basic Auth bloque l'accès anonyme, (b) le dashboard charge les 3 pages,
  (c) le snapshot a bien été récupéré (KPI non vides), (d) le WebSocket tient
  (navigation/filtres réactifs).
- **Test du cycle snapshot** : `make push-snapshot` → restart Railway → données
  rafraîchies visibles.

## 9. Risques & points d'attention

- **Chaîne d'imports du dashboard** : risque d'`ImportError` au boot si une dep
  transitive d'un agent manque dans l'image. Mitigation : audit explicite de la
  chaîne d'import + un boot local du conteneur avant le premier deploy.
- **Reflex en prod derrière un seul port** : le câblage `api_url` / WebSocket doit
  être calé précisément (point le plus délicat). Mitigation : suivre le pattern
  Docker officiel Reflex, smoke test WS.
- **Taille de l'image / build Node** : le build frontend Reflex tire Node + bun.
  Mitigation : multi-stage, ne garder que le build statique dans l'image finale.
- **Fraîcheur des données** : le restart est manuel après `push-snapshot`.
  Acceptable pour une démo ; documenté dans le Makefile / README.
- **Token GitHub dans le conteneur** : limiter le PAT à `contents: read` sur le
  seul repo, rotation possible. Ne jamais le logguer.

## 10. Découpage pressenti (pour le plan)

1. Rendre `EVERTRACK_DATA_DIR` configurable + test.
2. Audit de la chaîne d'imports → `requirements` complet du conteneur.
3. `deploy/Dockerfile` + `Caddyfile` + `entrypoint.sh` (sans snapshot, frontend
   exporté, Basic Auth) — boot local validé.
4. `entrypoint.sh` : fetch snapshot GitHub Release → `/data`.
5. `Makefile` : `push-snapshot` (tar.gz + `gh release upload --clobber`).
6. `.github/workflows/ci.yml` + `.env.example` + doc.
7. Setup Railway (manuel par Gautier : connexion repo, variables, premier deploy)
   + smoke test.
