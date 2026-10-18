"""Import a static GTFS feed: conditional download → Parquet tables in the lake → catalog rows in Postgres."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, delete, insert

from stopwatch.platform import dbschema as t
from stopwatch.platform.agencies import AgencyConfig
from stopwatch.platform.blobstore import BlobStore
from stopwatch.platform.duck import connect
from stopwatch.platform.http import fetch_bytes

from .schedule import current_key, meta_key, table_key

MAX_ZIP_BYTES = 200 * 1024 * 1024
KEEP_VERSIONS = 12
REQUIRED = ("routes.txt", "trips.txt", "stop_times.txt", "stops.txt")
OPTIONAL = ("calendar.txt", "calendar_dates.txt", "feed_info.txt")


@dataclass
class ImportResult:
    agency_id: str
    status: str  # imported | unchanged
    version: str | None = None
    counts: dict[str, int] | None = None


def _extract(zip_bytes: bytes, inner: str | None, dest: Path) -> None:
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    if inner:
        zf = zipfile.ZipFile(io.BytesIO(zf.read(inner)))
    names = set(zf.namelist())
    missing = [n for n in REQUIRED if n not in names]
    if missing:
        raise ValueError(f"GTFS zip is missing {missing}")
    dest.mkdir(parents=True, exist_ok=True)
    for name in (*REQUIRED, *OPTIONAL):
        if name in names:
            info = zf.getinfo(name)
            if info.file_size > 2 * MAX_ZIP_BYTES:
                raise ValueError(f"{name} is implausibly large")
            (dest / name).write_bytes(zf.read(name))


def _safe_version(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", raw)[:80] or "unknown"


def _build_tables(src: Path, out: Path, route_types: tuple[int, ...]) -> dict[str, Any]:
    """Filter to in-scope routes and write typed Parquet tables. Returns counts + feed info."""
    out.mkdir(parents=True, exist_ok=True)
    con = connect(out.parent / "duck")
    types = ",".join(str(int(x)) for x in route_types)

    def csv(name: str) -> str:
        # GTFS is RFC 4180 CSV; don't let the sniffer guess (it misses quoted commas in headsigns).
        return (f"read_csv('{(src / name).as_posix()}', all_varchar=true, header=true, delim=',', "
                "quote='\"', escape='\"')")

    con.execute(f"""
        CREATE TABLE routes AS
        SELECT route_id, route_short_name AS short_name, route_long_name AS long_name,
               CAST(route_type AS INTEGER) AS route_type,
               nullif(route_color, '') AS color, nullif(route_text_color, '') AS text_color,
               TRY_CAST(route_sort_order AS INTEGER) AS sort_order
        FROM {csv("routes.txt")} WHERE CAST(route_type AS INTEGER) IN ({types})""")
    con.execute(f"""
        CREATE TABLE trips AS
        SELECT t.route_id, t.service_id, t.trip_id, nullif(t.trip_headsign, '') AS headsign,
               COALESCE(TRY_CAST(t.direction_id AS INTEGER), 0) AS direction_id
        FROM {csv("trips.txt")} t JOIN routes r USING (route_id)""")
    con.execute(f"""
        CREATE TABLE stop_times AS
        SELECT st.trip_id, CAST(st.stop_sequence AS INTEGER) AS stop_sequence, st.stop_id,
               gtfs_secs(COALESCE(nullif(st.arrival_time, ''), st.departure_time)) AS arrival_s,
               gtfs_secs(COALESCE(nullif(st.departure_time, ''), st.arrival_time)) AS departure_s
        FROM {csv("stop_times.txt")} st JOIN trips USING (trip_id)""")
    con.execute(f"""
        CREATE TABLE stops AS
        WITH used AS (SELECT DISTINCT stop_id FROM stop_times),
        s AS (SELECT * FROM {csv("stops.txt")})
        SELECT s.stop_id, s.stop_name AS name, CAST(s.stop_lat AS DOUBLE) AS lat, CAST(s.stop_lon AS DOUBLE) AS lon,
               nullif(s.parent_station, '') AS parent_station
        FROM s WHERE s.stop_id IN (SELECT stop_id FROM used)
           OR s.stop_id IN (SELECT DISTINCT nullif(parent_station, '') FROM s WHERE stop_id IN (SELECT stop_id FROM used))""")
    if (src / "calendar.txt").exists():
        con.execute(f"""
            CREATE TABLE calendar AS SELECT service_id,
              monday = '1' AS mon, tuesday = '1' AS tue, wednesday = '1' AS wed, thursday = '1' AS thu,
              friday = '1' AS fri, saturday = '1' AS sat, sunday = '1' AS sun,
              strptime(start_date, '%Y%m%d')::DATE AS start_date, strptime(end_date, '%Y%m%d')::DATE AS end_date
            FROM {csv("calendar.txt")}""")
    else:
        con.execute("""CREATE TABLE calendar (service_id VARCHAR, mon BOOLEAN, tue BOOLEAN, wed BOOLEAN,
            thu BOOLEAN, fri BOOLEAN, sat BOOLEAN, sun BOOLEAN, start_date DATE, end_date DATE)""")
    if (src / "calendar_dates.txt").exists():
        con.execute(f"""
            CREATE TABLE calendar_dates AS SELECT service_id, strptime(date, '%Y%m%d')::DATE AS date,
              CAST(exception_type AS INTEGER) AS exception_type FROM {csv("calendar_dates.txt")}""")
    else:
        con.execute("CREATE TABLE calendar_dates (service_id VARCHAR, date DATE, exception_type INTEGER)")

    counts: dict[str, int] = {}
    for table in ("routes", "trips", "stop_times", "stops", "calendar", "calendar_dates"):
        con.execute(f"COPY {table} TO '{(out / f'{table}.parquet').as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
        counts[table] = int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])  # type: ignore[index]

    dates = con.execute("""
        SELECT least(min(start_date), (SELECT min(date) FROM calendar_dates)),
               greatest(max(end_date), (SELECT max(date) FROM calendar_dates)) FROM calendar""").fetchone()
    info: dict[str, Any] = {"counts": counts, "start_date": None, "end_date": None, "feed_version": None}
    if dates and dates[0]:
        info["start_date"], info["end_date"] = dates[0].isoformat(), dates[1].isoformat()
    if (src / "feed_info.txt").exists():
        cur = con.execute(f"SELECT * FROM {csv('feed_info.txt')} LIMIT 1")
        cols = [d[0] for d in cur.description]
        first = cur.fetchone()
        if first is not None and "feed_version" in cols:
            info["feed_version"] = first[cols.index("feed_version")]
    con.close()
    return info


def _route_stops(out: Path) -> list[dict[str, Any]]:
    con = connect(out.parent / "duck")
    rows = con.execute(f"""
        WITH x AS (
          SELECT t.route_id, t.direction_id, st.stop_id, min(st.stop_sequence) AS seq
          FROM '{(out / "stop_times.parquet").as_posix()}' st
          JOIN '{(out / "trips.parquet").as_posix()}' t USING (trip_id)
          GROUP BY ALL)
        SELECT route_id, direction_id, stop_id,
               row_number() OVER (PARTITION BY route_id, direction_id ORDER BY seq, stop_id) AS stop_order
        FROM x ORDER BY route_id, direction_id, stop_order""").fetchall()
    con.close()
    return [{"route_id": r, "direction_id": d, "stop_id": s, "stop_order": min(o, 32767)} for r, d, s, o in rows]


def upsert_catalog(conn: Connection, agency: AgencyConfig, out: Path, version: str, info: dict[str, Any]) -> None:
    """Replace the agency's catalog rows in one transaction (commutes reference ids, not FKs, so this is safe)."""
    con = connect(out.parent / "duck")
    routes = con.execute(f"SELECT * FROM '{(out / 'routes.parquet').as_posix()}'").fetchall()
    stops = con.execute(f"SELECT * FROM '{(out / 'stops.parquet').as_posix()}'").fetchall()
    con.close()
    route_stops = _route_stops(out)

    conn.execute(delete(t.route_stops).where(t.route_stops.c.agency_id == agency.id))
    conn.execute(delete(t.routes).where(t.routes.c.agency_id == agency.id))
    conn.execute(delete(t.stops).where(t.stops.c.agency_id == agency.id))
    existing = conn.execute(t.agencies.select().where(t.agencies.c.id == agency.id)).first()
    if existing is None:
        conn.execute(insert(t.agencies).values(id=agency.id, name=agency.name, timezone=agency.timezone,
                                               on_time_early_s=agency.on_time_early_s,
                                               on_time_late_s=agency.on_time_late_s))
    if info.get("start_date"):
        conn.execute(delete(t.feed_versions).where((t.feed_versions.c.agency_id == agency.id)
                                                   & (t.feed_versions.c.version == version)))
        conn.execute(insert(t.feed_versions).values(agency_id=agency.id, version=version,
                                                    start_date=info["start_date"], end_date=info["end_date"]))
    conn.execute(insert(t.routes), [
        {"agency_id": agency.id, "route_id": r[0], "short_name": r[1], "long_name": r[2], "route_type": r[3],
         "color": r[4], "text_color": r[5], "sort_order": r[6]} for r in routes])
    conn.execute(insert(t.stops), [
        {"agency_id": agency.id, "stop_id": s[0], "name": s[1], "lat": s[2], "lon": s[3], "parent_station": s[4]}
        for s in stops])
    if route_stops:
        conn.execute(insert(t.route_stops), [{"agency_id": agency.id, **rs} for rs in route_stops])


