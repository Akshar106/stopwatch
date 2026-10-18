"""Shared fixtures.

Database tests create a throwaway database per test session, run all migrations as the owner, and hand
out two engines: ``owner_engine`` (DDL rights) and ``app_engine`` (the least-privilege runtime role, same
grants as production). Set TEST_DB_ADMIN_URL to point at a server; tests marked ``integration`` are
skipped when it isn't reachable.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ADMIN_URL = os.environ.get(
    "TEST_DB_ADMIN_URL", "postgresql://stopwatch_owner:owner-local-only@localhost:5433/postgres"
)
APP_LOGIN = ("stopwatch_app", "app-local-only")


def _psycopg(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url


@pytest.fixture(scope="session")
def database_urls() -> Iterator[dict[str, str]]:
    admin = create_engine(_psycopg(ADMIN_URL), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text("select 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable at TEST_DB_ADMIN_URL ({exc.__class__.__name__}); run `make db`")
    name = f"stopwatch_test_{uuid.uuid4().hex[:10]}"
    with admin.connect() as conn:
        conn.execute(text(f'create database "{name}"'))
        # The app login role exists cluster-wide (scripts/db/init-local.sql); make sure it can connect.
        conn.execute(text(
            "do $$ begin "
            "if not exists (select 1 from pg_roles where rolname='stopwatch_app_role') then "
            "create role stopwatch_app_role nologin; end if; "
            "if not exists (select 1 from pg_roles where rolname='stopwatch_app') then "
            "create role stopwatch_app login password 'app-local-only'; end if; "
            "end $$"
        ))
        conn.execute(text("grant stopwatch_app_role to stopwatch_app"))
    owner_url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    app_url = (
        make_url(ADMIN_URL)
        .set(database=name, username=APP_LOGIN[0], password=APP_LOGIN[1])
        .render_as_string(hide_password=False)
    )
    env = {**os.environ, "DATABASE_OWNER_URL": owner_url}
    subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True,
        capture_output=True,
    )
    try:
        yield {"owner": owner_url, "app": app_url}
    finally:
        with admin.connect() as conn:
            conn.execute(text(
                "select pg_terminate_backend(pid) from pg_stat_activity where datname = :n and pid <> pg_backend_pid()"
            ), {"n": name})
            conn.execute(text(f'drop database if exists "{name}"'))
        admin.dispose()


@pytest.fixture(scope="session")
def owner_engine(database_urls: dict[str, str]) -> Iterator[Engine]:
    eng = create_engine(_psycopg(database_urls["owner"]))
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def app_engine(database_urls: dict[str, str]) -> Iterator[Engine]:
    eng = create_engine(_psycopg(database_urls["app"]))
    yield eng
    eng.dispose()


@pytest.fixture
def app_settings_env(database_urls: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point get_settings() at the test database and a temp blob store; returns the temp root."""
    from stopwatch.platform import config

    monkeypatch.setenv("STOPWATCH_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_urls["app"])
    monkeypatch.setenv("DATABASE_OWNER_URL", database_urls["owner"])
    monkeypatch.setenv("LAKE_URL", f"file://{tmp_path}/lake")
    monkeypatch.setenv("SITE_URL", f"file://{tmp_path}/site")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-" + "x" * 40)
    config.reset_settings_cache()
    yield tmp_path
    config.reset_settings_cache()
