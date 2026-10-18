"""Access to imported schedule versions in the lake (Parquet) and picking the version valid for a date."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from stopwatch.platform.blobstore import BlobStore

TABLES = ("routes", "trips", "stop_times", "stops", "calendar", "calendar_dates")


def current_key(agency_id: str) -> str:
    return f"schedule/agency={agency_id}/current.json"


def table_key(agency_id: str, version: str, table: str) -> str:
    return f"schedule/agency={agency_id}/version={version}/{table}.parquet"


def meta_key(agency_id: str, version: str) -> str:
    return f"schedule/agency={agency_id}/version={version}/meta.json"


@dataclass(frozen=True)
class VersionInfo:
    version: str
    start_date: date
    end_date: date
    imported_at: str


class ScheduleNotImportedError(RuntimeError):
    pass


class ScheduleCatalog:
    def __init__(self, lake: BlobStore, agency_id: str) -> None:
        self.lake = lake
        self.agency_id = agency_id
        blob = lake.get(current_key(agency_id))
        if blob is None:
            raise ScheduleNotImportedError(f"no schedule imported for {agency_id}; run schedule-import")
        self.current: dict[str, Any] = json.loads(blob.data)
        self.versions = [
            VersionInfo(v["version"], date.fromisoformat(v["start_date"]), date.fromisoformat(v["end_date"]),
                        v["imported_at"])
            for v in self.current.get("versions", [])
        ]

    def version_for(self, service_date: date) -> str:
        """Most recently imported version whose validity covers the date; otherwise the current version."""
        covering = [v for v in self.versions if v.start_date <= service_date <= v.end_date]
        if covering:
            return max(covering, key=lambda v: v.imported_at).version
        return str(self.current["version"])

    def table_path(self, version: str, table: str, workdir: Path) -> Path:
        """Local path to a table's Parquet file (downloaded into ``workdir`` for remote stores)."""
        key = table_key(self.agency_id, version, table)
        local = self.lake.local_path(key)
        if local is not None and local.exists():
            return local
        dest = workdir / "schedule" / self.agency_id / version / f"{table}.parquet"
        if not dest.exists():
            self.lake.download_to(key, dest)
        return dest
