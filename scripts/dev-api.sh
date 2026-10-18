#!/usr/bin/env bash
# Run the API on the host against local Postgres (make db) and ./.localdata. Used by .claude/launch.json.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
export STOPWATCH_ENV=local
export LAKE_URL="file://$ROOT/.localdata/lake" SITE_URL="file://$ROOT/.localdata/site"
export DATABASE_URL=postgresql://stopwatch_app:app-local-only@localhost:5433/stopwatch
export DATABASE_OWNER_URL=postgresql://stopwatch_owner:owner-local-only@localhost:5433/stopwatch
export SESSION_SECRET="${SESSION_SECRET:-local-dev-session-secret-0123456789abcdefghijklmnop}"
export PUBLIC_BASE_URL=http://localhost:5173
exec uv run uvicorn stopwatch.api.main:app --host 127.0.0.1 --port 8000 --app-dir src
