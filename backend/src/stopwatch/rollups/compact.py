"""Compact one service day of minute event batches into curated Parquet, joined to the schedule.

Dedup rule (idempotency): one served arrival per (trip, stop_sequence), preferring vehicle-observed
arrivals, then higher confidence, then the latest observation. Skips and cancellations are de-duplicated
the same way, so re-running compaction or re-delivered events never double count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from stopwatch.catalog.schedule import ScheduleCatalog
from stopwatch.core.gtfs import CalendarException, CalendarRow, active_service_ids, service_day_reference
from stopwatch.platform.agencies import AgencyConfig
from stopwatch.platform.blobstore import BlobStore
from stopwatch.platform.duck import connect

# Delays outside this window are treated as data errors (kept, but excluded from statistics).
DELAY_VALID_MIN_S = -30 * 60
DELAY_VALID_MAX_S = 120 * 60

EVENT_COLUMNS = {
    "kind": "VARCHAR",
    "service_date": "VARCHAR",
    "trip_id": "VARCHAR",
    "route_id": "VARCHAR",
    "direction_id": "INTEGER",
    "trip_status": "VARCHAR",
    "observed_at": "BIGINT",
    "stop_id": "VARCHAR",
    "stop_sequence": "INTEGER",
    "vehicle_id": "VARCHAR",
    "est_arrival": "BIGINT",
    "method": "VARCHAR",
    "confidence": "VARCHAR",
    "lead_s": "INTEGER",
}


def arrivals_key(agency_id: str, d: date) -> str:
    return f"curated/arrivals/agency={agency_id}/service_date={d.isoformat()}/part-0.parquet"


def trips_key(agency_id: str, d: date) -> str:
    return f"curated/trips/agency={agency_id}/service_date={d.isoformat()}/part-0.parquet"


@dataclass
class CompactResult:
    agency_id: str
    service_date: date
    event_files: int
    arrivals: int = 0
    skipped: int = 0
    scheduled_trips: int = 0
    observed_trips: int = 0
    canceled_trips: int = 0
    added_trips: int = 0
    delay_invalid: int = 0
    unmatched_arrivals: int = 0
    coverage_pct: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _local_files(lake: BlobStore, keys: list[str], workdir: Path) -> list[Path]:
    paths = []
    for key in keys:
        local = lake.local_path(key)
        if local is not None and local.exists():
            paths.append(local)
            continue
        dest = workdir / "events" / key.replace("/", "_")
        if not dest.exists():
            lake.download_to(key, dest)
        paths.append(dest)
    return paths


def load_calendar(
    con: Any, catalog: ScheduleCatalog, version: str, workdir: Path
) -> tuple[list[CalendarRow], list[CalendarException]]:
    cal = catalog.table_path(version, "calendar", workdir).as_posix()
    cd = catalog.table_path(version, "calendar_dates", workdir).as_posix()
    rows = [
        CalendarRow(r[0], (r[1], r[2], r[3], r[4], r[5], r[6], r[7]), r[8], r[9])
        for r in con.execute(
            f"SELECT service_id, mon, tue, wed, thu, fri, sat, sun, start_date, end_date FROM '{cal}'"
        ).fetchall()
    ]
    exc = [
        CalendarException(r[0], r[1], r[2])
        for r in con.execute(f"SELECT service_id, date, exception_type FROM '{cd}'").fetchall()
    ]
    return rows, exc


def compact_day(
    agency: AgencyConfig, lake: BlobStore, catalog: ScheduleCatalog, service_date: date, workdir: Path
) -> CompactResult:
    d = service_date
    keys = lake.list(f"events/agency={agency.id}/dt={d.isoformat()}/") + lake.list(
        f"events/agency={agency.id}/dt={(d + timedelta(days=1)).isoformat()}/"
    )
    keys = [k for k in keys if k.endswith(".jsonl.gz")]
    files = _local_files(lake, keys, workdir)
    res = CompactResult(agency_id=agency.id, service_date=d, event_files=len(files))

    con = connect(workdir)
    version = catalog.version_for(d)
    trips_p = catalog.table_path(version, "trips", workdir).as_posix()
    st_p = catalog.table_path(version, "stop_times", workdir).as_posix()
    routes_p = catalog.table_path(version, "routes", workdir).as_posix()
    cal_rows, cal_exc = load_calendar(con, catalog, version, workdir)
    active = sorted(active_service_ids(d, cal_rows, cal_exc))
    ref = int(service_day_reference(d, agency.timezone).timestamp())

    cols = ", ".join(f"'{k}': '{v}'" for k, v in EVENT_COLUMNS.items())
    if files:
        file_list = ", ".join(f"'{p.as_posix()}'" for p in files)
        con.execute(f"""CREATE TABLE ev AS SELECT * FROM read_json([{file_list}], format='newline_delimited',
                        compression='gzip', columns={{{cols}}})
                        WHERE service_date = '{d.isoformat()}'
                          AND route_id IN (SELECT route_id FROM '{routes_p}')""")
    else:
        con.execute("CREATE TABLE ev (" + ", ".join(f"{k} {v}" for k, v in EVENT_COLUMNS.items()) + ")")

    con.execute("CREATE TABLE active_services (service_id VARCHAR)")
    if active:
        con.executemany("INSERT INTO active_services VALUES (?)", [(s,) for s in active])
    con.execute(f"""CREATE TABLE sched_trips AS SELECT t.* FROM '{trips_p}' t
                    WHERE t.service_id IN (SELECT service_id FROM active_services)""")

    con.execute("""
        CREATE TABLE arr AS SELECT * FROM ev WHERE kind = 'arrival'
        QUALIFY row_number() OVER (
          PARTITION BY trip_id, stop_sequence
          ORDER BY CASE method WHEN 'vp_stopped' THEN 0 WHEN 'last_prediction' THEN 1 ELSE 2 END,
                   CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                   observed_at DESC) = 1""")
    con.execute("""
        CREATE TABLE skp AS SELECT * FROM ev e WHERE kind = 'skipped'
          AND NOT EXISTS (SELECT 1 FROM arr a WHERE a.trip_id = e.trip_id AND a.stop_sequence = e.stop_sequence)
        QUALIFY row_number() OVER (PARTITION BY trip_id, stop_sequence ORDER BY observed_at) = 1""")
    con.execute("""CREATE TABLE cxl AS SELECT DISTINCT trip_id FROM ev WHERE kind = 'canceled'""")

    con.execute(f"""
        CREATE TABLE curated AS
        SELECT DATE '{d.isoformat()}' AS service_date, a.trip_id, a.route_id, a.direction_id, a.stop_id,
               a.stop_sequence, a.vehicle_id, st.arrival_s AS sched_s,
               to_timestamp({ref} + st.arrival_s) AS scheduled_arrival,
               to_timestamp(a.est_arrival) AS est_arrival,
               CAST(a.est_arrival - ({ref} + st.arrival_s) AS INTEGER) AS delay_s,
               (a.est_arrival - ({ref} + st.arrival_s)) BETWEEN {DELAY_VALID_MIN_S} AND {DELAY_VALID_MAX_S}
                 AS delay_valid,
               a.method, a.confidence, 'served' AS stop_status, a.trip_status,
               to_timestamp(a.observed_at) AS observed_at, '{version}' AS schedule_version
        FROM arr a LEFT JOIN '{st_p}' st ON st.trip_id = a.trip_id AND st.stop_sequence = a.stop_sequence
        UNION ALL
        SELECT DATE '{d.isoformat()}', s.trip_id, s.route_id, s.direction_id, s.stop_id, s.stop_sequence,
               s.vehicle_id, st.arrival_s, to_timestamp({ref} + st.arrival_s), NULL, NULL, false,
               NULL, NULL, 'skipped', s.trip_status, to_timestamp(s.observed_at), '{version}'
        FROM skp s LEFT JOIN '{st_p}' st ON st.trip_id = s.trip_id AND st.stop_sequence = s.stop_sequence""")

    con.execute("""
        CREATE TABLE curated_trips AS
        SELECT t.trip_id, t.route_id, t.direction_id,
               CASE WHEN t.trip_id IN (SELECT trip_id FROM cxl) THEN 'canceled' ELSE 'scheduled' END AS status,
               EXISTS (SELECT 1 FROM curated c WHERE c.trip_id = t.trip_id AND c.stop_status = 'served')
                 AS observed
        FROM sched_trips t
        UNION ALL
        SELECT DISTINCT c.trip_id, c.route_id, c.direction_id, 'added', true
        FROM curated c WHERE c.trip_status = 'added' AND c.stop_status = 'served'
          AND c.trip_id NOT IN (SELECT trip_id FROM sched_trips)""")

    out = workdir / "curated"
    out.mkdir(parents=True, exist_ok=True)
    arr_path, trips_path = out / "arrivals.parquet", out / "trips.parquet"
    con.execute(
        f"COPY (SELECT * FROM curated ORDER BY route_id, trip_id, stop_sequence) TO "
        f"'{arr_path.as_posix()}' (FORMAT parquet, COMPRESSION zstd)"
    )
    con.execute(f"COPY curated_trips TO '{trips_path.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")

    stats = con.execute("""
        SELECT count(*) FILTER (WHERE stop_status = 'served'),
               count(*) FILTER (WHERE stop_status = 'skipped'),
               count(*) FILTER (WHERE stop_status = 'served' AND sched_s IS NOT NULL AND NOT delay_valid),
               count(*) FILTER (WHERE stop_status = 'served' AND sched_s IS NULL AND trip_status = 'scheduled')
        FROM curated""").fetchone()
    tstats = con.execute("""
        SELECT count(*) FILTER (WHERE status <> 'added'), count(*) FILTER (WHERE status = 'scheduled' AND observed),
               count(*) FILTER (WHERE status = 'canceled'), count(*) FILTER (WHERE status = 'added')
        FROM curated_trips""").fetchone()
    con.close()
    assert stats is not None and tstats is not None
    res.arrivals, res.skipped, res.delay_invalid, res.unmatched_arrivals = (int(x) for x in stats)
    res.scheduled_trips, res.observed_trips, res.canceled_trips, res.added_trips = (int(x) for x in tstats)
    runnable = res.scheduled_trips - res.canceled_trips
    res.coverage_pct = round(100.0 * res.observed_trips / runnable, 2) if runnable > 0 else None
    res.extra = {"schedule_version": version, "active_services": len(active)}

    lake.put(arrivals_key(agency.id, d), arr_path.read_bytes(), content_type="application/vnd.apache.parquet")
    lake.put(trips_key(agency.id, d), trips_path.read_bytes(), content_type="application/vnd.apache.parquet")
    return res
