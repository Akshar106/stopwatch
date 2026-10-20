"""Smoke-check a database before pointing the app at it (restore drill).

    DATABASE_URL=... python -m stopwatch.jobs.verify_db

Checks: connectivity, migrations at head, expected tables present, row counts readable, and that the runtime
role still cannot modify the audit log. Prints a JSON report; exits 1 on any failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from stopwatch.platform import dbschema
from stopwatch.platform.db import get_engine

EXPECTED_TABLES = (
    "users", "sessions", "agencies", "routes", "stops", "route_stops", "saved_commutes", "audit_log",
    "rate_limit_counters", "idempotency_keys", "route_daily_metrics", "push_subscriptions", "alert_rules",
    "notifications", "ask_usage",
)  # fmt: skip
MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations" / "versions"


def _head_revision() -> str | None:
    revisions, downs = set(), set()
    for f in MIGRATIONS.glob("*.py"):
        ns: dict[str, Any] = {}
        for line in f.read_text().splitlines():
            if line.startswith(("revision =", "down_revision =")):
                exec(line, ns)  # noqa: S102 - our own migration files, single literal assignments
        if "revision" in ns:
            revisions.add(ns["revision"])
            if ns.get("down_revision"):
                downs.add(ns["down_revision"])
    heads = revisions - downs
    return heads.pop() if len(heads) == 1 else None


def verify() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    engine = get_engine()
    with engine.connect() as conn:
        checks["connect"] = conn.execute(text("select 1")).scalar() == 1
        current = conn.execute(text("select version_num from alembic_version")).scalar()
        head = _head_revision()
        checks["migrations_at_head"] = {"ok": current == head, "current": current, "head": head}
        present = set(
            conn.execute(text("select table_name from information_schema.tables where table_schema='public'")).scalars()
        )
        missing = [t for t in EXPECTED_TABLES if t not in present]
        checks["tables"] = {"ok": not missing, "missing": missing}
        checks["row_counts"] = {
            table.name: conn.execute(select(func.count()).select_from(table)).scalar()
            for table in (dbschema.users, dbschema.saved_commutes, dbschema.routes, dbschema.stops, dbschema.audit_log)
            if table.name in present
        }
    try:
        with engine.begin() as conn:
            conn.execute(text("update audit_log set action = action where false"))
        checks["audit_append_only"] = {"ok": False, "detail": "runtime role can UPDATE audit_log"}
    except DBAPIError:
        checks["audit_append_only"] = {"ok": True}
    ok = (
        checks["connect"]
        and checks["migrations_at_head"]["ok"]
        and checks["tables"]["ok"]
        and checks["audit_append_only"]["ok"]
    )
    return {"ok": bool(ok), "checks": checks}


if __name__ == "__main__":
    report = verify()
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0 if report["ok"] else 1)
