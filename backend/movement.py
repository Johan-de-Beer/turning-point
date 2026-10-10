"""Continuous synthetic movement: all 22 players at 5 Hz for the whole match.

The tactical tracking in ``tracking`` only covers short episodes around attacks,
presses and corners. Workload and defensive line height need every frame, so this
module runs one velocity- and acceleration-limited "player" per shirt across both
halves. Each player chases a target:

* inside a tracking episode, their position in that episode (the episodes stay the
  source of truth where they exist);
* holding the ball, the ball;
* otherwise a formation spot that slides with the ball, in or out of possession.

The ball follows the recorded events. Coordinates use a fixed home frame (the home
team always attacks toward x = 100) on the nominal 105 x 68 m pitch. Like the
episodes, the motion is generated from server-only fictional tendencies; the
analysis in ``analytics`` re-measures everything from the frames and never reads them.

Only per-second running totals are kept, not every position, so the layer stays small.
"""
from __future__ import annotations

import math
from array import array
from dataclasses import dataclass, field

from .ingest import canonical_order
from .models import EventEnvelope, Match, PERIOD_MS
from .tactical_profiles import BACK_FOUR, FORWARDS, MIDFIELD, role, tendencies
from .tracking import FRAME_MS, X_M, Y_M, ATTACK_Y, Episode, metres

DT = FRAME_MS / 1000
HSR_MPS = 5.5            # high-speed running, 19.8 km/h
SPRINT_MPS = 7.0         # sprinting, 25.2 km/h
SPRINT_MIN_MS = 1_000    # a sprint effort lasts at least this long
ACCEL_MPS2 = 3.0         # acceleration / deceleration effort threshold
ACCEL_MIN_MS = 400
TRANSITION_MS = 5_000
SECONDS = 2 * PERIOD_MS // 1000

LINE_FIELDS = ("frames", "deepest", "back_four", "centroid", "gap", "width")
LINE_PHASES = ("all", "after_loss", "settled")


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


@dataclass
class PlayerTotals:
    """Running totals per match second (index s covers frames with t <= s * 1000)."""
    distance: array = field(default_factory=lambda: array("d", [0.0] * (SECONDS + 1)))
    hsr: array = field(default_factory=lambda: array("d", [0.0] * (SECONDS + 1)))
    sprint: array = field(default_factory=lambda: array("d", [0.0] * (SECONDS + 1)))
    load: array = field(default_factory=lambda: array("d", [0.0] * (SECONDS + 1)))
    sprints: list[int] = field(default_factory=list)       # effort start times
    accelerations: list[int] = field(default_factory=list)
    decelerations: list[int] = field(default_factory=list)
    top_speed: list[tuple[int, float]] = field(default_factory=list)  # (t, running max) when it rises


@dataclass
class LineReading:
    t: int
    deepest: float
    back_four: float
    centroid: float
    gap: float
    width: float


@dataclass
class Movement:
    players: dict[str, PlayerTotals]
    # team -> phase -> field -> running sums per second
    lines: dict[str, dict[str, dict[str, array]]]
    before_shots: dict[str, list[LineReading]]
    frames: int


def to_home(team: str, home: str, x: float, y: float) -> tuple[float, float]:
    return (x, y) if team == home else (100 - x, 100 - y)


