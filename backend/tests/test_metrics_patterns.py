import pytest

from backend.ingest import Ingestor
from backend.metrics import calculate_window, facts_for_snapshot, player_statistics, snapshot
from backend.models import Baseline, Coverage, PERIOD_MS, TeamMetrics, Window
from backend.patterns import PatternEngine, conditions_for
from .conftest import event, point


def records_at(match, fixture, cutoff, period=1):
    ingestion = Ingestor(match)
    for e in fixture:
        if e.available_at_ms <= cutoff and e.payload.period <= period:
            ingestion.apply(e)
    return ingestion.records


def snapshot_at(fixture, t, period=1):
    match, events = fixture
    records = records_at(match, events, t, period)
    return snapshot(match, records, "test", 1, 1, t, period, max(r.delivery_seq for r in records.values()))


def test_owned_duration_not_event_frequency_and_left_state(fixture):
    match, _ = fixture
    events = [event(1, 0, "PERIOD_START"), event(2, 0, "POSSESSION", "harbor", {"start": point(40)}),
              event(3, 150_000, "POSSESSION", "vale", {"start": point(40)}, possession="pos_2"),
              event(4, 180_000, "STOPPAGE", detail={"reason": "ball_out"})]
    records = {e.event_id: e for e in events}
    result = calculate_window(records, ["harbor", "vale"], 1, 60_000, 240_000)
    assert result.coverage.owned_in_play_ms == {"harbor": 90_000, "vale": 30_000}
    assert result.coverage.stoppage_ms == 60_000
    assert result.coverage.unknown_state_ms == 0
    assert result.coverage.eligible
    assert result.metrics["harbor"].possession_share == 75
    snap = snapshot(match, records, "test", 1, 1, 240_000, 1, 4)
    fact = facts_for_snapshot(match, records, snap, [("harbor", "possession_share")])[0]
    assert set(fact.source_event_refs) == {"test_2@1", "test_3@1", "test_4@1"}
    assert fact.source_event_refs[0] == "test_2@1"  # left-boundary ownership is essential


def test_null_denominators_warming_up_unknown_and_long_stoppage():
    records = {"a": event(1, 0, "PERIOD_START")}
    empty = calculate_window(records, ["harbor", "vale"], 1, 0, 180_000)
    assert empty.metrics["harbor"].possession_share is None
    assert empty.metrics["harbor"].pass_accuracy is None
    assert empty.coverage.unknown_state_ms == 180_000 and not empty.coverage.eligible
    records["b"] = event(2, 0, "POSSESSION", "harbor", {"start": point(40)})
    warming = calculate_window(records, ["harbor", "vale"], 1, 0, 179_999)
    assert warming.coverage.status == "warming_up"
    records["c"] = event(3, 60_000, "STOPPAGE", detail={"reason": "ball_out"})
    stopped = calculate_window(records, ["harbor", "vale"], 1, 0, 180_000)
    assert stopped.coverage.known_in_play_ms == 60_000
    assert not stopped.coverage.eligible


def test_windows_exclude_left_include_right_and_entry_thresholds():
    rows = [event(1, 0, "PERIOD_START"), event(2, 0, "POSSESSION", "harbor", {"start": point(40)}),
        event(3, 60_000, "SHOT", "harbor", {"position": point(85), "outcome": "saved"}),
        event(4, 240_000, "SHOT", "harbor", {"position": point(85), "outcome": "goal"})]
    for seq, t, x1, x2, y, complete in [(5, 80_000, 66.66, 66.67, 50, True), (6, 90_000, 66.67, 70, 50, True),
        (7, 100_000, 60, 83, 20, False), (8, 110_000, 60, 83, 20, True), (9, 120_000, 83, 90, 80, True),
        (10, 130_000, 85, 88, 19.99, True)]:
        rows.append(event(seq, t, "PASS", "harbor", {"recipient_id": "harbor_09", "completed": complete,
            "start": point(x1), "end": point(x2, y)}))
    result = calculate_window({e.event_id: e for e in rows}, ["harbor", "vale"], 1, 60_000, 240_000)
    assert result.metrics["harbor"].shots == 1
    assert result.metrics["harbor"].on_target == 1
    assert result.metrics["harbor"].goals == 1
    assert result.metrics["harbor"].final_third_entries == 2
    assert result.metrics["harbor"].box_entries == 1
    assert result.metrics["harbor"].pass_accuracy == 100 * 5 / 6


def test_turnovers_exclude_restarts_and_tackle_does_not_switch_owner():
    rows = [event(1, 0, "PERIOD_START"), event(2, 0, "POSSESSION", "harbor", {"start": point(40)}),
        event(3, 30_000, "TACKLE", "vale", {"position": point(50), "successful": True}),
        event(4, 60_000, "POSSESSION", "vale", {"start": point(40)}, possession="pos_2"),
        event(5, 80_000, "STOPPAGE", detail={"reason": "ball_out"}),
        event(6, 100_000, "POSSESSION", "harbor", {"start": point(40)}, possession="pos_3")]
    result = calculate_window({e.event_id: e for e in rows}, ["harbor", "vale"], 1, 0, 180_000)
    assert result.live_turnovers == 1
    assert result.coverage.owned_in_play_ms == {"harbor": 140_000, "vale": 20_000}


def test_period_window_and_baseline_do_not_cross_halftime(fixture):
    snap = snapshot_at(fixture, PERIOD_MS + 180_000, 2)
    assert snap.window.start_ms == PERIOD_MS
    assert snap.baseline is None
    assert snap.coverage.eligible
    assert all("@" in ref for ref in snap.evidence_refs)
    assert snapshot_at(fixture, 179_999).coverage.status == "warming_up"
    assert snapshot_at(fixture, 360_000).baseline is not None


