"""Live analytics: field tilt, xG, defensive line height, workload and possession value."""
import inspect
import json
from pathlib import Path

import pytest

import backend.analytics as analytics_module
from backend.analytics import AnalyticsEngine
from backend.chances import location_value, xg
from backend.metrics import calculate_window
from backend.models import PERIOD_MS, MatchAnalytics
from backend.tactical_profiles import position
from backend.tactics import TacticalEngine

from .test_api import CAP, client, control, create, headers  # noqa: F401
from .test_tactics import records_until

SAMPLE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "fixtures" / "analytics-20min.json"


@pytest.fixture(scope="module")
def engine(fixture):
    match, events = fixture
    return AnalyticsEngine(match, events, TacticalEngine(match, events))


@pytest.fixture(scope="module")
def full(engine, fixture):
    return engine.report(records_until(fixture, 2 * PERIOD_MS), 2 * PERIOD_MS)


def test_roster_carries_specific_positions(fixture):
    match, _ = fixture
    roles = {p.player_id: p.role for p in match.roster}
    assert roles["harbor_09"] == "ST" and roles["harbor_06"] == "CDM" and roles["harbor_07"] == "CM" and roles["vale_08"] == "CAM"
    assert all(p.role == position(p.player_id) for p in match.roster)


def test_xg_reference_values_and_modifiers():
    assert .25 <= xg(89.5, 50) <= .3          # penalty spot, open play
    assert .55 <= xg(94.8, 50) <= .65         # six-yard line
    assert xg(71.4, 50) < .03                 # ~30 m
    assert xg(89.5, 50, body_part="head") < xg(89.5, 50)
    assert xg(89.5, 50, "through_ball") > xg(89.5, 50, "pass") > xg(89.5, 50, "cross")
    assert xg(89.5, 20) < xg(89.5, 50)        # tighter angle
    assert location_value(95, 50) > location_value(83, 50) > location_value(60, 50) > 0


def test_chances_and_shots_are_consistent(full):
    shots, chances = full["shots"], full["chances"]
    for team, row in chances.items():
        own = [s for s in shots if s.team_id == team]
        assert row.shots == len(own) and row.xg == pytest.approx(sum(s.xg for s in own), abs=.011)
        assert row.xg_against == chances["vale" if team == "harbor" else "harbor"].xg
        assert row.major_chances == sum(s.chance == "major" for s in own)
    assert all((s.chance == "major") == (s.xg >= .3) for s in shots)
    assert {s.body_part for s in shots} <= {"right_foot", "left_foot", "head"}
    assert any(s.body_part == "left_foot" for s in shots)


def test_field_tilt_recovers_the_planted_pressure_phases(full):
    match_window = full["territory"].match
    assert sum(match_window.field_tilt.values()) == pytest.approx(100)
    first, *_rest, = full["territory"].intervals
    assert first.field_tilt["harbor"] >= 80        # Harbor's pressure, minutes 3-7
    after_break = full["territory"].intervals[3]   # 45-60: Vale's pressure, minutes 52-56
    assert after_break.field_tilt["vale"] >= 80
    assert len(full["territory"].intervals) == 6


def test_defensive_line_recovers_planted_heights(full):
    harbor, vale = full["defensive_line"]["harbor"], full["defensive_line"]["vale"]
    assert harbor.settled.back_four_m > vale.settled.back_four_m + 4
    assert harbor.block in ("mid", "high") and vale.block == "low"
    for line in (harbor, vale):
        assert line.match.deepest_m <= line.match.back_four_m <= line.match.centroid_m
        assert line.after_loss.back_four_m > line.settled.back_four_m   # caught high when the ball is lost
        assert line.shots_faced > 0 and line.before_shots.back_four_m < line.settled.back_four_m
        assert 25 <= line.match.width_m <= 45 and 5 <= line.match.gap_m <= 25