class MovementBuilder:
    def __init__(self, match: Match, events: list[EventEnvelope], episodes: list[Episode]):
        self.match = match
        self.home, self.away = match.home.team_id, match.away.team_id
        records = {e.event_id: e for e in events if e.revision == 1 and e.payload}
        self.ordered = canonical_order(records)
        self.episodes = episodes
        self.players = [p.player_id for p in match.roster]
        self.team_of = {p.player_id: p.team_id for p in match.roster}

    # ------------------------------------------------------------ timelines
    def timelines(self, period: int):
        """Ball keyframes, ball-holder changes and owner changes for one period, home frame."""
        rows = [r.payload for r in self.ordered if r.payload.period == period]
        ball: list[tuple[int, float, float]] = []
        holders: list[tuple[int, str | None]] = []
        owners: list[tuple[int, str | None]] = []
        shots: list[tuple[int, str]] = []
        for i, e in enumerate(rows):
            t = e.event_time_ms
            following = rows[i + 1].event_time_ms if i + 1 < len(rows) else t + 2_000
            team = e.team_id
            if e.kind == "POSSESSION":
                ball.append((t, *to_home(team, self.home, e.detail.start.x, e.detail.start.y)))
                holders.append((t, e.player_id))
                owners.append((t, team))
            elif e.kind in ("PASS", "CARRY"):
                a = to_home(team, self.home, e.detail.start.x, e.detail.start.y)
                b = to_home(team, self.home, e.detail.end.x, e.detail.end.y)
                pace = 15.0 if e.kind == "PASS" else 5.0
                arrive = int(min(t + metres(a, b) / pace * 1000, max(t + 200, following - 100)))
                ball.extend([(t, *a), (arrive, *b)])
                holders.append((t, e.player_id))
                if e.kind == "PASS":
                    holders.append((arrive, e.detail.recipient_id if e.detail.completed else None))
            elif e.kind == "SHOT":
                a = to_home(team, self.home, e.detail.position.x, e.detail.position.y)
                target = e.detail.target or e.detail.position
                b = to_home(team, self.home, target.x, target.y)
                ball.extend([(t, *a), (t + 400, *b)])
                holders.append((t, None))
                shots.append((t, team))
            elif e.kind == "TACKLE":
                ball.append((t, *to_home(team, self.home, e.detail.position.x, e.detail.position.y)))
                if e.detail.successful:
                    holders.append((t, None))
            elif e.kind in ("STOPPAGE", "PERIOD_END"):
                holders.append((t, None))
                owners.append((t, None))
        start = (period - 1) * PERIOD_MS
        if not ball or ball[0][0] > start:
            ball.insert(0, (start, 50.0, 50.0))
        ball.sort(key=lambda k: k[0])
        return ball, holders, owners, shots

    def overrides(self, start: int, end: int) -> dict[int, tuple[Episode, int]]:
        """Frame time -> (episode, index) for times an episode covers; the latest-starting wins."""
        result: dict[int, tuple[Episode, int]] = {}
        for ep in sorted(self.episodes, key=lambda e: e.start_ms):
            if ep.end_ms < start or ep.start_ms > end:
                continue
            first = start + math.ceil((max(ep.start_ms, start) - start) / FRAME_MS) * FRAME_MS
            for t in range(first, min(ep.end_ms, end) + 1, FRAME_MS):
                index = max(0, min(len(ep.frames) - 1, round((t - ep.start_ms) / FRAME_MS)))
                result[t] = (ep, index)
        return result

    # ------------------------------------------------------------------ run
    def build(self) -> Movement:
        totals = {pid: PlayerTotals() for pid in self.players}
        lines = {team: {phase: {name: array("d", [0.0] * (SECONDS + 1)) for name in LINE_FIELDS} for phase in LINE_PHASES}
                 for team in (self.home, self.away)}
        before: dict[str, list[LineReading]] = {self.home: [], self.away: []}
        frames = 0
        for period in (1, 2):
            frames += self.run_period(period, totals, lines, before)
        # Running sums: each array holds per-second increments until now.
        for player in totals.values():
            for name in ("distance", "hsr", "sprint", "load"):
                values = getattr(player, name)
                for s in range(1, SECONDS + 1):
                    values[s] += values[s - 1]
        for team in lines.values():
            for phase in team.values():
                for values in phase.values():
                    for s in range(1, SECONDS + 1):
                        values[s] += values[s - 1]
        return Movement(totals, lines, before, frames)

    def run_period(self, period: int, totals, lines, before) -> int:
        start, end = (period - 1) * PERIOD_MS, period * PERIOD_MS
        ball_keys, holders, owners, shots = self.timelines(period)
        override = self.overrides(start, end)
        home = self.home
        profiles = {team: tendencies(team)["movement"] for team in (self.home, self.away)}

        # Static per-player setup.
        setup = {}
        for n, pid in enumerate(self.players):
            team = self.team_of[pid]
            r = role(pid)
            profile = profiles[team]
            group = "GK" if r == "GK" else "BACK" if r in BACK_FOUR else "MID" if r in MIDFIELD else "FWD"
            setup[pid] = (team, r, group, ATTACK_Y.get(r, 0), profile["line_base"], profile["transition_mps"].get(pid, 4.6),
                          profile["cruise_mps"].get(pid, 3.1), profile["fade"].get(pid), 18_000 + (n * 2_377) % 13_000, n * .7)

        # Kick-off shape.
        state = {}
        for pid, (team, r, group, ay, *_rest) in setup.items():
            own = {"GK": (4, 50), "BACK": (24, 50 + ay), "MID": (38, 50 + ay * .9), "FWD": (48, 50 + ay * .6)}[group]
            x, y = to_home(team, home, *own)
            state[pid] = [x, y, 0.0, 0.0, 0.0, 0, 0, 0]  # x, y, vx, vy, speed, sprint_ms, accel_ms, decel_ms

        bi = hi = oi = 0
        holder, owner, live = None, None, True
        last_change = {self.home: -10**9, self.away: -10**9}
        lost_at = {self.home: -10**9, self.away: -10**9}
        # The frame one second before each shot (snapped to the frame clock).
        shot_times = {start + (t - 1_000 - start) // FRAME_MS * FRAME_MS: team for t, team in shots}
        count = 0
        for t in range(start, end + 1, FRAME_MS):
            while bi + 1 < len(ball_keys) and ball_keys[bi + 1][0] <= t:
                bi += 1
            k1 = ball_keys[bi]
            if bi + 1 < len(ball_keys) and ball_keys[bi + 1][0] > k1[0] and t > k1[0]:
                k2 = ball_keys[bi + 1]
                u = (t - k1[0]) / (k2[0] - k1[0])
                bx, by = k1[1] + (k2[1] - k1[1]) * u, k1[2] + (k2[2] - k1[2]) * u
            else:
                bx, by = k1[1], k1[2]
            while hi < len(holders) and holders[hi][0] <= t:
                holder = holders[hi][1]
                hi += 1
            while oi < len(owners) and owners[oi][0] <= t:
                new = owners[oi][1]
                if new is not None and owner is not None and new != owner:
                    last_change[new] = last_change[owner] = owners[oi][0]
                    lost_at[owner] = owners[oi][0]
                owner, live = new, new is not None
                oi += 1
            covered = override.get(t)
            if covered:
                ep, index = covered
                frame = ep.frames[index]
                previous = ep.frames[max(0, index - 1)]
                flip = ep.team_id != home
            second = t // 1000 if t % 1000 == 0 else t // 1000 + 1

            for pid, (team, r, group, ay, base, transition, cruise, fade, period_ms, phase) in setup.items():
                s = state[pid]
                if covered:
                    ex, ey = frame.players[pid]
                    tx, ty = (100 - ex, 100 - ey) if flip else (ex, ey)
                    # Match the episode's own pace rather than sprinting to close an entry offset.
                    px, py = previous.players[pid]
                    pace = math.hypot((ex - px) * X_M, (ey - py) * Y_M) / DT
                    # An episode cut (a player re-placed between frames) is not running.
                    cap = cruise if pace > 10 else min(9.5, max(cruise, pace * 1.1))
                    amax = 7.0 if pace > 5 else 2.5
                elif holder == pid:
                    tx, ty, cap, amax = bx, by, 5.2, 2.5
                else:
                    ox, oy = (bx, by) if team == home else (100 - bx, 100 - by)
                    wobble = math.sin(t / period_ms * 6.283 + phase) * 1.6
                    if owner == team:
                        lift = max(0.0, ox - 15)
                        if group == "GK":
                            px, py = 5.0, 50.0
                        elif group == "BACK":
                            # Full-backs push on in possession; centre-backs hold.
                            px, py = 16 + .45 * lift + (14 if abs(ay) > 20 else 0), 50 + ay + (oy - 50) * .2
                        elif group == "MID":
                            px, py = 34 + .5 * lift, 50 + ay + (oy - 50) * .25
                        else:
                            px, py = 55 + .4 * lift, 50 + ay * .9
                    else:
                        if not live:
                            ox, oy = 50.0, 50.0
                        back = clamp(base + .45 * (ox - 50), 8, 52)
                        if group == "GK":
                            px, py = min(14.0, 3 + .12 * back), 50 + (oy - 50) * .1
                        elif group == "BACK":
                            px, py = back, 50 + ay * .95 + (oy - 50) * .3
                        elif group == "MID":
                            px, py = back + 13, 50 + ay * .85 + (oy - 50) * .35
                        else:
                            px, py = back + 29, 50 + ay * .5 + (oy - 50) * .3
                    if group != "GK":
                        px, py = px + wobble, py + wobble * .8
                    tx, ty = to_home(team, home, clamp(px), clamp(py))
                    if not live:
                        cap, amax = 2.2, 2.0
                    elif t - last_change[team] <= TRANSITION_MS:
                        cap, amax = transition, 4.5
                    else:
                        cap, amax = cruise, 2.5
                if fade and t > fade[0]:
                    cap *= 1 - fade[1] * min(1.0, (t - fade[0]) / (2 * PERIOD_MS - fade[0]))
                # Arrive: head for the target no faster than the cap, braking within reach.
                x, y, vx, vy, speed = s[0], s[1], s[2], s[3], s[4]
                dx, dy = (tx - x) * X_M, (ty - y) * Y_M
                distance = math.hypot(dx, dy)
                if distance > 1e-6:
                    want = min(cap, math.sqrt(2 * amax * distance), distance / DT)
                    wx, wy = dx / distance * want, dy / distance * want
                else:
                    wx = wy = 0.0
                ax, ay_ = wx - vx, wy - vy
                change = math.hypot(ax, ay_)
                limit = amax * DT
                if change > limit:
                    ax, ay_ = ax * limit / change, ay_ * limit / change
                    change = limit
                vx, vy = vx + ax, vy + ay_
                new_speed = math.hypot(vx, vy)
                x, y = clamp(x + vx * DT / X_M), clamp(y + vy * DT / Y_M)
                if t == start:
                    vx = vy = new_speed = 0.0
                else:
                    step = new_speed * DT
                    p = totals[pid]
                    p.distance[second] += step
                    p.load[second] += change / 10
                    if new_speed >= HSR_MPS:
                        p.hsr[second] += step
                    if new_speed >= SPRINT_MPS:
                        p.sprint[second] += step
                        s[5] += FRAME_MS
                        if s[5] == SPRINT_MIN_MS:
                            p.sprints.append(t - SPRINT_MIN_MS + FRAME_MS)
                    else:
                        s[5] = 0
                    accel = (new_speed - speed) / DT
                    s[6] = s[6] + FRAME_MS if accel >= ACCEL_MPS2 else 0
                    s[7] = s[7] + FRAME_MS if accel <= -ACCEL_MPS2 else 0
                    if s[6] == ACCEL_MIN_MS:
                        p.accelerations.append(t)
                    if s[7] == ACCEL_MIN_MS:
                        p.decelerations.append(t)
                    if not p.top_speed or new_speed > p.top_speed[-1][1] + .05:
                        p.top_speed.append((t, round(new_speed, 2)))
                s[0], s[1], s[2], s[3], s[4] = x, y, vx, vy, new_speed

            # Defensive line of each team out of possession (live play only).
            for team in (self.home, self.away):
                if not live or owner is None or owner == team:
                    continue
                reading = self.line(team, state, t)
                phase = "after_loss" if t - lost_at[team] <= TRANSITION_MS else "settled"
                for name, value in zip(LINE_FIELDS, (1.0, reading.deepest, reading.back_four, reading.centroid, reading.gap, reading.width)):
                    lines[team]["all"][name][second] += value
                    lines[team][phase][name][second] += value
                if shot_times.get(t) and shot_times[t] != team:
                    before[team].append(reading)
            count += 1
        return count

    def line(self, team: str, state, t: int) -> LineReading:
        """Depths from the team's own goal line in metres."""
        flip = team != self.home
        depth = {pid: (100 - state[pid][0] if flip else state[pid][0]) * X_M for pid in self.players if self.team_of[pid] == team}
        lateral = {pid: state[pid][1] * Y_M for pid in depth}
        outfield = [pid for pid in depth if role(pid) != "GK"]
        back = [pid for pid in outfield if role(pid) in BACK_FOUR]
        mid = [pid for pid in outfield if role(pid) in MIDFIELD]
        back_mean = sum(depth[p] for p in back) / len(back)
        return LineReading(t, round(min(depth[p] for p in outfield), 2), round(back_mean, 2),
                           round(sum(depth[p] for p in outfield) / len(outfield), 2),
                           round(sum(depth[p] for p in mid) / len(mid) - back_mean, 2),
                           round(max(lateral[p] for p in back) - min(lateral[p] for p in back), 2))


def build_movement(match: Match, events: list[EventEnvelope], episodes: list[Episode]) -> Movement:
    return MovementBuilder(match, events, episodes).build()
