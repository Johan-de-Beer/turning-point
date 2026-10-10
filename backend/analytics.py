"""Live match analytics: field tilt, chance quality, defensive line height, player
workload and possession value, all for the observed prefix of the match.

Field tilt, xG and possession value come from observed events. Line height and
workload come from the continuous synthetic movement layer (``movement``), released
one second at a time with the playhead. Nothing here reads the generator's
tendencies or plans; tests recover the planted behaviour from these numbers.
"""
from __future__ import annotations

import threading
from statistics import median

from .chances import DEFINITIONS as CHANCE_DEFINITIONS, location_value, shot_quality
from .ingest import canonical_order
from .metrics import calculate_window, final_third_pass
from .models import (DefensiveLine, EventEnvelope, LineFigures, LineInterval, Match, PERIOD_MS, PlayerValue, PlayerWorkload,
                     ShotValue, TeamChances, TeamValue, Territory, TerritoryWindow, ValuedAction)
from .movement import HSR_MPS, SECONDS, SPRINT_MPS, Movement, build_movement
from .tactics import TacticalEngine

INTERVAL_MS = 900_000
RECENT_TILT_MS = 600_000
RECENT_LINE_S = 300
RECENT_WORK_S = 600
HIGH_LINE_M, LOW_LINE_M = 42.0, 30.0
MIN_LINE_S = 30
DROP_POINTS = 10.0

DEFINITIONS = {
    "field_tilt": "A team's share of both teams' final-third passes: attempted passes into or within the attacking final third (x ≥ 66.67). It shows where possession happens, not how good it is.",
    "possession_share": "Share of known owned in-play time, as in the match numbers.",
    **{key: CHANCE_DEFINITIONS[key] for key in ("xg", "xg_against", "chance_type", "assist_type", "possession_value", "location_value")},
    "line_height": "Out of possession in live play, from the continuous 5 Hz synthetic positions: the deepest outfield player's, the back four's mean and the ten outfield players' centroid distance from the team's own goal line, in metres.",
    "line_gap": "Distance from the back four's mean depth to the midfield three's mean depth: the space between the lines.",
    "line_width": "Distance between the widest two of the back four.",
    "block": f"From the back four's mean depth when settled out of possession: high at {HIGH_LINE_M:.0f} m or more, low under {LOW_LINE_M:.0f} m, otherwise mid. At least {MIN_LINE_S} s of settled defending is needed.",
    "line_phases": "After losing the ball: the first 5 s after the opponent wins possession. Settled: the rest of the time out of possession. Before shots: the frame 1 s before each opponent shot.",
    "distance": "Distance covered by the synthetic player track, in metres.",
    "hsr": f"High-speed running: distance at {HSR_MPS} m/s (19.8 km/h) or faster.",
    "sprint": f"Sprint distance at {SPRINT_MPS} m/s (25.2 km/h) or faster; a sprint effort lasts at least 1 s.",
    "accelerations": "Efforts above 3 m/s² (or below −3 m/s² for decelerations) held for at least 0.4 s.",
    "load": "Composite external load: the sum of velocity changes frame to frame, divided by 10 (arbitrary units).",
    "intensity_trend": f"Metres per minute in the last {RECENT_WORK_S // 60} minutes as a share of the player's match average. Flagged when it is {DROP_POINTS:.0f} or more points below the team's median outfield trend after 30 minutes.",
}

LIMITATIONS = [
    "Synthetic data: the event stream and the 5 Hz player tracks are generated from fictional tendencies. They are not measured players.",
    "xG and the location value surface are transparent heuristics with illustrative coefficients, not models fitted to shot data, so they rank chances within this sample rather than give calibrated probabilities.",
    "Possession value values on-ball actions only. Defensive actions, off-ball runs and the opponent's gain from a turnover are not valued.",
    "Workload is external load only (distance, speed bands, accelerations, a composite). Internal load such as heart rate, perceived exertion (RPE) and the acute:chronic workload ratio need physiological data and multi-week history that a single synthetic match does not have.",
    "Line height and workload come from continuous synthetic positions. Where a tactical tracking episode exists the positions follow it; elsewhere players move to formation spots that slide with the ball.",
    "Field tilt counts final-third passes only. Direct counter-attacks that reach a shot in one or two passes add little to it.",
]


