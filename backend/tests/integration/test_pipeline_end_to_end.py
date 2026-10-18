"""Recorded MBTA snapshots → real ingest tick → compaction → quality gate → compute → publish → rollback.

File-backed stores only (no database, no network), with a trimmed copy of the real MBTA schedule.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from stopwatch.catalog.schedule import ScheduleCatalog
from stopwatch.core.metrics import MIN_SAMPLES, histogram, percentile
from stopwatch.ingest.replay import replay_into_lake
from stopwatch.platform.agencies import get_agency
from stopwatch.platform.blobstore import BlobStore
from stopwatch.rollups import publish as pub
from stopwatch.rollups.compact import arrivals_key, compact_day, trips_key
from stopwatch.rollups.compute import compute_agency
from stopwatch.rollups.quality import evaluate
from tests.pipeline_helpers import SAMPLE_DATE, SAMPLE_RT, make_lake

D = date.fromisoformat(SAMPLE_DATE)
MBTA = get_agency("mbta")


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory: pytest.TempPathFactory) -> dict:
    root = tmp_path_factory.mktemp("pipeline")
    lake, site = make_lake(root)
    ticks = replay_into_lake(SAMPLE_RT, MBTA, lake, site)
    catalog = ScheduleCatalog(lake, "mbta")
    compacted = compact_day(MBTA, lake, catalog, D, root / "work" / "compact")
    report = evaluate(compacted, lake)
    build = compute_agency(MBTA, lake, catalog, D, root / "work" / "compute")
    manifest = pub.build_manifest("B1", "2026-10-19T08:15:00Z", [build.manifest])
    pub.publish(site, "B1", build.files, manifest)
    return {
        "root": root,
        "lake": lake,
        "site": site,
        "ticks": ticks,
        "compacted": compacted,
        "report": report,
        "build": build,
        "catalog": catalog,
    }


def _json(site: BlobStore, key: str) -> dict:
    blob = site.get(key)
    assert blob is not None, key
    return json.loads(blob.data)


def test_ticks_succeed_and_write_state_and_health(pipeline: dict) -> None:
    outcomes = [t.outcome for t in pipeline["ticks"]]
    assert outcomes[0] == "ok" and set(outcomes) <= {"ok", "not_advanced"}
    assert pipeline["lake"].get("state/mbta/latest.json.gz") is not None
    health = _json(pipeline["site"], "data/v1/health/mbta.json")
    assert health["agency_id"] == "mbta" and health["status"] in {"ok", "degraded", "stale"}


def test_compaction_joins_schedule_and_dedupes(pipeline: dict) -> None:
    c = pipeline["compacted"]
    assert c.arrivals > 100
    assert c.unmatched_arrivals / c.arrivals < 0.1
    path = pipeline["lake"].local_path(arrivals_key("mbta", D))
    con = duckdb.connect()
    dupes = con.execute(f"""SELECT count(*) FROM (SELECT trip_id, stop_sequence, count(*) n FROM '{path}'
                            WHERE stop_status = 'served' GROUP BY ALL HAVING n > 1)""").fetchone()[0]
    assert dupes == 0
    sane = con.execute(
        f"SELECT avg(CASE WHEN delay_valid THEN 1 ELSE 0 END) FROM '{path}' "
        "WHERE stop_status = 'served' AND sched_s IS NOT NULL"
    ).fetchone()[0]
    assert sane > 0.95


def test_compaction_is_idempotent(pipeline: dict, tmp_path: Path) -> None:
    lake = pipeline["lake"]
    before = lake.get(arrivals_key("mbta", D)).data  # type: ignore[union-attr]
    again = compact_day(MBTA, lake, pipeline["catalog"], D, tmp_path / "again")
    assert again.arrivals == pipeline["compacted"].arrivals
    con = duckdb.connect()
    a = con.execute(f"SELECT count(*) FROM '{lake.local_path(arrivals_key('mbta', D))}'").fetchone()[0]
    b_path = tmp_path / "before.parquet"
    b_path.write_bytes(before)
    b = con.execute(f"SELECT count(*) FROM '{b_path}'").fetchone()[0]
    assert a == b
    assert lake.get(trips_key("mbta", D)) is not None


def test_quality_gate_fails_on_partial_day(pipeline: dict) -> None:
    report = pipeline["report"]
    assert report.passed is False  # 12 minutes of data cannot cover a service day
    assert report.checks["coverage"]["ok"] is False
    assert pipeline["lake"].get(f"reports/quality/agency=mbta/service_date={SAMPLE_DATE}.json") is not None


def test_published_documents_match_contract(pipeline: dict) -> None:
    site = pipeline["site"]
    manifest = _json(site, "data/v1/manifest.json")
    assert manifest["schema_version"] == 1 and manifest["build_id"] == "B1"
    agency = manifest["agencies"][0]
    assert set(agency) >= {
        "id",
        "name",
        "timezone",
        "live_api",
        "window",
        "on_time_definition_s",
        "histogram_edges_s",
        "min_samples",
        "paths",
    }
    paths = agency["paths"]
    stops = _json(site, paths["stops"].lstrip("/"))
    assert stops["stops"] and set(stops["stops"][0]) == {"id", "name", "lat", "lon", "parent", "routes"}
    routes = _json(site, paths["routes"].lstrip("/"))
    ids = {r["id"] for r in routes["routes"]}
    assert {"1", "Red"} <= ids
    detail = _json(site, paths["route_template"].replace("{route_id}", "1").lstrip("/"))
    assert detail["route"]["id"] == "1" and detail["directions"]
    cell = detail["directions"][0]["stops"][0]["cells"][0]
    assert set(cell) == {
        "day",
        "hour",
        "n",
        "p50_s",
        "p90_s",
        "on_time_pct",
        "early_pct",
        "canceled",
        "skipped",
        "sched_headway_s",
        "ewt_s",
        "hist",
    }
    assert len(cell["hist"]) == len(agency["histogram_edges_s"]) + 1
    coverage = _json(site, paths["coverage"].lstrip("/"))
    assert coverage["days"][0]["service_date"] == SAMPLE_DATE


def test_cells_with_too_few_samples_hide_statistics(pipeline: dict) -> None:
    detail = _json(pipeline["site"], "data/v1/builds/B1/mbta/routes/1.json")
    for d in detail["directions"]:
        for s in d["stops"]:
            for c in s["cells"]:
                if c["n"] < MIN_SAMPLES:
                    assert c["p50_s"] is None and c["on_time_pct"] is None
                assert sum(c["hist"]) == c["n"]


def test_sql_metrics_match_python_reference(pipeline: dict) -> None:
    """Parity: the DuckDB rollup and stopwatch.core.metrics agree for the busiest stop."""
    path = pipeline["lake"].local_path(arrivals_key("mbta", D))
    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT route_id, direction_id, stop_id, list(delay_s) FROM '{path}'
        WHERE stop_status = 'served' AND delay_valid AND confidence IN ('high', 'medium')
          AND trip_status = 'scheduled' AND sched_s IS NOT NULL
        GROUP BY ALL ORDER BY len(list(delay_s)) DESC LIMIT 1""").fetchone()
    route_id, direction_id, stop_id, delays = rows
    detail = _json(pipeline["site"], f"data/v1/builds/B1/mbta/routes/{route_id}.json")
    stop = next(
        s
        for d in detail["directions"]
        if d["direction_id"] == direction_id
        for s in d["stops"]
        if s["stop_id"] == stop_id
    )
    assert stop["summary"]["n"] == len(delays)
    if len(delays) >= MIN_SAMPLES:
        assert stop["summary"]["p50_s"] == round(percentile(delays, 0.5))  # type: ignore[arg-type]
        assert stop["summary"]["p90_s"] == round(percentile(delays, 0.9))  # type: ignore[arg-type]
    assert sum(sum(c["hist"]) for c in stop["cells"]) == sum(histogram(delays))


def test_rollback_and_retention(pipeline: dict) -> None:
    site = pipeline["site"]
    build = pipeline["build"]
    pub.publish(site, "B2", build.files, pub.build_manifest("B2", "2026-10-20T08:15:00Z", [build.manifest]))
    assert _json(site, "data/v1/manifest.json")["build_id"] == "B2"
    pub.rollback(site, "B1")
    assert _json(site, "data/v1/manifest.json")["build_id"] == "B1"
    with pytest.raises(SystemExit):
        pub.rollback(site, "nope")
    # Retention keeps the newest N builds *and* the live one: rolling back to B1 protects it.
    assert pub.prune(site, keep=1, protect="B1") == []
    assert pub.list_builds(site) == ["B1", "B2"]
    pub.rollback(site, "B2")
    assert pub.prune(site, keep=1, protect="B2") == ["B1"]
    assert pub.list_builds(site) == ["B2"]
