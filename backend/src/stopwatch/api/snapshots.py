"""Republish alert-rule snapshots after a change has committed.

Publishing after the commit (not inside the request transaction) means the snapshot is built from
committed state, so two concurrent changes can't each publish a view that misses the other. A failed
publish never fails the user's request: the nightly maintenance job reconciles every snapshot.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from sqlalchemy import Engine

from stopwatch.alerts.snapshot import publish_rules_snapshot
from stopwatch.platform.blobstore import BlobStore, open_blobstore
from stopwatch.platform.config import Settings
from stopwatch.platform.db import transaction
from stopwatch.platform.observability import get_logger

log = get_logger("api")


@lru_cache(maxsize=4)
def _lake(url: str) -> BlobStore:
    return open_blobstore(url)


def republish(engine: Engine, settings: Settings, agency_ids: Iterable[str]) -> None:
    for agency_id in sorted(set(agency_ids)):
        try:
            with transaction(engine) as conn:
                count = publish_rules_snapshot(conn, _lake(settings.lake_url), agency_id)
            log.info("alert_snapshot_published", agency_id=agency_id, rules=count)
        except Exception as exc:  # noqa: BLE001 - best effort; maintenance reconciles nightly
            log.error("alert_snapshot_publish_failed", agency_id=agency_id, error_type=type(exc).__name__)
