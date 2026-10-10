"""Synthetic tactical tracking: 5 Hz positions of all 22 players and the ball.

The event stream records discrete on-ball actions only. Tactical questions (the
offside line, marking, pressing, runs, corner routines) need off-ball positions,
so this module synthesises short tracking episodes anchored to recorded events:

* ``attack``     every forward pass reaching the attacking 40% (x >= 60), from 3 s before the pass
                 until the ball arrives (both teams' shape, the defensive line, runs);
* ``possession`` every possession won or restarted in a team's own half, for up to
                 12 s (the opponent's press and the lines the ball has to pass);
* ``corner``     every corner delivery (target runs, the delivery's flight and curve).

Each frame matches its anchor event exactly where the event is recorded (the ball
leaves the pass origin at the pass time and lands at its recorded end). Between
recorded endpoints the motion is synthetic and illustrative. Coordinates use the
team-in-possession's attacking frame (it attacks toward x = 100; y = 0 is its left
touchline), on a nominal 105 × 68 m pitch so speeds read in metres per second.

Players move according to the server-only tendencies in ``tactical_profiles``; the
analysis in ``tactics`` never reads them and re-measures everything from frames.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from .ingest import canonical_order
from .models import EventEnvelope, Match, PERIOD_MS
from .tactical_profiles import BACK_FOUR, FORWARDS, MIDFIELD, TARGET_MEN, foot, other, player_for, role, tendencies

FRAME_MS = 200
X_M, Y_M = 1.05, .68  # metres per normalised unit along x and y

Point = tuple[float, float]
Motion = Callable[[int], Point]


def metres(a: Point, b: Point) -> float:
    return math.hypot((b[0] - a[0]) * X_M, (b[1] - a[1]) * Y_M)


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


@dataclass
class Frame:
    t: int
    ball: Point
    players: dict[str, Point]


@dataclass
class Episode:
    episode_id: str
    kind: str
    anchor_event_id: str
    anchor_ref: str
    period: int
    team_id: str
    opponent_id: str
    start_ms: int
    end_ms: int
    frames: list[Frame]
    # Observable attributes recorded with the anchor (e.g. the corner taker's kicking foot).
    observed: dict = field(default_factory=dict)

    def frame_at(self, t: int) -> Frame:
        index = round((t - self.start_ms) / FRAME_MS)
        return self.frames[max(0, min(len(self.frames) - 1, index))]


class Track:
    """Piecewise-linear keyframed motion."""

    def __init__(self, t: int, x: float, y: float):
        self.keys: list[tuple[int, float, float]] = [(t, clamp(x), clamp(y))]

    def to(self, t: int, x: float, y: float) -> "Track":
        self.keys.append((t, clamp(x), clamp(y)))
        self.keys.sort(key=lambda key: key[0])
        return self

    def hold(self, t: int) -> "Track":
        x, y = self(t)
        return self.to(t, x, y)

    def __call__(self, t: float) -> Point:
        keys = self.keys
        if t <= keys[0][0]:
            return keys[0][1], keys[0][2]
        for (t1, x1, y1), (t2, x2, y2) in zip(keys, keys[1:]):
            if t <= t2:
                ratio = 0 if t2 == t1 else (t - t1) / (t2 - t1)
                return x1 + (x2 - x1) * ratio, y1 + (y2 - y1) * ratio
        return keys[-1][1], keys[-1][2]


def follower(times: list[int], targets: Callable[[int], Point], speed_mps: Callable[[int], float], start: Point) -> Motion:
    """Velocity-limited pursuit of a moving target, sampled on the frame clock."""
    positions = {}
    x, y = start
    for t in times:
        tx, ty = targets(t)
        dx, dy = tx - x, ty - y
        distance = math.hypot(dx * X_M, dy * Y_M)
        limit = speed_mps(t) * FRAME_MS / 1000
        if distance > limit > 0:
            dx, dy = dx * limit / distance, dy * limit / distance
        x, y = clamp(x + dx), clamp(y + dy)
        positions[t] = (x, y)
    return lambda t: positions[t]


def frame_times(start: int, end: int) -> list[int]:
    return list(range(start, end + 1, FRAME_MS))


def ceil_frame(start: int, t: float) -> int:
    return start + math.ceil((t - start) / FRAME_MS) * FRAME_MS


def team_players(team: str) -> list[str]:
    return [f"{team}_{n:02d}" for n in range(1, 12)]


def by_role(team: str, roles) -> list[str]:
    return [player_for(team, r) for r in roles]


# Lateral offsets in the attacking team's frame (y grows toward its right touchline).
# A defending side faces the other way, so its right-back sits on the low-y flank.
ATTACK_Y = {"RB": 26, "RCB": 10, "LCB": -10, "LB": -26, "RCM": 16, "DM": 0, "LCM": -16, "RW": 32, "ST": 0, "LW": -32}
DEFEND_Y = {key: -value for key, value in ATTACK_Y.items()}


def frames(times: list[int], ball: Motion, motions: dict[str, Motion]) -> list[Frame]:
    return [Frame(t, tuple(round(v, 2) for v in ball(t)), {pid: tuple(round(v, 2) for v in motion(t)) for pid, motion in motions.items()})
            for t in times]


class TrackingBuilder:
    def __init__(self, match: Match, events: list[EventEnvelope], plans: dict[str, dict], seed: int):
        self.match, self.plans, self.seed = match, plans, seed
        records = {}
        for envelope in events:
            if envelope.revision == 1 and envelope.payload:
                records[envelope.event_id] = envelope
        self.ordered = canonical_order(records)

    def rng(self, kind: str, event_id: str) -> random.Random:
        return random.Random(f"{self.seed}:{kind}:{event_id}")

    def build(self) -> list[Episode]:
        episodes = []
        for index, envelope in enumerate(self.ordered):
            event = envelope.payload
            plan = self.plans.get(envelope.event_id, {})
            if event.kind == "PASS" and plan.get("type") == "corner":
                episodes.append(self.corner(envelope, plan))
            elif event.kind == "PASS" and event.detail.end.x >= 60 and event.detail.end.x - event.detail.start.x >= 4:
                episodes.append(self.attack(envelope, index))
            elif event.kind == "POSSESSION" and plan.get("type") == "possession":
                episodes.append(self.possession(envelope, index, plan))
        return episodes

    # ------------------------------------------------------------------ attack
    def attack(self, envelope: EventEnvelope, index: int) -> Episode:
        event = envelope.payload
        rng = self.rng("attack", envelope.event_id)
        team, opponent = event.team_id, other(event.team_id)
        attack_tendency, defence = tendencies(team), tendencies(opponent)
        s = (event.detail.start.x, event.detail.start.y)
        n = (event.detail.end.x, event.detail.end.y)
        t0 = event.event_time_ms
        period_start = (event.period - 1) * PERIOD_MS
        ts = max(period_start, t0 - 3_000)
        recipient, passer = event.detail.recipient_id, event.player_id
        through = n[0] >= 72 and rng.random() < .55
        line = n[0] - rng.uniform(4, 10) if through else n[0] + rng.uniform(3, 8)
        line = clamp(line, max(s[0] + 4, 58), 88)
        trap = rng.random() < defence["trap_rate"]
        centre = 50 + .32 * (s[1] - 50)
        flight = metres(s, n) / max(9.0, attack_tendency["pass_speed_mps"] + rng.uniform(-2.5, 2.5)) * 1000

        # Forwards choose their runs first; defenders may react to them.
        runs: dict[str, dict] = {}
        lanes = {pid: 50 + ATTACK_Y[role(pid)] * .9 + (centre - 50) * .3 for pid in by_role(team, FORWARDS)}
        for pid in by_role(team, FORWARDS):
            if pid == recipient and through:
                runs[pid] = {"onset": t0 - rng.uniform(500, 900), "speed": rng.uniform(7.2, 8.4), "targeted": True}
            elif pid not in (recipient, passer) and rng.random() < attack_tendency["run_rate"].get(pid, .2):
                runs[pid] = {"onset": t0 - rng.uniform(350, 900), "speed": rng.uniform(7.0, 8.6), "targeted": False}

        motions: dict[str, Motion] = {}
        late_step = {pid: defence["step_lag_ms"].get(pid, 0) for pid in by_role(opponent, BACK_FOUR)}
        follow: dict[str, tuple[int, float]] = {}
        if not trap:
            for pid, run in runs.items():
                nearest = min(by_role(opponent, BACK_FOUR), key=lambda d: abs(centre + DEFEND_Y[role(d)] * .88 - lanes[pid]))
                if nearest not in follow and rng.random() < defence["follow_runner"]:
                    follow[nearest] = (run["onset"] + defence["follow_lag_ms"].get(nearest, 220) + rng.gauss(0, 60), rng.uniform(4.2, 5.2))

        def back_line(pid: str) -> Motion:
            offset = DEFEND_Y[role(pid)]
            lag = defence["shift_lag_ms"].get(pid, 0) + rng.gauss(0, 70)
            lateral = Track(ts, 0, 50 + offset).to(int(ts + 600 + lag), 0, 50 + offset).to(int(t0 - 500 + lag), 0, centre + offset * .88)
            if trap:
                speed = rng.uniform(4.1, 4.7) / X_M / 1000
                onset = t0 - 1_300 + late_step[pid] + rng.gauss(0, 60)
                arrive = onset + 5 / speed
                depth = Track(ts, line + 5, 0).to(int(onset), line + 5, 0).to(int(arrive), line, 0)
            else:
                depth = Track(ts, line - 1.5, 0).to(t0, line, 0)
            recover = t0 + 600  # the whole line turns to chase once the ball is played

            def motion(t: float) -> Point:
                x = depth(min(t, recover))[0]
                if t > recover:
                    x += (t - recover) * .004
                if pid in follow:
                    start, speed_mps = follow[pid]
                    if t > start:
                        x = max(x, depth(start)[0] + (t - start) * speed_mps / X_M / 1000)
                return clamp(x), lateral(t)[1]
            return motion

        for pid in by_role(opponent, BACK_FOUR):
            motions[pid] = back_line(pid)
        motions[player_for(opponent, "GK")] = Track(ts, 97.5, 50 + .15 * (s[1] - 50)).to(t0, 97.5, 50 + .15 * (s[1] - 50)).to(int(t0 + 1_200), 95 if through else 97.5, 50 + .2 * (n[1] - 50))
        for pid in by_role(opponent, MIDFIELD):
            offset = DEFEND_Y[role(pid)]
            home = (line - (9 if trap else 12), 50 + offset)
            set_ = (line - 13, centre + offset * .9)
            track = Track(ts, *home).to(int(ts + 700), *home).to(t0, *set_)
            release = defence["early_release"].get(pid, .08)
            if metres(home, s) <= 22 and rng.random() < release:
                # Leaves the zone early to engage the ball carrier before the pass.
                engage = (s[0] + 3.5, s[1] + (centre + offset - s[1]) * .1)
                go = int(ts + rng.uniform(500, 1_000))
                arrive = go + int(metres(home, engage) / 6.0 * 1000)
                track = Track(ts, *home).to(go, *home).to(arrive, *engage).to(max(arrive + 200, t0), s[0] + 2.5, s[1])
            motions[pid] = track
        for pid in by_role(opponent, FORWARDS):
            motions[pid] = Track(ts, line - 31, 50 + DEFEND_Y[role(pid)] * .55).to(t0, line - 30, centre + DEFEND_Y[role(pid)] * .55)

        def offside_line(t: float) -> float:
            xs = sorted((motions[p](t)[0] for p in team_players(opponent)), reverse=True)
            return xs[1]

        # Attacking team.
        motions[player_for(team, "GK")] = Track(ts, 6, 50)
        for pid in by_role(team, BACK_FOUR):
            base = (max(20, s[0] - 32), 50 + ATTACK_Y[role(pid)] * .9 + (centre - 50) * .2)
            motions[pid] = Track(ts, base[0] - 2, base[1]).to(t0, *base)
        for pid in by_role(team, MIDFIELD):
            base = (min(s[0] + 2, line - 8), 50 + ATTACK_Y[role(pid)] + (s[1] - 50) * .25)
            motions[pid] = Track(ts, base[0] - 2, base[1]).to(t0, *base).to(int(t0 + 1_500), base[0] + 3, base[1])
        for pid in by_role(team, FORWARDS):
            lane = lanes[pid]
            if pid in runs:
                # Runners time their run against the line they can see. A trap moves
                # the line after they commit; a late defender can leave them onside.
                run = runs[pid]
                units = run["speed"] / X_M / 1000
                at_pass = line + rng.uniform(-1.5, 2.2) if trap else offside_line(t0) + rng.gauss(-1.0, 1.1)
                start_x = at_pass - units * (t0 - run["onset"])
                drift = (50 - lane) * .2
                track = Track(ts, start_x - 1.2, lane).to(int(run["onset"]), start_x, lane)
                track.to(t0, at_pass, lane + drift * (t0 - run["onset"]) / 2_200)
                track.to(int(run["onset"] + 2_200), start_x + units * 2_200, lane + drift)
                motions[pid] = track
            else:
                hold = rng.uniform(1.0, 2.5)
                motions[pid] = (lambda h, ln: (lambda t: (clamp(offside_line(min(t, t0)) - h), ln)))(hold, lane)

        # The passer carries the ball to the pass origin; the recipient meets the ball.
        motions[passer] = Track(ts, s[0] - 2.3, s[1]).to(t0, s[0] - .8, s[1]).to(int(t0 + 1_500), s[0] + 2, s[1])
        if recipient in runs:
            run = runs[recipient]
            at_pass = (min(offside_line(t0) - .3, n[0] - 1.5), lanes[recipient] + (n[1] - lanes[recipient]) * .3)
            # The pass is weighted into the runner's stride: ball and runner arrive together.
            length = metres(s, n)
            flight = min(max(metres(at_pass, n) / run["speed"] * 1000, length / 22 * 1000), length / 9 * 1000)
            units = run["speed"] / X_M / 1000
            onset_x = at_pass[0] - units * (t0 - run["onset"])
            motions[recipient] = Track(ts, onset_x - 1.2, lanes[recipient]).to(int(run["onset"]), onset_x, lanes[recipient]).to(t0, *at_pass).to(int(t0 + flight), *n)
        else:
            motions[recipient] = Track(ts, n[0] - 3.5, n[1]).to(t0, n[0] - 2, n[1]).to(int(t0 + flight), *n)
        arrival = t0 + flight
        te = ceil_frame(ts, arrival + 600)
        ball = Track(ts, s[0] - 1.5, s[1]).to(t0, *s).to(int(arrival), *n)
        times = frame_times(ts, te)
        return Episode(f"ep_attack_{envelope.event_id}", "attack", envelope.event_id, envelope.ref, event.period,
                       team, opponent, ts, te, frames(times, ball, motions))

    # -------------------------------------------------------------- possession
    def possession(self, envelope: EventEnvelope, index: int, plan: dict) -> Episode:
        event = envelope.payload
        rng = self.rng("possession", envelope.event_id)
        team, opponent = event.team_id, other(event.team_id)
        press = tendencies(opponent)["press"]
        t0 = event.event_time_ms
        later = self.ordered[index + 1:]
        end = next((e.payload.event_time_ms for e in later if e.payload.kind in ("POSSESSION", "STOPPAGE", "PERIOD_END")), t0 + 12_000)
        te = t0 + min(12_000, max(FRAME_MS, (end - t0) // FRAME_MS * FRAME_MS))
        actions = [e.payload for e in later if e.payload.possession_id == event.possession_id
                   and e.payload.kind in ("PASS", "CARRY", "SHOT") and e.payload.event_time_ms <= te]

        start = (event.detail.start.x, event.detail.start.y)
        ball = Track(t0, *start)
        holders: list[tuple[int, str | None]] = [(t0, event.player_id)]
        receipts: list[tuple[int, int, str, Point]] = []
        for position, action in enumerate(actions):
            t = action.event_time_ms
            following = actions[position + 1].event_time_ms if position + 1 < len(actions) else te
            if action.kind == "SHOT":
                break
            a, b = (action.detail.start.x, action.detail.start.y), (action.detail.end.x, action.detail.end.y)
            ball.to(t, *a)
            if action.kind == "PASS":
                arrive = min(t + metres(a, b) / 15.0 * 1000, following - 100)
                ball.to(int(arrive), *b)
                receipts.append((t, int(arrive), action.detail.recipient_id, b))
                holders.append((int(arrive), action.detail.recipient_id if action.detail.completed else None))
            else:
                ball.to(int(min(t + 2_000, following - 100)), *b)
        times = frame_times(t0, te)

        def holder(t: float) -> str | None:
            current = None
            for when, pid in holders:
                if when <= t:
                    current = pid
            return current

        def ball_x(t: float) -> float:
            return ball(t)[0]

        motions: dict[str, Motion] = {}
        # Team in possession: a formation that advances with the ball.
        for pid in team_players(team):
            r = role(pid)

            def target(t, r=r, pid=pid):
                bx, by = ball(t)
                for sent, arrive, receiver, where in receipts:
                    if receiver == pid and sent <= t <= arrive:
                        return where
                if r == "GK":
                    return (5, 50)
                lift = max(0.0, bx - 15)
                if r in BACK_FOUR:
                    return (16 + .45 * lift, 50 + ATTACK_Y[r] + (by - 50) * .2)
                if r in MIDFIELD:
                    return (34 + .5 * lift, 50 + ATTACK_Y[r] + (by - 50) * .25)
                return (55 + .4 * lift, 50 + ATTACK_Y[r] * .9)

            chase = follower(times, target, lambda t: 7.5, target(t0))

            def motion(t, pid=pid, chase=chase):
                return ball(t) if holder(t) == pid else chase(t)
            motions[pid] = motion

        pressed = plan["pressed"]
        weights = press["triggers"]
        trigger = rng.choices(list(weights), weights=list(weights.values()))[0] if pressed else None
        reaction = t0 + press["reaction_ms"] + rng.gauss(0, 90)
        sprint = press["speed_mps"] + rng.gauss(0, .3)
        cover = next((p for p in by_role(opponent, FORWARDS) if p != trigger), None) if pressed else None
        defenders_of_team = by_role(team, ("RCB", "LCB", "RB", "LB"))

        def shape(r: str, bx: float, by: float, high: bool) -> Point:
            lift = max(0.0, bx - 20)
            if r == "GK":
                return (97, 50 + .1 * (by - 50))
            if r in BACK_FOUR:
                return (min(84, (58 if high else 66) + .35 * lift), 50 + DEFEND_Y[r] + (by - 50) * .25)
            if r in MIDFIELD:
                return (min(72, (40 if high else 50) + .4 * lift), 50 + DEFEND_Y[r] * .9 + (by - 50) * .3)
            return (max(bx + (9 if high else 18), (24 if high else 36) + .45 * lift), 50 + DEFEND_Y[r] * (.4 if high else .55) + (by - 50) * .3)

        for pid in team_players(opponent):
            r = role(pid)
            if pid == trigger:
                def target(t, r=r):
                    bx, by = ball(t)
                    if t < reaction:
                        return shape(r, bx, by, True)
                    return (bx + 1.2, by)

                def speed(t):
                    return sprint if t >= reaction else 2.5
            elif pid == cover:
                def target(t, r=r):
                    bx, by = ball(t)
                    if t < reaction + 300:
                        return shape(r, bx, by, True)
                    options = [motions[d](t) for d in defenders_of_team if d != holder(t)]
                    nearest = min(options, key=lambda p: metres(p, (bx, by)))
                    return (bx + (nearest[0] - bx) * .45 + 2, by + (nearest[1] - by) * .45)

                def speed(t):
                    return 5.2 if t >= reaction + 300 else 2.5
            else:
                def target(t, r=r):
                    bx, by = ball(t)
                    return shape(r, bx, by, pressed)

                def speed(t):
                    return 3.6 if pressed else 2.8
            motions[pid] = follower(times, target, speed, shape(r, *start, pressed))
        return Episode(f"ep_possession_{envelope.event_id}", "possession", envelope.event_id, envelope.ref, event.period,
                       team, opponent, t0, te, frames(times, ball, motions))

    # ------------------------------------------------------------------ corner
    def corner(self, envelope: EventEnvelope, plan: dict) -> Episode:
        event = envelope.payload
        rng = self.rng("corner", envelope.event_id)
        team, opponent = event.team_id, other(event.team_id)
        profile = tendencies(team)["corner"]
        defence = tendencies(opponent)
        taker, side = event.player_id, plan["side"]
        flag = (event.detail.start.x, event.detail.start.y)
        landing = (event.detail.end.x, event.detail.end.y)
        t0 = event.event_time_ms
        ts = t0 - 2_400
        speed = profile["speed_mps"].get(taker, 20) + rng.gauss(0, .8)
        flight = metres(flag, landing) / speed * 1000 * 1.06
        arrival = t0 + flight
        te = ceil_frame(ts, arrival + 800)

        # The ball's curve follows the kicking foot: Magnus force bends a right-footed
        # inside-of-the-foot strike to the kicker's left.
        kicked = foot(taker)
        swing = "inswinger" if (kicked == "right") == (side == "left") else "outswinger"
        mid = ((flag[0] + landing[0]) / 2, (flag[1] + landing[1]) / 2)
        bulge = rng.uniform(3.2, 4.6) / X_M * (1 if swing == "inswinger" else -1)
        control = (mid[0] + bulge * 2, mid[1])

        def ball(t: float) -> Point:
            if t <= t0:
                return flag
            u = min(1.0, (t - t0) / flight)
            # An inswinger may bend over the goal line in the air; the plane stops at it.
            return (min(99.8, (1 - u) ** 2 * flag[0] + 2 * (1 - u) * u * control[0] + u * u * landing[0]),
                    (1 - u) ** 2 * flag[1] + 2 * (1 - u) * u * control[1] + u * u * landing[1])

        motions: dict[str, Motion] = {taker: Track(ts, *flag)}
        near = 42 if side == "left" else 58
        zones = {"near_post": (95.0, near), "penalty_spot": (89.5, 50.0), "far_post": (94.5, 100 - near)}
        free = [z for z in zones if z != plan["zone"]]
        attackers = [p for p in TARGET_MEN[team] if p != taker]
        setups = [(83.5, 40.0), (84.5, 50.0), (83.0, 60.0)]
        won = event.detail.completed
        for i, pid in enumerate(attackers):
            setup = setups[i % len(setups)]
            spot = (landing[0] + rng.uniform(-.6, .6), landing[1] + rng.uniform(-.8, .8)) if pid == plan["target_id"] else zones[free.pop(0)] if free else (88, 50)
            onset = t0 + profile["onset_ms"].get(pid, 0) + rng.gauss(0, 110)
            run_ms = metres(setup, spot) / rng.uniform(6.0, 6.9) * 1000
            if pid == plan["target_id"] and won and onset + run_ms > arrival + 250:
                onset = arrival + 250 - run_ms
            motions[pid] = Track(ts, *setup).to(int(onset), *setup).to(int(onset + run_ms), *spot)
        extras = [p for p in team_players(team) if p not in motions and role(p) != "GK"]
        for pid, place in zip(extras, [(78, 34), (78, 66), (88, 30), (62, 50), (55, 30), (55, 70), (40, 40), (40, 60)]):
            motions[pid] = Track(ts, *place)
        motions[player_for(team, "GK")] = Track(ts, 30, 50)

        keeper = player_for(opponent, "GK")
        motions[keeper] = Track(ts, 99, 50).to(int(t0 + 300), 98.5, 50 + (landing[1] - 50) * .2)
        markers = by_role(opponent, ("RCB", "LCB", "DM", "RB", "LB", "RCM", "LCM", "ST", "RW", "LW"))
        man = defence["follow_runner"] >= .5
        assigned = dict(zip(attackers, markers[:len(attackers)]))
        rest = markers[len(attackers):]
        times = frame_times(ts, te)
        for attacker, marker in assigned.items():
            lag = defence["follow_lag_ms"].get(marker, 220)
            if man:
                def target(t, attacker=attacker, lag=lag):
                    x, y = motions[attacker](max(ts, t - lag))
                    return (min(99, x + 1.2), y)
                motions[marker] = follower(times, target, lambda t: 6.6, (min(99, motions[attacker](ts)[0] + 1.2), motions[attacker](ts)[1]))
            else:
                rest.insert(0, marker)
        zone_spots = [(95, 40), (95, 47), (95, 53), (95, 60), (91, 44), (91, 56), (88, 50), (84, 35), (84, 65), (70, 50)]
        for pid, spot in zip(rest, zone_spots):
            motions[pid] = Track(ts, *spot)
        if not won:
            clearer = min((p for p in markers if p in motions), key=lambda p: metres(motions[p](t0), landing))
            origin = motions[clearer]
            motions[clearer] = (lambda origin: (lambda t: origin(t) if t <= t0 else (
                lambda u: (origin(t0)[0] + (landing[0] - origin(t0)[0]) * u, origin(t0)[1] + (landing[1] - origin(t0)[1]) * u))(min(1.0, (t - t0) / max(400, flight - 150)))))(origin)
        return Episode(f"ep_corner_{envelope.event_id}", "corner", envelope.event_id, envelope.ref, event.period,
                       team, opponent, ts, te, frames(times, ball, motions), observed={"taker_foot": kicked, "side": side})


def build_tracking(match: Match, events: list[EventEnvelope], plans: dict[str, dict], seed: int) -> list[Episode]:
    return list(TrackingBuilder(match, events, plans, seed).build())
