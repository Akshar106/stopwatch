"""Nightly maintenance (Scheduler, 05:00 America/New_York; docs/04 §9).

Purges expired and aged-out rows, reconciles the alert-rule snapshots, and checks that last night's
database backup landed. Every step is a delete-by-predicate or an overwrite, so re-running is harmless.

    python -m stopwatch.jobs.maintenance
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from stopwatch.accounts import service as accounts
from stopwatch.alerts import rules
from stopwatch.alerts.snapshot import publish_rules_snapshot
from stopwatch.platform import audit, idempotency, ratelimit
from stopwatch.platform.blobstore import BlobStore, open_blobstore
from stopwatch.platform.clock import utc_now
from stopwatch.platform.config import Settings, get_settings
from stopwatch.platform.db import get_engine, transaction
from stopwatch.platform.observability import flush_metrics, get_logger

log = get_logger("maintenance")

RATE_LIMIT_RETENTION = timedelta(days=1)
IDEMPOTENCY_RETENTION = idempotency.KEY_TTL
NOTIFICATION_RETENTION = timedelta(days=90)
AUDIT_RETENTION = timedelta(days=365)
BACKUP_PREFIX = "backups/postgres/"


def _purge(now: datetime) -> dict[str, int]:
    """All deletes in one owner-role transaction (the app role cannot delete audit rows)."""
    with transaction(get_engine(owner=True)) as conn:
        expired = accounts.purge_expired(conn, now=now)
        audit.record(conn, audit.SYSTEM, "system.demo_purge", details={"count": expired.demo_users})
        return {
            "sessions": expired.sessions,
            "demo_users": expired.demo_users,
            "rate_limit_counters": ratelimit.purge_before(conn, now - RATE_LIMIT_RETENTION),
            "idempotency_keys": idempotency.purge_before(conn, now - IDEMPOTENCY_RETENTION),
            "notifications": rules.purge_notifications_before(conn, now - NOTIFICATION_RETENTION),
            "audit_log": audit.purge_before(conn, now - AUDIT_RETENTION),
        }


def _republish_snapshots(lake: BlobStore, agency_ids: Sequence[str], now: datetime) -> dict[str, int]:
    published: dict[str, int] = {}
    for agency_id in agency_ids:
        with transaction(get_engine(owner=True)) as conn:
            published[agency_id] = publish_rules_snapshot(conn, lake, agency_id, now=now)
    return published


def check_backup(lake: BlobStore, now: datetime) -> str | None:
    """Return the key of today's or yesterday's ``pg_dump``, or None (and log a warning) if neither exists."""
    present = set(lake.list(BACKUP_PREFIX))
    for day in (now.date(), (now - timedelta(days=1)).date()):
        key = f"{BACKUP_PREFIX}{day.isoformat()}.dump"
        if key in present:
            return key
    log.warning("backup_missing", expected_prefix=BACKUP_PREFIX, date=now.date().isoformat())
    return None


def run(*, now: datetime | None = None, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    now = now or utc_now()
    lake = open_blobstore(settings.lake_url)
    purged = _purge(now)
    snapshots = _republish_snapshots(lake, settings.agency_ids, now)
    backup_key = check_backup(lake, now)
    summary = {
        "ran_at": now.isoformat(),
        "purged": purged,
        "alert_snapshots": snapshots,
        "backup_ok": backup_key is not None,
        "backup_key": backup_key,
    }
    log.info("maintenance_done", **{f"purged_{k}": v for k, v in purged.items()}, backup_ok=backup_key is not None)
    return summary


def handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    try:
        return run()
    finally:
        flush_metrics()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)
    print(json.dumps(run(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
