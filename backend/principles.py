"""Principles of play (principles_v1): build-up and rest-defence structures (2+3, 3+2 and friends),
winger roles and attacking width, the pressing system (man-to-man, zonal or hybrid) with its
triggers and the spare defender at the back, marking tightness by distance from the ball and free
receivers, counter-movements (drop-and-sprint, opposite runs, decoy runs, crisscross runs at
corners), third-man combinations, and a match report that answers a professional analyst's
questions phase by phase with strengths to keep and weaknesses to target.

``PrincipleReport`` extends the phase report, so it shares its observed prefix, its possessions and
phases and the continuous synthetic movement layer. Per-frame and per-second figures that do not
depend on the playhead are computed once per fixture (``Layout``); a report only reads the frames
up to its cutoff. Like the rest of the analysis it never reads the generator's tendencies or
plans, and tests recover the planted behaviour from these numbers.

Coordinates are team-relative (the team in question attacks toward x = 100) unless a name says
``home``. Depths are metres from the team's own goal line.
"""
from __future__ import annotations

import math
import threading
from array import array
from collections import Counter
from statistics import median

from .chances import X_M, Y_M, in_box
from .models import (FreeReceiver, MarkingBand, MatchReportTeam, Moment, MovementRow, PressUnit, ReportLine, RestLossRow, ShapeRow,
                     TeamMarking, TeamMovements, TeamPressSystem, TeamStructure, TeamThirdMan, TeamWidth, ThirdManRow, TriggerRow, WingerRow)
from .movement import Movement
from .advanced import ratio
from .phases import COUNTER_SHOT_MS, MOMENTS, Features, PhaseEngine, PhaseReport, channel, clock, mean, plural, r1, times
from .tactical_profiles import BACK_FOUR, FORWARDS, MIDFIELD, foot, role
from .tracking import FRAME_MS

OUTFIELD_ROLES = ("RB", "RCB", "LCB", "LB", "DM", "RCM", "LCM", "RW", "ST", "LW")
SHAPES = ("5", "1+4", "2+3", "3+2", "4+1")
LINE_GAP_M = 4.0            # the deepest five split into two lines at their largest depth gap, if this big
BEHIND_BALL_M = 10.0        # rest defence: outfield players this far or more goal-side of the ball
OVERCOMMITTED = 3           # this many or fewer behind the ball with the ball in the final third
WINGER_INSIDE_M = 18.0      # a winger this far or more from the touchline is inside (half-space or centre)
TOUCHLINE_M = 8.0           # a touchline winger's mean distance from it
MIN_WINGER_S = 60
CUT_IN_M = 8.0
FOLLOW_WINDOW_S = 2         # man-marking: does the nearest defender go with his man over 2 s
FOLLOW_MOVE_M = 3.0
FOLLOW_KEEP_M = 5.0
MAN_SHARE, ZONAL_SHARE = 55.0, 35.0
MIN_FOLLOW_SAMPLES = 20
FREE_M = 8.0                # an opponent with no defender this close is free
PRESSURE_M = 3.0
PRESSURE_WINDOW_FRAMES = 15  # 3 s
SHADOW_DEG = 30.0
RECEPTION_FREE_M = 5.0
BALL_MPS = 15.0             # the movement layer's pass speed, for the arrival frame
DROP_M, DROP_FRAMES = 4.0, 8            # a drop: 4 m toward own goal within 1.6 s
SPRINT_MPS, SPRINT_FRAMES, SPRINT_GAIN_M, SPRINT_WITHIN = 6.0, 3, 8.0, 10
STEP_M = 2.0                # a marker who comes 2 m or more out of the line with the dropping attacker
OPPOSITE_DROP_M, OPPOSITE_RUN_M, OPPOSITE_FRAMES, OPPOSITE_LATERAL_M, OPPOSITE_SPACE_M = 4.0, 5.0, 10, 15.0, 8.0
SETTLED_FRAMES = 25         # counter-movements are read in settled possession: 5 s after the ball was won
DECOY_RUN_M, DECOY_FRAMES, DECOY_NEAR_M, DECOY_DRAG_M, DECOY_SPACE_M = 6.0, 5, 8.0, 3.0, 12.0
FOUND_MS = 3_000
CRISS_MS, CRISS_MOVE_M = 3_000, 3.0
LAY_OFF_MS = 3_000          # third man: the middle player passes on within 3 s of the first pass
LANE_M = 2.5
FINAL_THIRD_MS = 10_000
BANDS = (("near", 0.0, 15.0), ("middle", 15.0, 30.0), ("far", 30.0, 1e9))
TRIGGERS = ("back_pass_keeper", "to_fullback", "to_centre_back", "into_midfield", "other")
UNITS = (("front", FORWARDS), ("midfield", MIDFIELD), ("back", BACK_FOUR))

