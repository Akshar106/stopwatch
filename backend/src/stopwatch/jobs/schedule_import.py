"""Lambda entry point: daily static-GTFS import (skips quickly when the feed hasn't changed)."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from stopwatch.catalog.gtfs_import import import_schedule
from stopwatch.platform.agencies import get_agency
from stopwatch.platform.blobstore import open_blobstore
from stopwatch.platform.config import get_settings
from stopwatch.platform.db import database_configured, transaction
from stopwatch.platform.observability import get_logger

log = get_logger("schedule_import")


def run(*, force: bool = False) -> list[dict[str, Any]]:
    settings = get_settings()
    lake = open_blobstore(settings.lake_url)
    results = []
    for agency_id in settings.agency_ids:
        agency = get_agency(agency_id)
        with tempfile.TemporaryDirectory(prefix=f"gtfs-{agency_id}-") as tmp:
            res = import_schedule(
                agency, lake, Path(tmp), force=force, db_conn_factory=transaction if database_configured() else None
            )
        summary = {"agency": agency_id, "status": res.status, "version": res.version, "counts": res.counts}
        log.info("schedule import", **summary)
        results.append(summary)
    return results


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return {"imports": run(force=bool((event or {}).get("force")))}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-import even if unchanged")
    print(json.dumps(run(force=ap.parse_args().force), indent=2))
    sys.exit(0)
