from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from tests.conftest import BACKEND

pytestmark = pytest.mark.integration


def test_all_tables_exist(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        tables = set(conn.execute(text(
            "select table_name from information_schema.tables where table_schema = 'public'"
        )).scalars())
    expected = {"users", "sessions", "agencies", "feed_versions", "routes", "stops", "route_stops",
                "saved_commutes", "idempotency_keys", "rate_limit_counters", "audit_log",
                "route_daily_metrics", "push_subscriptions", "alert_rules", "notifications", "ask_usage"}
    assert expected <= tables


def test_audit_log_is_append_only_for_app_role(app_engine: Engine) -> None:
    with app_engine.begin() as conn:
        conn.execute(text(
            "insert into audit_log (actor_kind, action, outcome) values ('system', 'test.write', 'success')"
        ))
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(text("update audit_log set action = 'tampered'"))
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        conn.execute(text("delete from audit_log"))


def test_app_role_cannot_run_ddl(app_engine: Engine) -> None:
    with pytest.raises(ProgrammingError), app_engine.begin() as conn:
        conn.execute(text("drop table users"))


def test_downgrade_then_upgrade_round_trip(database_urls: dict[str, str]) -> None:
    env = {**os.environ, "DATABASE_OWNER_URL": database_urls["owner"]}
    for args in (["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True,  # noqa: S603
                       capture_output=True)
