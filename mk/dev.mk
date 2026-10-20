# Local development and backend quality targets.
BACKEND := $(ROOT)/backend
UV := cd "$(BACKEND)" && uv run
TEST_DB_ADMIN_URL ?= postgresql://stopwatch_owner:owner-local-only@localhost:5433/postgres
LOCAL_ENV := STOPWATCH_ENV=local LAKE_URL="file://$(ROOT)/.localdata/lake" SITE_URL="file://$(ROOT)/.localdata/site" \
  DATABASE_URL=postgresql://stopwatch_app:app-local-only@localhost:5433/stopwatch \
  DATABASE_OWNER_URL=postgresql://stopwatch_owner:owner-local-only@localhost:5433/stopwatch

.PHONY: dev demo stop db install verify-db lint fmt typecheck test test-unit test-integration migrate seed ingest-once rollup replay record-fixtures

dev: ## Start the full local stack (db, migrations, api, worker, web) at http://localhost:5173
	docker compose up --build

demo: ## Offline demo: same stack, but the worker replays recorded MBTA snapshots (no internet needed)
	WORKER_MODE=replay docker compose up --build

stop: ## Stop the local stack (make down ENV=... tears down cloud infra)
	docker compose down

db: ## Start only Postgres (for tests and host-run commands)
	docker compose up -d --wait db

install: ## Install backend and frontend dependencies
	cd "$(BACKEND)" && uv sync --all-extras
	@# macOS can mark the editable-install .pth hidden; Python 3.13 skips hidden .pth files.
	-@chflags nohidden "$(BACKEND)"/.venv/lib/python3.13/site-packages/*.pth 2>/dev/null || true
	cd "$(ROOT)/frontend" && npm ci

lint: ## Ruff + import-linter (module boundaries)
	$(UV) ruff check src tests
	$(UV) ruff format --check src tests
	$(UV) lint-imports

fmt: ## Auto-format backend code
	$(UV) ruff format src tests
	$(UV) ruff check --fix src tests

typecheck: ## mypy (strict on stopwatch.core)
	$(UV) mypy

test-unit: ## Fast tests: unit, property, replay (no database)
	$(UV) pytest tests/unit tests/property tests/replay -q

test-integration: db ## Integration + API tests against local Postgres
	TEST_DB_ADMIN_URL=$(TEST_DB_ADMIN_URL) $(UV) pytest tests/integration tests/api -q

test: db ## All backend tests with coverage
	TEST_DB_ADMIN_URL=$(TEST_DB_ADMIN_URL) $(UV) pytest --cov --cov-report=term-missing:skip-covered -q

migrate: db ## Apply database migrations to local Postgres
	cd "$(BACKEND)" && $(LOCAL_ENV) uv run alembic upgrade head

verify-db: ## Smoke-check the database at DATABASE_URL (default: local) before switching to it
	cd "$(BACKEND)" && $(if $(DATABASE_URL),DATABASE_URL=$(DATABASE_URL),$(LOCAL_ENV)) uv run python -m stopwatch.jobs.verify_db

seed: migrate ## Import the static GTFS schedule + catalog for configured agencies
	cd "$(BACKEND)" && $(LOCAL_ENV) uv run python -m stopwatch.jobs.schedule_import

ingest-once: ## Run one ingest tick against the live feed (host)
	cd "$(BACKEND)" && $(LOCAL_ENV) uv run python -m stopwatch.jobs.ingest_tick

rollup: ## Run the daily rollup for DATE=YYYY-MM-DD (default: yesterday)
	cd "$(BACKEND)" && $(LOCAL_ENV) uv run python -m stopwatch.jobs.daily_rollup $(if $(DATE),--date $(DATE),)

replay: ## Replay recorded snapshots: make replay DIR=backend/tests/fixtures/rt_snapshots/sample
	cd "$(BACKEND)" && uv run python -m stopwatch.ingest.replay $(DIR)

record-fixtures: ## Record live snapshots: make record-fixtures MINUTES=30
	cd "$(BACKEND)" && uv run python "$(ROOT)/scripts/record_fixtures.py" --minutes $(or $(MINUTES),30)
