from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config


def _url() -> str:
    url = os.environ.get("DATABASE_OWNER_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_OWNER_URL (or DATABASE_URL) to run migrations")
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        # Guard rails from docs/06 §5: never hold long locks during a migration.
        connection.exec_driver_sql("SET lock_timeout = '3s'")
        connection.exec_driver_sql("SET statement_timeout = '60s'")
        # SET autobegins a transaction in SQLAlchemy 2.x; commit it so Alembic owns transaction boundaries
        # (session-level settings persist after commit).
        connection.commit()
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