def import_schedule(agency: AgencyConfig, lake: BlobStore, workdir: Path, *, force: bool = False,
                    db_conn_factory: Any = None) -> ImportResult:
    cur_blob = lake.get(current_key(agency.id))
    current = json.loads(cur_blob.data) if cur_blob else {"versions": []}
    fetched = fetch_bytes(
        agency.static_gtfs_url, max_bytes=MAX_ZIP_BYTES, read_timeout=60,
        if_none_match=None if force else current.get("etag"),
        if_modified_since=None if force else current.get("last_modified"),
    )
    if fetched.not_modified:
        return ImportResult(agency.id, "unchanged", current.get("version"))

    src = workdir / "gtfs" / agency.id
    _extract(fetched.data, agency.static_inner_zip, src)
    out = workdir / "parquet" / agency.id
    info = _build_tables(src, out, agency.route_types)
    digest = hashlib.sha256(fetched.data).hexdigest()[:12]
    version = _safe_version(str(info["feed_version"] or digest))
    if not force and version == current.get("version"):
        current.update({"etag": fetched.etag, "last_modified": fetched.last_modified})
        lake.put(current_key(agency.id), json.dumps(current).encode(), content_type="application/json")
        return ImportResult(agency.id, "unchanged", version)

    for table in ("routes", "trips", "stop_times", "stops", "calendar", "calendar_dates"):
        lake.put(table_key(agency.id, version, table), (out / f"{table}.parquet").read_bytes(),
                 content_type="application/vnd.apache.parquet")
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    meta = {"agency_id": agency.id, "version": version, "sha256_12": digest, "imported_at": now,
            "start_date": info["start_date"], "end_date": info["end_date"], "counts": info["counts"],
            "source": agency.static_gtfs_url}
    lake.put(meta_key(agency.id, version), json.dumps(meta, indent=2).encode(), content_type="application/json")

    versions = [v for v in current.get("versions", []) if v["version"] != version]
    versions.append({"version": version, "start_date": info["start_date"] or now[:10],
                     "end_date": info["end_date"] or now[:10], "imported_at": now})
    new_current = {"version": version, "versions": versions[-KEEP_VERSIONS:], "etag": fetched.etag,
                   "last_modified": fetched.last_modified}
    lake.put(current_key(agency.id), json.dumps(new_current, indent=2).encode(), content_type="application/json")

    if db_conn_factory is not None:
        with db_conn_factory() as conn:
            upsert_catalog(conn, agency, out, version, info)
    return ImportResult(agency.id, "imported", version, info["counts"])