DEFINITIONS = {
    "structure": f"The deepest five outfield players, sorted by depth and split into a base line and a screen at their largest depth gap (if it is {LINE_GAP_M:.0f} m or more; otherwise one flat line of five). 3+2 is a back three with two in front of it, 2+3 two centre-backs with three in front. Read every 200 ms in settled possession (outside transitions and set pieces): build-up with the ball in the team's own half, rest defence with the ball in the final third.",
    "behind_ball": f"Rest defence: outfield players {BEHIND_BALL_M:.0f} m or more goal-side of the ball while the team has it in the final third. Over-committed: {OVERCOMMITTED} or fewer.",
    "rest_losses": "Open-play losses in the final third, by the rest-defence shape at the moment of the loss: counters conceded (the opponent reached its final third within 10 s), and shots and xG conceded within 15 s.",
    "winger_role": f"From the 5 Hz synthetic positions while the team has the ball in the opponent's half: inverted when the winger spends 40% or more of that time {WINGER_INSIDE_M:.0f} m or more from the touchline; touchline when it averages {TOUCHLINE_M:.0f} m or less from it; otherwise balanced. At least {MIN_WINGER_S} s is needed. Opposite foot: a right winger who is left-footed or the reverse (preferred foot is a public player attribute).",
    "cut_in": f"A winger's carry that starts in its wide channel and ends in the centre, or ends {CUT_IN_M:.0f} m or more further from the touchline.",
    "fullback_width": "With the ball in the final third on a winger's side, the share of time its full-back is the wider of the two: the width the full-back provides while the winger is inside.",
    "width": "Attacking width: the outfield spread across the pitch in settled possession with the ball in the final third. Central entries: completed passes and carries into the final third that end in the centre channel. Crosses: passes from a wide channel of the final third into the box.",
    "press_system": f"During the opponent's settled build-up in its own half, each second: does a player's nearest opponent move {FOLLOW_MOVE_M:.0f} m or more over the next {FOLLOW_WINDOW_S} s, and does the player go with him (moving the same way and staying within {FOLLOW_KEEP_M:.0f} m)? A player who follows {MAN_SHARE:.0f}% of the time or more is man-oriented, {ZONAL_SHARE:.0f}% or less zonal. A unit is man when most of its players are man-oriented, zonal when most are zonal. Man-to-man when every unit with enough samples is man, zonal when every one is zonal, hybrid when they differ.",
    "spare_at_back": "During the opponent's build-up: the back four minus the opponent's outfield players positioned behind the team's midfield line. +1 means one spare defender.",
    "left_free": f"The opponent outfield player most often without a defender within {FREE_M:.0f} m during its own build-up (some teams leave one centre-back free on purpose to keep a spare man at the back).",
    "press_triggers": f"Opponent completed passes that end in its own half, by type: back to the keeper, out to a full-back, to a centre-back, into midfield, other. Pressured: a player within {PRESSURE_M:.0f} m of the receiver within {PRESSURE_WINDOW_FRAMES * FRAME_MS // 1000} s of the ball arriving. Regained: the team won the ball back within 5 s.",
    "cover_shadow": f"Of pressured receptions by the opponent's keeper or centre-backs, how often the presser's approach came within {SHADOW_DEG:.0f}° of the line from the receiver to the opponent's holding midfielder, blocking that pass with the run (a cover shadow).",
    "forced_wide": "Opponent build-ups that start in its own third: the share whose first entry into the middle third ends in a wide channel.",
    "marking_bands": "In settled defending, each opponent outfield player's distance to the nearest defender, by that opponent's distance from the ball: near (under 15 m), middle (15 to 30 m) and far (over 30 m). Tight near the ball and looser away from it is the usual man-marking rule.",
    "free_receptions": f"Opponent completed passes received in its middle or final third with no defender within {RECEPTION_FREE_M:.0f} m on arrival. Between the lines: received between the team's back four and its midfield line.",
    "drop_and_sprint": f"An attacker in possession drops {DROP_M:.0f} m or more toward its own goal within 1.6 s, then sprints forward at {SPRINT_MPS:.0f} m/s or more, gaining {SPRINT_GAIN_M:.0f} m or more in 2 s, starting within {SPRINT_WITHIN * FRAME_MS / 1000:.1f} s of the drop. Drew: the nearest defender stepped {STEP_M:.0f} m or more out with the drop. Found: the runner received the ball within 3 s of the sprint starting.",
    "opposite_runs": f"Two attacking team-mates within {OPPOSITE_LATERAL_M:.0f} m of each other across the pitch: one drops {OPPOSITE_DROP_M:.0f} m or more while the other runs {OPPOSITE_RUN_M:.0f} m or more forward over 2 s, ending within {OPPOSITE_SPACE_M:.0f} m of where the dropping player started (into the space it left). Drew: the dropping player's nearest defender stepped {STEP_M:.0f} m or more out with him. Read in settled possession (5 s or more after the ball was won), like the other counter-movements. Found: either received the ball within 3 s.",
    "decoy_run": f"An attacker runs {DECOY_RUN_M:.0f} m or more forward in 1 s with the ball in the attacking 60%, and the nearest defender (within {DECOY_NEAR_M:.0f} m) retreats {DECOY_DRAG_M:.0f} m or more with him (drew). Found: within 3 s a team-mate, not the runner, received a pass within {DECOY_SPACE_M:.0f} m of where that defender started.",
    "crisscross": f"At a corner: two attackers inside the final 20 m whose order across the pitch swaps in the {CRISS_MS // 1000} s before the delivery, each moving {CRISS_MOVE_M:.0f} m or more.",
    "third_man": f"A completed pass from A to B, then B passes on to C (not A) within {LAY_OFF_MS // 1000} s of A's pass, with C receiving further forward than A played from. Lane blocked: an opponent within {LANE_M} m of the straight line from A to C when A played. Free: no opponent within {RECEPTION_FREE_M:.0f} m of C on arrival. Zones: build-up (A in its own third), middle third or final third (where C receives).",
    "match_report": "A summary per team in the order a professional analyst works: in possession, out of possession, attack to defence, defence to attack and set pieces, then strengths to keep, weaknesses an opponent could target and the most influential player by expected threat. Each line is built from the numbers in this report and in Phases of play, with its sample. It describes what happened; it does not explain why.",
}

LIMITATIONS = [
    "Synthetic data: the events and the 5 Hz player positions are generated from fictional tendencies. Off-ball movement between events is illustrative.",
    "Structures use the deepest five outfield players and one depth gap. Real analysts also judge width, the opponent's front line and who is responsible for whom.",
    "Man-orientation is read from whether a player moves with the nearest opponent, which also happens when two players simply run the same way. Zonal teams can look man-oriented near the ball.",
    "Counter-movements are read from synthetic positions with fixed distances and windows. They show the pattern of the movement, not the intent behind it.",
    "Third-man combinations need two passes inside 3 s. The synthetic event stream spaces most passes further apart, so the count is mostly planted build-up combinations.",
    "The match report applies fixed rules to the numbers; it is a starting point for analysis, not a verdict. One match is a small sample.",
]


def unit_name(rows: list[str]) -> str:
    return ", ".join(rows)


