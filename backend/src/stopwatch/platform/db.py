"""Postgres access. Engines are cached per URL; Lambda containers keep a tiny pool (Neon scales to zero)."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.exc import OperationalError

from .config import get_settings


class DatabaseNotConfiguredError(RuntimeError):
    pass


def _normalize(url: str) -> str:
    # Accept plain postgres:// URLs (Neon console format) and pin the psycopg 3 driver.
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


@lru_cache(maxsize=4)
def _engine_for(url: str) -> Engine:
    in_lambda = bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
    return create_engine(
        _normalize(url),
        pool_size=1 if in_lambda else 5,
        max_overflow=1 if in_lambda else 5,
        pool_pre_ping=True,
        pool_recycle=240,  # Neon suspends idle compute after ~5 min; recycle before that
        connect_args={"connect_timeout": 5, "application_name": "stopwatch"},
    )


def get_engine(*, owner: bool = False) -> Engine:
    settings = get_settings()
    secret = settings.database_owner_url if owner and settings.database_owner_url else settings.database_url
    if secret is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not set")
    return _engine_for(secret.get_secret_value())


def database_configured() -> bool:
    return get_settings().database_url is not None


@contextmanager
def transaction(engine: Engine | None = None, *, owner: bool = False, attempts: int = 4) -> Iterator[Connection]:
    """Open a transaction, retrying only the *connect* step (safe: nothing has executed yet).

    Neon's first connection after idle can take ~0.5-1 s or fail transiently while compute wakes.
    """
    eng = engine or get_engine(owner=owner)
    delay = 0.1
    conn: Connection | None = None
    for attempt in range(attempts):
        try:
            conn = eng.connect()
            break
        except OperationalError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2
    assert conn is not None
    try:
        with conn.begin():
            yield conn
    finally:
        conn.close()
