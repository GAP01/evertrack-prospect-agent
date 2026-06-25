# EverTrack Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mettre le dashboard Reflex d'EverTrack en ligne sur Railway (démo à accès partagé), alimenté par des snapshots SQLite poussés manuellement via GitHub Releases, avec une CI GitHub propre.

**Architecture:** Un seul conteneur Docker tourne sur Railway. À l'intérieur, Caddy écoute le `$PORT` public, applique une Basic Auth, sert le frontend Reflex statique et reverse-proxy le WebSocket vers le backend Reflex (port 8000). Au démarrage, un `entrypoint.sh` télécharge le dernier snapshot SQLite depuis un asset de GitHub Release privé vers `/data`, puis lance le backend Reflex. Les agents ne tournent PAS sur le serveur — le dashboard est en lecture seule. La CI GitHub Actions exécute la suite unittest comme gate de PR ; Railway redéploie automatiquement à chaque push sur `main`.

**Tech Stack:** Reflex 0.9.0, Python 3.12, Caddy 2 (reverse proxy + Basic Auth), Docker multi-stage, Railway (PaaS), GitHub Releases (transport snapshot), GitHub Actions (CI), `gh` CLI.

**Référence spec :** `docs/superpowers/specs/2026-06-25-evertrack-deployment-design.md`

---

## Structure des fichiers

Nouveaux fichiers (tous à la racine du repo sauf mention) :

| Fichier | Responsabilité |
|---|---|
| `deploy/Dockerfile` | Image multi-stage : build frontend Reflex (bun) + runtime Python/Caddy |
| `deploy/Caddyfile` | Reverse proxy single-port + Basic Auth + service statique frontend |
| `deploy/entrypoint.sh` | Fetch snapshot GitHub Release → `/data`, lance backend Reflex + Caddy |
| `deploy/fetch_snapshot.py` | Script stdlib : télécharge + extrait l'asset release (testable isolément) |
| `deploy/README.md` | Checklist de setup Railway (manuelle, pour Gautier) |
| `railway.json` | Indique à Railway de builder via `deploy/Dockerfile` |
| `Makefile` | Cible `push-snapshot` (tar.gz + `gh release upload --clobber`) |
| `.github/workflows/ci.yml` | CI : suite unittest sur PR |
| `.env.example` | Documente toutes les variables d'environnement (sans valeurs) |
| Test : `deploy/tests/test_fetch_snapshot.py` | Tests unittest du fetch (mock urllib) |
| Test : `agents/dashboard_reflex/dashboard_reflex/services/tests/test_data_paths.py` | Régression `EVERTRACK_DATA_DIR` |

Fichiers modifiés :

| Fichier | Modification |
|---|---|
| `agents/dashboard_reflex/rxconfig.py` | `api_url` depuis l'env `API_URL` pour la prod |
| `CLAUDE.md` | Section déploiement (commandes + checklist) |

---

## Task 1: Test de régression sur `EVERTRACK_DATA_DIR`

