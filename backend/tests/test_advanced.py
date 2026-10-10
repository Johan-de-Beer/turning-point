"""Advanced metrics: game state, heatmaps, xGoT and goals prevented, tempo, PPDA, chance creation, packing and VAEP."""
import inspect

import pytest

import backend.advanced as advanced_module
from backend.analytics import AnalyticsEngine
from backend.chances import placement_reach, xgot
from backend.models import PERIOD_MS
from backend.tactics import TacticalEngine

from .test_tactics import records_until

FULL = 2 * PERIOD_MS


@pytest.fixture(scope="module")
def engine(fixture):
    match, events = fixture
    return AnalyticsEngine(match, events, TacticalEngine(match, events))


@pytest.fixture(scope="module")
def full(engine, fixture):
    return engine.report(records_until(fixture, FULL), FULL)


def test_xgot_rewards_placement_and_pace():
    assert placement_reach(0, 1.0) == 0 and placement_reach(3.66, 2.44) == pytest.approx(2 ** .5)
    central, corner = xgot(.27, 0, 1.0, 18), xgot(.27, 3.3, 2.3, 28)
    assert central < .1 and .5 < corner < .9
    assert xgot(.27, 2.5, .2, 25) > xgot(.27, 2.5, .2, 15)
    assert xgot(.5, 1, 1, 20) > xgot(.1, 1, 1, 20)


def test_xgot_only_for_on_target_shots(full):
    for shot in full["shots"]:
        assert (shot.xgot is not None) == (shot.outcome in ("goal", "saved"))
        assert (shot.placement is not None) == (shot.xgot is not None)


def test_goals_prevented_recovers_the_planted_shot_stoppers(full):
    keepers = {k.player_id: k for k in full["goalkeeping"].keepers}
    for k in keepers.values():
        assert k.xg_prevented == pytest.approx(k.xgot_faced - k.goals_conceded, abs=.011)
        assert k.saves + k.goals_conceded == k.shots_on_target
    # Harbor's keeper makes far more hard saves than Vale's (planted), so prevents more than expected.
    assert keepers["harbor_01"].xg_prevented > 1 > keepers["vale_01"].xg_prevented + 1
    shooting = full["goalkeeping"].shooting
    assert shooting["vale"].xgot == keepers["harbor_01"].xgot_faced
    for row in shooting.values():
        assert row.placement_added == pytest.approx(row.xgot - row.xg_on_target, abs=.011)


def test_game_state_segments_follow_the_score(full):
    state = full["game_state"]
    assert state.score == {"harbor": 2, "vale": 1}
    assert [s.score for s in state.segments] == [{"harbor": 0, "vale": 0}, {"harbor": 1, "vale": 0}, {"harbor": 1, "vale": 1}, {"harbor": 2, "vale": 1}]
    assert state.segments[0].start_ms == 0 and state.segments[-1].end_ms == FULL
    assert all(a.end_ms == b.start_ms for a, b in zip(state.segments, state.segments[1:]))
    harbor, vale = state.teams["harbor"], state.teams["vale"]
    assert harbor.current == "winning" and vale.current == "losing"
    minutes = {row.state: row.minutes for row in harbor.rows}
    assert sum(minutes.values()) == pytest.approx(90, abs=.2)
    assert {row.state: row.minutes for row in vale.rows} == {"losing": minutes["winning"], "drawing": minutes["drawing"]}
    for team, rows in (("harbor", harbor.rows), ("vale", vale.rows)):
        assert sum(r.shots for r in rows) == full["chances"][team].shots
        assert sum(r.goals for r in rows) == full["chances"][team].goals
        assert sum(r.xg for r in rows) == pytest.approx(full["chances"][team].xg, abs=.02)
    # A goal's own shot counts in the state before it.
    goals = [s for s in full["shots"] if s.outcome == "goal"]
    assert [s.game_state for s in goals] == ["drawing", "losing", "drawing"]   # 1-0, the equaliser, 2-1


def test_game_state_recovers_planted_game_management(full):
    rows = {r.state: r for r in full["game_state"].teams["harbor"].rows}
    # Harbor drop their line while protecting a lead (planted); the split shows it.
    assert rows["winning"].back_four_m < rows["drawing"].back_four_m - 1


def test_heatmaps_are_consistent_and_in_the_attacking_frame(full):
    heat = full["heatmaps"]
    assert heat.grid_x * heat.grid_y == 96
    maps = {(m.subject_id, m.kind): m for m in heat.maps}
    for team in ("harbor", "vale"):
        players = [m for m in heat.maps if m.team_id == team and m.subject_id != team]
        for kind in ("touches", "tracking", "received", "defensive"):
            assert maps[(team, kind)].cells == [sum(m.cells[i] for m in players if m.kind == kind) for i in range(96)]
        assert maps[(team, "received")].total < maps[(team, "touches")].total
        # Both goalkeepers live in the first column of their own attacking frame.
        keeper = maps[(f"{team}_01", "tracking")]
        assert keeper.total == FULL // 1000
        assert sum(keeper.cells[:16]) > .9 * keeper.total
    assert all(m.total == sum(m.cells) for m in heat.maps)


