"""Local stand-in for EventBridge Scheduler (docker compose `worker` service).

    python -m stopwatch.jobs.local_scheduler --mode live      # ingest the real feed every minute
    python -m stopwatch.jobs.local_scheduler --mode replay    # loop recorded fixtures (offline demo)

On start it imports the schedule if missing, then ticks every 60 s and publishes a "today so far" build
every 15 minutes so the local web app has data to show (cloud rollups run once a day for yesterday).
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stopwatch.catalog.schedule import ScheduleNotImportedError, current_key
from stopwatch.jobs import daily_rollup, ingest_tick, schedule_import
from stopwatch.platform.agencies import get_agency
from stopwatch.platform.blobstore import open_blobstore
from stopwatch.platform.config import get_settings
from stopwatch.platform.observability import get_logger

log = get_logger("local_scheduler")
FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "rt_snapshots" / "sample"
_stop = False


def _handle_signal(*_: object) -> None:
    global _stop  # noqa: PLW0603
    _stop = True


def _ensure_schedule() -> None:
    settings = get_settings()
    lake = open_blobstore(settings.lake_url)
    if any(lake.get(current_key(a)) is None for a in settings.agency_ids):
        log.info("no schedule imported yet; importing (takes ~10-30 s)")
        schedule_import.run()


def _replay_loop(interval: float) -> None:
    from stopwatch.ingest.replay import replay_into_lake

    settings = get_settings()
    agency = get_agency(settings.agency_ids[0])
    lake, site = open_blobstore(settings.lake_url), open_blobstore(settings.site_url)
    while not _stop:
        lake.delete(f"state/{agency.id}/latest.json.gz")
        results = replay_into_lake(FIXTURES, agency, lake, site)
        log.info("replayed fixtures", ticks=len(results))
        _rollup_today()
        for _ in range(int(interval)):
            if _stop:
                return
            time.sleep(1)


def _rollup_today() -> None:
    settings = get_settings()
    tz = get_agency(settings.agency_ids[0]).timezone
    today = datetime.now(ZoneInfo(tz)).date()
    try:
        summary = daily_rollup.run(today, force=True)
        log.info("published local build", build_id=summary["build_id"])
    except ScheduleNotImportedError:
        log.warning("schedule not imported; skipping rollup")
    except Exception as exc:  # noqa: BLE001 - keep the dev loop alive
        log.exception("local rollup failed", error_type=type(exc).__name__)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["live", "replay"], default="live")
    ap.add_argument("--rollup-every", type=int, default=15, help="minutes between local 'today' builds")
    args = ap.parse_args()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    _ensure_schedule()
    if args.mode == "replay":
        _replay_loop(interval=args.rollup_every * 60)
        return 0
    minute = 0
    while not _stop:
        started = time.monotonic()
        try:
            ingest_tick.run()
        except Exception as exc:  # noqa: BLE001 - one bad tick must not kill the worker
            log.exception("tick failed", error_type=type(exc).__name__)
        if minute % args.rollup_every == args.rollup_every - 1:
            _rollup_today()
        minute += 1
        while not _stop and time.monotonic() - started < 60:
            time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
