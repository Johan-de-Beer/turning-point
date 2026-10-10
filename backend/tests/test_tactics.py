"""Synthetic tracking and the tactical analysis measured from it."""
import inspect
import json
import math

import pytest

import backend.tactics as tactics_module
from backend.generator import FIXTURE_PATH, generate_fixture, generate_plans
from backend.ingest import Ingestor
from backend.models import PERIOD_MS
from backend.tactical_profiles import expected_swing, foot
from backend.tactics import TacticalEngine, second_last_x
from backend.tracking import FRAME_MS, X_M, Y_M, team_players

from .test_api import CAP, control, create, headers


@pytest.fixture(scope="module")
def engine(fixture):
    match, events = fixture
    return TacticalEngine(match, events)


def records_until(fixture, cutoff):
    match, events = fixture
    ingestor = Ingestor(match)
    for envelope in events:
        if envelope.available_at_ms <= cutoff:
            ingestor.apply(envelope)
    return ingestor.records


@pytest.fixture(scope="module")
def full(engine, fixture):
    return engine.report(records_until(fixture, 2 * PERIOD_MS), 2 * PERIOD_MS)


def test_committed_fixture_matches_the_generator_and_its_tactical_plans():
    match, events = generate_fixture()
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert raw["match"] == match.model_dump(mode="json") and raw["events"] == [e.model_dump(mode="json") for e in events]
    plans = generate_plans()
    ids = {e.event_id: e.payload for e in events}
    assert all(event_id in ids for event_id in plans)
    corners = [ids[i] for i, plan in plans.items() if plan["type"] == "corner"]
    assert corners and all(c.kind == "PASS" and c.detail.start.x == 99.5 for c in corners)
    assert {c.team_id for c in corners} == {"harbor", "vale"}


def test_episode_frames_agree_with_recorded_events_and_stay_physical(engine, fixture):
    _, events = fixture
    payloads = {e.event_id: e.payload for e in events if e.revision == 1}
    prepared = engine.prepared()
    assert {ep.kind for ep in prepared.episodes.values()} == {"attack", "possession", "corner"}
    for ep in prepared.episodes.values():
        event = payloads[ep.anchor_event_id]
        assert all(len(f.players) == 22 for f in ep.frames)
        assert all(0 <= v <= 100 for f in ep.frames for p in [f.ball, *f.players.values()] for v in p)
        assert [f.t for f in ep.frames] == list(range(ep.start_ms, ep.end_ms + 1, FRAME_MS))
        if ep.kind in ("attack", "corner"):
            at_pass = ep.frame_at(event.event_time_ms)
            assert at_pass.ball == (event.detail.start.x, event.detail.start.y)
            assert ep.frames[-1].ball == (event.detail.end.x, event.detail.end.y)
        else:
            assert ep.frames[0].ball == (event.detail.start.x, event.detail.start.y)
        # Off-ball defenders and pressers never move faster than a sprinting player.
        movers = [p for p in team_players(ep.opponent_id)]
        for a, b in zip(ep.frames, ep.frames[1:]):
            for p in movers:
                speed = math.hypot((b.players[p][0] - a.players[p][0]) * X_M, (b.players[p][1] - a.players[p][1]) * Y_M) / .2
                assert speed <= 9.5, (ep.episode_id, p, speed)


def test_analysis_recovers_planted_synthetic_tendencies(full):
    harbor, vale = full["teams"]["harbor"], full["teams"]["vale"]
    # Offside trap: Vale's left-back steps late and that leaves runners onside.
    briar = next(d for d in vale.offside_trap.defenders if d.player_id == "vale_03")
    assert briar.late_steps >= .7 * briar.traps and briar.mean_lag_ms > 300 and briar.runners_played_onside > 0
    assert all(d.late_steps <= .2 * d.traps for d in vale.offside_trap.defenders if d.player_id != "vale_03")
    assert vale.offside_trap.traps > harbor.offside_trap.traps
    opportunity = next(o for o in full["observations"] if o.category == "offside_trap" and o.kind == "opportunity")
    assert opportunity.subject_team_id == "vale" and opportunity.for_team_id == "harbor" and "vale_03" in opportunity.player_ids
    assert "harbor_10" in opportunity.player_ids  # the runner on that flank
    # Shape and marking.
    assert vale.shape.marking_system == "man_oriented" and harbor.shape.marking_system == "zonal"
    assert harbor.shape.shift_lags[0].player_id == "harbor_03"
    early = max(harbor.shape.marking, key=lambda m: m.early_releases)
    assert early.player_id == "harbor_06" and early.early_releases >= 3
    late = max(vale.shape.marking, key=lambda m: m.late_reactions)
    assert late.player_id == "vale_04" and late.mean_reaction_ms >= 450
    # Press: who triggers, whom they target, and how often it forces a recycle to the keeper.
    assert harbor.press.triggers[0].player_id == "harbor_09"
    assert vale.press.triggers[0].player_id in ("vale_09", "vale_10")
    assert harbor.press.mean_closing_speed_mps > vale.press.mean_closing_speed_mps
    assert harbor.press.when_pressing.forced_to_keeper > harbor.press.when_not_pressing.forced_to_keeper
    targeted = {o.player_ids[0] for o in full["observations"] if o.category == "press" and "press harder" in o.headline}
    assert targeted == {"vale_05", "harbor_04"}
    # Runs: Harbor's right winger runs most; Vale defenders drop with runs far more often.
    assert harbor.runs[0].player_id == "harbor_10"
    drag = lambda team: sum(r.drew_defender for r in team.runs) / max(1, sum(r.runs for r in team.runs))
    assert drag(harbor) > 2 * drag(vale)
    # Build-up from the keeper.
    assert harbor.build_up.short_starts > vale.build_up.short_starts and vale.build_up.long_starts > vale.build_up.short_starts
    assert harbor.build_up.sequences and vale.build_up.sequences and harbor.build_up.mean_lines_broken > 0
    # Chance creation never credits a goalkeeper and pass metrics come from tracked flights.
    assert all(c.player_id.split("_")[1] != "01" for t in (harbor, vale) for c in t.creators)
    assert any(d.speed_mps for d in harbor.decisive_passes)


