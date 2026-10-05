"""Recorded synthetic ball paths must explain the functional pitch replay."""
import math
import pytest
from pydantic import ValidationError

from backend.generator import generate_fixture
from backend.models import Control, SessionCreate, ShotDetail
from backend.replay import FakeClock, ReplayService, ServiceError
from backend.storage import Storage


def xy(point):
    return (point.x, point.y)


def test_complete_fixture_ball_and_holder_continuity_across_live_turnovers(fixture):
    _, events = fixture
    ball, holder, team = None, None, None
    turnovers = 0
    for envelope in events:
        event = envelope.payload
        if event.kind in ("PERIOD_START", "PERIOD_END", "STOPPAGE"):
            ball, holder, team = None, None, None
        elif event.kind == "POSSESSION":
            if ball is not None:
                expected = ball if event.team_id == team else tuple(round(100 - value, 2) for value in ball)
                assert xy(event.detail.start) == expected, envelope.ref
                turnovers += event.team_id != team
            ball, holder, team = xy(event.detail.start), event.player_id, event.team_id
        elif event.kind in ("PASS", "CARRY", "SHOT"):
            assert event.team_id == team
            assert event.player_id == holder, envelope.ref
            origin = event.detail.position if event.kind == "SHOT" else event.detail.start
            assert xy(origin) == ball, envelope.ref
            if event.kind == "SHOT":
                assert event.detail.target is not None
                ball = xy(event.detail.target)
            else:
                ball = xy(event.detail.end)
                if event.kind == "PASS":
                    holder = event.detail.recipient_id if event.detail.completed else None
    assert turnovers > 100


def test_fixture_paths_have_varied_lanes_and_recorded_outcome_specific_shot_targets(fixture):
    _, events = fixture
    for period in (1, 2):
        for team in ("harbor", "vale"):
            passes = [e.payload for e in events if e.payload.kind == "PASS" and e.payload.period == period and e.payload.team_id == team]
            paths = {(xy(e.detail.start), xy(e.detail.end)) for e in passes}
            assert len(paths) == len(passes)
            assert max(e.detail.end.y for e in passes) - min(e.detail.end.y for e in passes) > 50
            assert any(e.detail.end.y - e.detail.start.y > 20 for e in passes)
            assert any(e.detail.start.y - e.detail.end.y > 20 for e in passes)
            assert any(e.detail.start.x > e.detail.end.x for e in passes)
    shots = [e.payload for e in events if e.payload.kind == "SHOT"]
    assert {e.detail.outcome for e in shots} == {"goal", "saved", "blocked", "off_target"}
    for event in shots:
        target = event.detail.target
        assert target is not None and xy(target) != xy(event.detail.position)
        if event.detail.outcome == "goal":
            assert target.x == 100 and 44.61 < target.y < 55.39
        elif event.detail.outcome == "saved":
            assert 97 <= target.x < 100 and 44.61 < target.y < 55.39
        elif event.detail.outcome == "blocked":
            assert event.detail.position.x < target.x <= 95
        else:
            assert target.x == 100 and not 44.61 < target.y < 55.39
            next_event = next(e.payload for e in events if e.payload.event_time_ms > event.event_time_ms)
            assert next_event.kind == "STOPPAGE" and next_event.detail.reason == "ball_out"


def test_shot_target_is_optional_for_legacy_records_and_strict_when_present():
    legacy = ShotDetail(position={"x": 85, "y": 50}, outcome="saved")
    assert legacy.target is None
    for invalid in ({"x": "100", "y": 50}, {"x": 101, "y": 50}, {"x": 100, "y": float("nan")}):
        with pytest.raises(ValidationError):
            ShotDetail(position={"x": 85, "y": 50}, target=invalid, outcome="goal")


def test_recorded_carry_spacing_does_not_require_an_impossible_ball_holder_sprint(fixture):
    _, events = fixture
    previous_ms = 0
    for envelope in events:
        event = envelope.payload
        if event.kind == "CARRY":
            dx = (event.detail.end.x - event.detail.start.x) * 1.05
            dy = (event.detail.end.y - event.detail.start.y) * .68
            seconds = (event.event_time_ms - previous_ms) / 1000
            assert seconds > 0 and math.hypot(dx, dy) / seconds <= 9
        previous_ms = event.event_time_ms


def test_observed_shot_target_is_withheld_until_delivery_and_revision_is_consistent(service):
    replay, clock = service
    session = replay.create(SessionCreate(match_id=replay.match.match_id, speed=60), "path-test-owner")
    replay.controls(session, Control(action="play", expected_generation=1))
    clock.advance(.75)
    early = replay.state(session)
    assert early.playhead_ms == 45_000
    assert not any(e.payload and e.payload.kind == "SHOT" for e in early.events)
    assert "fixture_version" not in early.model_dump()
    clock.advance(.1)
    observed = replay.state(session)
    shot = next(e for e in observed.events if e.payload and e.payload.kind == "SHOT")
    assert shot.payload.detail.target is not None
    assert shot.available_at_ms == shot.payload.event_time_ms == 48_000 <= observed.playhead_ms
    _, revised_events = generate_fixture(correction=True)
    revision = next(e for e in revised_events if e.revision == 2)
    assert revision.payload.detail.outcome == "saved" and revision.payload.detail.target.x == 98
    assert revision.available_at_ms > revision.payload.event_time_ms


@pytest.mark.parametrize("legacy_record", [False, True])
def test_changed_private_fixture_version_cannot_mix_with_restored_session_prefix(fixture, legacy_record):
    match, events = fixture
    storage = Storage(":memory:")
    clock = FakeClock()
    replay = ReplayService(match, events, storage, clock=clock)
    session = replay.create(SessionCreate(match_id=match.match_id), "path-recovery-owner")
    replay.controls(session, Control(action="play", expected_generation=1))
    clock.advance(10)
    replay.state(session)
    raw = session.serialize()
    if legacy_record:
        raw.pop("fixture_version")
    else:
        raw["fixture_version"] = "synthetic_v1"
    storage.save_session(session.session_id, session.capability_hash, raw)
    restored = ReplayService(match, events, storage, clock=clock)
    assert restored.sessions == {} and storage.sessions() == []
    with pytest.raises(ServiceError) as error:
        restored.authorize(session.session_id, "path-recovery-owner")
    assert error.value.status == 404
    fresh = restored.create(SessionCreate(match_id=match.match_id), "path-recovery-owner")
    assert fresh.playhead_ms == 0 and fresh.fixture_version == match.fixture_version
