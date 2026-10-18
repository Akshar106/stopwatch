"""Lambda entry point: compact yesterday's events, gate on data quality, compute and publish a new build.

    python -m stopwatch.jobs.daily_rollup                    # yesterday (agency local time)
    python -m stopwatch.jobs.daily_rollup --date 2026-10-18  # a specific service date
    python -m stopwatch.jobs.daily_rollup --force            # publish even if the quality gate fails (dev)
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert as pg_insert

from stopwatch.catalog.schedule import ScheduleCatalog
from stopwatch.platform import dbschema as t
from stopwatch.platform.agencies import get_agency
from stopwatch.platform.blobstore import open_blobstore
from stopwatch.platform.config import get_settings
from stopwatch.platform.db import database_configured, transaction
from stopwatch.platform.observability import flush_metrics, get_logger, put_metric
from stopwatch.rollups import publish as pub
from stopwatch.rollups.compact import compact_day
from stopwatch.rollups.compute import compute_agency
from stopwatch.rollups.quality import evaluate

log = get_logger("rollup")


def _default_date(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date() - timedelta(days=1)


def _upsert_route_daily(rows: list[dict[str, Any]]) -> None:
    if not rows or not database_configured():
        return
    stmt = pg_insert(t.route_daily_metrics).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["agency_id", "route_id", "direction_id", "service_date"],
        set_={c: stmt.excluded[c] for c in ("trips_scheduled", "trips_observed", "trips_canceled", "on_time_pct",
                                             "median_delay_s", "p90_delay_s", "excess_wait_s")},
    )
    with transaction() as conn:
        conn.execute(stmt)


def run(service_date: date | None = None, *, force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    lake = open_blobstore(settings.lake_url)
    site = open_blobstore(settings.site_url)
    build_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    files: dict[str, bytes] = {}
    manifest_entries: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"build_id": build_id, "agencies": {}, "published": False}
    all_passed = True

    with tempfile.TemporaryDirectory(prefix="rollup-") as tmp:
        workdir = Path(tmp)
        for agency_id in settings.agency_ids:
            agency = get_agency(agency_id)
            d = service_date or _default_date(agency.timezone)
            catalog = ScheduleCatalog(lake, agency.id)
            compacted = compact_day(agency, lake, catalog, d, workdir / agency.id / "compact")
            report = evaluate(compacted, lake)
            if compacted.coverage_pct is not None:
                put_metric("RollupCoveragePct", compacted.coverage_pct)
            has_validation = site.get(f"data/v1/validation/{agency.id}.json") is not None
            build = compute_agency(agency, lake, catalog, d, workdir / agency.id / "compute",
                                   has_validation=has_validation)
            files.update(build.files)
            manifest_entries.append(build.manifest)
            try:
                _upsert_route_daily(build.route_daily)
            except Exception as exc:  # noqa: BLE001 - the DB copy is optional; publishing must not depend on it
                log.warning("route_daily_metrics upsert failed", error_type=type(exc).__name__)
            all_passed &= report.passed
            summary["agencies"][agency.id] = {
                "service_date": d.isoformat(), "quality_passed": report.passed,
                "failed_checks": [k for k, v in report.checks.items() if not v["ok"]],
                "coverage_pct": compacted.coverage_pct, "arrivals": compacted.arrivals,
                "event_files": compacted.event_files, **build.summary,
            }

    if all_passed or force:
        generated = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        pub.publish(site, build_id, files, pub.build_manifest(build_id, generated, manifest_entries))
        summary["published"] = True
        summary["files"] = len(files)
        put_metric("RollupSuccess", 1)
        log.info("rollup published", build_id=build_id, files=len(files), forced=force and not all_passed)
    else:
        put_metric("RollupSuccess", 0)
        log.error("quality gate failed; previous build stays live", build_id=build_id,
                  agencies=json.dumps(summary["agencies"], default=str))
    return summary


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    event = event or {}
    try:
        d = date.fromisoformat(event["date"]) if event.get("date") else None
        return run(d, force=bool(event.get("force")))
    finally:
        flush_metrics()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", type=date.fromisoformat)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.date, force=a.force), indent=2, default=str))
    sys.exit(0)
