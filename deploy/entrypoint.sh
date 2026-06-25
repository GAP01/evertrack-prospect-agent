#!/usr/bin/env bash
set -euo pipefail

export EVERTRACK_DATA_DIR="${EVERTRACK_DATA_DIR:-/data}"
mkdir -p "$EVERTRACK_DATA_DIR"

echo "[*] Recuperation du snapshot de donnees..."
python -m deploy.fetch_snapshot || true

echo "[*] Demarrage du backend Reflex (prod, backend-only) sur :8000..."
cd /app/agents/dashboard_reflex
reflex run --env prod --backend-only --backend-port 8000 &
BACKEND_PID=$!

cd /app
echo "[*] Demarrage de Caddy sur :${PORT:-8080}..."
exec caddy run --config /app/deploy/Caddyfile --adapter caddyfile