`data.py` lit déjà `os.environ.get("EVERTRACK_DATA_DIR", ...)`. On verrouille ce comportement par un test (rien à implémenter, c'est un filet de sécurité avant de bâtir le déploiement dessus).

**Files:**
- Create: `agents/dashboard_reflex/dashboard_reflex/services/tests/__init__.py` (si absent)
- Create: `agents/dashboard_reflex/dashboard_reflex/services/tests/test_data_paths.py`

- [ ] **Step 1: Vérifier l'existence du package de tests**

Run: `ls agents/dashboard_reflex/dashboard_reflex/services/tests/`
Si le dossier ou `__init__.py` n'existe pas, créer `__init__.py` vide :

```python
```
(fichier vide)

- [ ] **Step 2: Écrire le test**

Create `agents/dashboard_reflex/dashboard_reflex/services/tests/test_data_paths.py` :

```python
"""Verrouille la résolution du répertoire de données via EVERTRACK_DATA_DIR."""
from __future__ import annotations

import importlib
import os
import unittest
from pathlib import Path


class TestDataDirResolution(unittest.TestCase):
    def test_env_var_overrides_data_dir(self):
        os.environ["EVERTRACK_DATA_DIR"] = "/tmp/evertrack_test_data"
        try:
            from dashboard_reflex.services import data as data_mod
            importlib.reload(data_mod)
            self.assertEqual(data_mod.DATA_DIR, Path("/tmp/evertrack_test_data"))
            self.assertEqual(
                data_mod.INCIDENTS_DB, Path("/tmp/evertrack_test_data") / "incidents.sqlite"
            )
        finally:
            del os.environ["EVERTRACK_DATA_DIR"]

    def test_default_data_dir_when_unset(self):
        os.environ.pop("EVERTRACK_DATA_DIR", None)
        from dashboard_reflex.services import data as data_mod
        importlib.reload(data_mod)
        self.assertTrue(str(data_mod.DATA_DIR).replace("\\", "/").endswith("agents/data"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Lancer le test (depuis le dossier dashboard_reflex, avec son venv)**

Run: `cd agents/dashboard_reflex && .venv/Scripts/python.exe -m unittest dashboard_reflex.services.tests.test_data_paths -v`
Expected: 2 tests PASS. (Si `reload` provoque un ré-import des agents, le test reste vert car les modules sont déjà importables.)

- [ ] **Step 4: Commit**

```bash
git add agents/dashboard_reflex/dashboard_reflex/services/tests/
git commit -m "test(dashboard): lock EVERTRACK_DATA_DIR path resolution"
```

---

## Task 2: `rxconfig.py` — `api_url` configurable pour la prod

Reflex bake l'URL du backend dans le frontend. En prod, le frontend et le backend sont servis sous le même domaine public (via Caddy) ; on fournit ce domaine par `API_URL`.

**Files:**
- Modify: `agents/dashboard_reflex/rxconfig.py`

- [ ] **Step 1: Remplacer le contenu de `rxconfig.py`**

```python
"""Config Reflex EverTrack."""

import os

import reflex as rx
from reflex.plugins import SitemapPlugin

# En prod (Railway), API_URL = URL publique HTTPS du service ; le frontend
# parle au backend via cette origine (Caddy reverse-proxy le WebSocket).
# En local, None => Reflex utilise http://localhost:8000 par défaut.
_api_url = os.environ.get("API_URL") or None

config = rx.Config(
    app_name="dashboard_reflex",
    tailwind=None,
    disable_plugins=[SitemapPlugin],
    api_url=_api_url,
)
```

- [ ] **Step 2: Vérifier que le local n'est pas cassé (import config)**

Run: `cd agents/dashboard_reflex && .venv/Scripts/python.exe -c "import rxconfig; print('api_url=', rxconfig.config.api_url)"`
Expected: affiche `api_url= None` (env `API_URL` non défini en local).

- [ ] **Step 3: Vérifier la prise en compte de l'env**

Run (bash) : `cd agents/dashboard_reflex && API_URL=https://demo.example.com .venv/Scripts/python.exe -c "import rxconfig; print(rxconfig.config.api_url)"`
Expected: affiche `https://demo.example.com`

- [ ] **Step 4: Commit**

```bash
git add agents/dashboard_reflex/rxconfig.py
git commit -m "feat(dashboard): read api_url from API_URL env for prod"
```

---

## Task 3: Script de fetch du snapshot (testable isolément)

Logique pure stdlib (`urllib`) qui télécharge l'asset `data-snapshot.tar.gz` d'une GitHub Release privée et l'extrait dans le répertoire cible. Isolé du shell pour être testable.

**Files:**
- Create: `deploy/fetch_snapshot.py`
- Create: `deploy/tests/__init__.py` (vide)
- Create: `deploy/tests/test_fetch_snapshot.py`

- [ ] **Step 1: Écrire le test (mock urllib)**

Create `deploy/tests/test_fetch_snapshot.py` :

```python
"""Tests du fetch de snapshot GitHub Release (sans réseau)."""
from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from deploy import fetch_snapshot


def _make_tar_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class TestFindAssetId(unittest.TestCase):
    def test_picks_matching_asset(self):
        release = {"assets": [
            {"id": 11, "name": "other.txt"},
            {"id": 42, "name": "data-snapshot.tar.gz"},
        ]}
        self.assertEqual(
            fetch_snapshot.find_asset_id(release, "data-snapshot.tar.gz"), 42
        )

    def test_returns_none_when_absent(self):
        self.assertIsNone(
            fetch_snapshot.find_asset_id({"assets": []}, "data-snapshot.tar.gz")
        )


class TestExtractTar(unittest.TestCase):
    def test_extracts_sqlite_files(self):
        data = _make_tar_bytes({"incidents.sqlite": b"abc", "scores.sqlite": b"xyz"})
        with tempfile.TemporaryDirectory() as d:
            fetch_snapshot.extract_tar_bytes(data, Path(d))
            self.assertEqual((Path(d) / "incidents.sqlite").read_bytes(), b"abc")
            self.assertEqual((Path(d) / "scores.sqlite").read_bytes(), b"xyz")

    def test_rejects_path_traversal(self):
        data = _make_tar_bytes({"../evil.sqlite": b"nope"})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                fetch_snapshot.extract_tar_bytes(data, Path(d))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Lancer le test pour le voir échouer**

Run: `cd "$(git rev-parse --show-toplevel)" && python -m unittest deploy.tests.test_fetch_snapshot -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'deploy.fetch_snapshot'`

- [ ] **Step 3: Créer `deploy/__init__.py` et `deploy/tests/__init__.py` vides**

```python
```
(deux fichiers vides)

- [ ] **Step 4: Écrire l'implémentation**

Create `deploy/fetch_snapshot.py` :

```python
"""Télécharge le snapshot SQLite depuis un asset de GitHub Release privé.

Usage (dans le conteneur) :
    python -m deploy.fetch_snapshot

Variables d'environnement :
    GITHUB_REPO            ex: GAP01/evertrack-prospect-agent
    SNAPSHOT_TAG           ex: data-snapshot (défaut)
    SNAPSHOT_ASSET         ex: data-snapshot.tar.gz (défaut)
    GITHUB_SNAPSHOT_TOKEN  PAT fine-grained, contents:read
    EVERTRACK_DATA_DIR     répertoire cible (défaut /data)

Comportement : si le token ou l'asset est absent, log un WARNING et sort en
code 0 (démarrage à froid toléré — dashboard vide plutôt que crash).
"""
from __future__ import annotations

import json
import os
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

API_ROOT = "https://api.github.com"


def find_asset_id(release: dict[str, Any], asset_name: str) -> Optional[int]:
    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            return asset.get("id")
    return None


def extract_tar_bytes(data: bytes, dest: Path) -> None:
    import io

    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            member_path = (dest / member.name).resolve()
            if not str(member_path).startswith(str(dest.resolve())):
                raise ValueError(f"Path traversal refusé: {member.name}")
        tar.extractall(dest)


def _get(url: str, token: str, accept: str) -> bytes:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", accept)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main() -> int:
    repo = os.environ.get("GITHUB_REPO", "").strip()
    tag = os.environ.get("SNAPSHOT_TAG", "data-snapshot").strip()
    asset_name = os.environ.get("SNAPSHOT_ASSET", "data-snapshot.tar.gz").strip()
    token = os.environ.get("GITHUB_SNAPSHOT_TOKEN", "").strip()
    dest = Path(os.environ.get("EVERTRACK_DATA_DIR", "/data"))

    if not repo or not token:
        print("[~] GITHUB_REPO/GITHUB_SNAPSHOT_TOKEN absents — démarrage à froid (data vide)")
        return 0

    try:
        rel_url = f"{API_ROOT}/repos/{repo}/releases/tags/{tag}"
        release = json.loads(_get(rel_url, token, "application/vnd.github+json"))
        asset_id = find_asset_id(release, asset_name)
        if asset_id is None:
            print(f"[~] Asset {asset_name} introuvable sur la release {tag} — data vide")
            return 0
        asset_url = f"{API_ROOT}/repos/{repo}/releases/assets/{asset_id}"
        blob = _get(asset_url, token, "application/octet-stream")
        extract_tar_bytes(blob, dest)
        print(f"[ok] snapshot extrait dans {dest}")
        return 0
    except urllib.error.HTTPError as exc:
        print(f"[x] HTTP {exc.code} en récupérant le snapshot — démarrage à froid")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[x] échec fetch snapshot ({exc!r}) — démarrage à froid")
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Lancer les tests pour les voir passer**

Run: `cd "$(git rev-parse --show-toplevel)" && python -m unittest deploy.tests.test_fetch_snapshot -v`
Expected: 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add deploy/__init__.py deploy/fetch_snapshot.py deploy/tests/
git commit -m "feat(deploy): GitHub Release snapshot fetcher with tests"
```

---

## Task 4: Caddyfile (reverse proxy single-port + Basic Auth)

**Files:**
- Create: `deploy/Caddyfile`

- [ ] **Step 1: Écrire le Caddyfile**

Create `deploy/Caddyfile` :

```
{
	admin off
	auto_https off
}

:{$PORT} {
	encode gzip

	basic_auth {
		{$BASIC_AUTH_USER} {$BASIC_AUTH_HASH}
	}

	# Routes backend Reflex (WebSocket d'événements, healthcheck, upload)
	@backend path /_event* /ping* /_upload*
	reverse_proxy @backend localhost:8000

	# Frontend statique exporté par Reflex (React Router 7)
	root * /app/.web/build/client
	try_files {path} /index.html
	file_server
}
```

- [ ] **Step 2: Valider la syntaxe (si Caddy dispo localement, sinon différer au build Docker)**

Run: `caddy validate --config deploy/Caddyfile --adapter caddyfile` (si `caddy` installé)
Expected: `Valid configuration` — sinon, ce sera validé pendant le build Docker en Task 6.

- [ ] **Step 3: Commit**

```bash
git add deploy/Caddyfile
git commit -m "feat(deploy): Caddyfile single-port reverse proxy + basic auth"
```

---

## Task 5: entrypoint.sh

Orchestration au démarrage du conteneur : fetch snapshot → lance backend Reflex en arrière-plan → lance Caddy au premier plan.

**Files:**
- Create: `deploy/entrypoint.sh`

- [ ] **Step 1: Écrire l'entrypoint**

Create `deploy/entrypoint.sh` :

```bash
#!/usr/bin/env bash
set -euo pipefail

export EVERTRACK_DATA_DIR="${EVERTRACK_DATA_DIR:-/data}"
mkdir -p "$EVERTRACK_DATA_DIR"

echo "[*] Récupération du snapshot de données..."
python -m deploy.fetch_snapshot || true

echo "[*] Démarrage du backend Reflex (prod, backend-only) sur :8000..."
cd /app/agents/dashboard_reflex
reflex run --env prod --backend-only --backend-port 8000 &
BACKEND_PID=$!

cd /app
echo "[*] Démarrage de Caddy sur :${PORT:-8080}..."
exec caddy run --config /app/deploy/Caddyfile --adapter caddyfile
```

- [ ] **Step 2: Rendre exécutable (le bit sera aussi posé dans le Dockerfile)**

Run: `git update-index --chmod=+x deploy/entrypoint.sh 2>/dev/null || chmod +x deploy/entrypoint.sh`

- [ ] **Step 3: Commit**

```bash
git add deploy/entrypoint.sh
git commit -m "feat(deploy): container entrypoint (snapshot fetch + reflex + caddy)"
```

---

## Task 6: Dockerfile + railway.json + boot local

C'est l'étape la plus délicate (câblage Reflex prod single-port). On la valide empiriquement par un `docker run` local AVANT toute config Railway.

**Files:**
- Create: `deploy/Dockerfile`
- Create: `railway.json`

- [ ] **Step 1: Écrire le Dockerfile**

Create `deploy/Dockerfile` :

```dockerfile
# syntax=docker/dockerfile:1

# ---------- Stage 1 : build du frontend Reflex (bun) ----------
FROM python:3.12-slim AS frontend
ENV PYTHONUNBUFFERED=1 \
    REFLEX_TELEMETRY_ENABLED=false
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# Deps Python (cache layer)
COPY agents/dashboard_reflex/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Code (agents + dashboard) — nécessaire car le dashboard importe les agents
COPY agents/ /app/agents/

WORKDIR /app/agents/dashboard_reflex
# API_URL est requise au build pour bake l'origine backend dans le frontend.
ARG API_URL=http://localhost:8080
ENV API_URL=${API_URL}
# reflex init installe bun + dépendances JS, puis export du frontend statique.
RUN reflex init || true
RUN reflex export --frontend-only --no-zip

# ---------- Stage 2 : runtime (Python + Caddy) ----------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    REFLEX_TELEMETRY_ENABLED=false \
    EVERTRACK_DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends \
    caddy ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY agents/dashboard_reflex/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Code applicatif + frontend buildé depuis le stage 1
COPY --from=frontend /app/agents /app/agents
COPY --from=frontend /app/agents/dashboard_reflex/.web/build /app/agents/dashboard_reflex/.web/build
COPY deploy/ /app/deploy/

RUN chmod +x /app/deploy/entrypoint.sh && mkdir -p /data
ENV PYTHONPATH=/app

EXPOSE 8080
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
```

> NOTE pour l'exécutant : si `caddy` n'est pas dans les dépôts apt de l'image
> slim, remplacer l'install par le binaire officiel :
> `RUN curl -sfL https://github.com/caddyserver/caddy/releases/latest/download/caddy_linux_amd64 -o /usr/bin/caddy && chmod +x /usr/bin/caddy`
> (ou l'image `caddy:2` copiée en multi-stage : `COPY --from=caddy:2 /usr/bin/caddy /usr/bin/caddy`).

- [ ] **Step 2: Écrire railway.json**

Create `railway.json` :

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "deploy/Dockerfile"
  },
  "deploy": {
    "startCommand": null,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

- [ ] **Step 3: Build local de l'image**

Run: `cd "$(git rev-parse --show-toplevel)" && docker build -f deploy/Dockerfile -t evertrack-demo --build-arg API_URL=http://localhost:8080 .`
Expected: build réussi. Si `reflex export` échoue (bun/réseau), itérer ici — c'est le point de friction connu (voir spec §9). Vérifier que le path du build frontend (`.web/build/client`) correspond bien à ce qu'attend le Caddyfile ; ajuster `root *` si Reflex 0.9 émet un autre chemin (ex: `.web/_static`).

- [ ] **Step 4: Run local + smoke test**

Run (bash) :
```bash
# hash bcrypt de démo pour "demo123" via caddy (ou en dur un hash connu)
docker run --rm -p 8080:8080 \
  -e PORT=8080 \
  -e BASIC_AUTH_USER=demo \
  -e BASIC_AUTH_HASH='$2a$14$exampleHashReplaceMe' \
  -e API_URL=http://localhost:8080 \
  evertrack-demo
```
Dans un autre terminal :
- `curl -i http://localhost:8080/` → Expected: **401 Unauthorized** (Basic Auth active)
- `curl -i -u demo:demo123 http://localhost:8080/` → Expected: **200** + HTML du dashboard
- Ouvrir `http://demo:demo123@localhost:8080` dans un navigateur → Expected: les 4 pages chargent, la navigation est réactive (= WebSocket OK). Si la page est blanche / WS en échec : vérifier `API_URL` et les routes `@backend` du Caddyfile.

> Le `BASIC_AUTH_HASH` doit être un vrai hash bcrypt. Le générer avec :
> `docker run --rm caddy:2 caddy hash-password --plaintext demo123`

- [ ] **Step 5: Commit (une fois le smoke test vert)**

```bash
git add deploy/Dockerfile railway.json
git commit -m "feat(deploy): Dockerfile + railway.json (single-container, validated locally)"
```

---

## Task 7: Makefile — `push-snapshot`

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Écrire le Makefile**

Create `Makefile` (⚠️ indentation par TABULATIONS, pas des espaces) :

```makefile
# EverTrack — cibles de déploiement
GH ?= gh
REPO ?= GAP01/evertrack-prospect-agent
SNAPSHOT_TAG ?= data-snapshot
SNAPSHOT_ASSET ?= data-snapshot.tar.gz
DATA_DIR ?= agents/data

# Pousse un snapshot des SQLite vers l'asset de la release GitHub.
# Inclut uniquement les bases lues par le dashboard ; exclut secrets/caches.
push-snapshot:
	@echo "[*] Empaquetage des SQLite depuis $(DATA_DIR)..."
	tar -czf $(SNAPSHOT_ASSET) -C $(DATA_DIR) \
		incidents.sqlite scores.sqlite enrichissements.sqlite \
		signaux.sqlite outreach.sqlite
	@echo "[*] Assure l'existence de la release $(SNAPSHOT_TAG)..."
	$(GH) release view $(SNAPSHOT_TAG) --repo $(REPO) >/dev/null 2>&1 || \
		$(GH) release create $(SNAPSHOT_TAG) --repo $(REPO) \
			--prerelease --title "Data snapshot" \
			--notes "Snapshot SQLite du dashboard (écrasé à chaque push)."
	@echo "[*] Upload de l'asset (écrasement)..."
	$(GH) release upload $(SNAPSHOT_TAG) $(SNAPSHOT_ASSET) \
		--repo $(REPO) --clobber
	rm -f $(SNAPSHOT_ASSET)
	@echo "[ok] Snapshot poussé. Redémarre le service Railway pour rafraîchir."

.PHONY: push-snapshot
```

- [ ] **Step 2: Dry-run de l'empaquetage (sans toucher GitHub)**

Run (bash) : `tar -czf /tmp/snap-test.tar.gz -C agents/data incidents.sqlite scores.sqlite enrichissements.sqlite signaux.sqlite outreach.sqlite && tar -tzf /tmp/snap-test.tar.gz && rm /tmp/snap-test.tar.gz`
Expected: liste les 5 fichiers `.sqlite` sans erreur. (Si un fichier manque en local, ajuster la liste — mais ces 5 sont attendus d'après `agents/data/`.)

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat(deploy): make push-snapshot (tar + gh release upload)"
```

---

## Task 8: CI GitHub Actions + `.env.example`

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.env.example`

- [ ] **Step 1: Écrire le workflow CI**

Create `.github/workflows/ci.yml` :

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install agent dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests python-dateutil anthropic feedparser googlenewsdecoder

      - name: Run unittest suite
        working-directory: agents
        env:
          ANTHROPIC_API_KEY: ""
        run: python -m unittest discover -s . -p "test_*.py" -v
```

- [ ] **Step 2: Valider la commande de tests en local (telle que la CI la lance)**

Run: `cd agents && python -m unittest discover -s . -p "test_*.py" 2>&1 | tail -15`
Expected: la suite tourne et se termine `OK` (les tests qui dépendent d'API utilisent leurs fallbacks). Si des tests nécessitent une dépendance absente, l'ajouter à la ligne `pip install` du workflow.

> NOTE exécutant : le venv `dashboard_reflex/.venv` n'est pas sur GitHub. Les tests
> du dashboard qui importent `reflex` ne tourneront pas dans cette CI (pas de
> reflex installé) ; `discover -s .` depuis `agents/` peut les ramasser. Si la
> CI casse sur un import `reflex`, restreindre le discover aux agents :
> exclure `dashboard_reflex` via `-s .` + un `--pattern` ou lister les dossiers
> d'agents explicitement. Décider au vu du run réel de l'étape précédente.

- [ ] **Step 3: Écrire `.env.example`**

Create `.env.example` :

```bash
# --- Agents (local, fichier agents/.env) ---
ANTHROPIC_API_KEY=
PAPPERS_API_KEY=
SOCIETECOM_API_KEY=
TIKTOK_BRIDGE_BASE_URL=
TIKTOK_USER_AGENT=
TIKTOK_ALLOW_INSECURE_BRIDGE=

# --- Déploiement (variables Railway) ---
# Répertoire des SQLite dans le conteneur
EVERTRACK_DATA_DIR=/data
# URL publique HTTPS du service Railway (bake dans le frontend)
API_URL=
# Basic Auth de la démo
BASIC_AUTH_USER=demo
# Hash bcrypt : `caddy hash-password --plaintext <motdepasse>`
BASIC_AUTH_HASH=
# Snapshot via GitHub Release
GITHUB_REPO=GAP01/evertrack-prospect-agent
SNAPSHOT_TAG=data-snapshot
SNAPSHOT_ASSET=data-snapshot.tar.gz
# PAT fine-grained, scope contents:read sur le repo
GITHUB_SNAPSHOT_TOKEN=
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml .env.example
git commit -m "ci: unittest gate on PR + .env.example for deploy"
```

---

## Task 9: Doc de setup Railway + mise à jour CLAUDE.md

**Files:**
- Create: `deploy/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Écrire `deploy/README.md` (checklist manuelle pour Gautier)**

Create `deploy/README.md` :

```markdown
# Déploiement EverTrack (démo Railway)

Dashboard Reflex en lecture seule, données poussées manuellement par snapshot.

## Setup initial (une fois)

1. **PAT GitHub** : token fine-grained, repo `GAP01/evertrack-prospect-agent`,
   permission **Contents: Read-only**. Copier la valeur.
2. **Hash du mot de passe démo** :
   `docker run --rm caddy:2 caddy hash-password --plaintext <motdepasse>`
3. **Railway** :
   - New Project → Deploy from GitHub repo → `evertrack-prospect-agent`.
   - Railway détecte `railway.json` → build via `deploy/Dockerfile`.
   - Onglet **Variables**, ajouter :
     | Variable | Valeur |
     |---|---|
     | `BASIC_AUTH_USER` | `demo` (ou autre) |
     | `BASIC_AUTH_HASH` | hash bcrypt de l'étape 2 |
     | `GITHUB_REPO` | `GAP01/evertrack-prospect-agent` |
     | `GITHUB_SNAPSHOT_TOKEN` | le PAT de l'étape 1 |
     | `EVERTRACK_DATA_DIR` | `/data` |
   - Onglet **Settings → Networking** : générer un domaine public.
   - Ajouter la variable `API_URL` = l'URL publique générée (https://...).
     Re-déployer pour que le frontend bake la bonne origine.
4. **Premier snapshot** : en local, `make push-snapshot`, puis **Restart** le
   service Railway.

## Rafraîchir les données

```bash
# 1. Faire tourner les agents en local (cf. CLAUDE.md §3)
# 2. Pousser le snapshot
make push-snapshot
# 3. Redémarrer le service sur Railway (bouton Restart)
```

## Smoke test

- URL publique sans creds → 401.
- Avec creds → les 4 pages chargent, navigation réactive (WebSocket OK).
- KPI non vides (snapshot bien récupéré).
```

- [ ] **Step 2: Ajouter une section déploiement à `CLAUDE.md`**

Ajouter à la fin de `CLAUDE.md` (avant `## 8. Fichiers à ne JAMAIS toucher` ou en nouvelle section) :

```markdown
## Déploiement (démo Railway)

- Dashboard Reflex en ligne, lecture seule, sur Railway (1 conteneur).
- Données : snapshot manuel via GitHub Release. `make push-snapshot` puis
  Restart du service Railway pour rafraîchir.
- Auth : Basic Auth (Caddy), creds en variables Railway.
- CI : `.github/workflows/ci.yml` (unittest gate sur PR). Push sur `main` =
  redeploy auto Railway.
- Détails et checklist : `deploy/README.md`.
- Spec/plan : `docs/superpowers/specs/2026-06-25-evertrack-deployment-design.md`,
  `docs/superpowers/plans/2026-06-25-evertrack-deployment.md`.
```

- [ ] **Step 3: Commit**

```bash
git add deploy/README.md CLAUDE.md
git commit -m "docs(deploy): Railway setup checklist + CLAUDE.md deployment section"
```

---

## Task 10: Push de la branche + Pull Request

**Files:** aucun (opération git/GitHub)

- [ ] **Step 1: Vérifier que toute la suite passe**

Run: `cd agents && python -m unittest discover -s . -p "test_*.py" 2>&1 | tail -5`
Expected: `OK`

- [ ] **Step 2: Push de la branche**

Run: `git push -u origin feat/deployment-railway`

- [ ] **Step 3: Ouvrir la PR**

Run (chemin gh Windows) :
```bash
"/c/Program Files/GitHub CLI/gh.exe" pr create --repo GAP01/evertrack-prospect-agent \
  --base main --head feat/deployment-railway \
  --title "feat: déploiement Railway (dashboard démo + snapshots GitHub Release)" \
  --body "Déploiement du dashboard Reflex sur Railway. Voir docs/superpowers/plans/2026-06-25-evertrack-deployment.md. Setup Railway manuel : deploy/README.md."
```
Expected: URL de la PR affichée. La CI doit se déclencher et passer au vert.

- [ ] **Step 4: (Manuel, Gautier) Configurer la branch protection sur `main`**

Dans GitHub → Settings → Branches → Add rule sur `main` : « Require status checks to pass » → cocher le check `tests`. (Action manuelle, non scriptée ici.)

---

## Notes de bout en bout

- **Ordre des tâches** : 1→10 séquentiel. Tasks 1-2 préparent le code, 3-6 bâtissent
  l'image (6 = point de friction, valider en local), 7-9 outillage/doc, 10 livraison.
- **Le point dur** est le Task 6 (Reflex 0.9 prod single-port). Ne pas passer à
  Railway tant que le `docker run` local n'est pas vert. Le chemin exact du build
  frontend (`.web/build/client` vs autre) doit être vérifié sur l'image réelle.
- **Action manuelle de Gautier** : création du PAT, setup Railway (variables +
  domaine + premier restart), branch protection. Tout est dans `deploy/README.md`.
- **Aucune donnée n'est commitée** : les SQLite restent gitignorés et ne transitent
  que par l'asset de release privé.
```
