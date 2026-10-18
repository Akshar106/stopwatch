"""Compute the published JSON documents for one agency (docs/contracts.md §3) from curated Parquet.

All heavy lifting is DuckDB SQL over Parquet. The metric definitions mirror stopwatch.core.metrics (parity
tests in tests/integration/test_rollup_parity.py) and docs/methodology.md.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from stopwatch.catalog.schedule import ScheduleCatalog
from stopwatch.core.gtfs import active_service_ids
from stopwatch.core.metrics import HISTOGRAM_EDGES_S, MIN_SAMPLES
from stopwatch.platform.agencies import AgencyConfig
from stopwatch.platform.blobstore import BlobStore
from stopwatch.platform.duck import connect

from .compact import load_calendar

WINDOW_DAYS = 28
TREND_WEEKS = 8
COVERAGE_DAYS = 30
SAFE_ROUTE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
DAY_SQL = "CASE dayofweek({col}) WHEN 0 THEN 'sun' WHEN 6 THEN 'sat' ELSE 'wkd' END"


@dataclass
class AgencyBuild:
    agency_id: str
    files: dict[str, bytes] = field(default_factory=dict)  # path relative to the build dir
    manifest: dict[str, Any] = field(default_factory=dict)
    route_daily: list[dict[str, Any]] = field(default_factory=list)  # rows for route_daily_metrics (end date)
    summary: dict[str, Any] = field(default_factory=dict)


def _r(v: Any, nd: int = 1) -> Any:
    return None if v is None else round(float(v), nd)


def _i(v: Any) -> int | None:
    return None if v is None else round(float(v))


def _partition_files(lake: BlobStore, prefix: str, start: date, end: date, workdir: Path) -> list[Path]:
    """Local paths for curated partitions in [start, end], preserving hive directory layout."""
    out = []
    for key in lake.list(prefix):
        m = re.search(r"service_date=(\d{4}-\d{2}-\d{2})/", key)
        if not m or not (start <= date.fromisoformat(m.group(1)) <= end):
            continue
        local = lake.local_path(key)
        if local is None or not local.exists():
            local = workdir / "lake" / key
            if not local.exists():
                lake.download_to(key, local)
        out.append(local)
    return sorted(out)


def _representative_dates(end: date, start: date) -> dict[str, date]:
    """Most recent date of each day type within [start, end] (falls back to the week before start)."""
    reps: dict[str, date] = {}
    d = end
    while len(reps) < 3 and d >= start - timedelta(days=7):
        dt = "sat" if d.weekday() == 5 else "sun" if d.weekday() == 6 else "wkd"
        reps.setdefault(dt, d)
        d -= timedelta(days=1)
    return reps


def _list_sql(paths: list[Path]) -> str:
    return "[" + ", ".join(f"'{p.as_posix()}'" for p in paths) + "]"


def compute_agency(agency: AgencyConfig, lake: BlobStore, catalog: ScheduleCatalog, end: date, workdir: Path,
                   *, has_validation: bool = False) -> AgencyBuild:
    build = AgencyBuild(agency_id=agency.id)
    win_from = end - timedelta(days=WINDOW_DAYS - 1)
    trend_from = end - timedelta(days=7 * TREND_WEEKS - 1)
    cov_from = end - timedelta(days=COVERAGE_DAYS - 1)
    early, late = agency.on_time_early_s, agency.on_time_late_s
    version = catalog.version_for(end)
    trips_p = catalog.table_path(version, "trips", workdir).as_posix()
    st_p = catalog.table_path(version, "stop_times", workdir).as_posix()
    routes_p = catalog.table_path(version, "routes", workdir).as_posix()
    stops_p = catalog.table_path(version, "stops", workdir).as_posix()

    con = connect(workdir)
    arr_files = _partition_files(lake, f"curated/arrivals/agency={agency.id}/", trend_from, end, workdir)
    trip_files = _partition_files(lake, f"curated/trips/agency={agency.id}/", min(trend_from, cov_from), end,
                                  workdir)
    if arr_files:
        con.execute(f"CREATE VIEW arr_all AS SELECT * FROM read_parquet({_list_sql(arr_files)}, "
                    "hive_partitioning=false, union_by_name=true)")
    else:
        con.execute("""CREATE TABLE arr_all (service_date DATE, trip_id VARCHAR, route_id VARCHAR,
            direction_id INTEGER, stop_id VARCHAR, stop_sequence INTEGER, sched_s INTEGER, est_arrival TIMESTAMPTZ,
            delay_s INTEGER, delay_valid BOOLEAN, confidence VARCHAR, stop_status VARCHAR, trip_status VARCHAR)""")
    if trip_files:
        con.execute(f"CREATE VIEW trips_all AS SELECT trip_id, route_id, direction_id, status, observed, "
                    f"CAST(service_date AS DATE) AS service_date FROM read_parquet({_list_sql(trip_files)}, "
                    "hive_partitioning=true, union_by_name=true)")
    else:
        con.execute("""CREATE TABLE trips_all (trip_id VARCHAR, route_id VARCHAR, direction_id INTEGER,
            status VARCHAR, observed BOOLEAN, service_date DATE)""")

    day = DAY_SQL.format(col="service_date")
    stat_filter = ("stop_status = 'served' AND delay_valid AND confidence IN ('high', 'medium') "
                   "AND trip_status = 'scheduled' AND sched_s IS NOT NULL")
    con.execute(f"""CREATE TABLE stat AS SELECT *, {day} AS day, (sched_s // 3600) % 24 AS hour
                    FROM arr_all WHERE {stat_filter}""")
    con.execute(f"CREATE VIEW stat_w AS SELECT * FROM stat WHERE service_date BETWEEN DATE '{win_from}' "
                f"AND DATE '{end}'")

    # Scheduled service on representative dates -> the cell universe, scheduled headways and waits.
    cal_rows, cal_exc = load_calendar(con, catalog, version, workdir)
    con.execute("CREATE TABLE rep_services (day VARCHAR, service_id VARCHAR)")
    for dt, d in _representative_dates(end, win_from).items():
        svc = active_service_ids(d, cal_rows, cal_exc)
        if svc:
            con.executemany("INSERT INTO rep_services VALUES (?, ?)", [(dt, s) for s in sorted(svc)])
    con.execute(f"""CREATE TABLE sched_rep AS
        SELECT r.day, t.route_id, t.direction_id, st.stop_id, st.arrival_s
        FROM '{st_p}' st JOIN '{trips_p}' t USING (trip_id) JOIN rep_services r ON r.service_id = t.service_id
        WHERE st.arrival_s IS NOT NULL""")
    con.execute("""CREATE TABLE sched_cells AS
        WITH hw AS (
          SELECT day, route_id, direction_id, stop_id, (arrival_s // 3600) % 24 AS hour,
                 CAST(arrival_s - lag(arrival_s) OVER (PARTITION BY day, route_id, direction_id, stop_id
                                                       ORDER BY arrival_s) AS DOUBLE) AS h
          FROM sched_rep)
        SELECT day, route_id, direction_id, stop_id, hour, count(*) AS trips_sched,
               median(h) FILTER (WHERE h > 0) AS sched_headway_s,
               sum(h * h) FILTER (WHERE h > 0) / nullif(2.0 * sum(h) FILTER (WHERE h > 0), 0) AS sched_wait
        FROM hw GROUP BY ALL""")
    con.execute("""CREATE TABLE act_cells AS
        WITH hw AS (
          SELECT day, route_id, direction_id, stop_id, hour,
                 CAST(epoch(est_arrival) AS DOUBLE) - lag(CAST(epoch(est_arrival) AS DOUBLE)) OVER (
                   PARTITION BY service_date, route_id, direction_id, stop_id ORDER BY est_arrival) AS h
          FROM stat_w)
        SELECT day, route_id, direction_id, stop_id, hour,
               sum(h * h) / nullif(2.0 * sum(h), 0) AS act_wait
        FROM hw WHERE h > 0 AND h < 10800 GROUP BY ALL""")

    edges = HISTOGRAM_EDGES_S
    buckets = [f"count(*) FILTER (WHERE delay_s < {edges[0]})"]
    buckets += [f"count(*) FILTER (WHERE delay_s >= {lo} AND delay_s < {hi})" for lo, hi in zip(edges, edges[1:],
                                                                                              strict=False)]
    buckets += [f"count(*) FILTER (WHERE delay_s >= {edges[-1]})"]
    stats_sql = (f"count(*) AS n, quantile_cont(delay_s, 0.5) AS p50, quantile_cont(delay_s, 0.9) AS p90, "
                 f"100.0 * avg(CASE WHEN delay_s BETWEEN {early} AND {late} THEN 1 ELSE 0 END) AS on_time, "
                 f"100.0 * avg(CASE WHEN delay_s < {early} THEN 1 ELSE 0 END) AS early_pct")
    con.execute(f"""CREATE TABLE stat_cells AS SELECT route_id, direction_id, stop_id, day, hour, {stats_sql},
                    [{", ".join(buckets)}] AS hist FROM stat_w GROUP BY ALL""")
    con.execute(f"""CREATE TABLE skip_cells AS
        SELECT route_id, direction_id, stop_id, {day} AS day, (sched_s // 3600) % 24 AS hour, count(*) AS skipped
        FROM arr_all WHERE stop_status = 'skipped' AND sched_s IS NOT NULL
          AND service_date BETWEEN DATE '{win_from}' AND DATE '{end}' GROUP BY ALL""")
    con.execute(f"""CREATE TABLE cxl_cells AS
        SELECT t.route_id, t.direction_id, st.stop_id, {DAY_SQL.format(col="t.service_date")} AS day,
               (st.arrival_s // 3600) % 24 AS hour, count(*) AS canceled
        FROM trips_all t JOIN '{st_p}' st USING (trip_id)
        WHERE t.status = 'canceled' AND t.service_date BETWEEN DATE '{win_from}' AND DATE '{end}' GROUP BY ALL""")

    freq = agency.frequent_headway_s
    cells = con.execute(f"""
        SELECT s.route_id, s.direction_id, s.stop_id, s.day, s.hour,
               coalesce(c.n, 0), c.p50, c.p90, c.on_time, c.early_pct, coalesce(k.canceled, 0),
               coalesce(sk.skipped, 0), s.sched_headway_s,
               CASE WHEN s.sched_headway_s <= {freq} AND a.act_wait IS NOT NULL AND s.sched_wait IS NOT NULL
                    THEN a.act_wait - s.sched_wait END AS ewt,
               coalesce(c.hist, [{", ".join("0" for _ in range(len(edges) + 1))}])
        FROM sched_cells s
        LEFT JOIN stat_cells c USING (route_id, direction_id, stop_id, day, hour)
        LEFT JOIN cxl_cells k USING (route_id, direction_id, stop_id, day, hour)
        LEFT JOIN skip_cells sk USING (route_id, direction_id, stop_id, day, hour)
        LEFT JOIN act_cells a USING (route_id, direction_id, stop_id, day, hour)
        ORDER BY s.route_id, s.direction_id, s.stop_id,
                 CASE s.day WHEN 'wkd' THEN 0 WHEN 'sat' THEN 1 ELSE 2 END, s.hour""").fetchall()

    stop_stats = {(r[0], r[1], r[2]): r[3:] for r in con.execute(
        f"SELECT route_id, direction_id, stop_id, {stats_sql} FROM stat_w GROUP BY ALL").fetchall()}
    route_stats = {r[0]: r[1:] for r in con.execute(
        f"SELECT route_id, {stats_sql} FROM stat_w GROUP BY ALL").fetchall()}
    route_cov = {r[0]: r[1:] for r in con.execute(f"""
        SELECT route_id, count(*) FILTER (WHERE status = 'scheduled' AND observed),
               count(*) FILTER (WHERE status <> 'added') - count(*) FILTER (WHERE status = 'canceled')
        FROM trips_all WHERE service_date BETWEEN DATE '{win_from}' AND DATE '{end}' GROUP BY ALL""").fetchall()}
    trend: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in con.execute(f"""
        SELECT route_id, CAST(date_trunc('week', service_date) AS DATE) AS wk, {stats_sql}
        FROM stat WHERE service_date BETWEEN DATE '{trend_from}' AND DATE '{end}'
        GROUP BY ALL ORDER BY route_id, wk""").fetchall():
        n = int(r[2])
        ok = n >= MIN_SAMPLES
        trend[r[0]].append({"week_start": r[1].isoformat(), "n": n, "on_time_pct": _r(r[5]) if ok else None,
                            "p50_s": _i(r[3]) if ok else None, "p90_s": _i(r[4]) if ok else None})
    headsigns = {(r[0], r[1]): r[2] for r in con.execute(
        f"SELECT route_id, direction_id, mode(headsign) FROM '{trips_p}' GROUP BY ALL").fetchall()}
    stop_order = {(r[0], r[1], r[2]): r[3] for r in con.execute(f"""
        WITH x AS (SELECT t.route_id, t.direction_id, st.stop_id, min(st.stop_sequence) AS seq
                   FROM '{st_p}' st JOIN '{trips_p}' t USING (trip_id) GROUP BY ALL)
        SELECT route_id, direction_id, stop_id,
               row_number() OVER (PARTITION BY route_id, direction_id ORDER BY seq, stop_id) FROM x""").fetchall()}
    stop_rows = con.execute(f"SELECT stop_id, name, lat, lon, parent_station FROM '{stops_p}'").fetchall()
    stop_names = {r[0]: r[1] for r in stop_rows}
    stop_routes: dict[str, list[str]] = defaultdict(list)
    for sid, rid in con.execute(f"""SELECT DISTINCT st.stop_id, t.route_id FROM '{st_p}' st
                                     JOIN '{trips_p}' t USING (trip_id) ORDER BY 1, 2""").fetchall():
        stop_routes[sid].append(rid)
    routes = con.execute(f"SELECT route_id, short_name, long_name, route_type, color, text_color, sort_order "
                         f"FROM '{routes_p}' ORDER BY sort_order NULLS LAST, route_id").fetchall()
    coverage_days = con.execute(f"""
        SELECT service_date, count(*) FILTER (WHERE status <> 'added'),
               count(*) FILTER (WHERE status = 'scheduled' AND observed), count(*) FILTER (WHERE status = 'canceled')
        FROM trips_all WHERE service_date BETWEEN DATE '{cov_from}' AND DATE '{end}'
        GROUP BY 1 ORDER BY 1""").fetchall()
    first_data = con.execute(f"SELECT min(service_date) FROM stat_w").fetchone()
    # Route-level metrics for the end date (route_daily_metrics table).
    day_rows = con.execute(f"""
        WITH s AS (SELECT route_id, direction_id, {stats_sql} FROM stat WHERE service_date = DATE '{end}'
                   GROUP BY ALL),
             tr AS (SELECT route_id, direction_id, count(*) FILTER (WHERE status <> 'added') AS sched,
                           count(*) FILTER (WHERE status = 'scheduled' AND observed) AS obs,
                           count(*) FILTER (WHERE status = 'canceled') AS cxl
                    FROM trips_all WHERE service_date = DATE '{end}' GROUP BY ALL)
        SELECT tr.route_id, tr.direction_id, tr.sched, tr.obs, tr.cxl, s.on_time, s.p50, s.p90
        FROM tr LEFT JOIN s USING (route_id, direction_id)""").fetchall()
    con.close()

    # ---- assemble documents -------------------------------------------------------------------------------
    def stats_obj(row: Any) -> dict[str, Any]:
        n = int(row[0]) if row else 0
        ok = n >= MIN_SAMPLES
        return {"n": n, "on_time_pct": _r(row[3]) if ok else None, "p50_s": _i(row[1]) if ok else None,
                "p90_s": _i(row[2]) if ok else None}

    by_route: dict[str, dict[tuple[int, str], list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for (rid, did, sid, dt, hr, n, p50, p90, on_time, early_pct, cxl, skp, shw, ewt, hist) in cells:
        ok = n >= MIN_SAMPLES
        by_route[rid][(did, sid)].append({
            "day": dt, "hour": int(hr), "n": int(n),
            "p50_s": _i(p50) if ok else None, "p90_s": _i(p90) if ok else None,
            "on_time_pct": _r(on_time) if ok else None, "early_pct": _r(early_pct) if ok else None,
            "canceled": int(cxl), "skipped": int(skp), "sched_headway_s": _i(shw),
            "ewt_s": _i(ewt) if (ok and ewt is not None) else None, "hist": [int(x) for x in hist],
        })

    route_info = {r[0]: {"id": r[0], "short_name": r[1], "long_name": r[2], "type": int(r[3]),
                         "color": r[4], "text_color": r[5], "sort_order": r[6]} for r in routes}
    window_obj = {"from": (first_data[0] if first_data and first_data[0] else win_from).isoformat(),
                  "to": end.isoformat(), "days": 0}
    window_obj["days"] = (date.fromisoformat(window_obj["to"]) - date.fromisoformat(window_obj["from"])).days + 1
    route_summaries = []
    skipped_routes = []
    for rid, info in route_info.items():
        if rid not in by_route and rid not in route_stats:
            continue  # no service on representative dates and no data
        if not SAFE_ROUTE_ID.match(rid):
            skipped_routes.append(rid)
            continue
        cov = route_cov.get(rid)
        cov_pct = _r(100.0 * cov[0] / cov[1]) if cov and cov[1] else None
        rstats = stats_obj(route_stats.get(rid))
        route_summaries.append({**info, "summary": {**rstats, "coverage_pct": cov_pct}})
        directions = []
        for did in (0, 1):
            stops_in_dir = sorted({sid for (d2, sid) in by_route[rid] if d2 == did},
                                  key=lambda s, did=did: (stop_order.get((rid, did, s), 9999), s))
            if not stops_in_dir:
                continue
            directions.append({
                "direction_id": did, "headsign": headsigns.get((rid, did)),
                "stops": [{"stop_id": sid, "name": stop_names.get(sid, sid),
                           "order": int(stop_order.get((rid, did, sid), 0)),
                           "summary": stats_obj(stop_stats.get((rid, did, sid))),
                           "cells": by_route[rid][(did, sid)]} for sid in stops_in_dir],
            })
        detail = {
            "agency_id": agency.id, "route": info, "window": window_obj,
            "on_time_definition_s": [early, late], "histogram_edges_s": list(edges), "min_samples": MIN_SAMPLES,
            "directions": directions, "trend": trend.get(rid, []),
            "coverage": {"observed_trips": int(cov[0]) if cov else 0, "scheduled_trips": int(cov[1]) if cov else 0,
                         "coverage_pct": cov_pct},
        }
        build.files[f"{agency.id}/routes/{rid}.json"] = _dumps(detail)

    in_scope_stops = [r for r in stop_rows if r[0] in stop_routes]
    build.files[f"{agency.id}/stops.json"] = _dumps({"agency_id": agency.id, "stops": [
        {"id": r[0], "name": r[1], "lat": round(r[2], 6), "lon": round(r[3], 6), "parent": r[4],
         "routes": stop_routes[r[0]]} for r in in_scope_stops]})
    build.files[f"{agency.id}/routes.json"] = _dumps({"agency_id": agency.id, "routes": route_summaries})
    build.files[f"{agency.id}/coverage.json"] = _dumps({"agency_id": agency.id, "days": [
        {"service_date": d.isoformat(), "scheduled_trips": int(s), "observed_trips": int(o),
         "canceled_trips": int(c), "coverage_pct": _r(100.0 * o / (s - c)) if s - c > 0 else None}
        for d, s, o, c in coverage_days]})

    build.manifest = {
        "id": agency.id, "name": agency.name, "timezone": agency.timezone, "live_api": agency.live_api,
        "window": window_obj, "on_time_definition_s": [early, late], "histogram_edges_s": list(edges),
        "min_samples": MIN_SAMPLES, "_has_validation": has_validation,
    }
    build.route_daily = [
        {"agency_id": agency.id, "route_id": r[0], "direction_id": int(r[1]), "service_date": end,
         "trips_scheduled": int(r[2]), "trips_observed": int(r[3]), "trips_canceled": int(r[4]),
         "on_time_pct": _r(r[5], 2), "median_delay_s": _i(r[6]), "p90_delay_s": _i(r[7]), "excess_wait_s": None}
        for r in day_rows]
    build.summary = {"routes": len(route_summaries), "stops": len(in_scope_stops), "cells": len(cells),
                     "skipped_unsafe_route_ids": skipped_routes, "schedule_version": version,
                     "window": window_obj}
    return build


def _dumps(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str).encode()
