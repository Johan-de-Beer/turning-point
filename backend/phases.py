"""Game phases (phases_v1): phases of play, transitions and counter-pressing, defensive blocks,
ball progression (progressive carries and expected threat), full-back roles, positional
rotations, possession against control, pressing over time, finishing, and analyst notes that
pair each number with moments to watch on the replay.

``PhaseReport`` extends the live analytics report, so it shares its observed prefix, its
possessions, regains, shot quality and the continuous synthetic movement layer. Off-ball
measures read the layer's frame track (every player and the ball at 5 Hz); like the rest of
the analytics they never read the generator's tendencies or plans, and tests recover the
planted behaviour from these numbers.

Coordinates are team-relative (the team in question attacks toward x = 100) unless a name
says ``home``. Depths are metres from the team's own goal line.
"""
from __future__ import annotations

import math
import threading
from array import array
from bisect import bisect_right
from statistics import median

from .advanced import FORWARD_M, PPDA_ZONE_X, metres_to_goal, progressive, ratio, third
from .analytics import HIGH_LINE_M, LOW_LINE_M, AnalyticsEngine, AnalyticsReport
from .chances import X_M, Y_M, in_box
from .models import (AnalystNote, AttackingTransitions, BlockRow, ControlRow, CounterPress, EventEnvelope, FinishingRow, FullbackRow,
                     LineSnapshot, Moment, PERIOD_MS, PhaseRow, PlayerProgression, PressInterval, Recovery, RotationRow, TeamBlocks,
                     TeamPhases, TeamPressing, TeamProgression, TeamRotations, TeamTransitions, TeamXg, ThreatAction, XtGrid)
from .movement import Movement
from .tactical_profiles import BACK_FOUR, FORWARDS, MIDFIELD, player_for, role
from .tracking import FRAME_MS
from .xt import grid as xt_grid, threat

TRANSITION_MS = 10_000      # transition phase: the first 10 s after an open-play regain or loss
SET_PIECE_MS = 10_000       # set-piece phase: the first 10 s after a corner, free kick or throw-in
SET_PIECES = ("corner", "free_kick", "throw_in")
COUNTER_MS = 10_000         # a counter reaches the final third this soon after the regain
COUNTER_SHOT_MS = 15_000
LOST_QUICKLY_MS = 5_000
PRESS_WINDOW_MS = 3_000     # counter-press: pressure on the ball this soon after losing it
PRESSURE_M = 3.0
PACK_M = 10.0
PACK_AT_MS = 2_000
BYPASS_M = 20.0
RECOVERY_MS = 5_000
SWEEP_MS = 5_000
BOX_DEPTH_M, BOX_HALF_WIDTH_M = 16.5, 20.16
DEFENDING_THIRD_M = 35.0
BUILD_UP_MS = 8_000
HIGH_PRESS_M = 5.0
INSIDE_M = 18.0             # a full-back this far from the touchline is inside, in the half-space or centre
OVERLAP_FRAMES = 5          # 1 s
ROTATION_FRAMES = 10        # 2 s
STERILE_PASSES = 5
HIGH_REGAIN_X = 60.0
INTERVAL_MS = 900_000
MIN_FULLBACK_S = 60
TOP_THREAT = 10
MOMENTS = 3

PHASES = ("attacking", "attacking_transition", "attacking_set_piece", "defending", "defensive_transition", "defending_set_piece")
MIRROR = {"attacking": "defending", "attacking_transition": "defensive_transition", "attacking_set_piece": "defending_set_piece"}

DEFINITIONS = {
    "phases_of_play": f"Each team's live-ball time split into six phases: attacking (settled possession), defending (settled out of possession), attacking and defensive transitions (the first {TRANSITION_MS // 1000} s after an open-play regain or loss, or {COUNTER_SHOT_MS // 1000} s while it is a counter that reached the final third) and set pieces (the first {SET_PIECE_MS // 1000} s after a corner, free kick or throw-in, attacking or defending). Goal kicks and kick-offs start the attacking phase. Shots, xG and goals are credited to the phase in which the shot's possession was at the time.",
    "counter": f"An attacking transition that reaches the final third (x ≥ 66.67) within {COUNTER_MS // 1000} s of an open-play regain outside it. Recycled: the first action after the regain goes sideways or backward (less than {FORWARD_M:.0f} m of depth). Lost quickly: the possession ends within {LOST_QUICKLY_MS // 1000} s without reaching the final third. Counter shots are shots within {COUNTER_SHOT_MS // 1000} s of a regain.",
    "counter_press": f"After each open-play loss, from the 5 Hz synthetic positions: pressed when a player other than the one who lost it gets within {PRESSURE_M:.0f} m of the ball within {PRESS_WINDOW_MS // 1000} s; the pack is how many of the team's outfield players are within {PACK_M:.0f} m of the ball {PACK_AT_MS // 1000} s after the loss. Regained within 5 or 10 s comes from the events. Bypassed: the opponent moved the ball {BYPASS_M:.0f} m or more upfield within 10 s.",
    "rest_defence": "At the moment of each loss: how many outfield players were goal-side of the ball (nearer their own goal than it), and how many of those were back-four defenders.",
    "blocks": f"Settled defending time (out of possession, outside transitions and set pieces) classed every 200 ms by the back four's mean depth: high at {HIGH_LINE_M:.0f} m or more, low under {LOW_LINE_M:.0f} m, mid in between. For each block: length (deepest to highest outfield player), width, the gap between the back four and the midfield three, players in their own box while the ball is in their defending third ({DEFENDING_THIRD_M:.0f} m), and what the opponent did against it.",
    "wide_entries": "Opponent entries into its final third (completed passes and carries) ending in a wide channel (y < 33.3 or y > 66.7): the share of entries a block forced wide.",
    "long_shots": "Shots from outside the penalty area.",
    "crosses_faced": "Opponent passes from a wide channel of its final third into the penalty area.",
    "line_snapshots": f"The line during the opponent's first build-up (the first {BUILD_UP_MS // 1000} s of a possession it starts in its own third from a restart or its goalkeeper) and during a high press (the opponent has the ball in its own third and one of the team's players is within {HIGH_PRESS_M:.0f} m of it), against settled defending. Front line: mean depth of the three forwards.",
    "recovery": f"Balls in behind: opponent completed passes that end nearer the team's goal than its deepest outfield player, within 45 m of goal. Retreat is the back four's mean drop in depth over the next {RECOVERY_MS // 1000} s; top speed their fastest recovery speed; the keeper's distance from the goal line as the pass is played and the furthest within {SWEEP_MS // 1000} s. A sweep is the keeper leaving the penalty area ({BOX_DEPTH_M} m) in that time.",
    "progressive_carry": "A carry that moves the ball at least 10 m closer to the centre of the opponent's goal, or 5 m when it starts in the final 40% of the pitch (x ≥ 60), and ends further forward than it started (StatsBomb / FBref convention). Progressive carry metres add up the forward distance of those carries.",
    "take_on": "A carry that beat a challenge on the way (the defender lost the ground duel). Unlike a progressive carry it says nothing about how far the ball moved.",
    "xt": "Expected threat: each zone of a 12 x 8 grid has the chance that a possession there ends in a goal within the next few actions, learned by value iteration from how play moved in 24 other synthetic matches (never this one). A completed pass or carry is worth xT(end zone) − xT(start zone). Failed actions are not valued, as in the original method.",
    "xt_vs_pv": "Possession value (in Live analytics) uses a hand-set surface that rises steadily toward goal. xT is learned from the synthetic matches, so it shows where that play really leads to shots, including quirks of the generator.",
    "fullback_style": f"From the 5 Hz synthetic positions while the team has the ball: inverted when the full-back spends 40% or more of build-up time {INSIDE_M:.0f} m or more from the touchline; overlapping or underlapping when it gets ahead of its winger outside (wider) or inside (narrower) at least 3 times and twice as often as the other way; holding when, with the ball in the final third, it stays under 52 m from its own goal on average; otherwise balanced. At least {MIN_FULLBACK_S} s in possession is needed.",
    "overlap": "A full-back at least 2 m ahead of the winger on its side and at least 3 m wider, for 1 s or more. An underlap is the same run 3 m or more inside the winger.",
    "rotations": f"Position swaps held for {ROTATION_FRAMES * FRAME_MS // 1000} s or more while the team has the ball: the holding midfielder dropping level with or behind the centre-backs and between them; the striker dropping behind the most advanced central midfielder; a full-back overlapping or underlapping its winger (1 s); a full-back stepping inside (18 m or more from the touchline, 5 m ahead of the centre-backs) before the final third. The final-third rate compares possessions with the rotation against those without.",
    "control": f"Possession against control. Purposeful possessions reach the final third or a shot; sterile ones string {STERILE_PASSES} or more completed passes without either. The read compares possession with field tilt: control with territory (both 55% or more), possession without penetration (55% or more of the ball, under 50% of the final-third passes), territory without the ball (45% or less of the ball, 45% or more of the territory), pinned back (both under 45% and 40%), otherwise balanced.",
    "ppda_intervals": f"PPDA as in Live analytics (opponent passes in its own {PPDA_ZONE_X:.0f}% ÷ this team's duels and interceptions there), by half and by 15 minutes. High regains are open-play regains in the attacking 40% (x ≥ {HIGH_REGAIN_X:.0f}); their shots are within {COUNTER_SHOT_MS // 1000} s.",
    "finishing": "Goals minus xG per shooter: above zero, more goals than the chances' quality suggests. One match is far too small a sample to call anyone a good or poor finisher.",
    "analyst_notes": "Each note pairs a number (with its sample) with moments to watch on the replay: the data says what happened, the pictures show why. The notes do not explain causes; they point to where to look.",
}

