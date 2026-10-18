"""DuckDB connection settings tuned for Lambda (/tmp spill, bounded memory) and laptops alike."""

from __future__ import annotations

import os
from pathlib import Path


def connect(workdir: Path, *, memory_limit: str | None = None):  # type: ignore[no-untyped-def]
    import duckdb  # imported lazily: only the jobs package ships DuckDB

    workdir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(database=":memory:")
    spill = workdir / "duckdb-spill"
    spill.mkdir(exist_ok=True)
    con.execute(f"SET temp_directory = '{spill.as_posix()}'")
    limit = (
        memory_limit
        or os.environ.get("DUCKDB_MEMORY_LIMIT")
        or ("1200MB" if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else "4GB")
    )
    con.execute(f"SET memory_limit = '{limit}'")
    con.execute("SET preserve_insertion_order = false")
    # GTFS time "HH:MM:SS" (hours may exceed 23) -> seconds since noon-minus-12h.
    con.execute(
        "CREATE MACRO gtfs_secs(t) AS CASE WHEN t IS NULL OR t = '' THEN NULL ELSE "
        "CAST(split_part(t, ':', 1) AS INTEGER) * 3600 + CAST(split_part(t, ':', 2) AS INTEGER) * 60 "
        "+ CAST(split_part(t, ':', 3) AS INTEGER) END"
    )
    return con
