# syntax=docker/dockerfile:1

# ---------- Stage 1 : build du frontend Reflex (bun) ----------
FROM python:3.12-slim AS frontend
ENV PYTHONUNBUFFERED=1 \
    REFLEX_TELEMETRY_ENABLED=false \
    # Reflex needs this set before init/export
    PYTHONPATH=/app
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# Install Python deps for the dashboard (includes reflex, which pulls bun at init)
COPY agents/dashboard_reflex/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy the whole agents tree (dashboard imports sibling packages at boot)
COPY agents/ /app/agents/

# Build frontend from the Reflex app root
WORKDIR /app/agents/dashboard_reflex
ARG API_URL=http://localhost:8080
ENV API_URL=${API_URL}

# reflex init downloads bun and sets up .web scaffolding
RUN reflex init || true

# Export compiles the React SPA into .web/build/client
RUN reflex export --frontend-only --no-zip

# ---------- Stage 2 : runtime (Python + Caddy) ----------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    REFLEX_TELEMETRY_ENABLED=false \
    EVERTRACK_DATA_DIR=/data \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && rm -rf /var/lib/apt/lists/*

# Pull caddy binary from the official image (avoids apt repo setup)
COPY --from=caddy:2 /usr/bin/caddy /usr/bin/caddy

WORKDIR /app

# Install Python deps (same set as frontend stage)
COPY agents/dashboard_reflex/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy agents tree WITH the compiled .web frontend from stage 1
COPY --from=frontend /app/agents /app/agents

# Copy deploy scripts/config
COPY deploy/ /app/deploy/

RUN chmod +x /app/deploy/entrypoint.sh && mkdir -p /data

EXPOSE 8080
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