def test_tempo_counts_are_consistent_and_recover_short_build_up(full):
    tempo = full["tempo"]
    for team, row in tempo.items():
        fig = row.match
        passes = full["team_value"][team]
        assert fig.forward_passes + fig.lateral_passes + fig.backward_passes > 0
        assert fig.progressive_passes <= fig.forward_passes
        assert fig.possessions == passes.possessions
        assert len(row.intervals) == 6
    # Harbor build short from the back (planted), so their possessions from the defensive third last longer.
    assert tempo["harbor"].match.possession_s["defensive"] > tempo["vale"].match.possession_s["defensive"]


def test_ppda_recovers_the_planted_press(full):
    pressing = full["pressing"]
    for row in pressing.values():
        assert row.ppda == pytest.approx(row.opponent_passes / row.defensive_actions, abs=.06)
    assert pressing["harbor"].ppda < pressing["vale"].ppda   # Harbor press more often (planted)


def test_creation_counts_key_passes_box_touches_and_xa(full):
    shots = full["shots"]
    for team, row in full["creation"].items():
        fed = [s for s in shots if s.team_id == team and s.key_passer_id]
        assert row.key_passes == len(fed) == sum(row.key_pass_types.values()) == sum(row.key_pass_origins.values())
        assert row.xa == pytest.approx(sum(s.xg for s in fed), abs=.011)
        assert row.assists == sum(s.outcome == "goal" for s in fed) and row.first_time_key_passes <= row.key_passes
        players = [p for p in full["player_creation"] if p.team_id == team]
        assert sum(p.box_touches for p in players) == row.box_touches
        assert sum(p.key_passes for p in players) == row.key_passes
        state_touches = sum(r.box_touches for r in full["game_state"].teams[team].rows)
        assert state_touches == row.box_touches
    assert all(s.key_passer_id != s.player_id for s in shots if s.key_passer_id)


def test_packing_counts_bypassed_opponents(full):
    for action in full["top_packing"]:
        assert action.end.x > action.start.x and 0 < action.packed <= 10 and action.defenders_packed <= min(4, action.packed)
    assert full["top_packing"] == sorted(full["top_packing"], key=lambda a: (-a.packed, -a.defenders_packed, a.time_ms))
    for team, row in full["packing"].items():
        players = [p for p in full["player_packing"] if p.team_id == team]
        assert row.packed_by_passes == sum(p.packed_by_passes for p in players)
        assert row.passing_rate == pytest.approx(row.packed_by_passes / row.passes, abs=.006)
        assert row.line_breaking > 0


def test_vaep_charges_losses_and_credits_ball_winners(full):
    report = full
    actions = report["top_vaep"]
    assert actions == sorted(actions, key=lambda a: -a.vaep)
    for a in actions:
        assert a.vaep == pytest.approx(a.scoring_delta - a.conceding_delta, abs=1e-3)
    for team, value in report["team_value"].items():
        assert value.vaep == pytest.approx(sum(value.vaep_by_action.values()), abs=.01)
        assert value.vaep == pytest.approx(sum(p.vaep for p in report["player_value"] if p.team_id == team), abs=.01)
        assert value.vaep_by_action["dispossessed"] < 0 < value.vaep_by_action["tackle_won"]
        assert value.vaep_by_action["interception"] > 0
        # Possession value (xOVA) never credits defensive actions.
        assert "tackle_won" not in value.by_action and "interception" not in value.by_action
    defenders = [p for p in report["player_value"] if p.defensive_vaep > 0]
    assert defenders and all(p.player_id.split("_")[1] != "01" for p in defenders)


def test_advanced_metrics_use_only_the_observed_prefix(engine, fixture):
    cutoff = 20 * 60_000
    early = engine.report(records_until(fixture, cutoff), cutoff)
    assert all(m.total == cutoff // 1000 for m in early["heatmaps"].maps if m.kind == "tracking" and m.subject_id.endswith("_01"))
    assert early["game_state"].score == {"harbor": 1, "vale": 0}
    assert all(a.time_ms <= cutoff for a in early["top_packing"] + early["top_vaep"])
    assert len(early["tempo"]["harbor"].intervals) == 2


def test_advanced_metrics_never_read_the_generator_tendencies():
    source = inspect.getsource(advanced_module)
    assert "tendencies(" not in source and "_TENDENCIES" not in source and "generate_plans" not in source