class Layout:
    """Per-frame structures and per-second marking figures for each team, computed once per fixture."""

    def __init__(self, movement: Movement, home: str, teams: list[str]):
        track = movement.track
        self.frames = track.frames
        self.seconds = (self.frames - 1) * FRAME_MS // 1000 + 1
        players = track.players
        n = len(players)
        self.shape = {team: bytearray(self.frames) for team in teams}
        self.base = {team: array("H", [0]) * self.frames for team in teams}
        self.screen = {team: array("H", [0]) * self.frames for team in teams}
        self.behind = {team: bytearray(self.frames) for team in teams}
        self.touch = {pid: array("f", [0.0]) * self.frames for pid in players if role(pid) in ("RW", "LW")}
        xy, ball = track.xy, track.ball
        slots = {team: [k for k, pid in enumerate(players) if pid.startswith(team + "_") and role(pid) != "GK"] for team in teams}
        bit = {k: 1 << OUTFIELD_ROLES.index(role(players[k])) for team in teams for k in slots[team]}
        for team in teams:
            flip = team != home
            ks = slots[team]
            shape, base, screen, behind = self.shape[team], self.base[team], self.screen[team], self.behind[team]
            wingers = [(k, players[k]) for k in ks if role(players[k]) in ("RW", "LW")]
            for f in range(self.frames):
                b = f * n * 2
                bx = ball[2 * f]
                if flip:
                    bx = 100 - bx
                pts = sorted(((100 - xy[b + 2 * k] if flip else xy[b + 2 * k]) * X_M, k) for k in ks)
                five = pts[:5]
                gap, cut = max((five[i + 1][0] - five[i][0], i) for i in range(4))
                if gap >= LINE_GAP_M:
                    shape[f] = cut + 1                    # index into SHAPES: 1+4, 2+3, 3+2, 4+1
                    base[f] = sum(bit[k] for _, k in five[:cut + 1])
                    screen[f] = sum(bit[k] for _, k in five[cut + 1:])
                else:
                    shape[f] = 0
                    base[f] = sum(bit[k] for _, k in five)
                ball_m = bx * X_M
                behind[f] = sum(1 for depth, _ in pts if depth <= ball_m - BEHIND_BALL_M)
                for k, pid in wingers:
                    y = xy[b + 2 * k + 1]
                    if flip:
                        y = 100 - y
                    self.touch[pid][f] = (100 - y if role(pid) == "RW" else y) * Y_M

        # Per second: man-orientation of every outfield player against its nearest opponent, marking
        # distance by band, the spare defender at the back and who is left free.
        self.follow = {pid: bytearray(self.seconds) for pid in players if role(pid) != "GK"}   # 0 n/a, 1 followed, 2 not
        self.near = {pid: array("f", [0.0]) * self.seconds for pid in players if role(pid) != "GK"}
        self.bands = {team: {name: (array("d", [0.0]) * self.seconds, array("H", [0]) * self.seconds) for name, *_ in BANDS} for team in teams}
        self.spare = {team: array("f", [0.0]) * self.seconds for team in teams}
        self.free = {pid: bytearray(self.seconds) for pid in players if role(pid) != "GK"}
        everyone = {team: [k for k, pid in enumerate(players) if pid.startswith(team + "_")] for team in teams}

        def at(f: int, k: int) -> tuple[float, float]:
            b = (f * n + k) * 2
            return xy[b] * X_M, xy[b + 1] * Y_M          # home frame, metres

        last = self.frames - 1
        for team in teams:
            rival = teams[1] if team == teams[0] else teams[0]
            flip = team != home
            mine, theirs = slots[team], slots[rival]
            back = [k for k in mine if role(players[k]) in BACK_FOUR]
            mids = [k for k in mine if role(players[k]) in MIDFIELD]
            for s in range(self.seconds):
                f = min(last, s * 1000 // FRAME_MS)
                g = min(last, (s + FOLLOW_WINDOW_S) * 1000 // FRAME_MS)
                now = {k: at(f, k) for k in everyone[team] + slots[rival]}
                bx, by = ball[2 * f] * X_M, ball[2 * f + 1] * Y_M
                for k in mine:
                    px, py = now[k]
                    j = min(theirs, key=lambda j: (now[j][0] - px) ** 2 + (now[j][1] - py) ** 2)
                    self.near[players[k]][s] = math.hypot(now[j][0] - px, now[j][1] - py)
                    if g > f:
                        jx, jy = at(g, j)
                        kx, ky = at(g, k)
                        mx, my = jx - now[j][0], jy - now[j][1]
                        moved = math.hypot(mx, my)
                        if moved >= FOLLOW_MOVE_M:
                            dot = (kx - px) * mx + (ky - py) * my
                            kept = math.hypot(kx - jx, ky - jy) <= max(FOLLOW_KEEP_M, self.near[players[k]][s] + 1)
                            self.follow[players[k]][s] = 1 if dot >= .5 * moved * moved and kept else 2
                defenders = [now[k] for k in everyone[team]]
                for j in theirs:
                    jx, jy = now[j]
                    nearest = min(math.hypot(dx - jx, dy - jy) for dx, dy in defenders)
                    from_ball = math.hypot(jx - bx, jy - by)
                    for name, low, high in BANDS:
                        if low <= from_ball < high:
                            sums, counts = self.bands[team][name]
                            sums[s] += nearest
                            counts[s] += 1
                    self.free[players[j]][s] = 1 if nearest > FREE_M else 2
                # Depth in this team's frame (metres from its own goal).
                depth = (lambda x: (105 - x) if flip else x)
                mid_line = sum(depth(now[k][0]) for k in mids) / len(mids)
                behind_mid = sum(1 for j in theirs if depth(now[j][0]) < mid_line)
                self.spare[team][s] = len(back) - behind_mid
        self.episodes = {team: detect_episodes(track, home, team, teams[1] if team == teams[0] else teams[0]) for team in teams}


def detect_episodes(track, home: str, team: str, rival: str) -> list[dict]:
    """Counter-movement episodes of a team in possession over the whole track (outcomes are read per report)."""
    players = track.players
    n = len(players)
    xy, owner = track.xy, track.owner
    flip = team != home
    code = 1 if team == home else 2
    slot = {pid: k for k, pid in enumerate(players)}
    last = track.frames - 1

    def pos(f: int, pid: str) -> tuple[float, float]:
        b = (f * n + slot[pid]) * 2
        x, y = xy[b], xy[b + 1]
        return ((100 - x) * X_M, (100 - y) * Y_M) if flip else (x * X_M, y * Y_M)

    def owned(a: int, b: int) -> bool:
        """In possession from a to b, and settled: already in possession for the 5 s before a."""
        return a >= SETTLED_FRAMES and all(owner[f] == code for f in range(a - SETTLED_FRAMES, b + 1, 2))

    def nearest(f: int, pid: str) -> tuple[float, str]:
        px, py = pos(f, pid)
        return min((math.hypot(pos(f, q)[0] - px, pos(f, q)[1] - py), q) for q in players if q.startswith(rival + "_"))

    def ball_x(f: int) -> float:
        x = track.ball[2 * f]
        return (100 - x if flip else x)

    attackers = [pid for pid in players if pid.startswith(team + "_") and role(pid) in MIDFIELD + FORWARDS]
    depths = {pid: [pos(f, pid)[0] for f in range(track.frames)] for pid in attackers + [p for p in players if p.startswith(team + "_") and role(p) in ("RB", "LB")]}
    episodes = []
    # Drop-and-sprint.
    step = SPRINT_MPS * FRAME_MS / 1000
    for pid in attackers:
        d = depths[pid]
        f = 0
        while f + DROP_FRAMES + SPRINT_WITHIN + 10 <= last:
            if owner[f] != code or d[f + DROP_FRAMES] - d[f] > -DROP_M or not owned(f, f + DROP_FRAMES):
                f += 1
                continue
            g0 = f + DROP_FRAMES
            sprint = next((g for g in range(g0, g0 + SPRINT_WITHIN) if all(d[g + i + 1] - d[g + i] >= step for i in range(SPRINT_FRAMES))
                           and d[g + 10] - d[g] >= SPRINT_GAIN_M), None)
            if sprint is None or not owned(g0, sprint):
                f += 1
                continue
            _, marker = nearest(f, pid)
            drew = pos(f, marker)[0] - pos(g0, marker)[0] >= STEP_M
            episodes.append({"kind": "drop_and_sprint", "players": [pid], "start": f, "sprint": sprint, "end": sprint + 10, "drew": drew})
            f = sprint + 10
    # Opposite runs.
    for i, a in enumerate(attackers):
        for b in attackers[i + 1:]:
            f = 0
            while f + OPPOSITE_FRAMES <= last:
                g = f + OPPOSITE_FRAMES
                if owner[f] != code or abs(pos(f, a)[1] - pos(f, b)[1]) > OPPOSITE_LATERAL_M or not owned(f, g):
                    f += 5
                    continue
                da, db = depths[a][g] - depths[a][f], depths[b][g] - depths[b][f]
                pair = (a, b) if da <= -OPPOSITE_DROP_M and db >= OPPOSITE_RUN_M else (b, a) if db <= -OPPOSITE_DROP_M and da >= OPPOSITE_RUN_M else None
                # The runner moves into the space the dropping player has just left.
                if pair and math.hypot(pos(g, pair[1])[0] - pos(f, pair[0])[0], pos(g, pair[1])[1] - pos(f, pair[0])[1]) <= OPPOSITE_SPACE_M:
                    _, marker = nearest(f, pair[0])
                    drew = pos(f, marker)[0] - pos(g, marker)[0] >= STEP_M
                    episodes.append({"kind": "opposite_runs", "players": list(pair), "start": f, "end": g, "drew": drew})
                    f = g + 5
                else:
                    f += 5
    # Decoy runs.
    for pid in depths:
        d = depths[pid]
        f = 0
        while f + DECOY_FRAMES <= last:
            g = f + DECOY_FRAMES
            if owner[f] != code or d[g] - d[f] < DECOY_RUN_M or ball_x(f) < 40 or not owned(f, g):
                f += 1
                continue
            dist, marker = nearest(f, pid)
            if dist <= DECOY_NEAR_M and pos(g, marker)[0] - pos(f, marker)[0] >= DECOY_DRAG_M:
                mx, my = pos(f, marker)
                episodes.append({"kind": "decoy_run", "players": [pid], "start": f, "end": g + FOUND_MS // FRAME_MS, "drew": True,
                                 "marker": marker, "spot": (mx / X_M, my / Y_M)})
            f = g + 5
    return episodes


class PrinciplesEngine:
    """Shares the phase engine (and through it the movement layer); reports are cached per observed second."""

    def __init__(self, phases: PhaseEngine):
        self.phases = phases
        self._layout: Layout | None = None
        self._ready = False
        self._lock = threading.Lock()
        self._cache: dict[tuple, dict] = {}

    def layout(self) -> Layout | None:
        features = self.phases.features()
        with self._lock:
            if not self._ready:
                movement = self.phases.analytics.movement()
                match = self.phases.analytics.match
                self._layout = Layout(movement, match.home.team_id, [match.home.team_id, match.away.team_id]) \
                    if features and movement and movement.track else None
                self._ready = True
            return self._layout

    def report(self, records, playhead_ms: int) -> dict:
        layout = self.layout()
        cutoff = playhead_ms // 1000 * 1000
        key = (cutoff, len(records), sum(e.revision for e in records.values()))
        if key in self._cache:
            return self._cache[key]
        phases = self.phases.report(records, playhead_ms)
        analytics = self.phases.analytics
        result = PrincipleReport(analytics.match, analytics.movement(), records, cutoff, self.phases.features(), layout, phases).build_principles()
        if len(self._cache) > 64:
            self._cache.clear()
        self._cache[key] = result
        return result


class PrincipleReport(PhaseReport):
    def __init__(self, match, movement: Movement | None, records, playhead: int, features: Features | None, layout: Layout | None, phases: dict):
        super().__init__(match, movement, records, playhead, features)
        self.layout = layout if self.track else None
        self.phase_report = phases
        self.names = {p.player_id: p.display_name for p in match.roster}
        self.team_name = {match.home.team_id: match.home.display_name, match.away.team_id: match.away.display_name}
        self.snaps = movement.snapshots if movement else {}

    # --------------------------------------------------------------- helpers
    def attacking_codes(self, team: str) -> bytearray:
        """Per frame: 1 when the team is in settled possession (no transition or set piece)."""
        codes = bytearray(self.last_frame + 1)
        for p in self.plays:
            if p["team"] != team:
                continue
            a, b = self.frame(p["start"] + self.special_ms(p)), min(self.last_frame, self.frame(p["end"]) - 1)
            for f in range(a, b + 1):
                codes[f] = 1
        return codes

    def arrival(self, e) -> int:
        a, b = e.detail.start, e.detail.end
        return e.event_time_ms + int(math.hypot((b.x - a.x) * X_M, (b.y - a.y) * Y_M) / BALL_MPS * 1000)

    def gap_m(self, team: str, f: int, a: str, b: str) -> float:
        ax, ay = self.where(team, f, a)
        bx, by = self.where(team, f, b)
        return math.hypot((ax - bx) * X_M, (ay - by) * Y_M)

    def nearest(self, team: str, f: int, pid: str, of: str) -> tuple[float, str]:
        """Distance (m) and id of the nearest player of team ``of`` to ``pid``."""
        return min((self.gap_m(team, f, pid, q), q) for q in self.track.players if q.startswith(of + "_"))

    def moment(self, t: int, label: str, team: str | None = None) -> Moment:
        record = self.first_event(team, t - 2_000, t + 2_000) if team else None
        return Moment(time_ms=t, event_ref=record.ref if record else None, label=f"{label} ({clock(t)})")

    def roles_of(self, mask: int) -> list[str]:
        return [r for i, r in enumerate(OUTFIELD_ROLES) if mask & (1 << i)]

    def passes(self, team: str):
        for record in self.ordered:
            e = record.payload
            if e.kind == "PASS" and e.team_id == team and e.detail.completed and e.detail.recipient_id:
                yield record, e

    # ------------------------------------------------------------ structures
    def shape_rows(self, team: str, frames: list[int]) -> list[ShapeRow]:
        layout = self.layout
        counts: Counter = Counter()
        lines: dict[int, Counter] = {}
        for f in frames:
            code = layout.shape[team][f]
            counts[code] += 1
            lines.setdefault(code, Counter())[(layout.base[team][f], layout.screen[team][f])] += 1
        total = len(frames)
        rows = []
        for code, count in counts.most_common():
            base, screen = lines[code].most_common(1)[0][0]
            rows.append(ShapeRow(shape=SHAPES[code], seconds=round(count * FRAME_MS / 1000, 1), share=ratio(100 * count, total, 1),
                                 base=self.roles_of(base), screen=self.roles_of(screen)))
        return rows

    def structures(self) -> dict[str, TeamStructure]:
        result = {}
        for team in self.teams:
            if not self.layout:
                result[team] = TeamStructure(team_id=team, build_up_seconds=0, build_up=[], rest_seconds=0, rest_defence=[], behind_ball=None,
                                             overcommitted_share=None, losses=[], moments=[])
                continue
            codes = self.attacking_codes(team)
            build, rest = [], []
            for f in range(self.last_frame + 1):
                if codes[f]:
                    bx = self.ball(team, f)[0]
                    if bx < 50:
                        build.append(f)
                    elif bx >= 66.67:
                        rest.append(f)
            behind = [self.layout.behind[team][f] for f in rest]
            rival = self.other(team)
            losses: dict[int, list] = {}
            examples = []
            for p in self.plays:
                if p["team"] != rival or not p["regain"] or 100 - p["spot"][0] < 66.67:
                    continue
                f = max(0, self.frame(p["start"]) - 1)
                if f > self.last_frame:
                    continue
                code = self.layout.shape[team][f]
                fired = self.shots_in(rival, p, COUNTER_SHOT_MS)
                row = losses.setdefault(code, [0, 0, 0, 0.0])
                row[0] += 1
                row[1] += bool(p["counter"])
                row[2] += len(fired)
                row[3] += sum(q.xg for q in fired)
                if p["counter"]:
                    examples.append(Moment(time_ms=p["start"], event_ref=p["ref"],
                                           label=f"Lost in the final third with a {SHAPES[code]} rest defence ({self.layout.behind[team][f]} behind the ball): countered"))
            result[team] = TeamStructure(
                team_id=team, build_up_seconds=round(len(build) * FRAME_MS / 1000, 1), build_up=self.shape_rows(team, build),
                rest_seconds=round(len(rest) * FRAME_MS / 1000, 1), rest_defence=self.shape_rows(team, rest), behind_ball=r1(mean(behind)),
                overcommitted_share=ratio(100 * sum(1 for b in behind if b <= OVERCOMMITTED), len(behind), 1),
                losses=[RestLossRow(shape=SHAPES[code], losses=v[0], counters_conceded=v[1], shots_conceded=v[2], xg_conceded=round(v[3], 2))
                        for code, v in sorted(losses.items(), key=lambda kv: -kv[1][0])],
                moments=examples[:MOMENTS])
        return result

    # ------------------------------------------------------- wingers, width
    def wingers(self) -> tuple[list[WingerRow], dict[str, TeamWidth]]:
        rows, width = [], {}
        xt = {}
        for a in self.threats:
            xt[a.player_id] = xt.get(a.player_id, 0.0) + a.xt
        for team in self.teams:
            frames = [f for f in self.possession_frames(team) if self.ball(team, f)[0] >= 50] if self.layout else []
            for side, r in (("right", "RW"), ("left", "LW")):
                pid = f"{team}_{10 if r == 'RW' else 11:02d}"
                touch = [self.layout.touch[pid][f] for f in frames] if self.layout else []
                inside = sum(1 for d in touch if d >= WINGER_INSIDE_M)
                seconds = len(touch) * FRAME_MS / 1000
                share = ratio(100 * inside, len(touch), 1)
                mean_touch = mean(touch)
                style = "insufficient_evidence" if seconds < MIN_WINGER_S else "inverted" if share >= 40 else \
                    "touchline" if mean_touch <= TOUCHLINE_M else "balanced"
                # Width on its flank: the full-back wider than the winger with the ball in the final third on that side.
                fb = "fb_touch_right" if side == "right" else "fb_touch_left"
                flank = [f for f in frames if self.ball(team, f)[0] >= 66.67 and ((self.ball(team, f)[1] > 50) == (side == "right"))]
                wider = sum(1 for f in flank if self.feature(team, fb, f) < self.layout.touch[pid][f]) if self.layout else 0
                cut_ins, shots, central, moments = 0, 0, 0, []
                for record in self.ordered:
                    e = record.payload
                    if e.player_id != pid:
                        continue
                    if e.kind == "CARRY":
                        a, b = e.detail.start, e.detail.end
                        ta = (100 - a.y if side == "right" else a.y) * Y_M
                        tb = (100 - b.y if side == "right" else b.y) * Y_M
                        if (channel(a.y) != "centre" and channel(b.y) == "centre") or tb - ta >= CUT_IN_M:
                            cut_ins += 1
                            moments.append(Moment(time_ms=e.event_time_ms, event_ref=record.ref,
                                                  label=f"Cuts inside from {ta:.0f} m to {tb:.0f} m off the touchline"))
                    elif e.kind == "SHOT":
                        shots += 1
                        central += channel(e.detail.position.y) == "centre"
                preferred = foot(pid)
                rows.append(WingerRow(player_id=pid, team_id=team, side=side, foot=preferred, opposite_foot=(preferred == "left") == (side == "right"),
                                      style=style, seconds=round(seconds, 1), touchline_m=r1(mean_touch), inside_share=share, cut_ins=cut_ins, shots=shots,
                                      central_shots=central, fullback_width_share=ratio(100 * wider, len(flank), 1), xt=round(xt.get(pid, 0.0), 3),
                                      moments=moments[:MOMENTS]))
            codes = self.attacking_codes(team) if self.layout else bytearray()
            spread = [self.feature(team, "width", f) for f in range(len(codes)) if codes[f] and self.ball(team, f)[0] >= 66.67]
            entries = central = crosses = 0
            for record in self.ordered:
                e = record.payload
                if e.team_id != team or e.kind not in ("PASS", "CARRY") or (e.kind == "PASS" and not e.detail.completed):
                    continue
                a, b = e.detail.start, e.detail.end
                if a.x < 66.67 <= b.x:
                    entries += 1
                    central += channel(b.y) == "centre"
                if e.kind == "PASS" and a.x >= 66.67 and channel(a.y) != "centre" and in_box(b.x, b.y):
                    crosses += 1
            width[team] = TeamWidth(team_id=team, width_m=r1(mean(spread)), entries=entries, central_entry_share=ratio(100 * central, entries, 1),
                                    crosses=crosses)
        return rows, width

    # -------------------------------------------------------------- pressing
    def build_up_seconds(self, team: str) -> list[int]:
        """Seconds of the opponent's settled build-up in its own half (the team defending)."""
        codes = self.settled.get(team) or self.settled_codes(team)
        self.settled[team] = codes
        last = min(self.layout.seconds - 1 - 2, (self.last_frame - 2 * 1000 // FRAME_MS) * FRAME_MS // 1000)
        out = []
        for s in range(0, last + 1):
            f = s * 1000 // FRAME_MS
            if f < len(codes) and codes[f] and self.ball(team, f)[0] >= 50:
                out.append(s)
        return out

    def trigger_kind(self, e) -> str:
        receiver, passer = role(e.detail.recipient_id), role(e.player_id)
        if receiver == "GK":
            return "back_pass_keeper" if passer != "GK" else "other"
        if receiver in ("RB", "LB"):
            return "to_fullback"
        if receiver in ("RCB", "LCB"):
            return "to_centre_back"
        return "into_midfield" if receiver in MIDFIELD else "other"

    def pressing(self) -> dict[str, TeamPressSystem]:
        result = {}
        for team in self.teams:
            rival = self.other(team)
            outfield = [p.player_id for p in self.match.roster if p.team_id == team and role(p.player_id) != "GK"]
            seconds = self.build_up_seconds(team) if self.layout else []
            units, kinds = [], []
            for unit, roles in UNITS:
                members = [pid for pid in outfield if role(pid) in roles]
                follows = {pid: [self.layout.follow[pid][s] for s in seconds if self.layout.follow[pid][s]] for pid in members} if self.layout else {}
                samples = sum(len(v) for v in follows.values())
                followed = sum(sum(1 for x in v if x == 1) for v in follows.values())
                per = {pid: 100 * sum(1 for x in v if x == 1) / len(v) for pid, v in follows.items() if len(v) >= MIN_FOLLOW_SAMPLES}
                markers = [pid for pid, share in sorted(per.items(), key=lambda kv: -kv[1]) if share >= MAN_SHARE]
                zonal = [pid for pid, share in per.items() if share <= ZONAL_SHARE]
                if len(per) < 2:
                    kind = "insufficient_evidence"
                else:
                    kind = "man" if len(markers) * 2 > len(members) else "zonal" if len(zonal) * 2 > len(members) else "mixed"
                kinds.append(kind)
                near = [self.layout.near[pid][s] for pid in members for s in seconds] if self.layout else []
                units.append(PressUnit(unit=unit, samples=samples, follow_share=ratio(100 * followed, samples, 1), distance_m=r1(mean(near)),
                                       marking=kind, markers=markers))
            known = [k for k in kinds if k != "insufficient_evidence"]
            system = "insufficient_evidence" if not known else "man_to_man" if all(k == "man" for k in known) else \
                "zonal" if all(k == "zonal" for k in known) else "hybrid"
            spare = [self.layout.spare[team][s] for s in seconds] if self.layout else []
            rivals = [p.player_id for p in self.match.roster if p.team_id == rival and role(p.player_id) != "GK"]
            free = {pid: sum(1 for s in seconds if self.layout.free[pid][s] == 1) for pid in rivals} if self.layout and seconds else {}
            left = max(free, key=lambda pid: free[pid]) if free and max(free.values()) else None

            # Pressing triggers: pressure on the receiver of opponent passes into its own half.
            rows = {kind: {"passes": 0, "tracked": 0, "pressured": 0, "times": [], "regained": 0} for kind in TRIGGERS}
            shadow = shadow_tracked = 0
            examples = []
            regains = sorted(p["start"] for p in self.plays if p["team"] == team and p["regain"])
            dm = f"{rival}_06"
            for record, e in self.passes(rival):
                if e.detail.end.x >= 50 or self.possession_at(e.event_time_ms) is None:
                    continue
                kind = self.trigger_kind(e)
                row = rows[kind]
                row["passes"] += 1
                arrive = self.arrival(e)
                fa = self.frame(arrive)
                if not self.track or fa + PRESSURE_WINDOW_FRAMES > self.last_frame:
                    continue
                row["tracked"] += 1
                receiver = e.detail.recipient_id
                took, presser = None, None
                for f in range(fa, fa + PRESSURE_WINDOW_FRAMES + 1):
                    d, q = self.nearest(rival, f, receiver, team)
                    if d <= PRESSURE_M:
                        took, presser = (f - fa) * FRAME_MS / 1000, (f, q)
                        break
                won = any(arrive < t <= arrive + 5_000 for t in regains)
                row["regained"] += won
                if took is None:
                    continue
                row["pressured"] += 1
                row["times"].append(took)
                if kind in ("back_pass_keeper", "to_centre_back"):
                    shadow_tracked += 1
                    f, q = presser
                    rx, ry = self.where(rival, f, receiver)
                    px, py = self.where(rival, max(fa, f - 5), q)       # the approach, 1 s before contact
                    dx, dy = self.where(rival, f, dm)
                    a1 = math.atan2((py - ry) * Y_M, (px - rx) * X_M)
                    a2 = math.atan2((dy - ry) * Y_M, (dx - rx) * X_M)
                    angle = abs((math.degrees(a1 - a2) + 180) % 360 - 180)
                    if angle <= SHADOW_DEG:
                        shadow += 1
                if won:
                    examples.append(Moment(time_ms=e.event_time_ms, event_ref=record.ref,
                                           label=f"{self.names[receiver]} pressed {took:.1f} s after a pass {trigger_text(kind)}; ball won back"))
            triggers = [TriggerRow(trigger=kind, passes=v["passes"], tracked=v["tracked"], pressured=v["pressured"],
                                   rate=ratio(100 * v["pressured"], v["tracked"], 1), median_s=r1(median(v["times"])) if v["times"] else None,
                                   regained_5s=v["regained"]) for kind, v in rows.items() if v["passes"]]

            # Forced wide: where the opponent's build-ups from its own third first reach the middle third.
            build_ups = wide = 0
            for p in self.plays:
                if p["team"] != rival or p["spot"][0] >= 33.3:
                    continue
                for record in p["events"]:
                    e = record.payload
                    if e.kind in ("PASS", "CARRY") and (e.kind == "CARRY" or e.detail.completed) and e.detail.start.x < 33.3 <= e.detail.end.x:
                        build_ups += 1
                        wide += channel(e.detail.end.y) != "centre"
                        break
            by_channel = {"left": 0, "centre": 0, "right": 0}
            for p in self.plays:
                if p["team"] == team and p["regain"] and p["spot"][0] >= 50:
                    by_channel[channel(p["spot"][1])] += 1
            result[team] = TeamPressSystem(
                team_id=team, seconds=float(len(seconds)), system=system, units=units, spare_at_back=r1(mean(spare)),
                left_free=left, left_free_share=ratio(100 * free[left], len(seconds), 1) if left else None, triggers=triggers,
                cover_shadow=shadow, cover_shadow_tracked=shadow_tracked, build_ups=build_ups, forced_wide_share=ratio(100 * wide, build_ups, 1),
                regains_by_channel=by_channel, moments=examples[:MOMENTS])
        return result

    # --------------------------------------------------------------- marking
    def marking(self) -> dict[str, TeamMarking]:
        result = {}
        for team in self.teams:
            rival = self.other(team)
            bands = []
            if self.layout:
                codes = self.settled.get(team) or self.settled_codes(team)
                self.settled[team] = codes
                secs = [s for s in range(min(self.layout.seconds, self.last_frame * FRAME_MS // 1000 + 1)) if codes[min(len(codes) - 1, s * 1000 // FRAME_MS)]]
                for name, *_ in BANDS:
                    sums, counts = self.layout.bands[team][name]
                    total, count = sum(sums[s] for s in secs), sum(counts[s] for s in secs)
                    bands.append(MarkingBand(band=name, samples=count, distance_m=r1(total / count) if count else None))
            receptions = free = between = 0
            players: dict[str, list[int]] = {}
            examples = []
            for record, e in self.passes(rival):
                if e.detail.end.x < 33.3:
                    continue
                fa = self.frame(self.arrival(e))
                if not self.track or fa > self.last_frame:
                    continue
                receptions += 1
                receiver = e.detail.recipient_id
                d, _ = self.nearest(rival, fa, receiver, team)
                if d < RECEPTION_FREE_M:
                    continue
                free += 1
                row = players.setdefault(receiver, [0, 0])
                row[0] += 1
                depth = self.where(team, fa, receiver)[0] * X_M
                back = self.feature(team, "back_four", fa)
                if back < depth < back + self.feature(team, "gap", fa):
                    between += 1
                    row[1] += 1
                    examples.append((-d, Moment(time_ms=e.event_time_ms, event_ref=record.ref,
                                                label=f"{self.names[receiver]} free between the lines: nearest defender {d:.0f} m away")))
            examples.sort(key=lambda m: m[0])
            result[team] = TeamMarking(team_id=team, bands=bands, receptions=receptions, free=free, free_between_lines=between,
                                       free_players=[FreeReceiver(player_id=pid, free=v[0], between_lines=v[1])
                                                     for pid, v in sorted(players.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))[:5]],
                                       moments=[m for _, m in examples[:MOMENTS]])
        return result

    # ------------------------------------------------------- counter-movements
    def received_by(self, team: str, t0: int, t1: int, pid: str | None = None, near: tuple[float, float] | None = None,
                    exclude: str | None = None) -> bool:
        for record, e in self.passes(team):
            if e.event_time_ms > t1:
                break
            if e.event_time_ms < t0:
                continue
            if pid and e.detail.recipient_id == pid:
                return True
            if near and e.detail.recipient_id != exclude and math.hypot((e.detail.end.x - near[0]) * X_M, (e.detail.end.y - near[1]) * Y_M) <= DECOY_SPACE_M:
                return True
        return False

    def movements(self) -> dict[str, TeamMovements]:
        result = {}
        for team in self.teams:
            if not self.layout:
                result[team] = TeamMovements(team_id=team, rows=[], corners=0, crisscross_corners=0)
                continue
            found: dict[tuple, dict] = {}
            for ep in self.layout.episodes[team]:
                if ep["end"] > self.last_frame:
                    continue
                kind, players, f = ep["kind"], ep["players"], ep["start"]
                t0 = f * FRAME_MS
                if kind == "drop_and_sprint":
                    hit = self.received_by(team, ep["sprint"] * FRAME_MS, ep["sprint"] * FRAME_MS + FOUND_MS, pid=players[0])
                    label = f"{self.names[players[0]]} drops, then sprints in behind" + (", marker steps out" if ep["drew"] else "")
                elif kind == "opposite_runs":
                    t1 = ep["end"] * FRAME_MS + FOUND_MS
                    hit = self.received_by(team, t0, t1, pid=players[0]) or self.received_by(team, t0, t1, pid=players[1])
                    label = f"{self.names[players[0]]} drops as {self.names[players[1]]} runs beyond"
                else:
                    hit = self.received_by(team, t0, t0 + FOUND_MS, near=ep["spot"], exclude=players[0])
                    label = f"{self.names[players[0]]}'s run drags {self.names[ep['marker']]}" + (" and a team-mate uses the space" if hit else "")
                add_episode(found, kind, players, ep["drew"], hit, self.moment(t0, label, team))

            # Crisscross runs at corners.
            corners = criss = 0
            depth = lambda f, pid: self.where(team, f, pid)[0] * X_M
            for p in self.plays:
                if p["team"] != team or p["restart"] != "corner" or not p["events"]:
                    continue
                delivery = p["events"][0].payload
                fd = self.frame(delivery.event_time_ms)
                fs = fd - CRISS_MS // FRAME_MS
                if fs < 0 or fd > self.last_frame:
                    continue
                corners += 1
                box = [q.player_id for q in self.match.roster if q.team_id == team and role(q.player_id) != "GK" and depth(fd, q.player_id) >= 85]
                pairs = []
                for i, a in enumerate(box):
                    for b in box[i + 1:]:
                        swap = (self.where(team, fs, a)[1] - self.where(team, fs, b)[1]) * (self.where(team, fd, a)[1] - self.where(team, fd, b)[1]) < 0
                        moved = all(math.hypot((self.where(team, fd, x)[0] - self.where(team, fs, x)[0]) * X_M,
                                               (self.where(team, fd, x)[1] - self.where(team, fs, x)[1]) * Y_M) >= CRISS_MOVE_M for x in (a, b))
                        if swap and moved:
                            pairs.append((a, b))
                if pairs:
                    criss += 1
                    a, b = pairs[0]
                    won = delivery.kind == "PASS" and delivery.detail.completed
                    add_episode(found, "crisscross", [a, b], True, won, self.moment(fs * FRAME_MS, f"{self.names[a]} and {self.names[b]} cross runs at a corner"
                                                                                    + (", first contact won" if won else ""), team))
            rows = [MovementRow(kind=kind, players=list(players), episodes=v["episodes"], drew=v["drew"], found=v["found"], moments=v["moments"][-MOMENTS:])
                    for (kind, players), v in found.items()]
            rows.sort(key=lambda r: (MOVEMENT_KINDS.index(r.kind), -r.episodes))
            result[team] = TeamMovements(team_id=team, rows=rows, corners=corners, crisscross_corners=criss)
        return result

    # ------------------------------------------------------------ third man
    def third_man(self) -> dict[str, TeamThirdMan]:
        result = {}
        for team in self.teams:
            rival = self.other(team)
            passes = list(self.passes(team))
            count, tracked, blocked, free, gains, ft, shots = 0, 0, 0, 0, [], 0, 0
            zones = {"build_up": 0, "middle_third": 0, "final_third": 0}
            patterns: Counter = Counter()
            examples = []
            for (r1_, first), (r2, second) in zip(passes, passes[1:]):
                if second.player_id != first.detail.recipient_id or second.possession_id != first.possession_id:
                    continue
                if second.detail.recipient_id == first.player_id or second.event_time_ms - first.event_time_ms > LAY_OFF_MS:
                    continue
                if second.detail.end.x <= first.detail.start.x:
                    continue
                a, b, c = first.player_id, first.detail.recipient_id, second.detail.recipient_id
                count += 1
                zone = "build_up" if first.detail.start.x < 33.3 else "final_third" if second.detail.end.x >= 66.67 else "middle_third"
                zones[zone] += 1
                patterns[(a, b, c)] += 1
                gains.append((second.detail.end.x - first.detail.start.x) * X_M)
                p = self.possession_at(first.event_time_ms)
                if p:
                    reached = self.reached_final_third(p)
                    ft += reached is not None and p["start"] + reached >= first.event_time_ms - 1 and p["start"] + reached - first.event_time_ms <= FINAL_THIRD_MS
                    shots += any(first.event_time_ms <= q.time_ms <= first.event_time_ms + COUNTER_SHOT_MS for q in self.shots_in(team, p, 10**9))
                fa = self.frame(self.arrival(second))
                snap = self.snaps.get(r1_.event_id)
                lane = None
                if self.track and snap and fa <= self.last_frame:
                    tracked += 1
                    flip = team != self.home
                    pos = {pid: ((100 - x, 100 - y) if flip else (x, y)) for pid, (x, y) in snap.items()}
                    ax, ay = first.detail.start.x * X_M, first.detail.start.y * Y_M
                    cx, cy = pos[c][0] * X_M, pos[c][1] * Y_M
                    lane = any(segment_distance((ox * X_M, oy * Y_M), (ax, ay), (cx, cy)) <= LANE_M for pid, (ox, oy) in pos.items() if pid.startswith(rival + "_"))
                    blocked += lane
                    d, _ = self.nearest(team, fa, c, rival)
                    free += d >= RECEPTION_FREE_M
                examples.append(Moment(time_ms=first.event_time_ms, event_ref=r1_.ref,
                                       label=f"{self.names[a]} to {self.names[b]}, set first time for {self.names[c]}" + (" (direct lane blocked)" if lane else "")))
            result[team] = TeamThirdMan(team_id=team, combinations=count, by_zone=zones, tracked=tracked, lane_blocked=blocked, receiver_free=free,
                                        progress_m=r1(mean(gains)), final_third_10s=ft, shots_15s=shots,
                                        patterns=[ThirdManRow(first=a, second=b, third=c, count=n) for (a, b, c), n in patterns.most_common(5)],
                                        moments=examples[-MOMENTS:])
        return result

    # ---------------------------------------------------------- match report
    def match_report(self, structures, wingers, width, pressing, marking, movements, third) -> dict[str, MatchReportTeam]:
        ph = self.phase_report
        result = {}
        for team in self.teams:
            rival = self.other(team)
            who, them = self.team_name[team], self.team_name[rival]
            lines, strengths, weaknesses = [], [], []
            control, prog = ph["control"][team], ph["progression"][team]
            press, attack = ph["transitions"][team].defensive, ph["transitions"][team].attacking
            blocks = [r for r in ph["blocks"][team].rows if r.seconds]
            s = structures[team]

            # In possession.
            parts = []
            if s.build_up:
                top = s.build_up[0]
                parts.append(f"built up in a {top.shape} ({top.share:.0f}% of build-up time; base {unit_name(top.base)})")
            if prog.xt:
                flank = max(prog.xt_by_channel, key=lambda k: prog.xt_by_channel[k])
                parts.append(f"added most threat through the {flank} ({prog.xt_by_channel[flank]:+.2f} of {prog.xt:+.2f} xT)")
            tm = third[team]
            if tm.combinations:
                parts.append(f"used {plural(tm.combinations, 'third-man combination')}")
            inverted = [w for w in wingers if w.team_id == team and w.style == "inverted"]
            if inverted:
                parts.append(f"{self.names[inverted[0].player_id]} played as an inverted winger ({inverted[0].inside_share:.0f}% of attacking time inside)")
            if control.read != "insufficient_evidence":
                parts.append(f"{control.possession_share:.0f}% possession and {control.field_tilt:.0f}% field tilt")
            lines.append(ReportLine(topic="In possession", text=f"{who} " + "; ".join(parts) + "." if parts else "Not enough possession observed yet.",
                                    moments=tm.moments[:1]))

            # Out of possession.
            parts = []
            p = pressing[team]
            if blocks:
                main = max(blocks, key=lambda r: r.seconds)
                parts.append(f"defended mostly in a {main.block} block (back four at {main.back_four_m} m, {main.share:.0f}% of settled defending)")
            if p.system != "insufficient_evidence":
                markers = [u for u in p.units if u.marking == "man"]
                desc = {"man_to_man": "pressed man-to-man", "zonal": "pressed zonally",
                        "hybrid": "pressed with a hybrid: " + ", ".join(f"{u.unit} {u.marking}" for u in p.units if u.marking != "insufficient_evidence")}[p.system]
                parts.append(desc)
                if markers and markers[0].markers:
                    parts.append(f"{', '.join(self.names[m] for m in markers[0].markers)} followed their man")
            hot = [t for t in p.triggers if t.tracked >= 3 and t.rate is not None]
            if hot:
                best = max(hot, key=lambda t: t.rate)
                parts.append(f"pressed hardest on passes {trigger_text(best.trigger)} ({best.pressured} of {best.tracked}, {best.rate:.0f}%)")
            if p.spare_at_back is not None:
                parts.append(f"had {p.spare_at_back:+.1f} spare at the back against the build-up")
            lines.append(ReportLine(topic="Out of possession", text=f"{who} " + "; ".join(parts) + "." if parts else "Not enough defending observed yet.",
                                    moments=p.moments[:1]))

            # Attack to defence.
            parts = []
            if press.tracked:
                parts.append(f"counter-pressed after {press.pressed} of {press.tracked} losses ({press.press_rate:.0f}%), winning the ball back within 5 s {times(press.regained_5s)}")
            if s.rest_defence:
                top = s.rest_defence[0]
                parts.append(f"held a {top.shape} rest defence with the ball in the final third ({top.share:.0f}%), {s.behind_ball} players behind the ball on average")
            conceded = sum(r.counters_conceded for r in s.losses)
            if s.losses:
                parts.append(f"conceded {plural(conceded, 'counter')} from {plural(sum(r.losses for r in s.losses), 'final-third loss', 'final-third losses')}")
            lines.append(ReportLine(topic="Attack to defence", text=f"{who} " + "; ".join(parts) + "." if parts else "No losses observed yet.",
                                    moments=(press.moments + s.moments)[:1]))

            # Defence to attack.
            if attack.regains:
                vertical = attack.counters
                text = (f"{who} won the ball {times(attack.regains)} in open play; {attack.counters} became counters that reached the final third within 10 s "
                        f"and {attack.recycled} {'was' if attack.recycled == 1 else 'were'} recycled. "
                        + ("Transitions were mostly fast and vertical." if vertical > attack.recycled else "Transitions were mostly controlled resets."))
            else:
                text = "No open-play regains observed yet."
            lines.append(ReportLine(topic="Defence to attack", text=text, moments=attack.moments[:1]))

            # Set pieces.
            mv = movements[team]
            restarts = ph["phases"][team].restarts
            corners = restarts.get("corner", 0)
            set_row = next((r for r in ph["phases"][team].rows if r.phase == "attacking_set_piece"), None)
            text = (f"{who} took {plural(corners, 'corner')}" + (f", with crisscross runs at {mv.crisscross_corners}" if mv.corners else "")
                    + (f"; {plural(set_row.shots_for, 'shot')} ({set_row.xg_for:.2f} xG) came from set pieces." if set_row else "."))
            lines.append(ReportLine(topic="Set pieces", text=text, moments=[]))

            # Strengths and weaknesses (to target), with numbers.
            if press.tracked >= 5 and press.press_rate is not None and press.press_rate >= 60:
                strengths.append(ReportLine(topic="Counter-press", text=f"Pressed the ball after {press.press_rate:.0f}% of losses and won it back within 5 s {times(press.regained_5s)}.",
                                            moments=press.moments[:2]))
            if tm.combinations >= 3:
                strengths.append(ReportLine(topic="Third-man combinations", text=f"{tm.combinations} combinations, the receiver free on arrival {tm.receiver_free} of {tm.tracked} times, gaining {tm.progress_m} m on average.",
                                            moments=tm.moments[:2]))
            sprint = [r for r in mv.rows if r.kind == "drop_and_sprint" and r.episodes >= 3]
            if sprint:
                r = sprint[0]
                strengths.append(ReportLine(topic="Counter-movement", text=f"{self.names[r.players[0]]} dropped and then sprinted in behind {times(r.episodes)}; a marker stepped out with the drop {times(r.drew)}.",
                                            moments=r.moments[:2]))
            if prog.xt > 0 and prog.xt_by_channel:
                flank = max(prog.xt_by_channel, key=lambda k: prog.xt_by_channel[k])
                share = 100 * prog.xt_by_channel[flank] / prog.xt if prog.xt else 0
                if share >= 45:
                    strengths.append(ReportLine(topic="Main route to goal", text=f"{share:.0f}% of the expected threat came through the {flank}.", moments=[]))
            if s.overcommitted_share is not None and s.rest_seconds >= 30 and s.overcommitted_share >= 25:
                weaknesses.append(ReportLine(topic="Rest defence", text=f"Only {OVERCOMMITTED} or fewer players stayed {BEHIND_BALL_M:.0f} m behind the ball for {s.overcommitted_share:.0f}% of final-third possession.",
                                             moments=s.moments[:2]))
            if conceded >= 2:
                weaknesses.append(ReportLine(topic="Counters after losses high up", text=f"{them} countered {times(conceded)} after {who} lost the ball in the final third.",
                                             moments=s.moments[:2]))
            m = marking[team]
            if m.receptions >= 10 and m.free_between_lines >= 3:
                weaknesses.append(ReportLine(topic="Free men between the lines", text=f"{them} found a free receiver between {who}'s lines {times(m.free_between_lines)} ({m.free} free receptions of {m.receptions} in the middle and final thirds).",
                                             moments=m.moments[:2]))
            rec = ph["blocks"][team].recovery
            if rec.balls_in_behind >= 3:
                weaknesses.append(ReportLine(topic="Space behind the line", text=f"{plural(rec.balls_in_behind, 'ball')} played in behind the back four; {plural(rec.shots_conceded, 'shot')} conceded within 10 s.",
                                             moments=rec.moments[:2]))
            wide_wingers = [w for w in wingers if w.team_id == team and w.style == "inverted" and w.fullback_width_share is not None and w.fullback_width_share >= 50]
            if wide_wingers:
                w = wide_wingers[0]
                weaknesses.append(ReportLine(topic="Flank left by the inverted winger",
                                             text=f"With {self.names[w.player_id]} inside, the {w.side}-back gave the width {w.fullback_width_share:.0f}% of the time on that flank, so a turnover can leave the flank open.",
                                             moments=w.moments[:1]))
            if press.tracked >= 5 and press.press_rate is not None and press.press_rate < 35:
                weaknesses.append(ReportLine(topic="Slow reaction to losses", text=f"Pressed the ball after only {press.press_rate:.0f}% of losses; the opponent moved the ball 20 m upfield within 10 s {times(press.bypassed)}.",
                                             moments=press.moments[:1]))

            key = [r for r in ph["player_progression"] if r.team_id == team]
            key.sort(key=lambda r: -r.xt)
            key_player = key[0].player_id if key and key[0].xt > 0 else None
            reason = (f"Most expected threat added ({key[0].xt:+.3f} xT from {key[0].progressive_passes} progressive passes and "
                      f"{key[0].progressive_carries} progressive carries).") if key_player else None
            summary = " ".join(filter(None, [
                f"{who}: {control.possession_share:.0f}% of the ball, {control.xg:.2f} xG." if control.read != "insufficient_evidence" else None,
                f"Build-up {s.build_up[0].shape}, rest defence {s.rest_defence[0].shape}." if s.build_up and s.rest_defence else None,
                {"man_to_man": "Man-to-man press.", "zonal": "Zonal press.", "hybrid": "Hybrid press."}.get(p.system),
                f"Watch {self.names[key_player]}." if key_player else None]))
            result[team] = MatchReportTeam(team_id=team, summary=summary or "Not enough play observed yet.", phases=lines, strengths=strengths,
                                           weaknesses=weaknesses, key_player=key_player, key_player_reason=reason)
        return result

    # ----------------------------------------------------------------- build
    def build_principles(self) -> dict:
        limitations = list(LIMITATIONS)
        if not self.layout:
            limitations.append("Movement tracking is unavailable because the fixture does not match the tracking source, so off-ball measures are empty.")
        structures = self.structures()
        wingers, width = self.wingers()
        pressing = self.pressing()
        marking = self.marking()
        movements = self.movements()
        third = self.third_man()
        return {"structures": structures, "wingers": wingers, "width": width, "pressing": pressing, "marking": marking, "movements": movements,
                "third_man": third, "match_report": self.match_report(structures, wingers, width, pressing, marking, movements, third),
                "definitions": DEFINITIONS, "limitations": limitations}


MOVEMENT_KINDS = ("drop_and_sprint", "opposite_runs", "decoy_run", "crisscross")


def add_episode(found: dict, kind: str, players: list[str], drew: bool, hit: bool, moment: Moment):
    # Pairs are unordered: the striker dropping as the midfielder runs beyond, and the swap back, are the same pattern.
    row = found.setdefault((kind, tuple(sorted(players))), {"episodes": 0, "drew": 0, "found": 0, "moments": []})
    row["episodes"] += 1
    row["drew"] += drew
    row["found"] += hit
    # Keep the latest moments, preferring ones where the ball found the movement.
    if hit or not row["moments"]:
        row["moments"].append(moment)


def trigger_text(kind: str) -> str:
    return {"back_pass_keeper": "back to the keeper", "to_fullback": "out to a full-back", "to_centre_back": "to a centre-back",
            "into_midfield": "into midfield", "other": "elsewhere"}[kind]


def segment_distance(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance from p to the segment a-b, ignoring the last 3 m at either end (the passer and receiver themselves)."""
    ax, ay = a
    bx, by = b
    length = math.hypot(bx - ax, by - ay)
    if length < 7:
        return 1e9
    u = ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / (length * length)
    if u * length < 3 or (1 - u) * length < 3:
        return 1e9
    return math.hypot(p[0] - (ax + u * (bx - ax)), p[1] - (ay + u * (by - ay)))