def r1(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def share(part: int, total: int) -> float | None:
    return round(100 * part / total, 1) if total else None


class AnalyticsEngine:
    """Builds the continuous movement layer once per fixture; reports filter by the observed prefix."""

    def __init__(self, match: Match, fixture: list[EventEnvelope], tactics: TacticalEngine):
        self.match, self.fixture, self.tactics = match, fixture, tactics
        self._movement: Movement | None = None
        self._ready = False
        self._lock = threading.Lock()
        self._cache: dict[tuple, dict] = {}

    def movement(self) -> Movement | None:
        with self._lock:
            if not self._ready:
                prepared = self.tactics.prepared()
                self._movement = build_movement(self.match, self.fixture, list(prepared.episodes.values())) if prepared.available else None
                self._ready = True
            return self._movement

    def report(self, records: dict[str, EventEnvelope], playhead_ms: int) -> dict:
        movement = self.movement()
        cutoff = playhead_ms // 1000 * 1000
        key = (cutoff, len(records), sum(e.revision for e in records.values()))
        if key in self._cache:
            return self._cache[key]
        result = AnalyticsReport(self.match, movement, records, cutoff).build()
        if len(self._cache) > 64:
            self._cache.clear()
        self._cache[key] = result
        return result


class AnalyticsReport:
    def __init__(self, match: Match, movement: Movement | None, records: dict[str, EventEnvelope], playhead: int):
        self.match, self.movement, self.records, self.playhead = match, movement, records, playhead
        self.teams = [match.home.team_id, match.away.team_id]
        self.ordered = [r for r in canonical_order(records) if r.payload.event_time_ms <= playhead]
        self.second = min(SECONDS, playhead // 1000)

    def other(self, team: str) -> str:
        return self.teams[1] if team == self.teams[0] else self.teams[0]

    # ------------------------------------------------------------ territory
    def territory_window(self, start: int, end: int) -> TerritoryWindow:
        passes = {team: 0 for team in self.teams}
        for record in self.ordered:
            e = record.payload
            if start < e.event_time_ms <= end and final_third_pass(e):
                passes[e.team_id] += 1
        total = sum(passes.values())
        owned = {team: 0 for team in self.teams}
        for period in (1, 2):
            low, high = max(start, (period - 1) * PERIOD_MS), min(end, period * PERIOD_MS)
            if high <= low:
                continue
            window = calculate_window(self.records, self.teams, period, low, high)
            for team in self.teams:
                owned[team] += window.coverage.owned_in_play_ms[team]
        known = sum(owned.values())
        return TerritoryWindow(start_ms=start, end_ms=end, final_third_passes=passes,
            field_tilt={team: share(passes[team], total) for team in self.teams},
            possession_share={team: share(owned[team], known) for team in self.teams})

    def territory(self) -> Territory:
        intervals = []
        for start in range(0, self.playhead, INTERVAL_MS):
            intervals.append(self.territory_window(start, min(start + INTERVAL_MS, self.playhead)))
        return Territory(match=self.territory_window(0, self.playhead),
                         recent=self.territory_window(max(0, self.playhead - RECENT_TILT_MS), self.playhead), intervals=intervals)

    # -------------------------------------------------------------- chances
    def chances(self) -> tuple[dict[str, TeamChances], list[ShotValue]]:
        quality = shot_quality(self.records, self.ordered)
        shots = [ShotValue(event_ref=q.ref, time_ms=q.time_ms, team_id=q.team_id, player_id=q.player_id, outcome=q.outcome, xg=q.xg,
                           distance_m=q.distance_m, angle_deg=q.angle_deg, assist=q.assist, body_part=q.body_part, chance=q.chance)
                 for q in quality.values()]
        result = {}
        for team in self.teams:
            own = [s for s in shots if s.team_id == team]
            against = [s for s in shots if s.team_id != team]
            xg = round(sum(s.xg for s in own), 2)
            result[team] = TeamChances(team_id=team, shots=len(own), on_target=sum(s.outcome in ("goal", "saved") for s in own),
                goals=sum(s.outcome == "goal" for s in own), xg=xg, xg_against=round(sum(s.xg for s in against), 2),
                major_chances=sum(s.chance == "major" for s in own), xg_per_shot=round(xg / len(own), 3) if own else None)
        return result, shots

    # ------------------------------------------------------- defensive line
    def figures(self, team: str, phase: str, low: int, high: int) -> LineFigures:
        sums = self.movement.lines[team][phase]
        frames = sums["frames"][high] - (sums["frames"][low] if low >= 0 else 0)
        if frames <= 0:
            return LineFigures(seconds=0.0, deepest_m=None, back_four_m=None, centroid_m=None, gap_m=None, width_m=None)
        value = lambda name: r1((sums[name][high] - (sums[name][low] if low >= 0 else 0)) / frames)
        return LineFigures(seconds=round(frames * .2, 1), deepest_m=value("deepest"), back_four_m=value("back_four"),
                           centroid_m=value("centroid"), gap_m=value("gap"), width_m=value("width"))

    def defensive_line(self, team: str) -> DefensiveLine:
        s = self.second
        settled = self.figures(team, "settled", -1, s)
        block = "insufficient_evidence"
        if settled.seconds >= MIN_LINE_S:
            block = "high" if settled.back_four_m >= HIGH_LINE_M else "low" if settled.back_four_m < LOW_LINE_M else "mid"
        readings = [r for r in self.movement.before_shots[team] if r.t <= self.playhead]
        if readings:
            mean = lambda name: r1(sum(getattr(r, name) for r in readings) / len(readings))
            before = LineFigures(seconds=round(len(readings) * .2, 1), deepest_m=mean("deepest"), back_four_m=mean("back_four"),
                                 centroid_m=mean("centroid"), gap_m=mean("gap"), width_m=mean("width"))
        else:
            before = LineFigures(seconds=0.0, deepest_m=None, back_four_m=None, centroid_m=None, gap_m=None, width_m=None)
        intervals = []
        for start in range(0, self.playhead, INTERVAL_MS):
            end = min(start + INTERVAL_MS, self.playhead)
            figure = self.figures(team, "all", start // 1000 if start else -1, end // 1000)
            intervals.append(LineInterval(start_ms=start, end_ms=end, seconds=figure.seconds, back_four_m=figure.back_four_m, deepest_m=figure.deepest_m))
        return DefensiveLine(team_id=team, block=block, match=self.figures(team, "all", -1, s),
            recent=self.figures(team, "all", max(-1, s - RECENT_LINE_S), s), settled=settled,
            after_loss=self.figures(team, "after_loss", -1, s), before_shots=before, shots_faced=len(readings), intervals=intervals)

    # ------------------------------------------------------------- workload
    def workload(self) -> list[PlayerWorkload]:
        s = self.second
        minutes = s / 60
        recent_start = max(0, s - RECENT_WORK_S)
        rows = []
        for player in self.match.roster:
            totals = self.movement.players[player.player_id]
            distance = totals.distance[s]
            recent_minutes = (s - recent_start) / 60
            per_min = distance / minutes if minutes else None
            recent = (distance - totals.distance[recent_start]) / recent_minutes if recent_minutes else None
            top = max((v for t, v in totals.top_speed if t <= self.playhead), default=0.0)
            rows.append(PlayerWorkload(player_id=player.player_id, team_id=player.team_id, minutes=round(minutes, 1),
                distance_m=round(distance), hsr_m=round(totals.hsr[s]), sprint_m=round(totals.sprint[s]),
                sprints=sum(1 for t in totals.sprints if t <= self.playhead),
                accelerations=sum(1 for t in totals.accelerations if t <= self.playhead),
                decelerations=sum(1 for t in totals.decelerations if t <= self.playhead),
                load=round(totals.load[s], 1), top_speed_mps=round(top, 1), metres_per_min=r1(per_min), recent_metres_per_min=r1(recent),
                trend_pct=r1(100 * recent / per_min) if per_min and recent is not None and minutes >= RECENT_WORK_S / 60 else None, flag=None))
        if minutes >= 30:
            for team in self.teams:
                outfield = [r for r in rows if r.team_id == team and r.trend_pct is not None and not r.player_id.endswith("_01")]
                if not outfield:
                    continue
                typical = median(r.trend_pct for r in outfield)
                for row in outfield:
                    if row.trend_pct <= typical - DROP_POINTS:
                        row.flag = "intensity_drop"
        return rows

    # ---------------------------------------------------- possession value
    def possession_value(self) -> tuple[dict[str, TeamValue], list[PlayerValue], list[ValuedAction]]:
        quality = shot_quality(self.records, self.ordered)
        actions: list[ValuedAction] = []
        holder: dict[str, str | None] = {}
        possessions = {team: 0 for team in self.teams}

        def add(record, action, player, team, start, end, before, after, pv):
            actions.append(ValuedAction(event_ref=record.ref, time_ms=record.payload.event_time_ms, team_id=team, player_id=player,
                action=action, start={"x": start[0], "y": start[1]}, end=None if end is None else {"x": end[0], "y": end[1]},
                value_before=round(before, 4), value_after=round(after, 4), pv=round(pv, 4)))

        for record in self.ordered:
            e = record.payload
            if e.kind == "POSSESSION":
                possessions[e.team_id] += 1
                holder[e.possession_id] = e.player_id
            elif e.kind in ("PASS", "CARRY"):
                a, b = (e.detail.start.x, e.detail.start.y), (e.detail.end.x, e.detail.end.y)
                before = location_value(*a)
                if e.kind == "PASS" and not e.detail.completed:
                    add(record, "lost_pass", e.player_id, e.team_id, a, b, before, 0.0, -before)
                    holder[e.possession_id] = None
                else:
                    after = location_value(*b)
                    add(record, e.kind.lower(), e.player_id, e.team_id, a, b, before, after, after - before)
                    holder[e.possession_id] = e.detail.recipient_id if e.kind == "PASS" else e.player_id
            elif e.kind == "SHOT" and record.event_id in quality:
                a = (e.detail.position.x, e.detail.position.y)
                before, after = location_value(*a), quality[record.event_id].xg
                add(record, "shot", e.player_id, e.team_id, a, None, before, after, after - before)
                holder[e.possession_id] = None
            elif e.kind == "TACKLE" and e.detail.successful:
                victim = holder.get(e.possession_id)
                if victim:
                    # The tackle is recorded in the winner's frame; value the ball where the loser had it.
                    spot = (100 - e.detail.position.x, 100 - e.detail.position.y)
                    before = location_value(*spot)
                    add(record, "dispossessed", victim, self.other(e.team_id), spot, None, before, 0.0, -before)
                holder[e.possession_id] = None

        teams = {}
        for team in self.teams:
            own = [a for a in actions if a.team_id == team]
            total = sum(a.pv for a in own)
            by_action = {}
            for a in own:
                by_action[a.action] = by_action.get(a.action, 0.0) + a.pv
            teams[team] = TeamValue(team_id=team, actions=len(own), possessions=possessions[team], pv=round(total, 3),
                pv_per_action=round(total / len(own), 4) if own else None, by_action={k: round(v, 3) for k, v in sorted(by_action.items())})
        players = []
        for player in self.match.roster:
            own = [a for a in actions if a.player_id == player.player_id]
            if not own:
                continue
            best = max(own, key=lambda a: a.pv)
            players.append(PlayerValue(player_id=player.player_id, team_id=player.team_id, actions=len(own), pv=round(sum(a.pv for a in own), 3),
                positive_actions=sum(a.pv > 0 for a in own), best_ref=best.event_ref if best.pv > 0 else None))
        players.sort(key=lambda p: -p.pv)
        top = sorted((a for a in actions if a.action != "shot"), key=lambda a: -a.pv)[:10]
        return teams, players, top

    def build(self) -> dict:
        chances, shots = self.chances()
        team_value, player_value, top_actions = self.possession_value()
        limitations = list(LIMITATIONS)
        if self.movement:
            lines = {team: self.defensive_line(team) for team in self.teams}
            workload = self.workload()
        else:
            empty = LineFigures(seconds=0.0, deepest_m=None, back_four_m=None, centroid_m=None, gap_m=None, width_m=None)
            lines = {team: DefensiveLine(team_id=team, block="insufficient_evidence", match=empty, recent=empty, settled=empty,
                     after_loss=empty, before_shots=empty, shots_faced=0, intervals=[]) for team in self.teams}
            workload = []
            limitations.append("Movement tracking is unavailable because the fixture does not match the tracking source.")
        return {"territory": self.territory(), "chances": chances, "shots": shots, "defensive_line": lines, "workload": workload,
                "team_value": team_value, "player_value": player_value, "top_actions": top_actions,
                "definitions": DEFINITIONS, "limitations": limitations}