@pytest.mark.parametrize("time_ms,pattern,subject", [(360_000, "sustained_pressure", "harbor"),
    (1_020_000, "sterile_possession", "harbor"), (1_440_000, "end_to_end", None),
    (3_300_000, "sustained_pressure", "vale"), (4_020_000, "sterile_possession", "harbor"), (4_620_000, "end_to_end", None)])
def test_assertion_manifest_actual_fixture_windows_and_debounce(fixture, time_ms, pattern, subject):
    # This private server-side assertion manifest is never an agent or API input.
    snap = snapshot_at(fixture, time_ms, 1 if time_ms <= PERIOD_MS else 2)
    assert snap.coverage.eligible
    assert all(c.passed for c in conditions_for(snap, pattern, subject))
    engine = PatternEngine()
    assert engine.evaluate(snap) == []
    later = snapshot_at(fixture, time_ms + 5000, snap.period)
    emitted = engine.evaluate(later)
    assert len(emitted) == 1 and emitted[0].pattern == pattern
    assert engine.evaluate(later) == []  # episode deduplicated


def synthetic_snapshot(fixture, pattern="sustained_pressure"):
    snap = snapshot_at(fixture, 360_000)
    snap.team_metrics["harbor"] = TeamMetrics(shots=3, on_target=1, completed_passes=15, attempted_passes=20,
        pass_accuracy=75, final_third_entries=5, box_entries=1, possession_share=60, goals=0)
    snap.team_metrics["vale"] = TeamMetrics(shots=1, on_target=0, completed_passes=3, attempted_passes=5,
        pass_accuracy=60, final_third_entries=0, box_entries=0, possession_share=40, goals=0)
    return snap


def test_exact_pressure_threshold_and_near_misses(fixture):
    snap = synthetic_snapshot(fixture)
    assert all(c.passed for c in conditions_for(snap, "sustained_pressure", "harbor"))
    for metric, value in (("possession_share", 59.999), ("shots", 2), ("final_third_entries", 4)):
        changed = snap.model_copy(deep=True)
        setattr(changed.team_metrics["harbor"], metric, value)
        assert not all(c.passed for c in conditions_for(changed, "sustained_pressure", "harbor"))
    snap.team_metrics["vale"].shots = 2
    assert not all(c.passed for c in conditions_for(snap, "sustained_pressure", "harbor"))


def test_exact_sterile_end_to_end_limits_and_gate(fixture):
    snap = synthetic_snapshot(fixture)
    snap.team_metrics["harbor"].possession_share = 65
    snap.team_metrics["harbor"].shots = 1
    assert all(c.passed for c in conditions_for(snap, "sterile_possession", "harbor"))
    snap.team_metrics["harbor"].box_entries = 2
    assert not all(c.passed for c in conditions_for(snap, "sterile_possession", "harbor"))
    snap.team_metrics["harbor"].possession_share = 65
    snap.team_metrics["vale"].possession_share = 35
    snap.team_metrics["harbor"].shots = snap.team_metrics["vale"].shots = 2
    snap.live_turnovers = 6
    assert all(c.passed for c in conditions_for(snap, "end_to_end", None))
    snap.live_turnovers = 5
    assert not all(c.passed for c in conditions_for(snap, "end_to_end", None))
    snap.live_turnovers = 6
    snap.coverage.eligible = False
    engine = PatternEngine()
    assert engine.evaluate(snap) == [] and engine.evaluate(snap) == []


def test_debounce_close_after_two_failures_and_reset_period(fixture):
    snap = synthetic_snapshot(fixture)
    engine = PatternEngine()
    assert engine.evaluate(snap) == []
    assert len(engine.evaluate(snap)) == 1
    snap.team_metrics["harbor"].shots = 2
    engine.evaluate(snap)
    assert engine.states["sustained_pressure:harbor"]["active"]
    engine.evaluate(snap)
    assert not engine.states["sustained_pressure:harbor"]["active"]
    snap.team_metrics["harbor"].shots = 3
    engine.evaluate(snap)
    snap.period = 2
    assert engine.evaluate(snap) == []
    assert len(engine.evaluate(snap)) == 1


def test_neutral_windows_and_invalid_state_fail_closed(fixture):
    neutral = snapshot_at(fixture, 180_000)
    engine = PatternEngine()
    assert engine.evaluate(neutral) == [] and engine.evaluate(neutral) == []
    broken = {"pass": event(1, 60_000, "PASS", "harbor", {"recipient_id": "harbor_09", "completed": True,
              "start": point(40), "end": point(60)})}
    result = calculate_window(broken, ["harbor", "vale"], 1, 0, 180_000)
    assert not result.coverage.state_valid and not result.coverage.eligible


def test_observed_goal_does_not_automatically_create_pattern(fixture):
    snap = snapshot_at(fixture, 660_000)
    assert snap.coverage.eligible
    engine = PatternEngine()
    assert engine.evaluate(snap) == [] and engine.evaluate(snap) == []


def test_player_counts_use_actor_and_completed_recipient(fixture):
    match, _ = fixture
    rows = [event(1, 0, "PERIOD_START"), event(2, 0, "POSSESSION", "harbor", {"start": point(40)}),
        event(3, 10_000, "PASS", "harbor", {"recipient_id": "harbor_09", "completed": True, "start": point(40), "end": point(60)}),
        event(4, 20_000, "PASS", "harbor", {"recipient_id": "harbor_09", "completed": False, "start": point(40), "end": point(60)})]
    stats = player_statistics(match, {r.event_id: r for r in rows})
    assert stats["harbor_08"].passes_attempted == 2 and stats["harbor_08"].passes_completed == 1
    assert stats["harbor_09"].passes_received == 1 and stats["harbor_09"].involvement == 1
    assert stats["vale_08"].involvement == 0