LIMITATIONS = [
    "Synthetic data: the events and the 5 Hz player positions are generated from fictional tendencies. Off-ball movement between events is illustrative.",
    "Phases, counters and set pieces are classified from the event stream with fixed windows. Real analysts judge where a transition ends by the shape of both teams, not by a timer.",
    "Counter-pressing, blocks, recovery runs, full-back roles and rotations come from synthetic positions, so they show what the generator planted plus noise. Thresholds are documented conventions, not calibrated against real tracking data.",
    "Expected threat is learned from 24 synthetic matches built by the same scripted generator, so it inherits the generator's habits (for example keepers' long balls that reach a forward directly). It is not a model of real football.",
    "Free kicks and throw-ins are rare or absent in the synthetic events (fouls are recorded only as stoppages and the ball goes out mostly for goal kicks), so the set-piece phase is mostly corners.",
    "One match is a small sample. Read rates with their counts, and the analyst notes as prompts for what to watch, not conclusions.",
]


def r1(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def channel(y: float) -> str:
    return "left" if y < 33.3 else "right" if y > 66.7 else "centre"


def plural(n: int, word: str, words: str | None = None) -> str:
    return f"{n} {word if n == 1 else words or word + 's'}"


def times(n: int) -> str:
    return "once" if n == 1 else "twice" if n == 2 else f"{n} times"


def article(word: str) -> str:
    return ("an " if word[:1] in "aeiou" else "a ") + word


ROTATION_NAMES = {"holding_midfielder_drops": "holding midfielder drops in", "striker_drops": "striker drops deep",
                  "wide_overlap": "full-back overlaps", "wide_underlap": "full-back underlaps", "fullback_inverts": "full-back steps inside"}


def clock(t: int) -> str:
    return f"{t // 60_000}:{t // 1000 % 60:02d}"


class Features:
    """Per-frame figures and positional flags for each team from the track, computed once per fixture
    (they do not depend on the playhead; reports read the frames up to it)."""
    NAMES = ("back_four", "deepest", "highest", "width", "gap", "front", "box", "nearest", "ball_depth",
             "fb_depth_right", "fb_touch_right", "fb_depth_left", "fb_touch_left")
    FLAGS = ("over_right", "under_right", "invert_right", "over_left", "under_left", "invert_left", "drop_in", "drop_deep")

    def __init__(self, movement: Movement, home: str, teams: list[str]):
        track = movement.track
        self.frames = track.frames
        self.data = {team: {name: array("f", [0.0]) * self.frames for name in self.NAMES} for team in teams}
        self.flags = {team: {name: bytearray(self.frames) for name in self.FLAGS} for team in teams}
        players = track.players
        n = len(players)
        for team in teams:
            flip = team != home
            ks = [k for k, pid in enumerate(players) if pid.startswith(team + "_")]
            outfield = [k for k in ks if role(players[k]) != "GK"]
            back = [k for k in outfield if role(players[k]) in BACK_FOUR]
            mid = [k for k in outfield if role(players[k]) in MIDFIELD]
            front = [k for k in outfield if role(players[k]) in FORWARDS]
            out, flags = self.data[team], self.flags[team]
            at = {role(players[k]): k for k in ks}
            sides = (("right", at["RB"], at["RW"], lambda y: (100 - y) * Y_M), ("left", at["LB"], at["LW"], lambda y: y * Y_M))
            cb1, cb2, dm, st, cm1, cm2 = at["RCB"], at["LCB"], at["DM"], at["ST"], at["RCM"], at["LCM"]
            xy, ball = track.xy, track.ball
            for f in range(self.frames):
                base = f * n * 2
                bx, by = ball[2 * f], ball[2 * f + 1]
                if flip:
                    bx, by = 100 - bx, 100 - by
                depth, lateral = {}, {}
                for k in ks:
                    x, y = xy[base + 2 * k], xy[base + 2 * k + 1]
                    if flip:
                        x, y = 100 - x, 100 - y
                    depth[k], lateral[k] = x, y
                outs = [depth[k] for k in outfield]
                back_mean = sum(depth[k] for k in back) / len(back)
                out["back_four"][f] = back_mean * X_M
                out["deepest"][f] = min(outs) * X_M
                out["highest"][f] = max(outs) * X_M
                lat = [lateral[k] for k in outfield]
                out["width"][f] = (max(lat) - min(lat)) * Y_M
                out["gap"][f] = (sum(depth[k] for k in mid) / len(mid) - back_mean) * X_M
                out["front"][f] = sum(depth[k] for k in front) / len(front) * X_M
                out["box"][f] = sum(1 for k in ks if depth[k] * X_M <= BOX_DEPTH_M and abs(lateral[k] - 50) * Y_M <= BOX_HALF_WIDTH_M)
                out["nearest"][f] = min(math.hypot((depth[k] - bx) * X_M, (lateral[k] - by) * Y_M) for k in ks)
                out["ball_depth"][f] = bx * X_M
                cb_depth = (depth[cb1] + depth[cb2]) / 2 * X_M
                for side, fb, wing, touch in sides:
                    d, w = depth[fb] * X_M, depth[wing] * X_M
                    t_fb, t_w = touch(lateral[fb]), touch(lateral[wing])
                    out[f"fb_depth_{side}"][f], out[f"fb_touch_{side}"][f] = d, t_fb
                    ahead = d >= w + 2
                    flags[f"over_{side}"][f] = ahead and t_fb <= t_w - 3
                    flags[f"under_{side}"][f] = ahead and t_fb >= t_w + 3
                    flags[f"invert_{side}"][f] = bx < 66.67 and t_fb >= INSIDE_M and d >= cb_depth + 5
                flags["drop_in"][f] = depth[dm] <= max(depth[cb1], depth[cb2]) + 1 / X_M \
                    and min(lateral[cb1], lateral[cb2]) < lateral[dm] < max(lateral[cb1], lateral[cb2])
                flags["drop_deep"][f] = depth[st] < max(depth[cm1], depth[cm2]) - 1 / X_M


class PhaseEngine:
    """Shares the analytics engine's movement layer; reports are cached per observed second."""

    def __init__(self, analytics: AnalyticsEngine):
        self.analytics = analytics
        self._features: Features | None = None
        self._ready = False
        self._lock = threading.Lock()
        self._cache: dict[tuple, dict] = {}

    def features(self) -> Features | None:
        movement = self.analytics.movement()
        with self._lock:
            if not self._ready:
                match = self.analytics.match
                self._features = Features(movement, match.home.team_id, [match.home.team_id, match.away.team_id]) \
                    if movement and movement.track else None
                self._ready = True
            return self._features

    def report(self, records: dict[str, EventEnvelope], playhead_ms: int) -> dict:
        features = self.features()
        cutoff = playhead_ms // 1000 * 1000
        key = (cutoff, len(records), sum(e.revision for e in records.values()))
        if key in self._cache:
            return self._cache[key]
        result = PhaseReport(self.analytics.match, self.analytics.movement(), records, cutoff, features).build_phases()
        if len(self._cache) > 64:
            self._cache.clear()
        self._cache[key] = result
        return result


class PhaseReport(AnalyticsReport):
    def __init__(self, match, movement: Movement | None, records, playhead: int, features: Features | None):
        super().__init__(match, movement, records, playhead)
        self.features = features
        self.track = movement.track if movement and features else None
        self.home = self.teams[0]
        self.last_frame = min(self.track.frames - 1, playhead // FRAME_MS) if self.track else -1
        self.slot = {pid: k for k, pid in enumerate(self.track.players)} if self.track else {}
        self.settled: dict[str, bytearray] = {}
        self.owner_code = {self.teams[0]: 1, self.teams[1]: 2}
        self.plays = self.phase_possessions()
        for p in self.plays:
            reached = self.reached_final_third(p)
            p["counter"] = p["regain"] and p["spot"][0] < 66.67 and reached is not None and reached <= COUNTER_MS
        self.by_id = {p["id"]: p for p in self.plays}
        self.starts = [p["start"] for p in self.plays]
        self.takeons = self.take_ons()
        self.threats = self.threat_actions()

    # --------------------------------------------------------------- helpers
    def frame(self, t: int) -> int:
        return max(0, round(t / FRAME_MS))

    def tracked(self, t: int, window_ms: int = 0) -> bool:
        return self.track is not None and self.frame(t + window_ms) <= self.last_frame

    def where(self, team: str, f: int, pid: str) -> tuple[float, float]:
        """A player's team-frame position (normalised units) at frame f."""
        x, y = self.track.position(f, self.slot[pid])
        return (x, y) if team == self.home else (100 - x, 100 - y)

    def ball(self, team: str, f: int) -> tuple[float, float]:
        x, y = self.track.ball_at(f)
        return (x, y) if team == self.home else (100 - x, 100 - y)

    def feature(self, team: str, name: str, f: int) -> float:
        return self.features.data[team][name][f]

    def possession_at(self, t: int) -> dict | None:
        i = bisect_right(self.starts, t) - 1
        if i >= 0 and self.plays[i]["start"] <= t <= self.plays[i]["end"]:
            return self.plays[i]
        return None

    def special_ms(self, p: dict) -> int:
        """How long a possession's opening phase lasts: a set piece, a transition (longer while it is a counter) or none."""
        if p["restart"] in SET_PIECES:
            return SET_PIECE_MS
        if p["regain"]:
            return COUNTER_SHOT_MS if p["counter"] else TRANSITION_MS
        return 0

    def phase_of(self, p: dict, t: int) -> str:
        """The in-possession phase of possession p at time t (for its team)."""
        if t - p["start"] <= self.special_ms(p):
            return "attacking_set_piece" if p["restart"] in SET_PIECES else "attacking_transition"
        return "attacking"

    def phase_for(self, team: str, t: int, possession_id: str | None = None) -> str | None:
        p = self.by_id.get(possession_id) if possession_id else self.possession_at(t)
        if p is None:
            return None
        phase = self.phase_of(p, t)
        return phase if p["team"] == team else MIRROR[phase]

    def first_event(self, team: str, t0: int, t1: int) -> EventEnvelope | None:
        for record in self.ordered:
            e = record.payload
            if t0 <= e.event_time_ms <= t1 and e.team_id == team and e.kind in ("POSSESSION", "PASS", "CARRY", "SHOT"):
                return record
            if e.event_time_ms > t1:
                break
        return None

    def reached_final_third(self, p: dict) -> int | None:
        """Milliseconds after the start when the possession first reached the final third."""
        if p["spot"][0] >= 66.67:
            return 0
        for record in p["events"]:
            e = record.payload
            if e.kind == "SHOT" or (e.kind == "CARRY" and e.detail.end.x >= 66.67) or (e.kind == "PASS" and e.detail.completed and e.detail.end.x >= 66.67):
                return e.event_time_ms - p["start"]
            if e.kind == "PASS" and not e.detail.completed:
                break
        return None

    # ----------------------------------------------------------- possessions
    def phase_possessions(self) -> list[dict]:
        """Each observed possession with how it started: an open-play regain or a restart (and which)."""
        result, current, previous, stoppage = [], None, None, "interval"
        for record in self.ordered:
            e = record.payload
            if e.kind == "TACKLE":
                continue
            if e.kind in ("POSSESSION", "STOPPAGE", "PERIOD_END", "PERIOD_START"):
                if current:
                    current["end"] = e.event_time_ms
                    result.append(current)
                    current = None
                if e.kind == "STOPPAGE":
                    stoppage = e.detail.reason
                elif e.kind == "PERIOD_START":
                    stoppage = "interval"
                if e.kind == "POSSESSION":
                    restart, regain = None, False
                    if previous is None or previous.kind in ("STOPPAGE", "PERIOD_START"):
                        restart = {"corner": "corner", "foul": "free_kick"}.get(stoppage) or \
                            (("goal_kick" if e.detail.start.x < 20 else "throw_in") if stoppage == "ball_out" else "kick_off")
                    elif previous.team_id not in (None, e.team_id):
                        regain = True
                    current = {"team": e.team_id, "id": e.possession_id, "start": e.event_time_ms, "spot": (e.detail.start.x, e.detail.start.y),
                               "ref": record.ref, "player": e.player_id, "restart": restart, "regain": regain, "events": [], "end": None}
            elif current and e.possession_id == current["id"] and e.team_id == current["team"] and e.kind in ("PASS", "CARRY", "SHOT"):
                current["events"].append(record)
            previous = e
        if current:
            last = current["events"][-1].payload.event_time_ms if current["events"] else current["start"]
            current["end"] = max(last, min(self.playhead, last + 2_000))
            result.append(current)
        return result

    def threat_actions(self) -> list[ThreatAction]:
        rows = []
        for record in self.ordered:
            e = record.payload
            if e.kind == "CARRY" or (e.kind == "PASS" and e.detail.completed):
                a, b = e.detail.start, e.detail.end
                rows.append(ThreatAction(event_ref=record.ref, time_ms=e.event_time_ms, team_id=e.team_id, player_id=e.player_id,
                    action=e.kind.lower(), xt=round(threat(b.x, b.y) - threat(a.x, a.y), 4), start={"x": a.x, "y": a.y}, end={"x": b.x, "y": b.y}))
        return rows

    def shots_in(self, team: str, p: dict, within_ms: int) -> list:
        return [q for q in self.quality.values() if q.team_id == team
                and p["start"] <= q.time_ms <= min(p["end"], p["start"] + within_ms) and self.shot_possession(q) == p["id"]]

    def shot_possession(self, q) -> str | None:
        record = self.records.get(q.event_id)
        return record.payload.possession_id if record and record.payload else None

    # ------------------------------------------------------- phases of play
    def phases(self) -> dict[str, TeamPhases]:
        result = {}
        live = sum(p["end"] - p["start"] for p in self.plays) / 1000
        for team in self.teams:
            rows = {name: {"seconds": 0.0, "passes": 0, "entries": 0, "xt": 0.0, "shots_for": 0, "xg_for": 0.0, "goals_for": 0,
                           "shots_against": 0, "xg_against": 0.0, "goals_against": 0} for name in PHASES}
            restarts: dict[str, int] = {}
            for p in self.plays:
                length = p["end"] - p["start"]
                special = self.special_ms(p)
                first = self.phase_of(p, p["start"])
                head = min(length, special) if special else 0
                own = p["team"] == team
                name = first if own else MIRROR[first]
                rows[name]["seconds"] += head / 1000
                rows["attacking" if own else "defending"]["seconds"] += (length - head) / 1000
                if own and p["restart"] and p["restart"] != "kick_off":
                    restarts[p["restart"]] = restarts.get(p["restart"], 0) + 1
            for record in self.ordered:
                e = record.payload
                if e.kind not in ("PASS", "CARRY") or e.team_id != team:
                    continue
                phase = self.phase_for(team, e.event_time_ms, e.possession_id)
                if not phase:
                    continue
                if e.kind == "PASS":
                    rows[phase]["passes"] += 1
                if (e.kind == "CARRY" or e.detail.completed) and e.detail.start.x < 66.67 <= e.detail.end.x:
                    rows[phase]["entries"] += 1
            for a in self.threats:
                if a.team_id == team:
                    record = self.records[a.event_ref.split("@")[0]]
                    phase = self.phase_for(team, a.time_ms, record.payload.possession_id)
                    if phase:
                        rows[phase]["xt"] += a.xt
            for q in self.quality.values():
                phase = self.phase_for(team, q.time_ms, self.shot_possession(q))
                if not phase:
                    continue
                side = "for" if q.team_id == team else "against"
                rows[phase][f"shots_{side}"] += 1
                rows[phase][f"xg_{side}"] += q.xg
                rows[phase][f"goals_{side}"] += q.outcome == "goal"
            result[team] = TeamPhases(team_id=team, live_seconds=round(live, 1), restarts=dict(sorted(restarts.items())), rows=[
                PhaseRow(phase=name, seconds=round(row["seconds"], 1), share=ratio(100 * row["seconds"], live, 1), passes=row["passes"],
                         final_third_entries=row["entries"], xt=round(row["xt"], 3), shots_for=row["shots_for"], xg_for=round(row["xg_for"], 2),
                         goals_for=row["goals_for"], shots_against=row["shots_against"], xg_against=round(row["xg_against"], 2),
                         goals_against=row["goals_against"]) for name, row in rows.items()])
        return result

    # ----------------------------------------------------------- transitions
    def attacking_transitions(self, team: str) -> tuple[AttackingTransitions, set[str]]:
        regains = [p for p in self.plays if p["team"] == team and p["regain"]]
        counters, recycled, lost, shots, xg = 0, 0, 0, 0, 0.0
        times, moments, counter_ids = [], [], set()
        by_third = {"defensive": 0, "middle": 0, "final": 0}
        counters_by_third = {"defensive": 0, "middle": 0, "final": 0}
        for p in regains:
            zone = third(p["spot"][0])
            by_third[zone] += 1
            reached = self.reached_final_third(p)
            fired = self.shots_in(team, p, COUNTER_SHOT_MS)
            shots += len(fired)
            xg += sum(q.xg for q in fired)
            if p["counter"]:
                counters += 1
                counters_by_third[zone] += 1
                counter_ids.add(p["id"])
                times.append(reached / 1000)
                label = f"Won in the {zone} third, final third in {reached / 1000:.1f} s" + (f", shot worth {fired[0].xg:.2f} xG" if fired else "")
                moments.append((-(fired[0].xg if fired else 0), reached, Moment(time_ms=p["start"], event_ref=p["ref"], label=label)))
                continue
            first = next((r.payload for r in p["events"] if r.payload.kind in ("PASS", "CARRY")), None)
            if first is not None and (first.detail.end.x - first.detail.start.x) * X_M < FORWARD_M and reached is None:
                recycled += 1
            elif reached is None and not fired and p["end"] - p["start"] <= LOST_QUICKLY_MS:
                lost += 1
        moments.sort(key=lambda m: (m[0], m[1]))
        return AttackingTransitions(regains=len(regains), counters=counters, counter_shots=shots, counter_xg=round(xg, 2), recycled=recycled,
            lost_quickly=lost, median_to_final_third_s=r1(median(times)) if times else None, by_third=by_third,
            counters_by_third=counters_by_third, moments=[m[2] for m in moments[:MOMENTS]]), counter_ids

    def counter_press(self, team: str) -> CounterPress:
        rival = self.other(team)
        losses = [p for p in self.plays if p["team"] == rival and p["regain"]]
        tracked = pressed = regained5 = regained10 = bypassed = shots = 0
        xg = 0.0
        pressure, pack, rest, rest_back = [], [], [], []
        by_third = {"defensive": 0, "middle": 0, "final": 0}
        examples = []
        outfield = [p.player_id for p in self.match.roster if p.team_id == team and role(p.player_id) != "GK"]
        for p in losses:
            t0 = p["start"]
            spot = (100 - p["spot"][0], 100 - p["spot"][1])        # in this team's frame
            by_third[third(spot[0])] += 1
            again = next((q for q in self.plays if q["start"] > t0 and q["team"] == team), None)
            won_back = again["start"] - t0 if again and again["regain"] else None
            regained5 += won_back is not None and won_back <= 5_000
            regained10 += won_back is not None and won_back <= 10_000
            gained = 0.0
            for record in p["events"]:
                e = record.payload
                if e.event_time_ms - t0 > 10_000:
                    break
                end = e.detail.position if e.kind == "SHOT" else e.detail.end
                if e.kind != "PASS" or e.detail.completed:
                    gained = max(gained, (end.x - p["spot"][0]) * X_M)
            bypassed += gained >= BYPASS_M
            fired = self.shots_in(rival, p, COUNTER_SHOT_MS)
            shots += len(fired)
            xg += sum(q.xg for q in fired)
            if not self.tracked(t0, PRESS_WINDOW_MS):
                continue
            tracked += 1
            f0 = self.frame(t0)
            before = self.track.holder[max(0, f0 - 1)]
            loser = self.track.players[before] if before != 255 else None
            chasers = [pid for pid in outfield if pid != loser]
            took = None
            bx, by = self.ball(team, f0)
            # Only players who had to close the ball down count, not one already standing on it.
            closers = [pid for pid in chasers if math.hypot((self.where(team, f0, pid)[0] - bx) * X_M, (self.where(team, f0, pid)[1] - by) * Y_M) > PRESSURE_M]
            for f in range(f0 + 1, f0 + PRESS_WINDOW_MS // FRAME_MS + 1):
                bx, by = self.ball(team, f)
                if any(math.hypot((x - bx) * X_M, (y - by) * Y_M) <= PRESSURE_M for x, y in (self.where(team, f, pid) for pid in closers)):
                    took = (f - f0) * FRAME_MS / 1000
                    break
            if took is not None:
                pressed += 1
                pressure.append(took)
            fp = f0 + PACK_AT_MS // FRAME_MS
            bx, by = self.ball(team, fp)
            pack.append(sum(1 for pid in chasers if math.hypot((self.where(team, fp, pid)[0] - bx) * X_M, (self.where(team, fp, pid)[1] - by) * Y_M) <= PACK_M))
            bx, _ = self.ball(team, f0)
            behind = [pid for pid in outfield if self.where(team, f0, pid)[0] < bx]
            rest.append(len(behind))
            rest_back.append(sum(1 for pid in behind if role(pid) in BACK_FOUR))
            if took is not None and won_back is not None and won_back <= 5_000:
                examples.append((won_back, Moment(time_ms=t0, event_ref=p["ref"],
                    label=f"Lost in the {third(spot[0])} third, pressed in {took:.1f} s, won back in {won_back / 1000:.1f} s")))
            elif fired:
                examples.append((10**6 - fired[0].xg * 1000, Moment(time_ms=t0, event_ref=p["ref"],
                    label=f"Lost in the {third(spot[0])} third, not won back: shot conceded worth {fired[0].xg:.2f} xG")))
        examples.sort(key=lambda m: m[0])
        return CounterPress(losses=len(losses), tracked=tracked, pressed=pressed, press_rate=ratio(100 * pressed, tracked, 1),
            median_pressure_s=r1(median(pressure)) if pressure else None, pack_2s=r1(mean(pack)), regained_5s=regained5, regained_10s=regained10,
            bypassed=bypassed, shots_conceded=shots, xg_conceded=round(xg, 2), rest_defence=r1(mean(rest)), rest_defenders=r1(mean(rest_back)),
            by_third=by_third, moments=[m[1] for m in examples[:MOMENTS]])

    # ---------------------------------------------------------------- blocks
    def settled_codes(self, team: str) -> bytearray:
        """Per frame: 1 when the team is defending settled (out of possession, no transition or set piece)."""
        codes = bytearray(self.last_frame + 1)
        for p in self.plays:
            if p["team"] == team:
                continue
            a, b = self.frame(p["start"] + self.special_ms(p)), min(self.last_frame, self.frame(p["end"]) - 1)
            for f in range(a, b + 1):
                codes[f] = 1
        return codes

    def block_of(self, team: str, f: int) -> str:
        depth = self.feature(team, "back_four", f)
        return "high" if depth >= HIGH_LINE_M else "low" if depth < LOW_LINE_M else "mid"

    def blocks(self, counter_ids: dict[str, set[str]]) -> dict[str, TeamBlocks]:
        result = {}
        for team in self.teams:
            rival = self.other(team)
            if not self.track:
                result[team] = TeamBlocks(team_id=team, settled_seconds=0.0, rows=[], snapshots=[], recovery=self.recovery(team))
                continue
            codes = self.settled_codes(team)
            self.settled[team] = codes
            sums = {b: {"frames": 0, "back": 0.0, "length": 0.0, "width": 0.0, "gap": 0.0, "box": 0.0, "box_frames": 0,
                        "entries": 0, "wide": 0, "shots": 0, "long": 0, "xg": 0.0, "goals": 0, "crosses": 0, "passes": 0, "actions": 0,
                        "regains": 0, "counters": 0} for b in ("high", "mid", "low")}
            data = self.features.data[team]
            for f in range(self.last_frame + 1):
                if not codes[f]:
                    continue
                row = sums[self.block_of(team, f)]
                row["frames"] += 1
                row["back"] += data["back_four"][f]
                row["length"] += data["highest"][f] - data["deepest"][f]
                row["width"] += data["width"][f]
                row["gap"] += data["gap"][f]
                if data["ball_depth"][f] <= DEFENDING_THIRD_M:
                    row["box"] += data["box"][f]
                    row["box_frames"] += 1

            def settled_block(t: int) -> str | None:
                f = min(self.frame(t), self.last_frame)
                return self.block_of(team, f) if codes[f] else None

            for record in self.ordered:
                e = record.payload
                t = e.event_time_ms
                if e.team_id == rival and e.kind in ("PASS", "CARRY"):
                    block = settled_block(t)
                    if not block:
                        continue
                    row = sums[block]
                    a, b = e.detail.start, e.detail.end
                    if e.kind == "PASS" and a.x < PPDA_ZONE_X:
                        row["passes"] += 1
                    if (e.kind == "CARRY" or e.detail.completed) and a.x < 66.67 <= b.x:
                        row["entries"] += 1
                        row["wide"] += channel(b.y) != "centre"
                    if e.kind == "PASS" and a.x >= 66.67 and channel(a.y) != "centre" and in_box(b.x, b.y):
                        row["crosses"] += 1
                elif e.team_id == team and e.kind == "TACKLE" and e.detail.position.x >= 100 - PPDA_ZONE_X:
                    block = settled_block(t)
                    if block:
                        sums[block]["actions"] += 1
                elif e.team_id == team and e.kind == "POSSESSION" and record.event_id in self._regains:
                    block = settled_block(t - FRAME_MS)
                    if block:
                        sums[block]["regains"] += 1
                        sums[block]["counters"] += e.possession_id in counter_ids[team]
                        if record.event_id in self._interceptions and e.detail.start.x >= 100 - PPDA_ZONE_X:
                            sums[block]["actions"] += 1
            for q in self.quality.values():
                if q.team_id != rival:
                    continue
                block = settled_block(q.time_ms)
                if not block:
                    continue
                row = sums[block]
                record = self.records[q.event_id].payload
                row["shots"] += 1
                row["long"] += not in_box(record.detail.position.x, record.detail.position.y)
                row["xg"] += q.xg
                row["goals"] += q.outcome == "goal"
            total = sum(row["frames"] for row in sums.values())
            rows = []
            for block, row in sums.items():
                n = row["frames"]
                rows.append(BlockRow(block=block, seconds=round(n * FRAME_MS / 1000, 1), share=ratio(100 * n, total, 1),
                    back_four_m=r1(row["back"] / n) if n else None, length_m=r1(row["length"] / n) if n else None,
                    width_m=r1(row["width"] / n) if n else None, line_gap_m=r1(row["gap"] / n) if n else None,
                    box_defenders=r1(row["box"] / row["box_frames"]) if row["box_frames"] else None, opponent_entries=row["entries"],
                    wide_entry_share=ratio(100 * row["wide"], row["entries"], 1), opponent_shots=row["shots"],
                    long_shot_share=ratio(100 * row["long"], row["shots"], 1), xg_against=round(row["xg"], 2), goals_against=row["goals"],
                    crosses_faced=row["crosses"], ppda=ratio(row["passes"], row["actions"], 1), regains=row["regains"], counters=row["counters"]))
            result[team] = TeamBlocks(team_id=team, settled_seconds=round(total * FRAME_MS / 1000, 1), rows=rows,
                                      snapshots=self.snapshots(team, codes), recovery=self.recovery(team))
        return result

    def snapshots(self, team: str, codes: bytearray) -> list[LineSnapshot]:
        rival = self.other(team)
        data = self.features.data[team]
        build_up = bytearray(self.last_frame + 1)
        for p in self.plays:
            if p["team"] == rival and p["spot"][0] < 33.33 and (p["restart"] or role(p["player"]) == "GK"):
                for f in range(self.frame(p["start"]), min(self.last_frame, self.frame(min(p["end"], p["start"] + BUILD_UP_MS))) + 1):
                    build_up[f] = 1
        code = self.owner_code[rival]
        groups = {"settled": [], "opponent_build_up": [], "high_press": []}
        for f in range(self.last_frame + 1):
            if self.track.owner[f] != code:
                continue
            if codes[f]:
                groups["settled"].append(f)
            if build_up[f]:
                groups["opponent_build_up"].append(f)
            if data["ball_depth"][f] >= 70 and data["nearest"][f] <= HIGH_PRESS_M:
                groups["high_press"].append(f)
        rows = []
        for situation, frames in groups.items():
            n = len(frames)
            rows.append(LineSnapshot(situation=situation, seconds=round(n * FRAME_MS / 1000, 1),
                back_four_m=r1(sum(data["back_four"][f] for f in frames) / n) if n else None,
                front_line_m=r1(sum(data["front"][f] for f in frames) / n) if n else None,
                length_m=r1(sum(data["highest"][f] - data["deepest"][f] for f in frames) / n) if n else None))
        return rows

    def recovery(self, team: str) -> Recovery:
        rival = self.other(team)
        found = tracked = sweeps = shots = 0
        retreat, speeds, keeper_start, keeper_max, examples = [], [], [], [], []
        back = [player_for(team, r) for r in BACK_FOUR]
        keeper = player_for(team, "GK")
        for record in self.ordered:
            e = record.payload
            if e.kind != "PASS" or e.team_id != rival or not e.detail.completed or not self.track:
                continue
            t = e.event_time_ms
            f = self.frame(t)
            if f > self.last_frame:
                continue
            depth_end = (100 - e.detail.end.x) * X_M
            if depth_end >= 45 or depth_end >= self.feature(team, "deepest", f) - 1:
                continue
            found += 1
            p = self.by_id.get(e.possession_id)
            fired = [q for q in self.quality.values() if q.team_id == rival and t <= q.time_ms <= t + 10_000 and self.shot_possession(q) == e.possession_id]
            shots += bool(fired)
            if not self.tracked(t, RECOVERY_MS):
                continue
            tracked += 1
            frames = range(f, f + RECOVERY_MS // FRAME_MS + 1)
            drops, top = [], 0.0
            for pid in back:
                path = [self.where(team, g, pid) for g in frames]
                drops.append((path[0][0] - min(x for x, _ in path)) * X_M)
                for (x1, y1), (x2, y2) in zip(path, path[1:]):
                    top = max(top, math.hypot((x2 - x1) * X_M, (y2 - y1) * Y_M) / (FRAME_MS / 1000))
            retreat.append(sum(drops) / len(drops))
            speeds.append(top)
            spots = [self.where(team, g, keeper) for g in range(f, f + SWEEP_MS // FRAME_MS + 1)]
            keeper_start.append(spots[0][0] * X_M)
            furthest = max(x for x, _ in spots) * X_M
            keeper_max.append(furthest)
            swept = any(x * X_M > BOX_DEPTH_M or abs(y - 50) * Y_M > BOX_HALF_WIDTH_M for x, y in spots)
            sweeps += swept
            if swept or fired:
                label = (f"Ball in behind: keeper came {furthest:.0f} m off the line" if swept else "Ball in behind") + \
                        (f", shot conceded worth {fired[0].xg:.2f} xG" if fired else "")
                examples.append((not swept, -(fired[0].xg if fired else 0), Moment(time_ms=t, event_ref=record.ref, label=label)))
        examples.sort(key=lambda m: (m[0], m[1]))
        return Recovery(balls_in_behind=found, tracked=tracked, retreat_m=r1(mean(retreat)), top_speed_mps=r1(mean(speeds)),
            keeper_start_m=r1(mean(keeper_start)), keeper_max_m=r1(mean(keeper_max)), sweeps=sweeps, shots_conceded=shots,
            moments=[m[2] for m in examples[:MOMENTS]])

    # ----------------------------------------------------------- progression
    def progression(self) -> tuple[dict[str, TeamProgression], list[PlayerProgression], list[ThreatAction]]:
        players = {p.player_id: {"pp": 0, "pc": 0, "pcm": 0.0, "carries": 0, "c3": 0, "cbox": 0, "takeons": 0, "xtp": 0.0, "xtc": 0.0}
                   for p in self.match.roster}
        for record in self.ordered:
            e = record.payload
            if e.kind == "PASS" and e.detail.completed and progressive(e.detail.start, e.detail.end):
                players[e.player_id]["pp"] += 1
            elif e.kind == "CARRY":
                row = players[e.player_id]
                a, b = e.detail.start, e.detail.end
                row["carries"] += 1
                row["takeons"] += record.event_id in self.takeons
                gain = metres_to_goal(a.x, a.y) - metres_to_goal(b.x, b.y)
                if b.x > a.x and gain >= (5 if a.x >= 60 else 10):
                    row["pc"] += 1
                    row["pcm"] += (b.x - a.x) * X_M
                row["c3"] += a.x < 66.67 <= b.x
                row["cbox"] += in_box(b.x, b.y) and not in_box(a.x, a.y)
        for a in self.threats:
            players[a.player_id]["xtp" if a.action == "pass" else "xtc"] += a.xt
        rows = []
        for p in self.match.roster:
            r = players[p.player_id]
            if not (r["pp"] or r["carries"] or r["xtp"]):
                continue
            rows.append(PlayerProgression(player_id=p.player_id, team_id=p.team_id, progressive_passes=r["pp"], progressive_carries=r["pc"],
                progressive_carry_m=round(r["pcm"], 1), carries=r["carries"], carries_final_third=r["c3"], carries_box=r["cbox"],
                take_ons=r["takeons"], xt_passes=round(r["xtp"], 3), xt_carries=round(r["xtc"], 3), xt=round(r["xtp"] + r["xtc"], 3)))
        rows.sort(key=lambda r: (-(r.progressive_passes + r.progressive_carries), -r.xt, r.player_id))
        teams = {}
        for team in self.teams:
            own = [r for r in rows if r.team_id == team]
            pp, pc = sum(r.progressive_passes for r in own), sum(r.progressive_carries for r in own)
            acts = [a for a in self.threats if a.team_id == team]
            by_channel = {"left": 0.0, "centre": 0.0, "right": 0.0}
            for a in acts:
                by_channel[channel(a.start.y)] += a.xt
            intervals = [round(sum(a.xt for a in acts if start < a.time_ms <= start + INTERVAL_MS or (start == 0 and a.time_ms == 0)), 3)
                         for start in range(0, self.playhead, INTERVAL_MS)]
            teams[team] = TeamProgression(team_id=team, progressive_passes=pp, progressive_carries=pc, carry_share=ratio(100 * pc, pp + pc, 1),
                progressive_carry_m=round(sum(r.progressive_carry_m for r in own), 1), carries_final_third=sum(r.carries_final_third for r in own),
                carries_box=sum(r.carries_box for r in own), take_ons=sum(r.take_ons for r in own), xt=round(sum(a.xt for a in acts), 3),
                xt_passes=round(sum(a.xt for a in acts if a.action == "pass"), 3), xt_carries=round(sum(a.xt for a in acts if a.action == "carry"), 3),
                xt_by_channel={k: round(v, 3) for k, v in by_channel.items()}, xt_intervals=intervals)
        top = sorted(self.threats, key=lambda a: (-a.xt, a.time_ms))[:TOP_THREAT]
        return teams, rows, top

    # -------------------------------------------------- full-backs, rotations
    def episodes(self, flags: list[tuple[int, bool]], minimum: int) -> list[tuple[int, int]]:
        """Runs of consecutive true frames at least ``minimum`` long, as (first, last) frame."""
        runs, start, previous = [], None, None
        for f, on in flags:
            if on and start is not None and previous is not None and f == previous + 1:
                previous = f
                continue
            if start is not None and previous - start + 1 >= minimum:
                runs.append((start, previous))
            start, previous = (f, f) if on else (None, None)
        if start is not None and previous - start + 1 >= minimum:
            runs.append((start, previous))
        return runs

    def possession_frames(self, team: str) -> list[int]:
        code = self.owner_code[team]
        return [f for f in range(self.last_frame + 1) if self.track.owner[f] == code]

    def episode_moment(self, team: str, run: tuple[int, int], text: str) -> Moment:
        t0, t1 = run[0] * FRAME_MS, run[1] * FRAME_MS
        record = self.first_event(team, t0, t1)
        return Moment(time_ms=t0, event_ref=record.ref if record else None, label=f"{text} ({clock(t0)}–{clock(t1)})")

    def fullbacks_and_rotations(self) -> tuple[list[FullbackRow], dict[str, TeamRotations]]:
        fullbacks, rotations = [], {}
        prog = {r.player_id: r for r in self.progression_rows}
        for team in self.teams:
            rows: list[RotationRow] = []
            if not self.track:
                rotations[team] = TeamRotations(team_id=team, rows=rows)
                continue
            frames = self.possession_frames(team)
            data = self.features.data[team]
            cbs = [player_for(team, "RCB"), player_for(team, "LCB")]
            losses = [self.frame(p["start"]) for p in self.plays if p["team"] != team and p["regain"] and self.frame(p["start"]) <= self.last_frame]
            fb_runs: dict[str, dict[str, list]] = {}
            flags = self.features.flags[team]
            runs_of = lambda name, minimum: self.episodes([(f, flags[name][f]) for f in frames], minimum)
            for side, fb_role, wing_role in (("right", "RB", "RW"), ("left", "LB", "LW")):
                fb, wing = player_for(team, fb_role), player_for(team, wing_role)
                depths, touches = data[f"fb_depth_{side}"], data[f"fb_touch_{side}"]
                depth = [depths[f] for f in frames]
                lateral = [touches[f] for f in frames]
                attack = [depths[f] for f in frames if data["ball_depth"][f] >= 70]
                inside = [touches[f] >= INSIDE_M for f in frames if data["ball_depth"][f] < 70]
                overlaps, underlaps = runs_of(f"over_{side}", OVERLAP_FRAMES), runs_of(f"under_{side}", OVERLAP_FRAMES)
                inverts = runs_of(f"invert_{side}", ROTATION_FRAMES)
                fb_runs[side] = {"overlap": overlaps, "underlap": underlaps, "invert": inverts, "players": [fb, wing]}
                seconds = len(frames) * FRAME_MS / 1000
                inside_share = ratio(100 * sum(inside), len(inside), 1)
                attack_depth = mean(attack)
                if seconds < MIN_FULLBACK_S:
                    style = "insufficient_evidence"
                elif inside_share is not None and inside_share >= 40:
                    style = "inverted"
                elif len(overlaps) >= 3 and len(overlaps) >= 2 * len(underlaps):
                    style = "overlapping"
                elif len(underlaps) >= 3 and len(underlaps) >= 2 * len(overlaps):
                    style = "underlapping"
                elif attack_depth is not None and attack_depth < 52:
                    style = "holding"
                else:
                    style = "balanced"
                at_loss = [depths[f] for f in losses]
                crosses = sum(1 for r in self.ordered if r.payload.kind == "PASS" and r.payload.player_id == fb and r.payload.detail.start.x >= 66.67
                              and channel(r.payload.detail.start.y) != "centre" and in_box(r.payload.detail.end.x, r.payload.detail.end.y))
                p = prog.get(fb)
                runs = {"overlapping": overlaps, "underlapping": underlaps, "inverted": inverts}.get(style, overlaps or underlaps or inverts)
                what = {"overlapping": "Overlaps outside the winger", "underlapping": "Underlaps inside the winger", "inverted": "Steps inside into midfield"}
                fullbacks.append(FullbackRow(player_id=fb, team_id=team, side=side, style=style, seconds=round(seconds, 1), depth_m=r1(mean(depth)),
                    attack_depth_m=r1(attack_depth), touchline_m=r1(mean(lateral)), inside_share=inside_share, overlaps=len(overlaps),
                    underlaps=len(underlaps), depth_at_loss_m=r1(mean(at_loss)), crosses=crosses,
                    progressive_actions=(p.progressive_passes + p.progressive_carries) if p else 0, xt=p.xt if p else 0.0,
                    moments=[self.episode_moment(team, run, what.get(style, "Runs ahead of the winger")) for run in runs[:MOMENTS]]))
            # Midfield and forward rotations.
            dm, st = player_for(team, "DM"), player_for(team, "ST")
            cms = [player_for(team, "RCM"), player_for(team, "LCM")]
            found = [("holding_midfielder_drops", runs_of("drop_in", ROTATION_FRAMES), [dm, *cbs], "Holding midfielder drops between the centre-backs"),
                     ("striker_drops", runs_of("drop_deep", ROTATION_FRAMES), [st, *cms], "Striker drops behind the midfield")]
            for side in ("right", "left"):
                runs = fb_runs[side]
                found += [("wide_overlap", runs["overlap"], runs["players"], f"{side.title()}-back overlaps the winger"),
                          ("wide_underlap", runs["underlap"], runs["players"], f"{side.title()}-back underlaps the winger"),
                          ("fullback_inverts", runs["invert"], runs["players"][:1], f"{side.title()}-back steps inside")]
            own = [p for p in self.plays if p["team"] == team]
            merged: dict[str, dict] = {}
            for kind, runs, players, text in found:
                if not runs:
                    continue
                row = merged.setdefault(kind, {"runs": [], "players": []})
                row["runs"] += [(run, text) for run in runs]
                row["players"] += [pid for pid in players if pid not in row["players"]]
            for kind, row in merged.items():
                labelled = sorted(row["runs"])
                runs = [run for run, _text in labelled]
                spans = [(a * FRAME_MS, b * FRAME_MS) for a, b in runs]
                with_it = [p for p in own if any(a <= p["end"] and b >= p["start"] for a, b in spans)]
                without = [p for p in own if p not in with_it]
                reach = lambda ps: ratio(100 * sum(self.reached_final_third(p) is not None for p in ps), len(ps), 1)
                rows.append(RotationRow(kind=kind, players=row["players"], episodes=len(runs), seconds=round(sum(b - a + 1 for a, b in runs) * FRAME_MS / 1000, 1),
                    possessions=len(with_it), final_third_rate=reach(with_it), baseline_rate=reach(without),
                    moments=[self.episode_moment(team, run, text) for run, text in labelled[:MOMENTS]]))
            rows.sort(key=lambda r: -r.episodes)
            rotations[team] = TeamRotations(team_id=team, rows=rows)
        return fullbacks, rotations

    # ---------------------------------------------------- control and press
    def control(self, progression: dict[str, TeamProgression]) -> dict[str, ControlRow]:
        whole = self.territory_window(0, self.playhead)
        result = {}
        for team in self.teams:
            own = [p for p in self.plays if p["team"] == team]
            purposeful = sterile = sterile_passes = 0
            for p in own:
                completed = sum(1 for r in p["events"] if r.payload.kind == "PASS" and r.payload.detail.completed)
                shot = any(r.payload.kind == "SHOT" for r in p["events"])
                if self.reached_final_third(p) is not None or shot:
                    purposeful += 1
                elif completed >= STERILE_PASSES:
                    sterile += 1
                    sterile_passes += completed
            entries = sum(1 for r in self.ordered if r.payload.team_id == team and (r.payload.kind == "CARRY" or (r.payload.kind == "PASS" and r.payload.detail.completed))
                          and in_box(r.payload.detail.end.x, r.payload.detail.end.y) and not in_box(r.payload.detail.start.x, r.payload.detail.start.y))
            passes, actions = self.pressing_counts(team)
            possession, tilt = whole.possession_share[team], whole.field_tilt[team]
            if self.playhead < 600_000 or possession is None or tilt is None:
                read = "insufficient_evidence"
            elif possession >= 55 and tilt >= 55:
                read = "control_with_territory"
            elif possession >= 55 and tilt < 50:
                read = "possession_without_penetration"
            elif possession <= 45 and tilt >= 45:
                read = "territory_without_the_ball"
            elif possession <= 45 and tilt < 40:
                read = "pinned_back"
            else:
                read = "balanced"
            prog = progression[team]
            result[team] = ControlRow(team_id=team, possession_share=possession, field_tilt=tilt,
                final_third_entries=self.tempo_figures(team).final_third_entries, box_entries=entries,
                progressive_actions=prog.progressive_passes + prog.progressive_carries, xg=round(sum(q.xg for q in self.quality.values() if q.team_id == team), 2),
                ppda=ratio(passes, actions, 1), possessions=len(own), purposeful=purposeful, sterile=sterile, sterile_passes=sterile_passes, read=read)
        return result

    def press_interval(self, team: str, start: int, end: int) -> PressInterval:
        inside = lambda t: start < t <= end or (start == 0 and t == 0)
        passes, actions = self.pressing_counts(team, inside)
        high = sum(1 for p in self.plays if p["team"] == team and p["regain"] and p["spot"][0] >= HIGH_REGAIN_X and inside(p["start"]))
        return PressInterval(start_ms=start, end_ms=end, ppda=ratio(passes, actions, 1), opponent_passes=passes, defensive_actions=actions, high_regains=high)

    def pressing_over_time(self) -> dict[str, TeamPressing]:
        result = {}
        for team in self.teams:
            halves = [self.press_interval(team, a, min(b, self.playhead)) for a, b in ((0, PERIOD_MS), (PERIOD_MS, 2 * PERIOD_MS)) if a < self.playhead or a == 0]
            intervals = [self.press_interval(team, s, min(s + INTERVAL_MS, self.playhead)) for s in range(0, self.playhead, INTERVAL_MS)]
            high = [p for p in self.plays if p["team"] == team and p["regain"] and p["spot"][0] >= HIGH_REGAIN_X]
            fired = [q for p in high for q in self.shots_in(team, p, COUNTER_SHOT_MS)]
            by_third = {"defensive": 0, "middle": 0, "final": 0}
            for p in self.plays:
                if p["team"] == team and p["regain"]:
                    by_third[third(p["spot"][0])] += 1
            result[team] = TeamPressing(team_id=team, halves=halves, intervals=intervals, high_regains=len(high), high_regain_shots=len(fired),
                                        high_regain_xg=round(sum(q.xg for q in fired), 2), regains_by_third=by_third)
        return result

    # ------------------------------------------------------------- finishing
    def finishing(self) -> tuple[list[FinishingRow], dict[str, TeamXg]]:
        rows = {}
        for q in self.quality.values():
            row = rows.setdefault(q.player_id, {"team": q.team_id, "shots": 0, "goals": 0, "xg": 0.0})
            row["shots"] += 1
            row["goals"] += q.outcome == "goal"
            row["xg"] += q.xg
        players = [FinishingRow(player_id=pid, team_id=r["team"], shots=r["shots"], goals=r["goals"], xg=round(r["xg"], 2),
                                goals_minus_xg=round(r["goals"] - r["xg"], 2), xg_per_shot=ratio(r["xg"], r["shots"], 3)) for pid, r in rows.items()]
        players.sort(key=lambda r: (-r.xg, r.player_id))
        teams = {}
        for team in self.teams:
            own = [q for q in self.quality.values() if q.team_id == team]
            against = [q for q in self.quality.values() if q.team_id != team]
            setups: dict[str, float] = {}
            for q in against:
                setups[q.assist] = setups.get(q.assist, 0.0) + q.xg
            bucket = lambda shots, s: round(sum(q.xg for q in shots if s < q.time_ms <= s + INTERVAL_MS or (s == 0 and q.time_ms == 0)), 2)
            teams[team] = TeamXg(team_id=team, intervals=[bucket(own, s) for s in range(0, self.playhead, INTERVAL_MS)],
                                 intervals_against=[bucket(against, s) for s in range(0, self.playhead, INTERVAL_MS)],
                                 against_by_setup={k: round(v, 2) for k, v in sorted(setups.items())},
                                 goals_minus_xg=round(sum(q.outcome == "goal" for q in own) - sum(q.xg for q in own), 2))
        return players, teams

    # --------------------------------------------------------- analyst notes
    def notes(self, phases, transitions, blocks, progression, fullbacks, rotations, control, xg) -> list[AnalystNote]:
        notes = []
        name = {self.match.home.team_id: self.match.home.display_name, self.match.away.team_id: self.match.away.display_name}
        player = {p.player_id: p.display_name for p in self.match.roster}

        def add(team, topic, quantitative, look_for, moments, caveat=None):
            notes.append(AnalystNote(note_id=f"{team}_{len(notes) + 1:02d}", team_id=team, topic=topic, quantitative=quantitative,
                                     look_for=look_for, moments=moments[:MOMENTS], caveat=caveat))

        small = lambda n, k=8: f"Only {n} so far: a small sample." if n < k else None
        for team in self.teams:
            who = name[team]
            press = transitions[team].defensive
            if press.tracked:
                add(team, "Counter-press after losing the ball",
                    f"{who} pressed the ball within {PRESS_WINDOW_MS // 1000} s after {press.pressed} of {press.tracked} tracked losses ({press.press_rate:.0f}%), "
                    f"with {press.pack_2s} players within {PACK_M:.0f} m of the ball after 2 s on average. They won it back within 5 s {times(press.regained_5s)} "
                    f"and the opponent moved it {BYPASS_M:.0f} m upfield within 10 s {times(press.bypassed)}.",
                    "Whether the nearest players press together or one at a time, and whether the players behind squeeze up or leave gaps "
                    "(compactness) and how many stay goal-side as rest defence.",
                    press.moments, small(press.tracked))
            attack = transitions[team].attacking
            if attack.regains:
                add(team, "Attacking transitions",
                    f"Of {attack.regains} open-play regains, {attack.counters} became counters that reached the final third within {COUNTER_MS // 1000} s "
                    f"(median {attack.median_to_final_third_s if attack.median_to_final_third_s is not None else '—'} s); {attack.recycled} {'was' if attack.recycled == 1 else 'were'} recycled "
                    f"sideways or back and {attack.lost_quickly} {'was' if attack.lost_quickly == 1 else 'were'} lost again within {LOST_QUICKLY_MS // 1000} s. Shots within {COUNTER_SHOT_MS // 1000} s: "
                    f"{attack.counter_shots} ({attack.counter_xg:.2f} xG).",
                    "Where the space was when the ball was won (behind the opponent's advanced full-backs, through the middle) and whether the first "
                    "pass went forward or the team chose to settle.",
                    attack.moments, small(attack.regains))
            block_rows = [r for r in blocks[team].rows if r.seconds]
            if block_rows:
                main = max(block_rows, key=lambda r: r.seconds)
                parts = [f"{main.block} block for {main.share:.0f}% of settled defending (back four at {main.back_four_m} m, {main.length_m} m from deepest to highest player)"]
                if main.opponent_entries:
                    parts.append(f"{main.wide_entry_share:.0f}% of the opponent's final-third entries against it went wide")
                if main.opponent_shots:
                    parts.append(f"{plural(main.opponent_shots, 'shot')} faced, {main.long_shot_share:.0f}% from outside the box")
                codes = self.settled.get(team)
                faced = [(q, min(self.frame(q.time_ms), self.last_frame)) for q in sorted(self.quality.values(), key=lambda q: -q.xg) if q.team_id != team]
                moments = [Moment(time_ms=q.time_ms, event_ref=q.ref, label=f"Shot faced against {article(self.block_of(team, f))} block: {q.xg:.2f} xG")
                           for q, f in faced if codes and codes[f]][:MOMENTS] if self.track else []
                add(team, "Defensive block", f"{who} sat in a " + "; ".join(parts) + ".",
                    "How the lines shift together toward the ball, whether the block lets passes through the middle or only around it, "
                    "and who steps out to press and who covers.", moments)
            prog = progression[team]
            if prog.xt:
                flank = max(prog.xt_by_channel, key=lambda k: prog.xt_by_channel[k])
                top = [a for a in self.threats if a.team_id == team]
                top.sort(key=lambda a: -a.xt)
                carry = f"{prog.carry_share:.0f}%" if prog.carry_share is not None else "—"
                add(team, "Where the threat comes from",
                    f"{who} added {prog.xt:.2f} expected threat with completed passes and carries, most from the {flank} "
                    f"({prog.xt_by_channel[flank]:.2f}); {carry} of their {prog.progressive_passes + prog.progressive_carries} progressive actions were carries.",
                    "The movement that opened the passing lane or the carrying space: a run that dragged a marker away, a rotation, or a defender stepping out.",
                    [Moment(time_ms=a.time_ms, event_ref=a.event_ref, label=f"{player[a.player_id]} {a.action}: {a.xt:+.3f} xT") for a in top[:MOMENTS]])
            for row in fullbacks:
                if row.team_id == team and row.style not in ("balanced", "insufficient_evidence"):
                    style = row.style.replace("_", " ")
                    add(team, f"{row.side.title()}-back role",
                        f"{player[row.player_id]} played as {article(style)} full-back: {row.inside_share:.0f}% of build-up time inside, {plural(row.overlaps, 'overlap')} and "
                        f"{plural(row.underlaps, 'underlap')}, {row.attack_depth_m if row.attack_depth_m is not None else '—'} m from goal on average with the ball in the final third, "
                        f"{row.depth_at_loss_m if row.depth_at_loss_m is not None else '—'} m when the ball was lost.",
                        "Who covers the space the full-back leaves behind, and whether the winger's movement inside or wide is what frees the run.",
                        row.moments)
            for row in rotations[team].rows[:2]:
                if row.episodes:
                    rate = f"{row.final_third_rate:.0f}%" if row.final_third_rate is not None else "—"
                    base = f"{row.baseline_rate:.0f}%" if row.baseline_rate is not None else "—"
                    add(team, "Rotation: " + ROTATION_NAMES[row.kind],
                        f"Seen {times(row.episodes)} ({row.seconds:.0f} s). Possessions with it reached the final third {rate} of the time, against {base} without it.",
                        "Which opponent follows the rotating player and what space that opens; a rotation can work without the ball ever going there.",
                        row.moments, small(row.possessions, 5))
            c = control[team]
            if c.read != "insufficient_evidence":
                read = {"control_with_territory": "had the ball and the territory", "possession_without_penetration": "had the ball but not the territory",
                        "territory_without_the_ball": "had territory without much of the ball", "pinned_back": "had neither the ball nor the territory",
                        "balanced": "shared the ball and the territory"}[c.read]
                sterile = [p for p in self.plays if p["team"] == team and self.reached_final_third(p) is None and not any(r.payload.kind == "SHOT" for r in p["events"])
                           and sum(1 for r in p["events"] if r.payload.kind == "PASS" and r.payload.detail.completed) >= STERILE_PASSES]
                add(team, "Possession against control",
                    f"{who} {read}: {c.possession_share:.0f}% possession, {c.field_tilt:.0f}% field tilt, {c.xg:.2f} xG. {c.purposeful} of {c.possessions} "
                    f"possessions reached the final third or a shot; {c.sterile} strung {STERILE_PASSES} or more passes without either.",
                    "In the sterile spells: whether the opponent's block invited the passes, and whether anyone tried to break a line.",
                    [Moment(time_ms=p["start"], event_ref=p["ref"], label=f"Sterile possession: {sum(1 for r in p['events'] if r.payload.kind == 'PASS')} passes, no final third")
                     for p in sterile[:MOMENTS]])
            t = xg[team]
            own = sorted((q for q in self.quality.values() if q.team_id == team), key=lambda q: -q.xg)
            if own:
                goals = sum(q.outcome == "goal" for q in own)
                add(team, "Chances against goals",
                    f"{who} scored {goals} from {sum(q.xg for q in own):.2f} xG ({t.goals_minus_xg:+.2f}).",
                    "Whether the best chances were missed through rushed finishing or a good save, and whether the final pass was on time.",
                    [Moment(time_ms=q.time_ms, event_ref=q.ref, label=f"{player[q.player_id]}: {q.xg:.2f} xG, {q.outcome.replace('_', ' ')}") for q in own[:MOMENTS]],
                    "One match is far too few shots to judge finishing.")
        return notes

    # ----------------------------------------------------------------- build
    def build_phases(self) -> dict:
        limitations = list(LIMITATIONS)
        if not self.track:
            limitations.append("Movement tracking is unavailable because the fixture does not match the tracking source, so off-ball measures are empty.")
        transitions, counter_ids = {}, {}
        for team in self.teams:
            attacking, counter_ids[team] = self.attacking_transitions(team)
            transitions[team] = TeamTransitions(team_id=team, attacking=attacking, defensive=self.counter_press(team) if self.track else
                CounterPress(losses=sum(1 for p in self.plays if p["team"] != team and p["regain"]), tracked=0, pressed=0, press_rate=None,
                             median_pressure_s=None, pack_2s=None, regained_5s=0, regained_10s=0, bypassed=0, shots_conceded=0, xg_conceded=0.0,
                             rest_defence=None, rest_defenders=None, by_third={"defensive": 0, "middle": 0, "final": 0}, moments=[]))
        phases = self.phases()
        progression, players, top = self.progression()
        self.progression_rows = players
        blocks = self.blocks(counter_ids)
        fullbacks, rotations = self.fullbacks_and_rotations()
        control = self.control(progression)
        finishing, xg = self.finishing()
        g = xt_grid()
        return {"phases": phases, "transitions": transitions, "blocks": blocks, "progression": progression, "player_progression": players,
                "top_threat": top, "xt_grid": XtGrid(grid_x=g["grid_x"], grid_y=g["grid_y"], values=g["values"],
                                                     training={k: v for k, v in g["training"].items() if k != "iterations"}),
                "fullbacks": fullbacks, "rotations": rotations, "control": control, "pressing": self.pressing_over_time(),
                "finishing": finishing, "xg": xg,
                "notes": self.notes(phases, transitions, blocks, progression, fullbacks, rotations, control, xg),
                "definitions": DEFINITIONS, "limitations": limitations}
