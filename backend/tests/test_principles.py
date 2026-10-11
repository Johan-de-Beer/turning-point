"""Principles of play: structures, wingers, pressing system and triggers, marking, counter-movements,
third-man combinations and the match report."""
import inspect
import json
from pathlib import Path

import pytest

import backend.principles as principles_module
from backend.analytics import AnalyticsEngine
from backend.models import PERIOD_MS, PlayPrinciples
from backend.phases import PhaseEngine
from backend.principles import PrinciplesEngine, segment_distance
from backend.tactics import TacticalEngine

from .test_api import CAP, client, control, create, headers  # noqa: F401
from .test_tactics import records_until

FULL = 2 * PERIOD_MS
SAMPLE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "fixtures" / "principles-20min.json"
HIDDEN = ("rest_shape", "drop_sprint", "man_marking", "trigger_hunt", "winger_habits", "lay_off_rate", "cycle_ms", "sprint_ms")


@pytest.fixture(scope="module")
def engine(fixture):
    match, events = fixture
    return PrinciplesEngine(PhaseEngine(AnalyticsEngine(match, events, TacticalEngine(match, events))))


@pytest.fixture(scope="module")
def full(engine, fixture):
    return engine.report(records_until(fixture, FULL), FULL)


def test_analysis_never_reads_the_planted_tendencies():
    source = inspect.getsource(principles_module)
    assert "tendencies(" not in source and "_TENDENCIES" not in source and "generate_plans" not in source


def test_structures_recover_the_planted_rest_defence(full):
    harbor, vale = full["structures"]["harbor"], full["structures"]["vale"]
    # Harbor keeps two centre-backs with three in front (2+3); Vale a back three with two in front (3+2).
    assert harbor.rest_defence[0].shape == "2+3" and harbor.rest_defence[0].base == ["RCB", "LCB"]
    assert vale.rest_defence[0].shape == "3+2" and vale.rest_defence[0].base == ["RB", "RCB", "LCB"]
    assert vale.rest_defence[0].share > 50
    for s in (harbor, vale):
        assert sum(r.share for r in s.rest_defence) == pytest.approx(100, abs=.5)
        assert sum(r.share for r in s.build_up) == pytest.approx(100, abs=.5)


def test_winger_roles_recover_the_planted_habits(full):
    rows = {w.player_id: w for w in full["wingers"]}
    assert rows["harbor_10"].style == "inverted" and rows["harbor_10"].opposite_foot
    assert rows["vale_11"].style == "touchline"
    assert rows["harbor_10"].inside_share > 80 > 15 > rows["vale_11"].inside_share
    # The inverted winger leaves the width on his flank to the overlapping full-back.
    assert rows["harbor_10"].fullback_width_share > 80
    assert full["width"]["vale"].width_m > full["width"]["harbor"].width_m


def test_pressing_system_recovers_the_planted_man_marking(full):
    harbor, vale = full["pressing"]["harbor"], full["pressing"]["vale"]
    assert harbor.system == "zonal"
    assert vale.system == "hybrid"
    units = {u.unit: u for u in vale.units}
    assert units["midfield"].marking == "man" and units["front"].marking == "zonal"
    assert set(units["midfield"].markers) == {"vale_07", "vale_08"}


def test_pressing_triggers_recover_the_planted_triggers(full):
    harbor = {t.trigger: t for t in full["pressing"]["harbor"].triggers}
    vale = {t.trigger: t for t in full["pressing"]["vale"].triggers}
    # Harbor hunts passes back to the keeper and to the centre-backs; Vale's man-markers sit on midfield receivers.
    assert harbor["back_pass_keeper"].rate > 50 > vale.get("back_pass_keeper").rate
    assert harbor["to_centre_back"].rate > vale["to_centre_back"].rate + 20
    assert vale["into_midfield"].rate > harbor["into_midfield"].rate + 20


