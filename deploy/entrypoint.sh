#!/usr/bin/env bash
set -euo pipefail

export EVERTRACK_DATA_DIR="${EVERTRACK_DATA_DIR:-/data}"
mkdir -p "$EVERTRACK_DATA_DIR"

# Basic Auth : on prefere BASIC_AUTH_HASH_B64 (base64 du hash bcrypt). Les hash
# bcrypt contiennent des '$' que certaines plateformes (Railway) interpretent
# comme des references de variables, corrompant la valeur. Le base64 n'a aucun
# caractere special et traverse intact. Si fourni, on le decode ici.
if [ -n "${BASIC_AUTH_HASH_B64:-}" ]; then
	BASIC_AUTH_HASH="$(printf '%s' "$BASIC_AUTH_HASH_B64" | base64 -d)"
	export BASIC_AUTH_HASH
	echo "[*] BASIC_AUTH_HASH decode depuis BASIC_AUTH_HASH_B64."
fi

echo "[*] Recuperation du snapshot de donnees..."
python -m deploy.fetch_snapshot || true

echo "[*] Demarrage du backend Reflex (prod, backend-only) sur :8000..."
cd /app/agents/dashboard_reflex
reflex run --env prod --backend-only --backend-port 8000 &
BACKEND_PID=$!

cd /app
echo "[*] Demarrage de Caddy sur :${PORT:-8080}..."
exec caddy run --config /app/deploy/Caddyfile --adapter caddyfile
