"""Tactical analysis over released synthetic tracking and observed events.

Every number here is measured from frames (positions every 200 ms) and observed
event records. Nothing reads the generator's tendencies or plans. Results are
descriptive tendencies within this synthetic sample, never predictions or causes.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from statistics import mean, median

from .generator import generate_plans
from .ingest import canonical_order
from .models import (BuildUp, Corners, CornerDelivery, Creator, DecisivePass, DefenderStep, EventEnvelope, KeyMoment,
                     MarkingRecord, Match, MomentPlayer, OffsideTrap, Press, PressOutcomes, PressTarget, PressTrigger, Runner,
                     ShapeShift, ShiftLag, TacticalEvidence, TacticalObservation, TargetMan, TeamTactics)
from .tactical_profiles import BACK_FOUR, FORWARDS, MIDFIELD, expected_swing, other, player_for, role
from .tracking import FRAME_MS, X_M, Y_M, Episode, Frame, build_tracking, metres, team_players

# Thresholds (see docs/tactical-engine.md for the reasoning behind each one).
STEP_SPEED_MPS = 2.0        # a defender moving up the pitch at least this fast is stepping
LATE_STEP_MS = 250          # step onset this far behind the line's median onset is late
RUN_SPEED_MPS = 5.5         # high-speed running threshold used for runs (19.8 km/h)
DROP_SPEED_MPS = 2.0        # a defender retreating at least this fast is dropping with a run
LATE_REACTION_MS = 450
PRESS_SPEED_MPS = 4.5       # speed toward the ball that marks a pressing action
PRESS_DISTANCE_M = 25.0
PRESSURE_DISTANCE_M = 2.5
PRESS_WINDOW_MS = 12_000
BUILD_UP_WINDOW_MS = 20_000
MIDDLE_THIRD_X, FINAL_THIRD_X = 100 / 3, 200 / 3

DEFINITIONS = {
    "offside_trap": "Three or more of the back four step toward halfway at ≥2 m/s within 1.8 s before a pass into the attacking 40%. Onset is the first of two consecutive frames above that speed.",
    "late_step": "A back-four defender whose step onset is ≥250 ms after the line's median onset, or who does not step while the rest do.",
    "offside_position": "At the pass frame the runner is beyond both the ball and the second-last defender (goalkeeper included) in the opponent half. Body parts and the referee's judgement are not modelled.",
    "trap_broken": "A runner was onside only because a late-stepping defender was deeper than the rest of the line.",
    "line_height": "Distance from the defending team's goal line to the back four's median position at the pass, in metres.",
    "line_spread": "Front-to-back spread of the back four at the pass, in metres; lower is flatter.",
    "shift_to_ball": "Lateral movement of the ten outfield players' centre toward the ball's side between 3 s before the pass and the pass.",
    "shift_lag": "Time a player takes to finish 90% of their lateral shift, relative to the unit's median.",
    "early_release": "The nearest defender at the start of the move is engaging the ball carrier (≤5 m) at the pass while that attacker is free (no defender within 5 m).",
    "late_reaction": "A defender starts dropping with a run ≥450 ms after the run begins.",
    "marking_system": "Man-oriented when the nearest defender drops with at least 60% of runs, zonal at 35% or less, otherwise mixed.",
    "run": "An attacker moving toward goal at ≥5.5 m/s for three consecutive frames, starting within 12 units of the defensive line.",
    "drew_defender": "A back-four defender in the runner's channel retreats at ≥2 m/s, starting before the pass, within 1.2 s of the run.",
    "press": "An opponent outfield player within 25 m of the ball runs toward it at ≥4.5 m/s for two consecutive frames within 3 s of a possession starting in the team's own half.",
    "press_trigger": "The first player to make that pressing run. The target is the player in possession at that moment.",
    "time_to_pressure": "From the trigger's onset until they are within 2.5 m of the ball.",
    "press_outcome": "The first of: a pass to the goalkeeper (forced to keeper), an opponent possession (regained), a completed pass or carry past halfway (played through), a stoppage, within 12 s.",
    "build_up": "A sequence from the goalkeeper's possession or receipt until the possession ends or 20 s. Lines broken counts opponent lines (forwards, midfield, back four mean x) a completed pass crosses.",
    "attack_initiator": "In a possession that reaches the final third or a chance, the first player to complete a pass or carry gaining ≥12 units or entering the final third.",
    "chance": "A shot or a completed entry into the box. Time to chance is measured from the start of the possession.",
    "pass_angle": "Direction of a pass relative to straight at goal: 0° is straight forward, positive toward the passer's right.",
    "pass_speed": "Mean ball speed between leaving the passer and arriving, from 5 Hz synthetic ball positions.",
    "corner_swing": "Measured from the ball's curve: bending toward the goal line is an inswinger. Expected swing follows the kicking foot and corner side.",
    "corner_accuracy": "Distance from where the delivery arrives to the nearest attacker at that moment.",
    "time_to_spot": "Time from the delivery being struck until the nearest attacker at arrival is within 1.5 m of where it lands.",
}

LIMITATIONS = [
    "Synthetic tracking: positions are generated from fictional tendencies at 5 Hz. They are not measured players.",
    "Positions agree with recorded events where events exist. Between them, motion is illustrative.",
    "Offside uses one point per player and ignores body parts, deliberate play and refereeing judgement.",
    "Tendencies describe what happened in the released sample. They are not predictions, and small samples are labelled.",
    "Opportunities point to repeated patterns an opponent could test. They do not claim that a goal or chance would follow.",
]


def r1(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def avg(values) -> float | None:
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def name(match: Match, pid: str) -> str:
    return next((p.display_name for p in match.roster if p.player_id == pid), pid)


def team_name(match: Match, team: str) -> str:
    return match.home.display_name if match.home.team_id == team else match.away.display_name


ROLE_NAMES = {"GK": "goalkeeper", "RB": "right-back", "LB": "left-back", "RCB": "right centre-back", "LCB": "left centre-back",
              "DM": "defensive midfielder", "RCM": "right central midfielder", "LCM": "left central midfielder",
              "ST": "striker", "RW": "right winger", "LW": "left winger"}


def label(match: Match, pid: str) -> str:
    return f"{name(match, pid)} ({ROLE_NAMES[role(pid)]})"


def velocity(a: Frame, b: Frame, pid: str) -> tuple[float, float]:
    (x1, y1), (x2, y2) = a.players[pid], b.players[pid]
    dt = (b.t - a.t) / 1000
    return (x2 - x1) * X_M / dt, (y2 - y1) * Y_M / dt


def second_last_x(frame: Frame, team: str) -> float:
    return sorted((frame.players[p][0] for p in team_players(team)), reverse=True)[1]


# ------------------------------------------------------------- measurements
@dataclass
class RunMeasure:
    player_id: str
    onset_ms: int
    targeted: bool
    offside: bool
    in_behind: bool
    defender_id: str | None
    reaction_ms: int | None


@dataclass
class AttackMeasure:
    episode: Episode
    t0: int
    trap: bool
    onsets: dict[str, int]
    lags: dict[str, float | None]
    late: set[str]
    depth_at_pass: dict[str, float]
    step_speed: float | None
    line_height: float
    line_spread: float
    runs: list[RunMeasure]
    caught: list[str]
    broken_by: dict[str, list[str]]
    width: tuple[float, float]
    length: tuple[float, float]
    shift_to_ball: float | None
    shift_times: dict[str, int]
    assignments: dict[str, str]
    early_releases: list[tuple[str, str]]
    through_ball: bool
    pass_speed: float | None
    offside_line: float


@dataclass
class PossessionMeasure:
    episode: Episode
    trigger: str | None = None
    onset_ms: int | None = None
    time_to_pressure: int | None = None
    closing_speed: float | None = None


@dataclass
class CornerMeasure:
    episode: Episode
    swing: str
    curve: float
    flight_ms: int
    speed: float
    target: str
    accuracy: float
    time_to_spot: int | None
    arrival_vs_ball: int | None
    in_box: int


def measure_attack(ep: Episode, event) -> AttackMeasure:
    team, opponent = ep.team_id, ep.opponent_id
    t0 = event.event_time_ms
    back = [player_for(opponent, r) for r in BACK_FOUR]
    f0 = ep.frame_at(t0)
    xs = {d: f0.players[d][0] for d in back}
    line_x = median(xs.values())
    window = [f for f in ep.frames if t0 - 2_000 <= f.t <= t0]
    onsets, speeds = {}, []
    for d in back:
        ups = [(b.t, -velocity(a, b, d)[0]) for a, b in zip(window, window[1:])]
        for (t1, v1), (_t2, v2) in zip(ups, ups[1:]):
            if v1 >= STEP_SPEED_MPS and v2 >= STEP_SPEED_MPS:
                onsets[d] = t1 - FRAME_MS
                break
        speeds.extend(v for _t, v in ups if v >= STEP_SPEED_MPS)
    trap = len(onsets) >= 3
    lags, late = {}, set()
    if trap:
        centre = median(onsets.values())
        for d in back:
            lags[d] = onsets[d] - centre if d in onsets else None
            if d not in onsets or onsets[d] - centre >= LATE_STEP_MS:
                late.add(d)
    depth = {d: (xs[d] - line_x) * X_M for d in back}
    offside_line = second_last_x(f0, opponent)

    # Runs by any outfield attacker.
    runs = []
    frames = ep.frames
    for pid in team_players(team):
        if role(pid) == "GK":
            continue
        streak, onset = 0, None
        for a, b in zip(frames, frames[1:]):
            if b.t < t0 - 1_800 or b.t > t0 + 600:
                streak = 0
                continue
            if velocity(a, b, pid)[0] >= RUN_SPEED_MPS:
                streak += 1
                if streak == 3:
                    onset = b.t - 3 * FRAME_MS
                    break
            else:
                streak = 0
        if onset is None or onset > t0:
            continue
        start = ep.frame_at(onset)
        if start.players[pid][0] < second_last_x(start, opponent) - 12:
            continue
        x_pass = f0.players[pid][0]
        offside = x_pass > offside_line and x_pass > f0.ball[0] and x_pass > 50
        later = [f for f in frames if t0 <= f.t <= t0 + 800]
        in_behind = not offside and any(f.players[pid][0] > median(f.players[d][0] for d in back) + 1 for f in later)
        lane = start.players[pid][1]
        channel = min(back, key=lambda d: abs(start.players[d][1] - lane))
        reaction = None
        drops = [(b.t, velocity(a, b, channel)[0]) for a, b in zip(frames, frames[1:]) if onset <= a.t and b.t <= t0 + 600]
        for (t1, v1), (_t2, v2) in zip(drops, drops[1:]):
            if t1 - FRAME_MS > t0 + 200:
                break
            if v1 >= DROP_SPEED_MPS and v2 >= DROP_SPEED_MPS:
                reaction = t1 - FRAME_MS - onset
                break
        runs.append(RunMeasure(pid, onset, pid == event.detail.recipient_id, offside, in_behind,
                               channel if reaction is not None and reaction <= 1_200 else None, reaction))
    caught = [r.player_id for r in runs if r.offside]
    broken = {}
    if trap and late:
        on_time = [p for p in team_players(opponent) if p not in late]
        strict_line = sorted((f0.players[p][0] for p in on_time), reverse=True)[1]
        for run in runs:
            x = f0.players[run.player_id][0]
            if not run.offside and x > strict_line and x > f0.ball[0] and x > 50:
                broken[run.player_id] = sorted(d for d in late if f0.players[d][0] >= x)

    outfield = [p for p in team_players(opponent) if role(p) != "GK"]
    first = ep.frames[0]

    def width(f):
        ys = [f.players[p][1] for p in outfield]
        return (max(ys) - min(ys)) * Y_M

    def length(f):
        xs_ = [f.players[p][0] for p in outfield]
        return (max(xs_) - min(xs_)) * X_M

    side = f0.ball[1] - 50
    shift = None
    if abs(side) >= 5:
        before = mean(first.players[p][1] for p in outfield)
        after = mean(f0.players[p][1] for p in outfield)
        shift = (after - before) * Y_M * (1 if side > 0 else -1)
    last = ep.frames[-1]
    shift_times = {}
    for p in outfield:
        moved = last.players[p][1] - first.players[p][1]
        if abs(moved) * Y_M < 2:
            continue
        for f in ep.frames:
            if abs(f.players[p][1] - first.players[p][1]) >= .9 * abs(moved):
                shift_times[p] = f.t
                break

    # Marking: nearest-defender assignments at the start of the move.
    attackers = [p for p in team_players(team) if role(p) != "GK" and first.players[p][0] >= 55]
    pairs = sorted(((metres(first.players[a], first.players[d]), a, d) for a in attackers for d in outfield))
    assignments, used = {}, set()
    for _distance, a, d in pairs:
        if a not in assignments and d not in used:
            assignments[a] = d
            used.add(d)
    releases = []
    for a, d in assignments.items():
        if metres(f0.players[d], f0.ball) <= 5 and metres(f0.players[a], f0.ball) > 5:
            if min(metres(f0.players[a], f0.players[o]) for o in outfield) > 5:
                releases.append((d, a))

    flight = [f for f in ep.frames if f.t >= t0]
    end = (event.detail.end.x, event.detail.end.y)
    arrive = next((f for f in flight if metres(f.ball, end) < .3), None)
    pass_speed = None
    if arrive and arrive.t > t0:
        path = sum(metres(a.ball, b.ball) for a, b in zip(flight, flight[1:]) if b.t <= arrive.t)
        pass_speed = path / ((arrive.t - t0) / 1000)
    return AttackMeasure(ep, t0, trap, onsets, lags, late, depth, avg(speeds), (100 - line_x) * X_M,
                         (max(xs.values()) - min(xs.values())) * X_M, runs, caught, broken, (width(first), width(f0)),
                         (length(first), length(f0)), shift, shift_times, assignments, releases,
                         end[0] > line_x, pass_speed, offside_line)


def measure_possession(ep: Episode) -> PossessionMeasure:
    result = PossessionMeasure(ep)
    pressers = [p for p in team_players(ep.opponent_id) if role(p) != "GK"]
    early = [f for f in ep.frames if f.t <= ep.start_ms + 3_000]
    streaks = dict.fromkeys(pressers, 0)
    for a, b in zip(early, early[1:]):
        for p in pressers:
            vx, vy = velocity(a, b, p)
            dx, dy = (a.ball[0] - a.players[p][0]) * X_M, (a.ball[1] - a.players[p][1]) * Y_M
            distance = math.hypot(dx, dy)
            toward = (vx * dx + vy * dy) / distance if distance > .5 else 0
            streaks[p] = streaks[p] + 1 if toward >= PRESS_SPEED_MPS and distance <= PRESS_DISTANCE_M else 0
            if streaks[p] == 2 and result.trigger is None:
                result.trigger, result.onset_ms = p, a.t - FRAME_MS
        if result.trigger:
            break
    if result.trigger:
        p = result.trigger
        sprint = [f for f in ep.frames if f.t >= result.onset_ms]
        reached = next((f for f in sprint if metres(f.players[p], f.ball) <= PRESSURE_DISTANCE_M), None)
        if reached:
            result.time_to_pressure = reached.t - result.onset_ms
            covered = sum(metres(a.players[p], b.players[p]) for a, b in zip(sprint, sprint[1:]) if b.t <= reached.t)
            result.closing_speed = covered / max(.2, (reached.t - result.onset_ms) / 1000)
    return result


def measure_corner(ep: Episode, event) -> CornerMeasure:
    t0 = event.event_time_ms
    flag = (event.detail.start.x, event.detail.start.y)
    landing = (event.detail.end.x, event.detail.end.y)
    flight = [f for f in ep.frames if f.t >= t0]
    arrive = next((f for f in flight if metres(f.ball, landing) < .3), flight[-1])
    path = [f for f in flight if f.t <= arrive.t]
    length = sum(metres(a.ball, b.ball) for a, b in zip(path, path[1:]))
    # Signed deviation from the straight line flag→landing; toward the goal line (+x) is inswinging.
    cx, cy = (landing[0] - flag[0]) * X_M, (landing[1] - flag[1]) * Y_M
    chord = math.hypot(cx, cy)
    deviations = []
    for f in path:
        px, py = (f.ball[0] - flag[0]) * X_M, (f.ball[1] - flag[1]) * Y_M
        along = (px * cx + py * cy) / chord
        perp = (px - along * cx / chord, py - along * cy / chord)
        deviations.append(perp[0])  # x-component of the perpendicular offset
    curve = max(deviations, key=abs) if deviations else 0.0
    attackers = [p for p in team_players(ep.team_id) if p != event.player_id and role(p) != "GK"]
    target = min(attackers, key=lambda p: metres(arrive.players[p], landing))
    accuracy = metres(arrive.players[target], landing)
    reached = next((f for f in ep.frames if metres(f.players[target], landing) <= 1.5), None)
    strike = ep.frame_at(t0)
    in_box = sum(1 for p in attackers if strike.players[p][0] >= 83 and 20 <= strike.players[p][1] <= 80)
    return CornerMeasure(ep, "inswinger" if curve > 0 else "outswinger", abs(curve), arrive.t - t0,
                         length / max(.2, (arrive.t - t0) / 1000), target, accuracy,
                         None if reached is None else reached.t - t0, None if reached is None else reached.t - arrive.t, in_box)


def corner_zone(point: tuple[float, float], side: str) -> str:
    x, y = point
    near = y < 50 if side == "left" else y > 50
    if x >= 94.5 and 40 <= y <= 60:
        return "six_yard" if 46 <= y <= 54 else "near_post" if near else "far_post"
    if x >= 92:
        return "near_post" if near else "far_post"
    if 85 <= x < 92 and abs(y - 50) <= 12:
        return "penalty_spot"
    return "other"


# ------------------------------------------------------------------ engine
@dataclass
class Prepared:
    episodes: dict[str, Episode]
    attacks: dict[str, AttackMeasure] = field(default_factory=dict)
    possessions: dict[str, PossessionMeasure] = field(default_factory=dict)
    corners: dict[str, CornerMeasure] = field(default_factory=dict)
    by_anchor: dict[str, Episode] = field(default_factory=dict)
    available: bool = True


class TacticalEngine:
    """Builds and measures every episode once per fixture; reports filter by the observed prefix."""

    def __init__(self, match: Match, fixture: list[EventEnvelope]):
        self.match, self.fixture = match, fixture
        self._prepared: Prepared | None = None
        self._lock = threading.Lock()
        self._cache: dict[tuple, tuple] = {}

    def prepared(self) -> Prepared:
        with self._lock:
            if self._prepared is None:
                self._prepared = self._prepare()
            return self._prepared

    def _prepare(self) -> Prepared:
        plans = generate_plans(self.match.seed)
        payloads = {e.event_id: e.payload for e in self.fixture if e.revision == 1 and e.payload}
        if any(event_id not in payloads for event_id in plans):
            # A fixture that no longer matches its plan cannot be tracked honestly.
            return Prepared({}, available=False)
        episodes = build_tracking(self.match, self.fixture, plans, self.match.seed)
        prepared = Prepared({ep.episode_id: ep for ep in episodes})
        for ep in episodes:
            event = payloads[ep.anchor_event_id]
            prepared.by_anchor[ep.anchor_event_id] = ep
            if ep.kind == "attack":
                prepared.attacks[ep.episode_id] = measure_attack(ep, event)
            elif ep.kind == "possession":
                prepared.possessions[ep.episode_id] = measure_possession(ep)
            else:
                prepared.corners[ep.episode_id] = measure_corner(ep, event)
        return prepared

    def report(self, records: dict[str, EventEnvelope], playhead_ms: int) -> dict:
        prepared = self.prepared()
        # Whole match seconds: the effective cutoff never runs ahead of the playhead.
        cutoff = playhead_ms // 1000 * 1000
        key = (cutoff, len(records), sum(e.revision for e in records.values()))
        if key in self._cache:
            return self._cache[key]
        result = Report(self.match, prepared, canonical_order(records), records, cutoff).build()
        if len(self._cache) > 64:
            self._cache.clear()
        self._cache[key] = result
        return result


class Report:
    def __init__(self, match: Match, prepared: Prepared, ordered: list[EventEnvelope], records: dict[str, EventEnvelope], playhead: int):
        self.match, self.prepared, self.ordered, self.records, self.playhead = match, prepared, ordered, records, playhead
        self.teams = [match.home.team_id, match.away.team_id]
        self.released = set()
        for ep in prepared.episodes.values():
            record = records.get(ep.anchor_event_id)
            if record and record.operation == "upsert" and record.payload and ep.end_ms <= playhead:
                self.released.add(ep.episode_id)
        self.observations: list[TacticalObservation] = []
        self.moments: list[KeyMoment] = []

    # -------------------------------------------------------------- helpers
    def attacks_against(self, team: str) -> list[AttackMeasure]:
        return [m for i, m in self.prepared.attacks.items() if i in self.released and m.episode.opponent_id == team]

    def attacks_by(self, team: str) -> list[AttackMeasure]:
        return [m for i, m in self.prepared.attacks.items() if i in self.released and m.episode.team_id == team]

    def ref(self, event_id: str) -> str:
        return self.records[event_id].ref

    def observe(self, category, kind, subject, for_team, headline, detail, players, sample, episodes, events=(), moment=None):
        oid = f"obs_{category}_{subject}_{len(self.observations) + 1}"
        self.observations.append(TacticalObservation(observation_id=oid, category=category, kind=kind, subject_team_id=subject,
            for_team_id=for_team, headline=headline[:140], detail=detail[:600], player_ids=list(dict.fromkeys(players)), sample_size=sample,
            evidence=TacticalEvidence(episode_ids=sorted(set(episodes))[-40:], event_refs=list(dict.fromkeys(events))[-40:]), moment_id=moment))

    def moment(self, ep: Episode, t: int, category: str, title: str, highlight: list[str], line: float | None = None, path=None) -> str:
        frame = ep.frame_at(t)
        mid = f"moment_{category}_{ep.anchor_event_id}"
        if any(m.moment_id == mid for m in self.moments):
            return mid
        self.moments.append(KeyMoment(moment_id=mid, category=category, time_ms=frame.t, period=ep.period, team_id=ep.team_id,
            title=title[:140], ball={"x": frame.ball[0], "y": frame.ball[1]},
            players=[MomentPlayer(player_id=p, team_id=p.rsplit("_", 1)[0], x=x, y=y) for p, (x, y) in frame.players.items()],
            offside_line_x=line, highlight_ids=highlight, path=[{"x": x, "y": y} for x, y in (path or [])], event_ref=self.ref(ep.anchor_event_id)))
        return mid

    # ------------------------------------------------------------- sections
    def offside_trap(self, team: str) -> OffsideTrap:
        faced = self.attacks_against(team)
        traps = [m for m in faced if m.trap]
        defenders = []
        for d in [player_for(team, r) for r in BACK_FOUR]:
            lags = [m.lags[d] for m in traps if m.lags.get(d) is not None]
            late = [m for m in traps if d in m.late]
            onside = sum(1 for m in traps for broken in m.broken_by.values() if d in broken)
            defenders.append(DefenderStep(player_id=d, traps=len(traps), steps=sum(1 for m in traps if d in m.onsets), late_steps=len(late),
                mean_lag_ms=r1(avg(lags)), mean_depth_at_pass_m=r1(avg(m.depth_at_pass[d] for m in traps)), runners_played_onside=onside))
        trap = OffsideTrap(attacks_faced=len(faced), traps=len(traps), caught_offside=sum(1 for m in traps if m.caught),
            broken=sum(1 for m in traps if m.broken_by), mean_step_speed_mps=r1(avg(m.step_speed for m in traps)),
            mean_line_height_m=r1(avg(m.line_height for m in faced)), mean_line_spread_m=r1(avg(m.line_spread for m in faced)), defenders=defenders)
        opponent = other(team)
        if len(traps) >= 3:
            self.observe("offside_trap", "tendency", team, opponent, f"{team_name(self.match, team)} stepped up as a line in {len(traps)} of {len(faced)} attacks",
                f"Mean step speed {trap.mean_step_speed_mps} m/s; the line sat a mean {trap.mean_line_height_m} m from goal. "
                f"{trap.caught_offside} trap(s) left a runner in an offside position and {trap.broken} were broken by a late step.",
                [], len(faced), [m.episode.episode_id for m in traps])
        for row in defenders:
            share = row.late_steps / row.traps if row.traps else 0
            if row.traps >= 3 and row.late_steps >= 2 and share >= .5:
                d = row.player_id
                episodes = [m for m in traps if d in m.late]
                lanes = [m.episode.frame_at(m.t0).players[d][1] for m in episodes]
                lane = mean(lanes)
                runners = {}
                for m in episodes:
                    for run in m.runs:
                        if abs(m.episode.frame_at(run.onset_ms).players[run.player_id][1] - lane) <= 18:
                            runners[run.player_id] = runners.get(run.player_id, 0) + 1
                exploit = max(runners, key=runners.get) if runners else None
                broken = [m for m in episodes if any(d in ds for ds in m.broken_by.values())]
                moment = None
                if broken:
                    m = broken[-1]
                    runner = next(p for p, ds in m.broken_by.items() if d in ds)
                    moment = self.moment(m.episode, m.t0, "offside_trap", f"{name(self.match, d)} steps late; {name(self.match, runner)} stays onside",
                        [d, runner], m.offside_line)
                side = "left" if role(d) in ("LB", "LCB") else "right"
                detail = (f"{label(self.match, d)} started the step a mean {row.mean_lag_ms:.0f} ms after the rest of the line in {row.late_steps} of {row.traps} traps "
                          f"and was {row.mean_depth_at_pass_m} m deeper than the line at the pass. A late step there kept {row.runners_played_onside} runner(s) onside.")
                if exploit:
                    detail += f" {label(self.match, exploit)} made {runners[exploit]} run(s) in that channel during those traps."
                self.observe("offside_trap", "opportunity", team, opponent, f"{team_name(self.match, team)}'s line steps up late on its {side}",
                    detail, [d] + ([exploit] if exploit else []), row.traps, [m.episode.episode_id for m in episodes],
                    [m.episode.anchor_ref for m in episodes], moment)
        return trap

    def shape(self, team: str) -> ShapeShift:
        faced = self.attacks_against(team)
        outfield = [p for p in team_players(team) if role(p) != "GK"]
        lags: dict[str, list[float]] = {}
        for m in faced:
            if len(m.shift_times) >= 4:
                centre = median(m.shift_times.values())
                for p, t in m.shift_times.items():
                    lags.setdefault(p, []).append(t - centre)
        shift_lags = sorted((ShiftLag(player_id=p, shifts=len(v), mean_lag_ms=round(mean(v), 1)) for p, v in lags.items() if len(v) >= 2),
                            key=lambda s: -s.mean_lag_ms)
        marking = {p: {"assignments": 0, "early": 0, "runs": 0, "tracked": 0, "late": 0, "reactions": []} for p in outfield}
        follow_total = follow_hits = 0
        release_eps: dict[str, list] = {}
        for m in faced:
            for d in m.assignments.values():
                marking[d]["assignments"] += 1
            for d, a in m.early_releases:
                marking[d]["early"] += 1
                release_eps.setdefault(d, []).append((m, a))
            if m.trap:
                continue
            for run in m.runs:
                f = m.episode.frame_at(run.onset_ms)
                channel = min((player_for(team, r) for r in BACK_FOUR), key=lambda d: abs(f.players[d][1] - f.players[run.player_id][1]))
                marking[channel]["runs"] += 1
                follow_total += 1
                if run.defender_id and run.reaction_ms is not None:
                    follow_hits += 1
                    marking[channel]["reactions"].append(run.reaction_ms)
                    if run.reaction_ms >= LATE_REACTION_MS:
                        marking[channel]["late"] += 1
                    else:
                        marking[channel]["tracked"] += 1
        rate = follow_hits / follow_total if follow_total else None
        system = "insufficient_evidence" if follow_total < 5 else "man_oriented" if rate >= .6 else "zonal" if rate <= .35 else "mixed"
        records = [MarkingRecord(player_id=p, assignments=v["assignments"], early_releases=v["early"], runs_faced=v["runs"], tracked=v["tracked"],
                                 late_reactions=v["late"], mean_reaction_ms=r1(avg(v["reactions"]))) for p, v in marking.items()]
        shape = ShapeShift(attacks_faced=len(faced), mean_width_before_m=r1(avg(m.width[0] for m in faced)), mean_width_at_pass_m=r1(avg(m.width[1] for m in faced)),
            mean_length_before_m=r1(avg(m.length[0] for m in faced)), mean_length_at_pass_m=r1(avg(m.length[1] for m in faced)),
            mean_shift_to_ball_m=r1(avg(m.shift_to_ball for m in faced)), shift_lags=shift_lags[:6], marking_system=system,
            follow_rate=None if rate is None else round(100 * rate, 1), marking=records)
        opponent = other(team)
        if len(faced) >= 3:
            names = {"man_oriented": "man-oriented", "zonal": "zonal", "mixed": "mixed", "insufficient_evidence": "not yet clear"}
            self.observe("shape", "tendency", team, opponent, f"{team_name(self.match, team)} shift {shape.mean_shift_to_ball_m} m toward the ball as attacks build",
                f"Outfield width goes from {shape.mean_width_before_m} m to {shape.mean_width_at_pass_m} m and the block's length from {shape.mean_length_before_m} m to "
                f"{shape.mean_length_at_pass_m} m by the pass. Marking reads as {names[system]}: the nearest defender dropped with "
                f"{shape.follow_rate if shape.follow_rate is not None else '—'}% of runs outside traps.", [], len(faced), [m.episode.episode_id for m in faced])
        if shift_lags and shift_lags[0].mean_lag_ms >= 400 and shift_lags[0].shifts >= 3:
            slow = shift_lags[0]
            self.observe("shape", "opportunity", team, opponent, f"{name(self.match, slow.player_id)} is last to finish the shift",
                f"{label(self.match, slow.player_id)} finished the lateral shift a mean {slow.mean_lag_ms:.0f} ms after the unit's median in {slow.shifts} moves, "
                f"so that channel stays open for longer after the ball changes side.", [slow.player_id], slow.shifts,
                [m.episode.episode_id for m in faced if slow.player_id in m.shift_times])
        for p, v in marking.items():
            if v["early"] >= 2 and v["early"] >= .25 * v["assignments"]:
                eps = release_eps[p]
                m, attacker = eps[-1]
                moment = self.moment(m.episode, m.t0, "marking", f"{name(self.match, p)} leaves {name(self.match, attacker)} to engage the ball", [p, attacker])
                freed = sorted({a for _m, a in eps})
                self.observe("marking", "opportunity", team, opponent, f"{name(self.match, p)} leaves their man to engage the ball",
                    f"{label(self.match, p)} was engaging the ball carrier at the pass while their starting assignment stood free in {v['early']} of "
                    f"{v['assignments']} moves. Freed: {', '.join(name(self.match, a) for a in freed)}.",
                    [p] + freed, v["assignments"], [mm.episode.episode_id for mm, _a in eps], [mm.episode.anchor_ref for mm, _a in eps], moment)
            if v["runs"] >= 3 and v["late"] >= 2 and v["late"] >= v["tracked"]:
                self.observe("marking", "opportunity", team, opponent, f"{name(self.match, p)} reacts late to runs",
                    f"{label(self.match, p)} started dropping a mean {avg(v['reactions']):.0f} ms after the run began, late in {v['late']} of {v['runs']} runs in their channel.",
                    [p], v["runs"], [m.episode.episode_id for m in faced if not m.trap])
        return shape

    def possession_outcome(self, ep: Episode) -> tuple[str, int | None] | None:
        team, t0 = ep.team_id, ep.start_ms
        anchor = self.records[ep.anchor_event_id].payload
        keeper = player_for(team, "GK")
        later = [e.payload for e in self.ordered if e.payload.event_time_ms > t0 or (e.payload.event_time_ms == t0 and e.event_id > ep.anchor_event_id)]
        for event in later:
            t = event.event_time_ms
            if t - t0 > PRESS_WINDOW_MS:
                break
            if event.kind == "POSSESSION":
                return ("regained", t - t0) if event.team_id != team else ("retained", None)
            if event.kind in ("STOPPAGE", "PERIOD_END"):
                return "stoppage", None
            if event.team_id != team or event.possession_id != anchor.possession_id:
                continue
            if event.kind == "PASS" and event.detail.completed and event.detail.recipient_id == keeper:
                return "forced_to_keeper", t - t0
            if event.kind in ("PASS", "CARRY") and (event.kind == "CARRY" or event.detail.completed) and event.detail.end.x >= 50:
                return "played_through", None
        if self.playhead >= t0 + PRESS_WINDOW_MS:
            return "retained", None
        return None

    def press(self, team: str) -> Press:
        """``team`` presses; the episodes are the opponent's possessions."""
        measures = [m for i, m in self.prepared.possessions.items() if i in self.released and m.episode.opponent_id == team]
        pressing = {"yes": [], "no": []}
        triggers: dict[str, list[PossessionMeasure]] = {}
        holders: dict[str, list[bool]] = {}
        for m in measures:
            outcome = self.possession_outcome(m.episode)
            if outcome is None:
                continue
            pressing["yes" if m.trigger else "no"].append((m, outcome))
            if m.trigger:
                triggers.setdefault(m.trigger, []).append(m)
            holder = self.records[m.episode.anchor_event_id].payload.player_id
            holders.setdefault(holder, []).append(bool(m.trigger))

        def outcomes(rows) -> PressOutcomes:
            counts = {k: 0 for k in ("regained", "forced_to_keeper", "played_through", "stoppage", "retained")}
            keeper, regain = [], []
            for _m, (kind, t) in rows:
                counts[kind] += 1
                (keeper if kind == "forced_to_keeper" else regain if kind == "regained" else []).append(t)
            return PressOutcomes(possessions=len(rows), **counts, mean_time_to_keeper_ms=r1(avg(keeper)), mean_time_to_regain_ms=r1(avg(regain)))

        trigger_rows = sorted((PressTrigger(player_id=p, presses=len(v), mean_time_to_pressure_ms=r1(avg(m.time_to_pressure for m in v)),
            mean_closing_speed_mps=r1(avg(m.closing_speed for m in v))) for p, v in triggers.items()), key=lambda r: -r.presses)
        target_rows = sorted((PressTarget(player_id=p, possessions=len(v), presses=sum(v), press_rate=round(100 * sum(v) / len(v), 1))
                              for p, v in holders.items()), key=lambda r: (-r.presses, -r.press_rate))
        pressed = [m for m, _o in pressing["yes"]]
        result = Press(opportunities=len(pressing["yes"]) + len(pressing["no"]), presses=len(pressed), triggers=trigger_rows, targets=target_rows,
            when_pressing=outcomes(pressing["yes"]), when_not_pressing=outcomes(pressing["no"]),
            mean_time_to_pressure_ms=r1(avg(m.time_to_pressure for m in pressed)), mean_closing_speed_mps=r1(avg(m.closing_speed for m in pressed)))
        opponent = other(team)
        if result.presses >= 3:
            top = trigger_rows[0]
            share = 100 * top.presses / result.presses
            m = triggers[top.player_id][-1]
            moment = self.moment(m.episode, m.onset_ms, "press", f"{name(self.match, top.player_id)} triggers the press",
                [top.player_id, self.records[m.episode.anchor_event_id].payload.player_id])
            self.observe("press", "tendency", team, opponent, f"{name(self.match, top.player_id)} triggers {share:.0f}% of {team_name(self.match, team)}'s presses",
                f"{label(self.match, top.player_id)} started {top.presses} of {result.presses} presses, closing to within 2.5 m in a mean "
                f"{(top.mean_time_to_pressure_ms or 0) / 1000:.1f} s at {top.mean_closing_speed_mps} m/s.",
                [top.player_id], result.presses, [x.episode.episode_id for x in triggers[top.player_id]], moment=moment)
            wp, wn = result.when_pressing, result.when_not_pressing
            if wp.possessions >= 3:
                keeper_rate = 100 * wp.forced_to_keeper / wp.possessions
                calm_rate = 100 * wn.forced_to_keeper / wn.possessions if wn.possessions else 0
                timing = f" in a mean {wp.mean_time_to_keeper_ms / 1000:.1f} s" if wp.mean_time_to_keeper_ms else ""
                self.observe("press", "tendency", team, opponent, f"Pressed, {team_name(self.match, opponent)} went back to the keeper {keeper_rate:.0f}% of the time",
                    f"{wp.forced_to_keeper} of {wp.possessions} pressed possessions were recycled to the goalkeeper{timing}, against {calm_rate:.0f}% "
                    f"when not pressed. {wp.regained} were regained and {wp.played_through} were played past halfway.",
                    [], wp.possessions, [m.episode.episode_id for m in pressed])
            base = [t for t in target_rows if t.possessions >= 3]
            if base:
                favourite = max(base, key=lambda t: (t.press_rate, t.presses))
                others = [t for t in target_rows if t.player_id != favourite.player_id]
                rest_rate = 100 * sum(t.presses for t in others) / max(1, sum(t.possessions for t in others))
                if favourite.presses >= 3 and favourite.press_rate >= 1.5 * rest_rate:
                    self.observe("press", "tendency", team, opponent, f"{team_name(self.match, team)} press harder when {name(self.match, favourite.player_id)} has the ball",
                        f"{label(self.match, favourite.player_id)} was pressed in {favourite.presses} of {favourite.possessions} possessions they started "
                        f"({favourite.press_rate:.0f}%), against {rest_rate:.0f}% for their teammates.", [favourite.player_id], favourite.possessions,
                        [m.episode.episode_id for m in measures if self.records[m.episode.anchor_event_id].payload.player_id == favourite.player_id])
        return result

    def runs(self, team: str) -> list[Runner]:
        rows: dict[str, list[RunMeasure]] = {}
        episodes: dict[str, list[str]] = {}
        drawn = total = 0
        for m in self.attacks_by(team):
            for run in m.runs:
                rows.setdefault(run.player_id, []).append(run)
                episodes.setdefault(run.player_id, []).append(m.episode.episode_id)
                if not m.trap:
                    total += 1
                    drawn += run.defender_id is not None
        result = []
        for p, runs in rows.items():
            outside = [r for r, eid in zip(runs, episodes[p]) if not self.prepared.attacks[eid].trap]
            result.append(Runner(player_id=p, runs=len(runs), in_behind=sum(r.in_behind for r in runs), targeted=sum(r.targeted for r in runs),
                offside=sum(r.offside for r in runs), drew_defender=sum(r.defender_id is not None for r in outside),
                drag_rate=round(100 * sum(r.defender_id is not None for r in outside) / len(outside), 1) if outside else None))
        result.sort(key=lambda r: -r.runs)
        opponent = other(team)
        if result and result[0].runs >= 3:
            top = result[0]
            decoys = top.runs - top.targeted
            pick = next((m for m in reversed(self.attacks_by(team)) for r in m.runs if r.player_id == top.player_id and r.defender_id and not r.targeted), None)
            moment = None
            if pick:
                run = next(r for r in pick.runs if r.player_id == top.player_id and r.defender_id)
                moment = self.moment(pick.episode, pick.t0, "runs", f"{name(self.match, top.player_id)}'s run pulls {name(self.match, run.defender_id)} back",
                    [top.player_id, run.defender_id], pick.offside_line)
            self.observe("runs", "tendency", team, team, f"{name(self.match, top.player_id)} makes the most runs in behind",
                f"{label(self.match, top.player_id)} made {top.runs} runs ({top.in_behind} got beyond the line, {top.targeted} were found by the pass, "
                f"{decoys} were not). A defender dropped with {top.drew_defender} of them.", [top.player_id], top.runs, episodes[top.player_id], moment=moment)
        if total >= 5:
            self.observe("runs", "opportunity" if drawn / total >= .5 else "tendency", opponent, team, f"{team_name(self.match, opponent)} defenders drop with {100 * drawn / total:.0f}% of runs",
                f"Outside offside traps, a back-four defender in the runner's channel retreated with {drawn} of {total} {team_name(self.match, team)} runs, "
                "whether or not the runner was the pass target.", [], total, [m.episode.episode_id for m in self.attacks_by(team) if not m.trap])
        return result

    def chance_creation(self, team: str) -> tuple[list[Creator], list[DecisivePass]]:
        possessions: dict[str, list] = {}
        for record in self.ordered:
            e = record.payload
            if e.team_id == team and e.possession_id and e.kind in ("POSSESSION", "PASS", "CARRY", "SHOT"):
                possessions.setdefault(e.possession_id, []).append(record)
        creators: dict[str, dict] = {}
        decisive: list[DecisivePass] = []
        for rows in possessions.values():
            start = rows[0].payload
            if start.kind != "POSSESSION":
                continue
            initiator, chance, last_pass, entered = None, None, None, False
            for record in rows:
                e = record.payload
                if e.kind == "SHOT":
                    chance = chance or (record, e.event_time_ms)
                    break
                completed = e.kind == "CARRY" or (e.kind == "PASS" and e.detail.completed)
                if e.kind in ("PASS", "CARRY") and completed:
                    gain = e.detail.end.x - e.detail.start.x
                    final = e.detail.start.x < FINAL_THIRD_X <= e.detail.end.x
                    entered |= e.detail.end.x >= FINAL_THIRD_X
                    if initiator is None and role(e.player_id) != "GK" and (gain >= 12 or final):
                        initiator = e.player_id
                    if e.kind == "PASS":
                        last_pass = record
                    box = e.detail.end.x >= 83 and 20 <= e.detail.end.y <= 80 and not (e.detail.start.x >= 83 and 20 <= e.detail.start.y <= 80)
                    if box and chance is None:
                        chance = (record, e.event_time_ms)
                        break
            if not entered and not chance:
                continue
            if start.detail.start.x >= 99:  # corners are set pieces, not open-play attacks
                continue
            initiator = initiator or next((r.payload.player_id for r in rows if role(r.payload.player_id) != "GK"), None)
            if initiator is None:
                continue
            row = creators.setdefault(initiator, {"attacks": 0, "chances": 0, "times": []})
            row["attacks"] += 1
            if chance:
                row["chances"] += 1
                row["times"].append(chance[1] - start.event_time_ms)
                if last_pass:
                    decisive.append(self.decisive(last_pass, True))
        for m in self.attacks_by(team):
            record = self.records[m.episode.anchor_event_id]
            if m.through_ball and record.payload.detail.start.x >= 50:
                if not any(d.event_ref == record.ref for d in decisive):
                    decisive.append(self.decisive(record, False))
        rows = sorted((Creator(player_id=p, attacks_started=v["attacks"], chances=v["chances"], mean_time_to_chance_ms=r1(avg(v["times"])))
                       for p, v in creators.items()), key=lambda c: (-c.attacks_started, -c.chances))
        decisive.sort(key=lambda d: d.time_ms)
        if rows and rows[0].attacks_started >= 3:
            top = rows[0]
            timing = f", a mean {top.mean_time_to_chance_ms / 1000:.1f} s after the possession began" if top.mean_time_to_chance_ms else ""
            self.observe("chance_creation", "tendency", team, team, f"{name(self.match, top.player_id)} starts the most {team_name(self.match, team)} attacks",
                f"{label(self.match, top.player_id)} made the first progressive action in {top.attacks_started} attacks; {top.chances} reached a shot or box entry{timing}.",
                [top.player_id], top.attacks_started, [], [])
        fast = [d for d in decisive if d.speed_mps is not None]
        if len(fast) >= 3:
            quick = max(fast, key=lambda d: d.speed_mps)
            self.observe("chance_creation", "tendency", team, team, f"{team_name(self.match, team)}'s decisive passes travel at {mean(d.speed_mps for d in fast):.1f} m/s",
                f"Across {len(fast)} through balls and final passes, the mean angle was {mean(abs(d.angle_deg) for d in fast):.0f}° off straight and "
                f"{sum(1 for d in fast if d.through_ball)} went beyond the defensive line. Quickest: {name(self.match, quick.passer_id)} to "
                f"{name(self.match, quick.recipient_id)} at {quick.speed_mps} m/s.", [quick.passer_id, quick.recipient_id], len(fast), [], [d.event_ref for d in fast])
        return rows[:8], decisive[-10:]

    def decisive(self, record: EventEnvelope, chance: bool) -> DecisivePass:
        e = record.payload
        dx, dy = (e.detail.end.x - e.detail.start.x) * X_M, (e.detail.end.y - e.detail.start.y) * Y_M
        ep = self.prepared.by_anchor.get(record.event_id)
        measure = self.prepared.attacks.get(ep.episode_id) if ep and ep.episode_id in self.released else None
        ran = None
        if measure:
            ran = any(r.player_id == e.detail.recipient_id for r in measure.runs)
        return DecisivePass(event_ref=record.ref, time_ms=e.event_time_ms, passer_id=e.player_id, recipient_id=e.detail.recipient_id,
            completed=e.detail.completed, length_m=round(math.hypot(dx, dy), 1), angle_deg=round(math.degrees(math.atan2(dy, dx)), 1),
            speed_mps=r1(measure.pass_speed) if measure else None, through_ball=measure.through_ball if measure else None,
            recipient_ran=ran, led_to_chance=chance)

    def build_up(self, team: str) -> BuildUp:
        keeper = player_for(team, "GK")
        sequences = []
        for index, record in enumerate(self.ordered):
            e = record.payload
            starts = (e.kind == "POSSESSION" and e.team_id == team and e.player_id == keeper) or \
                     (e.kind == "PASS" and e.team_id == team and e.detail.completed and e.detail.recipient_id == keeper)
            if not starts:
                continue
            t0 = e.event_time_ms
            events, ended = [], False
            for later in self.ordered[index + 1:]:
                x = later.payload
                if x.event_time_ms - t0 > BUILD_UP_WINDOW_MS:
                    ended = True
                    break
                if x.kind in ("POSSESSION", "STOPPAGE", "PERIOD_END") or x.possession_id != e.possession_id:
                    ended = True
                    events.append(later)
                    break
                events.append(later)
                if x.kind == "PASS" and x.detail.recipient_id == keeper:
                    ended = True
                    break
            if not ended and self.playhead < t0 + BUILD_UP_WINDOW_MS:
                continue
            sequences.append((record, events))
        lengths, middle, final, lines = [], [], [], []
        attempted = completed = lost = short = long_ = 0
        for record, events in sequences:
            t0 = record.payload.event_time_ms
            first = next((x.payload for x in events if x.payload.kind == "PASS" and x.payload.team_id == team), None)
            if first:
                length = metres((first.detail.start.x, first.detail.start.y), (first.detail.end.x, first.detail.end.y))
                short += length <= 30
                long_ += length > 30
            reach_mid = reach_final = None
            broken = 0
            for x in events:
                p = x.payload
                if p.team_id != team or p.kind not in ("PASS", "CARRY"):
                    if p.kind == "POSSESSION" and p.team_id != team and (100 - p.detail.start.x) < 50:
                        lost += 1
                    continue
                if p.kind == "PASS":
                    attempted += 1
                    completed += p.detail.completed
                if p.kind == "CARRY" or p.detail.completed:
                    if reach_mid is None and p.detail.end.x >= MIDDLE_THIRD_X:
                        reach_mid = p.event_time_ms - t0
                    if reach_final is None and p.detail.end.x >= FINAL_THIRD_X:
                        reach_final = p.event_time_ms - t0
                    if p.kind == "PASS":
                        broken += self.lines_crossed(team, p)
            middle.append(reach_mid)
            final.append(reach_final)
            lines.append(broken)
        result = BuildUp(sequences=len(sequences), short_starts=short, long_starts=long_,
            reached_middle_third=sum(m is not None for m in middle), reached_final_third=sum(f is not None for f in final),
            mean_time_to_middle_ms=r1(avg(middle)), mean_time_to_final_ms=r1(avg(final)), passes_attempted=attempted, passes_completed=completed,
            pass_accuracy=round(100 * completed / attempted, 1) if attempted else None, lines_broken=sum(lines),
            mean_lines_broken=round(mean(lines), 2) if lines else None, lost_in_own_half=lost)
        if result.sequences >= 3:
            style = "short" if short > long_ else "long"
            timing = f" in a mean {result.mean_time_to_middle_ms / 1000:.1f} s" if result.mean_time_to_middle_ms else ""
            self.observe("build_up", "tendency", team, team, f"{team_name(self.match, team)} build {style} from the keeper",
                f"{result.sequences} sequences from the goalkeeper: {short} started short and {long_} long. {result.reached_middle_third} reached the middle third{timing} "
                f"and {result.reached_final_third} the final third. Pass accuracy {result.pass_accuracy}%, {result.mean_lines_broken} opponent lines broken per sequence.",
                [player_for(team, "GK")], result.sequences, [], [r.ref for r, _e in sequences])
        return result

    def lines_crossed(self, team: str, event) -> int:
        t = event.event_time_ms
        for m in self.prepared.possessions.values():
            ep = m.episode
            if ep.episode_id in self.released and ep.team_id == team and ep.start_ms <= t <= ep.end_ms:
                frame = ep.frame_at(t)
                opponent = ep.opponent_id
                count = 0
                for group in (FORWARDS, MIDFIELD, BACK_FOUR):
                    x = mean(frame.players[player_for(opponent, r)][0] for r in group)
                    count += event.detail.start.x < x < event.detail.end.x
                return count
        return 0

    def corners(self, team: str) -> Corners:
        measures = [m for i, m in self.prepared.corners.items() if i in self.released and m.episode.team_id == team]
        deliveries = []
        for m in measures:
            record = self.records[m.episode.anchor_event_id]
            e = record.payload
            side = m.episode.observed["side"]
            kicked = m.episode.observed["taker_foot"]
            deliveries.append(CornerDelivery(event_ref=record.ref, time_ms=e.event_time_ms, taker_id=e.player_id, foot=kicked, side=side,
                swing=m.swing, expected_swing=expected_swing(kicked, side), curve_m=round(m.curve, 1), flight_ms=m.flight_ms, speed_mps=round(m.speed, 1),
                zone=corner_zone((e.detail.end.x, e.detail.end.y), side), target_id=m.target, accuracy_m=round(m.accuracy, 1),
                time_to_spot_ms=m.time_to_spot, arrival_vs_ball_ms=m.arrival_vs_ball, first_contact="attack" if e.detail.completed else "defence",
                attackers_in_box=m.in_box))
        targets: dict[str, list[CornerDelivery]] = {}
        for d in deliveries:
            targets.setdefault(d.target_id, []).append(d)
        target_rows = sorted((TargetMan(player_id=p, deliveries=len(v), reached_spot=sum(d.time_to_spot_ms is not None for d in v),
            mean_time_to_spot_ms=r1(avg(d.time_to_spot_ms for d in v)), mean_arrival_vs_ball_ms=r1(avg(d.arrival_vs_ball_ms for d in v)),
            first_contacts=sum(d.first_contact == "attack" for d in v)) for p, v in targets.items()), key=lambda t: -t.deliveries)
        result = Corners(corners=len(deliveries), deliveries=deliveries, target_men=target_rows)
        opponent = other(team)
        if len(deliveries) >= 2:
            swings = {}
            for d in deliveries:
                swings.setdefault((d.taker_id, d.foot, d.side, d.swing), []).append(d)
            parts = [f"{name(self.match, taker)} ({foot_}-footed) from the {side}: {len(v)} {swing}{'s' if len(v) != 1 else ''}"
                     for (taker, foot_, side, swing), v in sorted(swings.items())]
            matches = sum(d.swing == d.expected_swing for d in deliveries)
            m = measures[-1]
            last = deliveries[-1]
            moment = self.moment(m.episode, last.time_ms + last.flight_ms, "corners", f"{name(self.match, last.taker_id)}'s {last.swing} meets {name(self.match, last.target_id)}",
                [last.taker_id, last.target_id], path=[f.ball for f in m.episode.frames if last.time_ms <= f.t <= last.time_ms + last.flight_ms])
            self.observe("corners", "tendency", team, opponent, f"{team_name(self.match, team)} corners: {mean(d.flight_ms for d in deliveries) / 1000:.1f} s deliveries at {mean(d.speed_mps for d in deliveries):.1f} m/s",
                f"{'; '.join(parts)}. {matches} of {len(deliveries)} curved the way the kicking foot predicts. Deliveries arrived a mean "
                f"{mean(d.accuracy_m for d in deliveries):.1f} m from the nearest attacker and {sum(d.first_contact == 'attack' for d in deliveries)} won first contact.",
                [d.taker_id for d in deliveries], len(deliveries), [m.episode.episode_id for m in measures], [d.event_ref for d in deliveries], moment)
            timed = [t for t in target_rows if t.mean_arrival_vs_ball_ms is not None and t.deliveries >= 2]
            if timed:
                early = min(timed, key=lambda t: t.mean_arrival_vs_ball_ms)
                late = max(timed, key=lambda t: t.mean_arrival_vs_ball_ms)
                detail = f"{label(self.match, early.player_id)} reached the landing spot a mean {early.mean_time_to_spot_ms / 1000:.2f} s after the strike, {abs(early.mean_arrival_vs_ball_ms):.0f} ms {'before' if early.mean_arrival_vs_ball_ms < 0 else 'after'} the ball."
                if late.player_id != early.player_id:
                    detail += f" {label(self.match, late.player_id)} arrived {abs(late.mean_arrival_vs_ball_ms):.0f} ms {'before' if late.mean_arrival_vs_ball_ms < 0 else 'after'} it."
                self.observe("corners", "tendency", team, opponent, f"{name(self.match, early.player_id)} attacks the corner spot first", detail,
                    [t.player_id for t in timed], sum(t.deliveries for t in timed), [m.episode.episode_id for m in measures])
        return result

    def build(self) -> dict:
        teams = {}
        if not self.prepared.available:
            return {"episodes_observed": 0, "teams": {t: self.empty(t) for t in self.teams}, "observations": [], "key_moments": [],
                    "definitions": DEFINITIONS, "limitations": LIMITATIONS + ["Tracking is unavailable because the fixture does not match the tracking source."]}
        for team in self.teams:
            trap = self.offside_trap(team)
            shape = self.shape(team)
            press = self.press(team)
            runs = self.runs(team)
            creators, decisive = self.chance_creation(team)
            teams[team] = TeamTactics(team_id=team, offside_trap=trap, shape=shape, press=press, runs=runs, creators=creators,
                decisive_passes=decisive, build_up=self.build_up(team), corners=self.corners(team))
        order = {"opportunity": 0, "tendency": 1}
        observations = sorted(self.observations, key=lambda o: (order[o.kind], -o.sample_size))
        return {"episodes_observed": len(self.released), "teams": teams, "observations": observations,
                "key_moments": self.moments, "definitions": DEFINITIONS, "limitations": LIMITATIONS}

    def empty(self, team: str) -> TeamTactics:
        none = PressOutcomes(possessions=0, regained=0, forced_to_keeper=0, played_through=0, stoppage=0, retained=0,
                             mean_time_to_keeper_ms=None, mean_time_to_regain_ms=None)
        return TeamTactics(team_id=team, offside_trap=OffsideTrap(attacks_faced=0, traps=0, caught_offside=0, broken=0, mean_step_speed_mps=None,
            mean_line_height_m=None, mean_line_spread_m=None, defenders=[]),
            shape=ShapeShift(attacks_faced=0, mean_width_before_m=None, mean_width_at_pass_m=None, mean_length_before_m=None, mean_length_at_pass_m=None,
                mean_shift_to_ball_m=None, shift_lags=[], marking_system="insufficient_evidence", follow_rate=None, marking=[]),
            press=Press(opportunities=0, presses=0, triggers=[], targets=[], when_pressing=none, when_not_pressing=none,
                        mean_time_to_pressure_ms=None, mean_closing_speed_mps=None),
            runs=[], creators=[], decisive_passes=[], build_up=BuildUp(sequences=0, short_starts=0, long_starts=0, reached_middle_third=0,
                reached_final_third=0, mean_time_to_middle_ms=None, mean_time_to_final_ms=None, passes_attempted=0, passes_completed=0,
                pass_accuracy=None, lines_broken=0, mean_lines_broken=None, lost_in_own_half=0), corners=Corners(corners=0, deliveries=[], target_men=[]))
