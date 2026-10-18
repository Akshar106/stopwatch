"""Data-quality gate: a build is published only if the day's data looks sane (docs/05 §10.2, RB-3)."""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from stopwatch.platform.blobstore import BlobStore

from .compact import CompactResult

MIN_COVERAGE_PCT = 80.0
MAX_ROW_DELTA = 0.40  # vs median of the previous 7 days
MAX_INVALID_DELAY_PCT = 5.0
MAX_UNMATCHED_PCT = 10.0


def report_key(agency_id: str, d: date) -> str:
    return f"reports/quality/agency={agency_id}/service_date={d.isoformat()}.json"


@dataclass
class QualityReport:
    agency_id: str
    service_date: str
    passed: bool
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)


def _history(lake: BlobStore, agency_id: str, d: date, days: int = 7) -> list[dict[str, Any]]:
    out = []
    for i in range(1, days + 1):
        blob = lake.get(report_key(agency_id, d - timedelta(days=i)))
        if blob:
            out.append(json.loads(blob.data))
    return out


def evaluate(res: CompactResult, lake: BlobStore) -> QualityReport:
    stats = asdict(res)
    stats["service_date"] = res.service_date.isoformat()
    checks: dict[str, dict[str, Any]] = {}

    checks["coverage"] = {"value": res.coverage_pct, "min": MIN_COVERAGE_PCT,
                          "ok": res.coverage_pct is not None and res.coverage_pct >= MIN_COVERAGE_PCT}
    invalid_pct = 100.0 * res.delay_invalid / res.arrivals if res.arrivals else 0.0
    checks["delay_sanity"] = {"value": round(invalid_pct, 2), "max": MAX_INVALID_DELAY_PCT,
                              "ok": invalid_pct <= MAX_INVALID_DELAY_PCT}
    unmatched_pct = 100.0 * res.unmatched_arrivals / res.arrivals if res.arrivals else 0.0
    checks["schedule_match"] = {"value": round(unmatched_pct, 2), "max": MAX_UNMATCHED_PCT,
                                "ok": unmatched_pct <= MAX_UNMATCHED_PCT}

    history = [h["stats"]["arrivals"] for h in _history(lake, res.agency_id, res.service_date)
               if h.get("stats", {}).get("arrivals")]
    if len(history) >= 3:
        median = statistics.median(history)
        delta = abs(res.arrivals - median) / median if median else 0.0
        checks["row_delta"] = {"value": round(delta, 3), "max": MAX_ROW_DELTA, "median_7d": median,
                               "ok": delta <= MAX_ROW_DELTA}
    else:
        checks["row_delta"] = {"value": None, "ok": True, "note": "fewer than 3 days of history"}

    report = QualityReport(agency_id=res.agency_id, service_date=res.service_date.isoformat(),
                           passed=all(c["ok"] for c in checks.values()), checks=checks, stats=stats)
    lake.put(report_key(res.agency_id, res.service_date), json.dumps(asdict(report), indent=2, default=str).encode(),
             content_type="application/json")
    return report