def test_counter_movements_recover_the_planted_runs(full):
    harbor = {(r.kind, tuple(r.players)): r.episodes for r in full["movements"]["harbor"].rows}
    vale = {(r.kind, tuple(r.players)): r.episodes for r in full["movements"]["vale"].rows}
    sprints = {k[1][0]: v for k, v in {**harbor, **vale}.items() if k[0] == "drop_and_sprint"}
    # Harbor's striker drops and sprints in behind far more than anyone else.
    assert sprints["harbor_09"] > 3 * max(v for p, v in sprints.items() if p != "harbor_09")
    # Vale's striker drops as the attacking midfielder runs into the space he left (and back).
    opposite = {k[1]: v for k, v in {**harbor, **vale}.items() if k[0] == "opposite_runs"}
    assert opposite[("vale_08", "vale_09")] > 3 * max(v for p, v in opposite.items() if p != ("vale_08", "vale_09"))


def test_third_man_recovers_the_planted_lay_off(full):
    harbor, vale = full["third_man"]["harbor"], full["third_man"]["vale"]
    assert harbor.combinations > 3 * vale.combinations
    assert harbor.by_zone["build_up"] > harbor.by_zone["middle_third"]
    top = harbor.patterns[0]
    assert (top.first, top.second) == ("harbor_01", "harbor_06") and top.third in ("harbor_04", "harbor_05")


def test_lane_distance_ignores_the_ends():
    assert segment_distance((10, 1), (0, 0), (20, 0)) == pytest.approx(1)
    assert segment_distance((1, 0), (0, 0), (20, 0)) > 100


def test_match_report_lines_carry_numbers_and_past_moments(full):
    for team, report in full["match_report"].items():
        assert [line.topic for line in report.phases] == ["In possession", "Out of possession", "Attack to defence", "Defence to attack", "Set pieces"]
        assert report.key_player and report.key_player.startswith(team)
        for line in report.phases + report.strengths + report.weaknesses:
            assert any(ch.isdigit() for ch in line.text) or line.text.endswith("yet.")
            assert "because" not in line.text and "caused" not in line.text
    assert any(line.topic == "Counter-press" for line in full["match_report"]["harbor"].strengths)
    assert any(line.topic == "Third-man combinations" for line in full["match_report"]["harbor"].strengths)


def test_report_uses_only_the_observed_prefix(engine, fixture):
    cutoff = 20 * 60_000
    early = engine.report(records_until(fixture, cutoff), cutoff)
    moments = [m for team in early["structures"].values() for m in team.moments]
    moments += [m for team in early["movements"].values() for r in team.rows for m in r.moments]
    moments += [m for team in early["third_man"].values() for m in team.moments]
    moments += [m for team in early["match_report"].values() for line in team.phases + team.strengths + team.weaknesses for m in line.moments]
    assert moments and all(m.time_ms <= cutoff for m in moments)
    late = engine.report(records_until(fixture, FULL), FULL)
    assert early["third_man"]["harbor"].combinations <= late["third_man"]["harbor"].combinations


def test_principles_endpoint_is_capability_scoped_and_hides_the_plan(client):  # noqa: F811
    app, _replay, clock = client
    sid = create(app).json()["session_id"]
    assert app.get(f"/api/sessions/{sid}/principles", headers=headers("w" * 64)).status_code == 404
    control(app, sid, "play")
    clock.advance(20)
    report = app.get(f"/api/sessions/{sid}/principles", headers=headers()).json()
    assert report["engine_version"] == "principles_v1" and report["playhead_ms"] == 1_200_000
    text = json.dumps(report)
    for hidden in HIDDEN:
        assert hidden not in text
    assert CAP not in text


def test_frontend_contract_sample_matches_the_backend_report(engine, fixture):
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    cutoff = sample["playhead_ms"]
    report = PlayPrinciples(session_id="sample", generation=1, data_epoch=1, playhead_ms=cutoff, next_cursor="c",
                            **engine.report(records_until(fixture, cutoff), cutoff))
    assert report.model_dump(mode="json") == sample
