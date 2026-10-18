"""Helpers to stand up a file-backed lake with the trimmed real MBTA schedule fixture."""

from __future__ import annotations

from pathlib import Path

from stopwatch.catalog.schedule import current_key, table_key
from stopwatch.platform.blobstore import BlobStore, open_blobstore

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE_RT = FIXTURES / "rt_snapshots" / "sample"
SAMPLE_SCHEDULE = FIXTURES / "schedule_sample"
SAMPLE_DATE = "2026-10-18"


def make_lake(root: Path) -> tuple[BlobStore, BlobStore]:
    lake = open_blobstore(f"file://{root}/lake")
    site = open_blobstore(f"file://{root}/site")
    for table in ("routes", "trips", "stop_times", "stops", "calendar", "calendar_dates"):
        lake.put(table_key("mbta", "sample", table), (SAMPLE_SCHEDULE / f"{table}.parquet").read_bytes())
    lake.put(current_key("mbta"), (SAMPLE_SCHEDULE / "current.json").read_bytes())
    return lake, site
