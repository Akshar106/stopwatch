"""Least-privilege runtime role: DML on app tables, append-only audit log (docs/05 §9).

Login users (local: ``stopwatch_app``; Neon: the app role) are granted membership in
``stopwatch_app_role``. Migrations run as the owner.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = r"""
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'stopwatch_app_role') then
    create role stopwatch_app_role nologin;
  end if;
end $$;

grant usage on schema public to stopwatch_app_role;
grant select, insert, update, delete on
  users, sessions, agencies, feed_versions, routes, stops, route_stops, saved_commutes,
  idempotency_keys, rate_limit_counters, route_daily_metrics, push_subscriptions, alert_rules,
  notifications, ask_usage
  to stopwatch_app_role;
-- Audit log is append-only for the application.
grant select, insert on audit_log to stopwatch_app_role;
grant usage on all sequences in schema public to stopwatch_app_role;
"""

DOWNGRADE = r"""
revoke all on all tables in schema public from stopwatch_app_role;
revoke all on all sequences in schema public from stopwatch_app_role;
revoke usage on schema public from stopwatch_app_role;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
