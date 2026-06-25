# Déploiement EverTrack (démo Railway)

Dashboard Reflex en lecture seule, mis en ligne sur Railway. Les données sont
poussées manuellement par snapshot (les agents tournent en local, pas sur le
serveur). Accès protégé par Basic Auth.

Spec et plan :
- `docs/superpowers/specs/2026-06-25-evertrack-deployment-design.md`
- `docs/superpowers/plans/2026-06-25-evertrack-deployment.md`

## Architecture (rappel)

Un seul conteneur (`deploy/Dockerfile`) : Caddy écoute le `$PORT` public de
Railway, applique la Basic Auth, sert le frontend Reflex statique et
reverse-proxy le WebSocket vers le backend Reflex (`:8000`). Au démarrage,
`deploy/entrypoint.sh` télécharge le dernier snapshot SQLite depuis un asset de
GitHub Release privé vers `/data`, puis lance le backend.

## Setup initial (une fois)

1. **PAT GitHub** : créer un token fine-grained, repo `GAP01/evertrack-prospect-agent`,
   permission **Contents: Read-only**. Copier la valeur (commence par `github_pat_...`).
2. **Hash du mot de passe démo, en base64** (bcrypt encodé base64). On encode en
   base64 car le hash bcrypt contient des `$` que Railway interprète comme des
   références de variables et corrompt (erreur Caddy `base64-decoding password`).
   ```
   HASH=$(docker run --rm caddy:2 caddy hash-password --plaintext <motdepasse>)
   printf '%s' "$HASH" | base64 -w0
   ```
   Copier la chaîne base64 produite (uniquement des lettres/chiffres, aucun `$`).
3. **Railway** :
   - New Project -> Deploy from GitHub repo -> `evertrack-prospect-agent`.
     (Sélectionner la branche `feat/deployment-railway` tant que la PR n'est pas
     mergée ; après merge, `main` convient.)
   - Railway détecte `railway.json` et build via `deploy/Dockerfile`.
   - Onglet **Variables**, ajouter :
     | Variable | Valeur |
     |---|---|
     | `BASIC_AUTH_USER` | `demo` (ou autre) |
     | `BASIC_AUTH_HASH_B64` | la chaîne base64 de l'étape 2 |
     | `GITHUB_REPO` | `GAP01/evertrack-prospect-agent` |
     | `GITHUB_SNAPSHOT_TOKEN` | le PAT de l'étape 1 |
     | `EVERTRACK_DATA_DIR` | `/data` |

     > L'entrypoint décode `BASIC_AUTH_HASH_B64` vers `BASIC_AUTH_HASH` au
     > démarrage. On peut aussi fournir directement `BASIC_AUTH_HASH` (hash brut),
     > mais sur Railway les `$` du hash sont corrompus — préférer la version base64.
   - Onglet **Settings -> Networking** : générer un domaine public. Noter l'URL
     `https://<service>.up.railway.app`.
   - Ajouter la variable `API_URL` = cette URL publique HTTPS.
4. **Important — `API_URL` est bouclé au build du frontend.** Le premier build se
   fait avant que le domaine existe ; le frontend pointera alors vers une mauvaise
   origine WebSocket. Séquence correcte :
   - Laisser le premier déploiement se faire (domaine généré).
   - Renseigner `API_URL` avec le domaine public.
   - **Redéployer** (Railway -> Deployments -> Redeploy) pour que le frontend soit
     rebuild avec la bonne `API_URL`. Sans ce rebuild, le dashboard se charge mais
     le WebSocket (réactivité live) ne se connecte pas.
5. **Premier snapshot de données** : en local,
   ```
   make push-snapshot GH="/c/Program Files/GitHub CLI/gh.exe"
   ```
   puis **Restart** le service Railway pour qu'il récupère le snapshot.

## Rafraîchir les données

```
# 1. Faire tourner les agents en local (voir CLAUDE.md, section commandes CLI)
# 2. Pousser le snapshot
make push-snapshot GH="/c/Program Files/GitHub CLI/gh.exe"
# 3. Redémarrer le service sur Railway (bouton Restart)
```

Le conteneur re-télécharge le snapshot à chaque démarrage (pas de volume
persistant). Restart = données rafraîchies.

## Smoke test après déploiement

- URL publique SANS identifiants -> doit renvoyer 401.
- AVEC identifiants -> les 4 pages du dashboard chargent.
- Navigation/filtres réactifs -> le WebSocket fonctionne (sinon, vérifier que
  `API_URL` a bien été renseignée ET que le service a été redéployé après).
- KPI non vides -> le snapshot a bien été récupéré.

## Note RGPD / données

Les snapshots contiennent des données contact/prospect. Ils sont stockés comme
asset d'une **release GitHub privée** (accès gated par le PAT en lecture seule),
jamais publics. À garder en tête comme traitement de données : ces informations
transitent et résident chez GitHub. Pour une démo courte c'est acceptable ; pour
un usage prolongé, envisager le chiffrement du tar avant upload.

## CI / pipeline

- `.github/workflows/ci.yml` exécute la suite unittest sur chaque PR vers `main`
  (gate qualité).
- Push sur `main` = redéploiement automatique par Railway.
- Activer la **branch protection** sur `main` (Settings -> Branches) pour exiger
  la CI verte avant merge.