def test_workload_is_physical_and_recovers_planted_work_rates(full):
    rows = {w.player_id: w for w in full["workload"]}
    for pid, w in rows.items():
        assert w.top_speed_mps <= 9.6 and w.sprint_m <= w.hsr_m <= w.distance_m
        if pid.endswith("_01"):
            assert w.distance_m < 4_000
        else:
            assert 7_500 <= w.distance_m <= 14_000
    defenders = ["harbor_02", "harbor_03", "harbor_04", "harbor_05"]
    assert max(defenders, key=lambda p: rows[p].distance_m) == "harbor_02"
    assert min(["vale_09", "vale_10", "vale_11"], key=lambda p: rows[p].distance_m) == "vale_11"
    harbor = [w for w in full["workload"] if w.team_id == "harbor"]
    assert max(harbor, key=lambda w: w.hsr_m).player_id == "harbor_10"
    assert [w.player_id for w in full["workload"] if w.flag] == ["vale_08"]


def test_possession_value_is_value_after_minus_before(engine, fixture):
    report = engine.report(records_until(fixture, 2 * PERIOD_MS), 2 * PERIOD_MS)
    actions = report["top_actions"]
    assert actions and all(a.pv == pytest.approx(a.value_after - a.value_before, abs=1e-3) for a in actions)
    assert actions == sorted(actions, key=lambda a: -a.pv)
    for team, value in report["team_value"].items():
        assert value.pv == pytest.approx(sum(value.by_action.values()), abs=.01)
        assert value.pv == pytest.approx(sum(p.pv for p in report["player_value"] if p.team_id == team), abs=.01)
    assert report["team_value"]["harbor"].by_action["dispossessed"] < 0


def test_report_uses_only_the_observed_prefix(engine, fixture):
    cutoff = 20 * 60_000
    early = engine.report(records_until(fixture, cutoff), cutoff)
    late = engine.report(records_until(fixture, 2 * PERIOD_MS), 2 * PERIOD_MS)
    assert all(s.time_ms <= cutoff for s in early["shots"]) and all(a.time_ms <= cutoff for a in early["top_actions"])
    assert early["territory"].match.end_ms == cutoff and len(early["territory"].intervals) == 2
    by_id = {w.player_id: w for w in late["workload"]}
    assert all(w.distance_m <= by_id[w.player_id].distance_m and w.minutes == 20 for w in early["workload"])
    assert all(i.end_ms <= cutoff for line in early["defensive_line"].values() for i in line.intervals)
    empty = engine.report({}, 0)
    assert empty["shots"] == [] and all(w.distance_m == 0 for w in empty["workload"])


def test_analytics_never_reads_the_generator_tendencies():
    source = inspect.getsource(analytics_module)
    assert "tendencies(" not in source and "_TENDENCIES" not in source and "generate_plans" not in source


def test_window_metrics_add_duels_xg_and_field_tilt(fixture):
    match, events = fixture
    records = records_until(fixture, 600_000)
    window = calculate_window(records, ["harbor", "vale"], 1, 300_000, 600_000)
    harbor, vale = window.metrics["harbor"], window.metrics["vale"]
    assert harbor.duels == vale.duels and harbor.duels_won + vale.duels_won == harbor.duels > 0
    assert harbor.field_tilt + vale.field_tilt == pytest.approx(100) and harbor.field_tilt > 50
    assert harbor.xg > 0 and harbor.on_target <= harbor.shots


def test_analytics_endpoint_is_capability_scoped_and_advances(client):  # noqa: F811
    app, _replay, clock = client
    sid = create(app).json()["session_id"]
    assert app.get(f"/api/sessions/{sid}/analytics", headers=headers("w" * 64)).status_code == 404
    first = app.get(f"/api/sessions/{sid}/analytics", headers=headers()).json()
    assert first["engine_version"] == "analytics_v2" and first["shots"] == []
    control(app, sid, "play")
    clock.advance(20)
    later = app.get(f"/api/sessions/{sid}/analytics", headers=headers()).json()
    assert later["playhead_ms"] == 1_200_000 and later["shots"] and later["workload"][0]["distance_m"] > 0
    text = json.dumps(later)
    for hidden in ("line_base", "transition_mps", "cruise_mps", "fade", "lead_drop", "hard_save_rate"):
        assert hidden not in text
    assert CAP not in text


def test_frontend_contract_sample_matches_the_backend_report(engine, fixture):
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    cutoff = sample["playhead_ms"]
    report = MatchAnalytics(session_id="sample", generation=1, data_epoch=1, playhead_ms=cutoff, next_cursor="c",
                            **engine.report(records_until(fixture, cutoff), cutoff))
    assert report.model_dump(mode="json") == sample
