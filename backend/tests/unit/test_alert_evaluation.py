from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from stopwatch.alerts.evaluate import Rule, find_candidates, rule_is_live
from stopwatch.alerts.vapid import generate
from stopwatch.core.inference import Snapshot, StopPrediction, TripKey, TripState, TripStatus
from stopwatch.ingest.state import IngestState

TZ = "America/New_York"
# Monday 2026-10-19 07:50 local
NOW = int(datetime(2026, 10, 19, 7, 50, tzinfo=ZoneInfo(TZ)).timestamp())
RULE = Rule("r1", "1", 0, "64", days_mask=0b0011111, window_start="07:30", window_end="08:30",
            threshold_min=10, notify_cancellations=True)


def snapshot(pred_offset_s: int | None, status: TripStatus = TripStatus.SCHEDULED) -> Snapshot:
    key = TripKey("trip-805", "20261019")
    stops = {} if pred_offset_s is None else {
        12: StopPrediction(12, "64", NOW + pred_offset_s)}
    return Snapshot(feed_ts=NOW, trips={key: TripState(key, "1", 0, "v1", status, stops)})


# trip-805 is scheduled at 08:05 local at stop 64 -> GTFS seconds 8*3600+5*60
SCHED = {("trip-805", "64"): 8 * 3600 + 5 * 60}


def test_rule_live_only_on_selected_days_and_near_window() -> None:
    assert rule_is_live(RULE, NOW, TZ)
    saturday = int(datetime(2026, 10, 24, 7, 50, tzinfo=ZoneInfo(TZ)).timestamp())
    assert not rule_is_live(RULE, saturday, TZ)
    late_night = int(datetime(2026, 10, 19, 22, 0, tzinfo=ZoneInfo(TZ)).timestamp())
    assert not rule_is_live(RULE, late_night, TZ)


def test_delay_over_threshold_alerts() -> None:
    # predicted 08:17 vs scheduled 08:05 -> 12 min late
    [c] = find_candidates([RULE], snapshot(27 * 60), SCHED, NOW, TZ)
    assert c.kind == "delay" and c.delay_s == 12 * 60
    assert c.dedupe_key == "r1:2026-10-19:trip-805:delay"


def test_delay_under_threshold_is_quiet() -> None:
    assert find_candidates([RULE], snapshot(20 * 60), SCHED, NOW, TZ) == []  # 5 min late


def test_cancellation_alerts_when_enabled() -> None:
    [c] = find_candidates([RULE], snapshot(None, TripStatus.CANCELED), SCHED, NOW, TZ)
    assert c.kind == "canceled"
    quiet = Rule(**{**RULE.__dict__, "notify_cancellations": False})
    assert find_candidates([quiet], snapshot(None, TripStatus.CANCELED), SCHED, NOW, TZ) == []


def test_trips_outside_the_window_or_other_routes_are_ignored() -> None:
    assert find_candidates([RULE], snapshot(27 * 60), {("trip-805", "64"): 9 * 3600}, NOW, TZ) == []
    other = Rule(**{**RULE.__dict__, "route_id": "47"})
    assert find_candidates([other], snapshot(27 * 60), SCHED, NOW, TZ) == []


def test_hook_dedupes_across_ticks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import json

    from stopwatch.alerts.evaluate import make_alert_hook
    from stopwatch.platform.agencies import get_agency
    from tests.pipeline_helpers import make_lake

    lake, _ = make_lake(tmp_path)
    lake.put("config/alert_rules/mbta.json", json.dumps({"rules": [RULE.__dict__]}).encode())
    sent: list[dict] = []

    class FixedLookup:
        def for_stops(self, stops, d):  # type: ignore[no-untyped-def]
            return SCHED

    hook = make_alert_hook(get_agency("mbta"), lake, None, invoker=sent.append, lookup=FixedLookup())
    st = IngestState()
    hook(snapshot(27 * 60), st, NOW)
    hook(snapshot(28 * 60), st, NOW + 60)
    assert len(sent) == 1 and len(sent[0]["candidates"]) == 1


def test_vapid_keys_have_expected_shapes() -> None:
    pub, priv = generate()
    assert len(pub) == 87 and len(priv) == 43  # 65-byte point and 32-byte scalar, base64url without padding
