"""Phases of play, transitions, counter-press, blocks, carries and xT, full-back roles, rotations and analyst notes."""
import inspect
import json
from pathlib import Path

import pytest

import backend.phases as phases_module
import backend.xt as xt_module
from backend.analytics import AnalyticsEngine
from backend.models import PERIOD_MS, GamePhases
from backend.phases import PhaseEngine
from backend.tactics import TacticalEngine

from .test_api import CAP, client, control, create, headers  # noqa: F401
from .test_tactics import records_until

FULL = 2 * PERIOD_MS
SAMPLE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "fixtures" / "phases-20min.json"
HIDDEN = ("window_ms", "reach_m", "sweeper", "drop_in", "drop_deep", "line_base", "transition_mps",
          "hard_save_rate")


@pytest.fixture(scope="module")
def engine(fixture):
    match, events = fixture
    return PhaseEngine(AnalyticsEngine(match, events, TacticalEngine(match, events)))


@pytest.fixture(scope="module")
def full(engine, fixture):
    return engine.report(records_until(fixture, FULL), FULL)


def test_xt_grid_is_reproducible_and_out_of_sample():
    committed = xt_module.grid()
    assert xt_module.DEMO_SEED not in xt_module.TRAINING_SEEDS
    with pytest.raises(AssertionError):
        xt_module.fit((1, xt_module.DEMO_SEED))
    assert xt_module.fit() == committed
    values = committed["values"]
    assert len(values) == committed["grid_x"] * committed["grid_y"]
    # Threat rises toward the opponent's goal: central zones next to the box beat midfield.
    assert xt_module.threat(95, 50) > xt_module.threat(80, 50) > xt_module.threat(50, 50)


def test_phase_seconds_add_up_to_live_time(full):
    for team, row in full["phases"].items():
        assert sum(r.seconds for r in row.rows) == pytest.approx(row.live_seconds, abs=1)
        assert sum(r.share for r in row.rows) == pytest.approx(100, abs=.5)


def test_counter_press_recovers_the_planted_hunters(full):
    harbor, vale = full["transitions"]["harbor"].defensive, full["transitions"]["vale"].defensive
    # Harbor sends three players for 4 s after 80% of losses; Vale one player for 1.2 s after 40%.
    assert harbor.press_rate > 70 > 40 > vale.press_rate
    assert harbor.pack_2s > vale.pack_2s + .5
    assert harbor.regained_10s > vale.regained_10s


def test_full_back_roles_recover_the_planted_habits(full):
    styles = {row.player_id: row.style for row in full["fullbacks"]}
    assert styles == {"harbor_02": "overlapping", "harbor_03": "inverted", "vale_02": "holding", "vale_03": "underlapping"}


def test_rotations_recover_the_planted_drops(full):
    episodes = {team: {r.kind: r.episodes for r in row.rows} for team, row in full["rotations"].items()}
    assert episodes["harbor"]["holding_midfielder_drops"] > 2 * episodes["vale"].get("holding_midfielder_drops", 0)
    assert episodes["vale"]["striker_drops"] > 2 * episodes["harbor"].get("striker_drops", 0)


def test_blocks_snapshots_and_recovery_recover_the_planted_lines(full):
    vale_low = next(r for r in full["blocks"]["vale"].rows if r.block == "low")
    assert vale_low.share > 60
    snaps = {s.situation: s for s in full["blocks"]["harbor"].snapshots}
    # Harbor's line squeezes up when the opponent builds from the back and when pressing high.
    assert snaps["opponent_build_up"].back_four_m > snaps["settled"].back_four_m + 10
    assert snaps["high_press"].back_four_m > snaps["settled"].back_four_m + 10
    # Only Harbor's keeper is planted to sweep behind the line.
    assert full["blocks"]["harbor"].recovery.sweeps > full["blocks"]["vale"].recovery.sweeps == 0


def test_carries_and_xt_are_consistent(full):
    for team, row in full["progression"].items():
        assert row.xt == pytest.approx(row.xt_passes + row.xt_carries, abs=.002)
        players = [p for p in full["player_progression"] if p.team_id == team]
        assert row.progressive_carries == sum(p.progressive_carries for p in players)
    assert all(a.action in ("pass", "carry") for a in full["top_threat"])


def test_report_uses_only_the_observed_prefix(engine, fixture):
    cutoff = 900_000
    early = GamePhases(session_id="s", generation=1, data_epoch=1, playhead_ms=cutoff, next_cursor="c",
                       **engine.report(records_until(fixture, cutoff), cutoff))
    data = early.model_dump(mode="json")

    def times(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ("time_ms", "start_ms") and isinstance(v, int):
                    yield v
                yield from times(v)
        elif isinstance(value, list):
            for v in value:
                yield from times(v)
    assert max(times(data)) <= cutoff
    for team in ("harbor", "vale"):
        assert data["phases"][team]["live_seconds"] <= cutoff / 1000


def test_notes_carry_numbers_and_evidence_moments(full):
    notes = full["notes"]
    assert {n.team_id for n in notes} == {"harbor", "vale"}
    for note in notes:
        assert any(ch.isdigit() for ch in note.quantitative) and note.look_for
        assert " an holding" not in note.quantitative and " 1 were " not in note.quantitative


def test_phases_never_read_the_generator_tendencies():
    source = inspect.getsource(phases_module) + inspect.getsource(xt_module)
    assert "tendencies(" not in source and "_TENDENCIES" not in source and "generate_plans" not in source


def test_phases_endpoint_is_capability_scoped_and_hides_the_plan(client):  # noqa: F811
    app, _replay, clock = client
    sid = create(app).json()["session_id"]
    assert app.get(f"/api/sessions/{sid}/phases", headers=headers("w" * 64)).status_code == 404
    first = app.get(f"/api/sessions/{sid}/phases", headers=headers()).json()
    assert first["engine_version"] == "phases_v1" and first["notes"] == []
    control(app, sid, "play")
    clock.advance(20)
    later = app.get(f"/api/sessions/{sid}/phases", headers=headers()).json()
    assert later["playhead_ms"] == 1_200_000 and later["notes"]
    text = json.dumps(later)
    for hidden in HIDDEN:
        assert hidden not in text
    assert CAP not in text


def test_frontend_contract_sample_matches_the_backend_report(engine, fixture):
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    cutoff = sample["playhead_ms"]
    report = GamePhases(session_id="sample", generation=1, data_epoch=1, playhead_ms=cutoff, next_cursor="c",
                        **engine.report(records_until(fixture, cutoff), cutoff))
    assert report.model_dump(mode="json") == sample
