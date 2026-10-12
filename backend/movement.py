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

Per-second running totals feed workload and line height. Every player's position, the
ball and who owns it are also kept at every frame (``Track``, about 5 MB per fixture) for
the phase-of-play analysis, which needs off-ball positions at arbitrary moments.
"""
from __future__ import annotations

import math
from array import array
from dataclasses import dataclass, field

from .ingest import canonical_order
from .models import EventEnvelope, Match, PERIOD_MS
from .tactical_profiles import BACK_FOUR, FORWARDS, MIDFIELD, number, player_for, role, tendencies
from .tracking import FRAME_MS, X_M, Y_M, ATTACK_Y, Episode, metres

DT = FRAME_MS / 1000
HSR_MPS = 5.5            # high-speed running, 19.8 km/h
SPRINT_MPS = 7.0         # sprinting, 25.2 km/h
SPRINT_MIN_MS = 1_000    # a sprint effort lasts at least this long
ACCEL_MPS2 = 3.0         # acceleration / deceleration effort threshold
ACCEL_MIN_MS = 400
TRANSITION_MS = 5_000
FREE_BALL_M = 5.0        # the ball is pressed while a defender is this close to it
SECONDS = 2 * PERIOD_MS // 1000

GRID_X, GRID_Y = 12, 8   # heatmap cells along and across the pitch
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
class Track:
    """Every frame of the layer: positions (home frame, normalised units), ball, owner and holder."""
    players: list[str]
    xy: array          # (frame * len(players) + k) * 2 -> x, then y
    ball: array        # frame * 2 -> x, then y
    owner: bytearray   # 0 dead ball, 1 home, 2 away
    holder: bytearray  # index into players, or 255 for nobody

    @property
    def frames(self) -> int:
        return len(self.owner)

    def position(self, frame: int, k: int) -> tuple[float, float]:
        base = (frame * len(self.players) + k) * 2
        return self.xy[base], self.xy[base + 1]

    def ball_at(self, frame: int) -> tuple[float, float]:
        return self.ball[frame * 2], self.ball[frame * 2 + 1]


@dataclass
class Movement:
    players: dict[str, PlayerTotals]
    # team -> phase -> field -> running sums per second
    lines: dict[str, dict[str, dict[str, array]]]
    before_shots: dict[str, list[LineReading]]
    frames: int
    # Heatmap cell (home frame, x-major: cx * GRID_Y + cy) of each player at every whole second.
    cells: dict[str, bytearray] = field(default_factory=dict)
    # Every player's position (home frame) at the frame nearest each pass and carry, by event id.
    snapshots: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    track: Track | None = None


def dropped(t: int) -> bool:
    """A dropping striker's cycle: 7 s deep in every 12 s, so the team-mate's run into the space repeats."""
    return t % 12_000 < 7_000


def cell(x: float, y: float) -> int:
    return min(GRID_X - 1, int(x / 100 * GRID_X)) * GRID_Y + min(GRID_Y - 1, int(y / 100 * GRID_Y))


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
        self.goals = [(r.payload.event_time_ms, r.payload.team_id) for r in self.ordered
                      if r.payload.kind == "SHOT" and r.payload.detail.outcome == "goal"]

    def leading(self, team: str, t: int) -> bool:
        scored = sum(1 for at, side in self.goals if at < t and side == team)
        return scored > sum(1 for at, side in self.goals if at < t and side != team)

    # ------------------------------------------------------------ timelines
    def timelines(self, period: int):
        """Ball keyframes, ball-holder changes and owner changes for one period, home frame."""
        rows = [r.payload for r in self.ordered if r.payload.period == period]
        ball: list[tuple[int, float, float]] = []
        holders: list[tuple[int, str | None]] = []
        owners: list[tuple[int, str | None]] = []
        shots: list[tuple[int, str]] = []
        receptions: list[tuple[int, str, str, str, float]] = []   # arrive, team, passer, recipient, end x (team frame)
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
                    if e.detail.completed and e.detail.recipient_id:
                        receptions.append((arrive, team, e.player_id, e.detail.recipient_id, e.detail.end.x))
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
        receptions.sort(key=lambda k: k[0])
        return ball, holders, owners, shots, receptions

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
        self.cells = {pid: bytearray(SECONDS + 1) for pid in self.players}
        self.snapshots: dict[str, dict[str, tuple[float, float]]] = {}
        count = 2 * PERIOD_MS // FRAME_MS + 1
        self.track = Track(list(self.players), array("f", [0.0]) * (count * len(self.players) * 2), array("f", [0.0]) * (count * 2),
                           bytearray(count), bytearray(b"\xff" * count))
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
        return Movement(totals, lines, before, frames, self.cells, self.snapshots, self.track)

    def run_period(self, period: int, totals, lines, before) -> int:
        start, end = (period - 1) * PERIOD_MS, period * PERIOD_MS
        ball_keys, holders, owners, shots, receptions = self.timelines(period)
        override = self.overrides(start, end)
        home = self.home
        profiles = {team: tendencies(team)["movement"] for team in (self.home, self.away)}

        # Static per-player setup.
        fullbacks = {team: profiles[team].get("fullbacks", {}) for team in profiles}
        rotations = {team: {style: pid for pid, style in profiles[team].get("rotations", {}).items()} for team in profiles}
        # Full-back habit on each flank, so a winger can make room for an overlapping full-back.
        flank_style = {(self.team_of[pid], ATTACK_Y[role(pid)] > 0): style for team in profiles for pid, style in fullbacks[team].items()}
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

        markers = {team: profiles[team].get("man_marking", {}) for team in profiles}
        triggers = {team: profiles[team].get("trigger_hunt") for team in profiles}
        bi = hi = oi = ri = 0
        holder, owner, live = None, None, True
        slot = {pid: k for k, pid in enumerate(self.players)}
        pressers: dict[str, set[str]] = {self.home: set(), self.away: set()}
        last_change = {self.home: -10**9, self.away: -10**9}
        lost_at = {self.home: -10**9, self.away: -10**9}
        hunters: dict[str, set[str]] = {self.home: set(), self.away: set()}
        hunt_at = {self.home: -10**9, self.away: -10**9}
        pressed_at = {self.home: -10**9, self.away: -10**9}
        free_level = {self.home: 0.0, self.away: 0.0}
        shapes = {team: profiles[team].get("defensive_shape", {}) for team in profiles}
        # The frame one second before each shot (snapped to the frame clock).
        shot_times = {start + (t - 1_000 - start) // FRAME_MS * FRAME_MS: team for t, team in shots}
        # Frames at which to keep everyone's position: the frame nearest each pass and carry.
        snap_at: dict[int, list[str]] = {}
        for r in self.ordered:
            e = r.payload
            if e.period == period and e.kind in ("PASS", "CARRY"):
                snap_at.setdefault(start + round((e.event_time_ms - start) / FRAME_MS) * FRAME_MS, []).append(r.event_id)
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
                    pressers[owner] = self.counter_pressers(owner, state, bx, by, profiles[owner].get("counter_press"), owners[oi][0])
                owner, live = new, new is not None
                oi += 1
            while ri < len(receptions) and receptions[ri][0] <= t:
                at, team, passer, recipient, end_x = receptions[ri]
                ri += 1
                defending = self.away if team == self.home else self.home
                plan = triggers[defending]
                if plan and plan["players"] and self.trigger(passer, recipient, end_x) in plan["on"] \
                        and (at // FRAME_MS * 2_246_822_519) % 1000 < plan["rate"] * 1000:
                    # A pressing trigger: the nearest players hunt the receiver.
                    hunters[defending] = self.counter_pressers(defending, state, bx, by, {"players": plan["players"], "reach_m": 32.0, "rate": 1.0}, at)
                    hunt_at[defending] = at
            covered = override.get(t)
            if covered:
                ep, index = covered
                frame = ep.frames[index]
                previous = ep.frames[max(0, index - 1)]
                flip = ep.team_id != home
            second = t // 1000 if t % 1000 == 0 else t // 1000 + 1
            # Game management: a leading side drops its line by its planted amount.
            drop = {team: profiles[team].get("lead_drop", 0.0) if self.leading(team, t) else 0.0
                    for team in (self.home, self.away)}
            # Control depth: a side may drop its back two lines (not the front line, which stays to press)
            # while nobody has pressed the ball for a second.
            free_drop = {self.home: 0.0, self.away: 0.0}
            for team in (self.home, self.away):
                if live and owner not in (None, team) and any(
                        math.hypot((state[pid][0] - bx) * X_M, (state[pid][1] - by) * Y_M) <= FREE_BALL_M
                        for pid in self.players if self.team_of[pid] == team and role(pid) != "GK"):
                    pressed_at[team] = t
                # The line eases back over 2 s once the ball has been free for 1 s, and up again as the pressure returns.
                free = live and owner not in (None, team) and t - pressed_at[team] >= 1_000
                free_level[team] = min(1.0, free_level[team] + DT / 2) if free else max(0.0, free_level[team] - DT / 2)
                free_drop[team] = profiles[team].get("free_ball_drop", 0.0) * free_level[team]

            for pid, (team, r, group, ay, base, transition, cruise, fade, period_ms, phase) in setup.items():
                s = state[pid]
                ox, oy = (bx, by) if team == home else (100 - bx, 100 - by)
                wobble = math.sin(t / period_ms * 6.283 + phase) * 1.6
                # Corners keep their staged runs: the rest-defence shape is an open-play habit.
                habit = self.habit(team, pid, group, ay, ox, oy, fullbacks[team], rotations[team], flank_style,
                                   profiles[team] if not (covered and ep.kind == "corner") else None, t) \
                    if live and owner == team and holder != pid else None
                marked = markers[team].get(pid)
                if live and owner not in (None, team) and pid in pressers[team] \
                        and t - lost_at[team] <= profiles[team]["counter_press"]["window_ms"]:
                    # Counter-press: hunt the ball straight after losing it.
                    tx, ty, cap, amax = bx, by, max(transition, 6.5), 4.5
                elif live and owner not in (None, team) and pid in hunters[team] and t - hunt_at[team] <= triggers[team]["window_ms"]:
                    # Pressing trigger: close down the player who has just received.
                    tx, ty, cap, amax = bx, by, max(transition, 7.0), 5.0
                elif marked and live and owner not in (None, team) and ox > 50 and t - last_change[team] > TRANSITION_MS:
                    # Man-marking against the opponent's build-up (in its own half): stay goal-side of the man.
                    mx, my = state[player_for(owner, marked)][0], state[player_for(owner, marked)][1]
                    tx, ty = (mx - 1.7, my) if team == home else (mx + 1.7, my)
                    tx, ty, cap, amax = clamp(tx), clamp(ty), max(transition, 5.8), 4.0
                elif group == "GK" and live and owner not in (None, team) and profiles[team].get("sweeper") \
                        and (sweep := self.sweep(team, bx, by, base - drop[team])):
                    # Sweeper-keeper: come off the line toward a ball played in behind.
                    tx, ty, cap, amax = *sweep, 6.5, 4.0
                elif habit is not None:
                    # A planted positional habit in possession (full-back role or rotation).
                    tx, ty = to_home(team, home, clamp(habit[0] + wobble), clamp(habit[1] + wobble * .8))
                    # Full-backs sprint to get beyond; the other habits are positional drifts.
                    cap, amax = (6.5, 4.0) if group == "BACK" and fullbacks[team].get(pid) in ("overlap", "underlap") \
                        else (8.5, 6.0) if len(habit) > 2 and habit[2] == "sprint" else (5.0, 4.0) if len(habit) > 2 \
                        else (transition, 4.5) if t - last_change[team] <= TRANSITION_MS else (max(cruise, 4.0), 3.0)
                elif covered:
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
                        spot = shapes[team].get(pid)
                        front = spot[0] == "front" if spot else group == "FWD"
                        back = clamp(base - drop[team] - (0.0 if front else free_drop[team]) + .45 * (ox - 50), 8, 52)
                        if spot:
                            # The planted out-of-possession shape: this player's line and lateral spot.
                            px, py = back + (13 if spot[0] == "midfield" else 29), 50 + spot[1] + (oy - 50) * .35
                        elif group == "GK":
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

            if t % 1000 == 0:
                for pid in self.players:
                    self.cells[pid][t // 1000] = cell(state[pid][0], state[pid][1])
            track, i = self.track, t // FRAME_MS
            base_xy = i * len(self.players) * 2
            for k, pid in enumerate(self.players):
                track.xy[base_xy + 2 * k], track.xy[base_xy + 2 * k + 1] = state[pid][0], state[pid][1]
            track.ball[2 * i], track.ball[2 * i + 1] = bx, by
            track.owner[i] = 0 if not live or owner is None else 1 if owner == home else 2
            track.holder[i] = slot.get(holder, 255) if live else 255
            for event_id in snap_at.get(t, ()):
                self.snapshots[event_id] = {pid: (round(state[pid][0], 2), round(state[pid][1], 2)) for pid in self.players}

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

    @staticmethod
    def trigger(passer: str, recipient: str, end_x: float) -> str | None:
        """The pressing-trigger kind of a completed pass ending in the receiving team's own half."""
        if end_x >= 50:
            return None
        if role(recipient) == "GK":
            return "back_pass_keeper" if role(passer) != "GK" else None
        if role(recipient) in ("RB", "LB"):
            return "to_fullback"
        if role(recipient) in ("RCB", "LCB"):
            return "to_centre_back"
        return "into_midfield" if role(recipient) in MIDFIELD else None

    def habit(self, team: str, pid: str, group: str, ay: float, ox: float, oy: float, fullbacks: dict, rotations: dict,
              flank_style: dict, profile: dict | None = None, t: int = 0) -> tuple | None:
        """A planted in-possession habit (team frame), or None. These apply inside tracking episodes too:
        the episodes stage the defending side and the ball, the continuous layer adds these habits.
        A third element "sprint" asks for a sprinting pace."""
        profile = profile or {}
        lift = max(0.0, ox - 15)
        side = 1 if ay > 0 else -1
        flank = (oy - 50) * side > 4 and ox >= 58
        rest = profile.get("rest_shape")
        if rest and ox >= 60 and (pid in rest["base"] or pid in rest["screen"]):
            # Rest defence while attacking: a base line and a screen in front of it, shifted toward the ball.
            line = rest["base"] if pid in rest["base"] else rest["screen"]
            k = line.index(pid)
            # Listed right to left; a line of three spans 26 units, a pair of centre-backs 22, a pair of midfielders 16.
            spread = 26.0 if len(line) == 3 else 22.0 if line is rest["base"] else 16.0
            lateral = 50 + (spread / 2 - k * spread / (len(line) - 1) if len(line) > 1 else 0) + (oy - 50) * .2
            depth = ox - (42 if line is rest["base"] else 30)
            return depth, lateral
        spot = profile.get("attack_shape", {}).get(pid)
        if spot and ox >= 66:
            # The attacking shape: this player joins the front line in the final third.
            return min(92.0, ox + spot[0]), 50 + spot[1] + (oy - 50) * .2
        if group == "BACK":
            style = fullbacks.get(pid)
            if style == "overlap":
                return (min(92.0, ox + 12), 50 + side * 46) if flank else (36 + .45 * lift, 50 + ay + side * 6 + (oy - 50) * .2)
            if style == "underlap" and (oy - 50) * side > 0 and ox >= 60:
                # Inside the half-space, and always inside the ball (a winger on it cuts in too).
                return min(92.0, ox + 12), (min(69.0, oy - 6) if side > 0 else max(31.0, oy + 6))
            if style == "invert" and ox < 66:
                return 30 + .5 * lift, 50 + side * 11
            if style == "hold":
                return 14 + .3 * lift, 50 + ay + (oy - 50) * .15
            if abs(ay) < 20 and "drop_in" in rotations and ox < 45:
                # Centre-backs split wide when the holding midfielder drops between them.
                return 16 + .45 * lift, 50 + ay * 2.3
        elif group == "MID":
            if rotations.get("drop_in") == pid and ox < 45:
                return 15 + .45 * lift, 50.0
            if "drop_deep" in rotations and pid == player_for(team, "LCM") and 30 <= ox <= 75 and dropped(t):
                # The attacking midfielder pushes into the space the striker leaves (an opposite run).
                return 57 + .4 * lift, 46.0
        elif group == "FWD":
            winger = profile.get("winger_habits", {}).get(pid)
            if winger == "invert" and ox >= 40:
                # Inverted winger: drifts in off the touchline into the half-space.
                return 55 + .4 * lift, 50 + ay * .4 + (oy - 50) * .15
            if winger == "hug" and ox >= 40:
                # Touchline winger: holds the width.
                return 55 + .4 * lift, 50 + side * 46
            plan = profile.get("drop_sprint", {}).get(pid)
            if plan and 35 <= ox <= 72:
                # Counter-movement: drop toward the ball as if to receive, then sprint in behind.
                phase = (t + number(pid) * 1_000) % plan["cycle_ms"]
                if phase < plan["drop_ms"]:
                    return 47 + .4 * lift, 50.0, "check"
                if phase < plan["drop_ms"] + plan["sprint_ms"]:
                    return min(95.0, 69 + .4 * lift), 50.0, "sprint"
            if abs(ay) > 20 and flank and flank_style.get((team, ay > 0)) == "overlap":
                # Make room on the outside for the overlapping full-back.
                return 55 + .4 * lift, 50 + ay * .45
            if rotations.get("drop_deep") == pid and 30 <= ox <= 75 and dropped(t):
                return 38 + .5 * lift, 50.0
        return None

    def sweep(self, team: str, bx: float, by: float, base: float) -> tuple[float, float] | None:
        """Where a sweeper-keeper heads (home frame) when the ball is beyond its line, else None."""
        ox, oy = (bx, by) if team == self.home else (100 - bx, 100 - by)
        back = clamp(base + .45 * (ox - 50), 8, 52)
        if ox >= min(40.0, back - 2):
            return None
        return to_home(team, self.home, clamp(ox - 4, 3, 26), 50 + (oy - 50) * .5)

    def counter_pressers(self, team: str, state, bx: float, by: float, plan: dict | None, t: int) -> set[str]:
        """The nearest outfield players (within reach) who hunt the ball after this team loses it.
        Whether the team counter-presses this time is a deterministic draw from the loss time."""
        if not plan or not plan["players"] or (t // FRAME_MS * 2_654_435_761) % 1000 >= plan["rate"] * 1000:
            return set()
        near = sorted((math.hypot((state[pid][0] - bx) * X_M, (state[pid][1] - by) * Y_M), pid) for pid in self.players
                      if self.team_of[pid] == team and role(pid) != "GK")
        return {pid for distance, pid in near[:plan["players"]] if distance <= plan["reach_m"]}

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
