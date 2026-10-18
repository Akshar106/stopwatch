"""Demo accounts: isolated, short-lived users so visitors can try saved commutes without signing in.

Limits (docs/05 §2): 24-hour lifetime, at most 500 active at once (per-IP creation limits are applied by the
API), 3 commutes, no push alerts and no Ask. The maintenance job deletes them when they expire.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Connection, func, select

from . import repository
from .models import User

DEMO_LIFETIME = timedelta(hours=24)
MAX_ACTIVE_DEMO_USERS = 500
DEMO_DISPLAY_NAME = "Demo rider"
_CREATION_LOCK_ID = 0x5357_4445_4D4F  # arbitrary constant ("SWDEMO") for pg_advisory_xact_lock


class DemoCapacityError(Exception):
    """Too many demo accounts are active right now."""


def create_demo_user(conn: Connection, *, now: datetime, max_active: int | None = None) -> User:
    """Create a demo user, enforcing the global cap. Creation is serialized so the cap holds under load."""
    cap = MAX_ACTIVE_DEMO_USERS if max_active is None else max_active
    conn.execute(select(func.pg_advisory_xact_lock(_CREATION_LOCK_ID)))
    if repository.count_active_demo_users(conn, now=now) >= cap:
        raise DemoCapacityError
    return repository.insert_demo_user(conn, display_name=DEMO_DISPLAY_NAME, expires_at=now + DEMO_LIFETIME)