def test_corner_swing_is_measured_from_the_curve_and_matches_the_kicking_foot(full):
    deliveries = [d for t in full["teams"].values() for d in t.corners.deliveries]
    assert len(deliveries) >= 6
    for d in deliveries:
        assert d.foot == foot(d.taker_id)
        assert d.swing == d.expected_swing == expected_swing(d.foot, d.side)
        assert d.curve_m > 1 and 800 <= d.flight_ms <= 3000 and 12 <= d.speed_mps <= 30
    vale = full["teams"]["vale"].corners.deliveries
    assert {(d.side, d.swing) for d in vale} == {("left", "inswinger"), ("right", "outswinger")}
    harbor = full["teams"]["harbor"].corners
    assert harbor.target_men and all(t.mean_time_to_spot_ms is not None for t in harbor.target_men if t.reached_spot)
    assert expected_swing("left", "right") == "inswinger" and expected_swing("left", "left") == "outswinger"


def test_offside_line_counts_the_goalkeeper_and_caught_runners_are_beyond_it(engine):
    prepared = engine.prepared()
    caught = 0
    for m in prepared.attacks.values():
        frame = m.episode.frame_at(m.t0)
        xs = sorted((frame.players[p][0] for p in team_players(m.episode.opponent_id)), reverse=True)
        assert second_last_x(frame, m.episode.opponent_id) == xs[1]
        for run in m.runs:
            x = frame.players[run.player_id][0]
            assert run.offside == (x > xs[1] and x > frame.ball[0] and x > 50)
            caught += run.offside
            if run.player_id in m.broken_by:
                assert not run.offside and m.trap and m.late
    assert caught > 0


def test_report_uses_only_the_observed_prefix(engine, fixture):
    cutoff = 12 * 60_000 + 500
    report = engine.report(records_until(fixture, cutoff), cutoff)
    prepared = engine.prepared()
    assert 0 < report["episodes_observed"] < len(prepared.episodes)
    for observation in report["observations"]:
        for episode_id in observation.evidence.episode_ids:
            assert prepared.episodes[episode_id].end_ms <= cutoff
    for moment in report["key_moments"]:
        assert moment.time_ms <= cutoff
    for team in report["teams"].values():
        assert all(d.time_ms <= cutoff for d in team.corners.deliveries + team.decisive_passes)
    empty = engine.report({}, 0)
    assert empty["episodes_observed"] == 0 and empty["observations"] == []


def test_analysis_never_reads_the_generator_tendencies():
    source = inspect.getsource(tactics_module)
    assert "tendencies(" not in source and "_TENDENCIES" not in source
    # Plans only drive the synthetic generator; measurements see frames and events.
    for measured in (tactics_module.measure_attack, tactics_module.measure_possession, tactics_module.measure_corner, tactics_module.Report):
        assert "plan" not in inspect.getsource(measured)


def test_tactics_endpoint_is_capability_scoped_and_advances_with_the_replay(client):
    app, _replay, clock = client
    sid = create(app).json()["session_id"]
    assert app.get(f"/api/sessions/{sid}/tactics", headers=headers("w" * 64)).status_code == 404
    first = app.get(f"/api/sessions/{sid}/tactics", headers=headers()).json()
    assert first["episodes_observed"] == 0 and first["engine_version"] == "tactics_v1" and first["provenance"] == "synthetic_tracking"
    control(app, sid, "play")
    clock.advance(20)  # 20 s at 60× is 20 match minutes
    later = app.get(f"/api/sessions/{sid}/tactics", headers=headers()).json()
    assert later["episodes_observed"] > 0 and later["playhead_ms"] == 1_200_000
    assert set(later["teams"]) == {"harbor", "vale"} and later["limitations"]
    text = json.dumps(later)
    for hidden in ("trap_rate", "step_lag_ms", "follow_runner", "follow_lag", "target_bonus", "force_back", "short_build_up", "\"pressed\""):
        assert hidden not in text
    assert CAP not in text


from .test_api import client  # noqa: E402,F401  (shared API fixture)


def test_frontend_contract_sample_matches_the_backend_report(engine, fixture):
    from pathlib import Path
    from backend.models import TacticalReport
    path = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "fixtures" / "tactics-15min.json"
    sample = json.loads(path.read_text(encoding="utf-8"))
    cutoff = sample["playhead_ms"]
    report = TacticalReport(session_id="sample", generation=1, data_epoch=1, playhead_ms=cutoff, next_cursor="c",
                            **engine.report(records_until(fixture, cutoff), cutoff))
    assert report.model_dump(mode="json") == sample
