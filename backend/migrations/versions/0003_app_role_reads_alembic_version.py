"""Let the runtime role read alembic_version (read-only) so `make verify-db` can confirm migrations are at head.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("grant select on alembic_version to stopwatch_app_role")


def downgrade() -> None:
    op.execute("revoke select on alembic_version from stopwatch_app_role")
