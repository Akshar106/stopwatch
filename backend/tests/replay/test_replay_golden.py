"""Golden test: replaying recorded MBTA snapshots must keep producing exactly the same events.

If inference changes intentionally, regenerate with:
    uv run python -m stopwatch.ingest.replay tests/fixtures/rt_snapshots/sample --jsonl \
        > tests/replay/golden_events.jsonl
and review the diff in the PR.
"""

from __future__ import annotations

import json
from pathlib import Path

from stopwatch.ingest.replay import replay_directory
from stopwatch.ingest.tick import event_to_dict
from tests.pipeline_helpers import SAMPLE_RT

GOLDEN = Path(__file__).with_name("golden_events.jsonl")


def test_replay_matches_golden() -> None:
    events = [json.dumps(event_to_dict(e), sort_keys=True) for e in replay_directory(SAMPLE_RT)]
    expected = GOLDEN.read_text().splitlines()
    assert len(events) == len(expected)
    assert events == expected


def test_replay_events_are_plausible() -> None:
    events = replay_directory(SAMPLE_RT)
    arrivals = [e for e in events if e.kind.value == "arrival"]
    assert len(arrivals) > 100
    assert {e.route_id for e in arrivals} >= {"1", "Red"}
    high = sum(1 for e in arrivals if e.confidence and e.confidence.value == "high")
    assert high / len(arrivals) > 0.8
    assert all(e.est_arrival <= e.observed_at for e in arrivals)  # type: ignore[operator]
