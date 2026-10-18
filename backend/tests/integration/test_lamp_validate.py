from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from stopwatch.jobs.lamp_validate import validate
from stopwatch.platform.blobstore import open_blobstore
from stopwatch.platform.http import FetchError
from stopwatch.rollups.compact import arrivals_key

D = date(2026, 10, 18)


def _parquet(tmp: Path, name: str, sql: str) -> bytes:
    p = tmp / name
    duckdb.connect().execute(f"COPY ({sql}) TO '{p}' (FORMAT parquet)")
    return p.read_bytes()


def test_matches_by_vehicle_and_stop_and_reports_errors(tmp_path: Path) -> None:
    lake = open_blobstore(f"file://{tmp_path}/lake")
    site = open_blobstore(f"file://{tmp_path}/site")
    ours = _parquet(
        tmp_path,
        "ours.parquet",
        """
        SELECT * FROM (VALUES
          ('Red', 't1', '70061', 1, 'R-1', 'vp_stopped', to_timestamp(1000), 'served'),
          ('Red', 't1', '70063', 2, 'R-1', 'last_prediction', to_timestamp(1300), 'served'),
          ('Red', 't2', '70061', 1, 'R-2', 'last_prediction', to_timestamp(5000), 'served'),
          ('1',   'b1', '64',    5, 'y1',  'last_prediction', to_timestamp(900),  'served'))
        AS v(route_id, trip_id, stop_id, stop_sequence, vehicle_id, method, est_arrival, stop_status)""",
    )
    lake.put(arrivals_key("mbta", D), ours)
    lamp = _parquet(
        tmp_path,
        "lamp.parquet",
        """
        SELECT * FROM (VALUES
          ('R-1', '70061', 'ADDED-9', 1000::BIGINT),   -- exact (different trip id; matched by vehicle)
          ('R-1', '70063', 'ADDED-9', 1240::BIGINT),   -- we are 60 s late
          ('R-2', '70061', 't2',      9000::BIGINT))   -- too far apart: no match
        AS v(vehicle_id, stop_id, trip_id, stop_timestamp)""",
    )

    def fetch(url: str) -> bytes:
        if D.isoformat() in url:
            return lamp
        raise FetchError("404")

    report = validate(lake, site, D, tmp_path / "work", fetch=fetch, days=2)
    assert report["sample"] == 2
    assert report["median_abs_error_s"] == 30 and report["by_route"]["Red"]["n"] == 2
    assert report["by_method"]["vp_stopped"]["median_abs_error_s"] == 0
    assert site.get("data/v1/validation/mbta.json") is not None


def test_no_lamp_data_yields_empty_report(tmp_path: Path) -> None:
    lake = open_blobstore(f"file://{tmp_path}/lake")
    site = open_blobstore(f"file://{tmp_path}/site")
    report = validate(lake, site, D, tmp_path / "w", fetch=lambda u: (_ for _ in ()).throw(FetchError("x")))
    assert report["sample"] == 0 and report["median_abs_error_s"] is None


@pytest.mark.network
def test_live_lamp_index_reachable() -> None:  # pragma: no cover - manual check
    from stopwatch.platform.http import fetch_bytes

    head = fetch_bytes(
        "https://performancedata.mbta.com/lamp/subway-on-time-performance-v1/index.csv", max_bytes=5_000_000
    ).data[:60]
    assert head.startswith(b"size_bytes,last_modified,service_date,file_url")
