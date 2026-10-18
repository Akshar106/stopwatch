"""Weekly accuracy check: our inferred subway arrivals vs MBTA LAMP's official arrival times.

LAMP publishes one Parquet file per service day at
https://performancedata.mbta.com/lamp/subway-on-time-performance-v1/{date}-subway-on-time-performance-v1.parquet
with `stop_timestamp` (arrival, epoch seconds) per vehicle and stop. Trip ids differ between LAMP and the
GTFS-Realtime feed for many subway trips, so we match on (vehicle_id, stop_id) with the nearest timestamp
within 15 minutes, which is unambiguous for a single vehicle.

    python -m stopwatch.jobs.lamp_validate [--end 2026-10-18]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from stopwatch.platform.blobstore import BlobStore, open_blobstore
from stopwatch.platform.config import get_settings
from stopwatch.platform.duck import connect
from stopwatch.platform.http import FetchError, fetch_bytes
from stopwatch.platform.observability import get_logger
from stopwatch.rollups.compact import arrivals_key

log = get_logger("lamp_validate")
LAMP_URL = (
    "https://performancedata.mbta.com/lamp/subway-on-time-performance-v1/{d}-subway-on-time-performance-v1.parquet"
)
SUBWAY = ("Red", "Orange", "Blue", "Green-B", "Green-C", "Green-D", "Green-E", "Mattapan")
MATCH_WINDOW_S = 900

Fetch = Callable[[str], bytes]


def _default_fetch(url: str) -> bytes:
    return fetch_bytes(url, max_bytes=50 * 1024 * 1024, read_timeout=60).data


def validate(
    lake: BlobStore, site: BlobStore, end: date, workdir: Path, fetch: Fetch = _default_fetch, days: int = 7
) -> dict[str, Any]:
    lamp_files, ours_files = [], []
    for i in range(days):
        d = end - timedelta(days=i)
        key = arrivals_key("mbta", d)
        local = lake.local_path(key)
        if local is None or not local.exists():
            if lake.get(key) is None:
                continue
            local = workdir / "ours" / f"{d}.parquet"
            lake.download_to(key, local)
        try:
            data = fetch(LAMP_URL.format(d=d.isoformat()))
        except FetchError as exc:
            log.warning("LAMP file unavailable", date=d.isoformat(), error=str(exc)[:120])
            continue
        lp = workdir / "lamp" / f"{d}.parquet"
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_bytes(data)
        lamp_files.append(lp)
        ours_files.append(local)

    week = (end - timedelta(days=end.weekday())).isoformat()
    report: dict[str, Any] = {
        "agency_id": "mbta",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "week": week,
        "days": len(lamp_files),
        "sample": 0,
        "median_abs_error_s": None,
        "p90_abs_error_s": None,
        "by_route": {},
        "by_method": {},
    }
    if lamp_files:
        con = connect(workdir)
        ours = "[" + ", ".join(f"'{p.as_posix()}'" for p in ours_files) + "]"
        lamp = "[" + ", ".join(f"'{p.as_posix()}'" for p in lamp_files) + "]"
        routes = ", ".join(f"'{r}'" for r in SUBWAY)
        con.execute(f"""
            CREATE TABLE m AS
            WITH o AS (SELECT route_id, trip_id, stop_id, stop_sequence, vehicle_id, method,
                              epoch(est_arrival) AS t FROM read_parquet({ours}, union_by_name=true)
                       WHERE stop_status = 'served' AND route_id IN ({routes})),
                 l AS (SELECT vehicle_id, stop_id, trip_id, stop_timestamp FROM read_parquet({lamp}, union_by_name=true)
                       WHERE stop_timestamp IS NOT NULL),
                 j AS (SELECT o.*, l.stop_timestamp, abs(o.t - l.stop_timestamp) AS err
                       FROM o JOIN l ON l.stop_id = o.stop_id
                        AND (l.vehicle_id = o.vehicle_id OR l.trip_id = o.trip_id)
                        AND abs(o.t - l.stop_timestamp) <= {MATCH_WINDOW_S})
            SELECT * FROM j QUALIFY row_number() OVER (PARTITION BY trip_id, stop_sequence ORDER BY err) = 1""")
        stats = con.execute("SELECT count(*), median(err), quantile_cont(err, 0.9) FROM m").fetchone()
        n, med, p90 = stats if stats else (0, None, None)
        report.update(
            {
                "sample": int(n),
                "median_abs_error_s": None if med is None else round(float(med)),
                "p90_abs_error_s": None if p90 is None else round(float(p90)),
            }
        )
        report["by_route"] = {
            r: {"n": int(c), "median_abs_error_s": round(float(e))}
            for r, c, e in con.execute("SELECT route_id, count(*), median(err) FROM m GROUP BY 1 ORDER BY 1").fetchall()
        }
        report["by_method"] = {
            r: {"n": int(c), "median_abs_error_s": round(float(e))}
            for r, c, e in con.execute("SELECT method, count(*), median(err) FROM m GROUP BY 1 ORDER BY 1").fetchall()
        }
        con.close()

    body = json.dumps(report, indent=2).encode()
    lake.put(f"reports/lamp/agency=mbta/week={week}.json", body, content_type="application/json")
    site.put(
        "data/v1/validation/mbta.json", body, content_type="application/json", cache_control="public, max-age=3600"
    )
    return report


def run(end: date | None = None) -> dict[str, Any]:
    settings = get_settings()
    if "mbta" not in settings.agency_ids:
        return {"skipped": "LAMP validation only applies to the MBTA"}
    end = end or datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    with tempfile.TemporaryDirectory(prefix="lamp-") as tmp:
        report = validate(open_blobstore(settings.lake_url), open_blobstore(settings.site_url), end, Path(tmp))
    log.info(
        "lamp validation",
        sample=report["sample"],
        median_abs_error_s=report["median_abs_error_s"],
        p90_abs_error_s=report["p90_abs_error_s"],
    )
    return report


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    e = event or {}
    return run(date.fromisoformat(e["end"]) if e.get("end") else None)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--end", type=date.fromisoformat)
    print(json.dumps(run(ap.parse_args().end), indent=2))
    sys.exit(0)
