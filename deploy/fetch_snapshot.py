"""Telecharge le snapshot SQLite depuis un asset de GitHub Release prive.

Usage (dans le conteneur) :
    python -m deploy.fetch_snapshot

Variables d'environnement :
    GITHUB_REPO            ex: GAP01/evertrack-prospect-agent
    SNAPSHOT_TAG           ex: data-snapshot (defaut)
    SNAPSHOT_ASSET         ex: data-snapshot.tar.gz (defaut)
    GITHUB_SNAPSHOT_TOKEN  PAT fine-grained, contents:read
    EVERTRACK_DATA_DIR     repertoire cible (defaut /data)

Comportement : si le token ou l'asset est absent, log un WARNING et sort en
code 0 (demarrage a froid tolere -- dashboard vide plutot que crash).
"""
from __future__ import annotations

import io
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
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            member_path = (dest / member.name).resolve()
            if not member_path.is_relative_to(dest_resolved):
                raise ValueError(f"Path traversal refuse: {member.name}")
        tar.extractall(dest, filter="data")


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
        print("[~] GITHUB_REPO/GITHUB_SNAPSHOT_TOKEN absents - demarrage a froid (data vide)")
        return 0

    try:
        rel_url = f"{API_ROOT}/repos/{repo}/releases/tags/{tag}"
        release = json.loads(_get(rel_url, token, "application/vnd.github+json"))
        asset_id = find_asset_id(release, asset_name)
        if asset_id is None:
            print(f"[~] Asset {asset_name} introuvable sur la release {tag} - data vide")
            return 0
        asset_url = f"{API_ROOT}/repos/{repo}/releases/assets/{asset_id}"
        blob = _get(asset_url, token, "application/octet-stream")
        extract_tar_bytes(blob, dest)
        print(f"[ok] snapshot extrait dans {dest}")
        return 0
    except urllib.error.HTTPError as exc:
        print(f"[x] HTTP {exc.code} en recuperant le snapshot - demarrage a froid")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[x] echec fetch snapshot ({exc!r}) - demarrage a froid")
        return 0


if __name__ == "__main__":
    sys.exit(main())
