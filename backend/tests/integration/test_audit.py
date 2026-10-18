"""platform.audit: append-only for the app role, PII-free details, retention purge by the owner role."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import ProgrammingError

from stopwatch.platform import audit
from stopwatch.platform.audit import AuditContext
from stopwatch.platform.clock import utc_now
from stopwatch.platform.dbschema import audit_log

pytestmark = pytest.mark.integration


def test_record_writes_a_pseudonymous_row(app_engine: Engine) -> None:
    user_id = uuid.uuid4()
    ctx = AuditContext("user", user_id, request_id="req-audit-1", ip_prefix="203.0.113.0/24")
    with app_engine.begin() as conn:
        audit.record(
            conn,
            ctx,
            "commute.create",
            target_kind="commute",
            target_id="c-1",
            details={"fields": ["label"], "email": "x@example.com", "nested": {"token": "t"}},
        )
        row = conn.execute(select(audit_log).where(audit_log.c.request_id == "req-audit-1")).mappings().one()
    assert (row["actor_kind"], row["actor_user_id"], row["action"], row["outcome"]) == (
        "user",
        user_id,
        "commute.create",
        "success",
    )
    assert str(row["ip_prefix"]) == "203.0.113.0/24"
    assert row["details"] == {"fields": ["label"], "email": "[redacted]", "nested": {"token": "[redacted]"}}


def test_unknown_actions_fail_loudly(app_engine: Engine) -> None:
    with pytest.raises(ValueError, match="unknown audit action"), app_engine.begin() as conn:
        audit.record(conn, audit.SYSTEM, "made.up")


def test_list_for_actor_is_scoped_and_newest_first(app_engine: Engine) -> None:
    me, other = uuid.uuid4(), uuid.uuid4()
    with app_engine.begin() as conn:
        audit.record(conn, AuditContext("user", me), "auth.login")
        audit.record(conn, AuditContext("user", other), "auth.login")
        audit.record(conn, AuditContext("user", me), "auth.logout")
        entries = audit.list_for_actor(conn, me)
    assert [e["action"] for e in entries] == ["auth.logout", "auth.login"]
    assert set(entries[0]) == {"at", "action", "outcome"}


def test_app_role_cannot_purge_but_owner_can(app_engine: Engine, owner_engine: Engine) -> None:
    old_id = uuid.uuid4()
    with app_engine.begin() as conn:
        audit.record(conn, AuditContext("user", old_id), "auth.login")
    with owner_engine.begin() as conn:
        conn.execute(
            audit_log.update().where(audit_log.c.actor_user_id == old_id).values(at=utc_now() - timedelta(days=400))
        )
    cutoff = utc_now() - timedelta(days=365)
    with pytest.raises(ProgrammingError, match="permission denied"), app_engine.begin() as conn:
        audit.purge_before(conn, cutoff)
    with owner_engine.begin() as conn:
        assert audit.purge_before(conn, cutoff) >= 1
        assert conn.execute(select(audit_log).where(audit_log.c.actor_user_id == old_id)).first() is None
