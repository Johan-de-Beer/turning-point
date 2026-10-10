"""Advanced live metrics: game state, heatmaps, xGoT and goals prevented, tempo, pressing
(PPDA), chance creation (touches in the box, Zone 14, key passes, xA) and packing.

``AdvancedMetrics`` is mixed into ``analytics.AnalyticsReport`` and works on the same
observed prefix. Like the rest of the analytics it measures events and the synthetic
movement layer only; it never reads the generator's tendencies or plans.

Coordinates are team-relative (the team in question attacks toward x = 100) unless a
name says ``home``.
"""
from __future__ import annotations

import math
from statistics import median

from .chances import X_M, in_box
from .metrics import calculate_window
from .models import (CreatingAction, DefensiveRow, GameState, GameStateRow, Goalkeeping, Heatmap, Heatmaps, KeeperRow, NetworkEdge, NetworkNode,
                     PackingAction, PassNetwork, PERIOD_MS, PlayerCreation,
                     PlayerPacking, Pressing, ScoreSegment, TeamCreation, TeamGameState, TeamPacking, TeamShooting, TeamTempo,
                     TempoFigures, TempoInterval)
from .movement import GRID_X, GRID_Y, cell
from .tactical_profiles import BACK_FOUR, role

STATES = ("winning", "drawing", "losing")
FORWARD_M = 5.0             # a pass is forward (or backward) when it gains (or loses) this much depth
PPDA_ZONE_X = 60.0          # opponent passes in their own 60% of the pitch
LINE_BREAKING = 3           # packed opponents for a line-breaking action
INTERVAL_MS = 900_000
TOP_PACKING = 10
NETWORK_MIN_PASSES = 2      # pass-network links shown from this many completed passes
PER90_MIN_MINUTES = 10      # per-90 rates need at least this much observed play

ADVANCED_DEFINITIONS = {
    "game_state": "The scoreline from each team's point of view: winning, drawing or losing. A goal's own shot counts in the state before it. Every game-state row covers only the minutes spent in that state.",
    "heatmap": f"Counts on a {GRID_X} x {GRID_Y} grid in the team's attacking direction (left to right). Touches: on-ball events (gaining the ball, passes, receptions, carries, shots). Tracking: seconds spent in each cell from the 5 Hz synthetic positions. Received: completed passes received. Defensive: duels contested and interceptions. A hot zone shows where things happen, not how well.",
    "xg_prevented": "Expected goals prevented: the xGoT of on-target shots a goalkeeper faced minus the goals conceded. Positive means more saves than an average keeper would make from those placements.",
    "placement_added": "A team's xGoT minus the pre-shot xG of the same on-target shots: how much the shot placement and pace added or took away.",
    "vertical_mps": "Vertical progression rate: net metres the ball moved toward the opponent's goal per second of possession.",
    "passes_per_entry": "Average completed passes in a possession before it first enters the final third (x ≥ 66.67), counting the entering pass, for possessions that start outside it.",
    "directness": f"Forward passes divided by lateral and backward passes. Forward or backward means at least {FORWARD_M:.0f} m of depth gained or lost.",
    "possession_s": "Average possession length in seconds, by the third where the possession started.",
    "progressive_pass": "A completed forward pass that moves the ball at least 10 m closer to the goal centre when played from outside the final third, or at least 5 m when played from inside it.",
    "sca": "Shot-creating actions: the two offensive actions directly before a shot, by the shooting team in the same possession: a live-ball pass, a dead-ball pass (the first pass after a restart, corners included), a take-on (a carry that beat a challenge), an earlier shot whose rebound was shot again, or the tackle or interception that won the ball. Goal-creating actions (GCA) are the same for shots that were scored.",
    "pass_network": f"Each player at the average spot of their passes and receptions, linked to teammates they completed at least {NETWORK_MIN_PASSES} passes with (both directions together). Width and depth are the spread of the outfield players' spots.",
    "defensive_actions": f"Tackles won and lost (challenges on the ball carrier), aerial duels won, interceptions and loose-ball recoveries. Per 90 scales the count to a full match once {PER90_MIN_MINUTES} minutes have been observed. Clearances and blocks are not in the event data.",
    "goals_minus_xg_against": "Goals conceded minus the xG of the shots conceded. Below zero, the team let in fewer goals than its chances allowed (good goalkeeping, last-ditch defending or poor finishing); above zero, more.",
    "regain_to_progressive_s": "Median seconds from winning the ball in open play to the first progressive pass of that possession.",
    "ppda": f"Passes allowed per defensive action: the opponent's attempted passes in their own {PPDA_ZONE_X:.0f}% of the pitch divided by this team's duels and interceptions in that area. Lower means a more aggressive press.",
    "box_touches": "On-ball touches inside the opponent's penalty area (x ≥ 83, 20 ≤ y ≤ 80), including receptions.",
    "zone14": "The central area just outside the box (66.67 ≤ x < 83, 33.3 ≤ y ≤ 66.7). Entries are completed passes or carries that end there from outside it.",
    "key_pass": "The last completed pass to a teammate who then shoots, whatever the shot's outcome. As in the main data providers the receiver may carry the ball first, but no other teammate may touch it; first-time key passes are the stricter count where the receiver shoots straight away. An assist is a key pass whose shot is scored.",
    "xa": "Expected assists: the xG of the shots a player's key passes set up.",
    "packing": f"Opponents bypassed: outfield opponents whose depth lay between the ball's start and end of a completed pass or carry, from the synthetic positions at the frame of the action. Packing rate divides that by all pass attempts (or carries). Line-breaking actions bypass {LINE_BREAKING} or more.",
    "vaep": "A VAEP-style value: the change an action causes in the team's chance of scoring minus the change in its chance of conceding, both from the location value surface. Unlike possession value it charges a lost ball for the chance it hands the opponent, and credits the defender who wins the ball (a tackle or an interception) with half of that swing.",
    "xova": "Expected offensive value added: the scoring side of the value model only, which here is the possession value.",
}

ADVANCED_LIMITATIONS = [
    "Game-state splits are small samples: one match has a handful of goals, so a state may last only minutes. Read them as context for the other numbers, not as a verdict.",
    "xGoT uses the synthetic recorded placement (side, height, pace) of goals and saved shots and illustrative coefficients. It is not a fitted post-shot model.",
    "Packing uses the continuous synthetic positions at the frame nearest each action and counts outfield opponents only. It treats every bypassed opponent alike, whatever their position.",
    "Shot- and goal-creating actions cannot include fouls drawn: the synthetic events record a foul stoppage but not who was fouled.",
    "VAEP here is a transparent analogue built on the location value surface with a fixed counter-attack risk, not the trained VAEP model.",
]


def r2(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def ratio(part: float, total: float, digits: int = 2) -> float | None:
    return round(part / total, digits) if total else None


def metres_to_goal(x: float, y: float) -> float:
    return math.hypot((100 - x) * X_M, (y - 50) * .68)


def progressive(start, end) -> bool:
    gain = metres_to_goal(start.x, start.y) - metres_to_goal(end.x, end.y)
    return end.x > start.x and gain >= (5 if start.x >= 66.67 else 10)


def in_zone14(x: float, y: float) -> bool:
    return 66.67 <= x < 83 and 33.3 <= y <= 66.7


def third(x: float) -> str:
    return "defensive" if x < 33.33 else "middle" if x < 66.67 else "final"


class AdvancedMetrics:
    """Mixed into AnalyticsReport, which provides match, movement, records, ordered, playhead, second, teams and other()."""

    # ------------------------------------------------------------ game state
    def goals(self) -> list[tuple[int, str]]:
        return [(r.payload.event_time_ms, r.payload.team_id) for r in self.ordered
                if r.payload.kind == "SHOT" and r.payload.detail.outcome == "goal"]

    def state_at(self, team: str, t: int) -> str:
        """The team's game state for an event at ``t``; a goal's own shot counts in the state before it."""
        scored = sum(1 for at, side in self._goals if at < t and side == team)
        against = sum(1 for at, side in self._goals if at < t and side != team)
        return "winning" if scored > against else "losing" if scored < against else "drawing"

    def segments(self) -> list[ScoreSegment]:
        result, start = [], 0
        score = {team: 0 for team in self.teams}
        for at, side in self._goals:
            if at > start:
                result.append(ScoreSegment(start_ms=start, end_ms=at, score=dict(score)))
            score[side] += 1
            start = at
        if self.playhead > start or not result:
            result.append(ScoreSegment(start_ms=start, end_ms=self.playhead, score=dict(score)))
        return result

    def owned(self, start: int, end: int) -> dict[str, int]:
        owned = {team: 0 for team in self.teams}
        for period in (1, 2):
            low, high = max(start, (period - 1) * PERIOD_MS), min(end, period * PERIOD_MS)
            if high > low:
                window = calculate_window(self.records, self.teams, period, low, high)
                for team in self.teams:
                    owned[team] += window.coverage.owned_in_play_ms[team]
        return owned

    def game_state(self, shots, actions) -> GameState:
        segments = self.segments()
        teams = {}
        for team in self.teams:
            rival = self.other(team)
            rows = []
            for state in STATES:
                spans = [(s.start_ms, s.end_ms) for s in segments
                         if (s.score[team] > s.score[rival]) == (state == "winning") and (s.score[team] < s.score[rival]) == (state == "losing")]
                ms = sum(b - a for a, b in spans)
                if not ms:
                    continue
                inside = lambda t: any(a < t <= b for a, b in spans) or (t == 0 and spans[0][0] == 0)
                owned = {k: 0 for k in self.teams}
                for a, b in spans:
                    for k, v in self.owned(a, b).items():
                        owned[k] += v
                events = [r.payload for r in self.ordered if inside(r.payload.event_time_ms)]
                third_passes = {k: sum(1 for e in events if e.kind == "PASS" and e.team_id == k and max(e.detail.start.x, e.detail.end.x) >= 66.67)
                                for k in self.teams}
                own_shots = [s for s in shots if s.team_id == team and inside(s.time_ms)]
                xg = sum(s.xg for s in own_shots)
                own_actions = [a for a in actions if a.team_id == team and inside(a.time_ms)]
                vaep = sum(a.vaep for a in own_actions)
                tempo = self.tempo_figures(team, lambda t: inside(t))
                press = self.pressing_counts(team, inside)
                back = self.state_line(team, spans)
                rows.append(GameStateRow(state=state, minutes=round(ms / 60_000, 1),
                    possession_share=ratio(100 * owned[team], sum(owned.values()), 1),
                    field_tilt=ratio(100 * third_passes[team], sum(third_passes.values()), 1),
                    passes=sum(1 for e in events if e.kind == "PASS" and e.team_id == team), shots=len(own_shots), xg=round(xg, 2),
                    xg_per_shot=ratio(xg, len(own_shots), 3), goals=sum(s.outcome == "goal" for s in own_shots),
                    box_touches=sum(1 for t in self._touches if t[1] == team and in_box(t[2], t[3]) and inside(t[4])),
                    xova=round(sum(a.pv for a in own_actions), 3), vaep=round(vaep, 3), vaep_per_action=ratio(vaep, len(own_actions), 4),
                    ppda=ratio(press[0], press[1], 1), vertical_mps=tempo.vertical_mps, directness=tempo.directness, back_four_m=back))
            teams[team] = TeamGameState(team_id=team, current=self.state_at(team, self.playhead + 1), rows=rows)
        score = {team: sum(1 for _, side in self._goals if side == team) for team in self.teams}
        return GameState(score=score, segments=segments, teams=teams)

    def state_line(self, team: str, spans: list[tuple[int, int]]) -> float | None:
        if not self.movement:
            return None
        sums = self.movement.lines[team]["settled"]
        frames = total = 0.0
        for a, b in spans:
            low, high = a // 1000, min(self.second, b // 1000)
            if high <= low:
                continue
            frames += sums["frames"][high] - sums["frames"][low]
            total += sums["back_four"][high] - sums["back_four"][low]
        return round(total / frames, 1) if frames else None

    # --------------------------------------------------------------- touches
    def collect_touches(self) -> list[tuple[str, str, float, float, int, str]]:
        """(player, team, x, y, time, kind) for every on-ball touch, in the player's team frame."""
        rows = []
        for record in self.ordered:
            e = record.payload
            t = e.event_time_ms
            if e.kind == "POSSESSION":
                rows.append((e.player_id, e.team_id, e.detail.start.x, e.detail.start.y, t, "gain"))
            elif e.kind == "PASS":
                rows.append((e.player_id, e.team_id, e.detail.start.x, e.detail.start.y, t, "pass"))
                if e.detail.completed:
                    rows.append((e.detail.recipient_id, e.team_id, e.detail.end.x, e.detail.end.y, t, "received"))
            elif e.kind == "CARRY":
                rows.append((e.player_id, e.team_id, e.detail.end.x, e.detail.end.y, t, "carry"))
            elif e.kind == "SHOT":
                rows.append((e.player_id, e.team_id, e.detail.position.x, e.detail.position.y, t, "shot"))
        return rows

    def interceptions(self) -> dict[str, str]:
        """Event id of each open-play regain straight after an opponent's lost pass -> the lost pass's event id."""
        result, previous = {}, None
        for record in self.ordered:
            e = record.payload
            if e.kind == "POSSESSION" and previous is not None and previous.payload.kind == "PASS" \
                    and not previous.payload.detail.completed and previous.payload.team_id != e.team_id:
                result[record.event_id] = previous.event_id
            if e.kind != "TACKLE":
                previous = record
        return result

    def regains(self) -> dict[str, tuple[str, str]]:
        """Each open-play regain (a POSSESSION event id) -> (how: tackle, interception or recovery, the player who won it)."""
        result, previous, tackle = {}, None, None
        for record in self.ordered:
            e = record.payload
            if e.kind == "TACKLE":
                tackle = record
                continue
            if e.kind == "POSSESSION" and previous is not None and previous.payload.kind not in ("STOPPAGE", "PERIOD_START", "PERIOD_END") \
                    and previous.payload.team_id not in (None, e.team_id):
                t = tackle.payload if tackle else None
                if t and t.detail.successful and t.team_id == e.team_id and e.event_time_ms - t.event_time_ms <= 1_000:
                    result[record.event_id] = ("tackle", t.player_id)
                elif record.event_id in self._interceptions:
                    result[record.event_id] = ("interception", e.player_id)
                else:
                    result[record.event_id] = ("recovery", e.player_id)
            previous = record
        return result

    def take_ons(self) -> set[str]:
        """Carries that beat a challenge on the way (the defender lost the ground duel)."""
        carries, result = [], set()
        for record in self.ordered:
            e = record.payload
            if e.kind == "CARRY":
                carries.append(record)
            elif e.kind == "TACKLE" and not e.detail.successful and e.detail.contest == "ground":
                for carry in carries[-2:]:
                    c = carry.payload
                    if c.possession_id == e.possession_id and 0 < e.event_time_ms - c.event_time_ms <= 1_500:
                        result.add(carry.event_id)
        return result

    # ------------------------------------------------- shot- and goal-creating actions
    def creating_actions(self) -> list[CreatingAction]:
        regains, take_ons = self._regains, self.take_ons()
        chains: dict[str, list[tuple[str, str]]] = {}     # possession id -> qualifying (kind, player) so far
        after_restart: set[str] = set()
        previous = None
        result = []
        for record in self.ordered:
            e = record.payload
            if e.kind == "TACKLE":
                continue
            if e.kind == "POSSESSION":
                chain = chains.setdefault(e.possession_id, [])
                if record.event_id in regains:
                    how, player = regains[record.event_id]
                    if how != "recovery":
                        chain.append(("defensive", player))
                if previous is None or previous.payload.kind in ("STOPPAGE", "PERIOD_START"):
                    after_restart.add(e.possession_id)
            elif e.kind in ("PASS", "CARRY", "SHOT") and e.possession_id:
                chain = chains.setdefault(e.possession_id, [])
                if e.kind == "SHOT":
                    goal = e.detail.outcome == "goal"
                    for kind, player in chain[-2:]:
                        result.append(CreatingAction(shot_ref=record.ref, time_ms=e.event_time_ms, team_id=e.team_id, player_id=player, kind=kind, goal=goal))
                    chain.append(("shot", e.player_id))
                elif e.kind == "PASS":
                    dead = e.possession_id in after_restart and not any(k.startswith("pass") for k, _ in chain)
                    if e.detail.completed:
                        chain.append(("pass_dead" if dead else "pass_live", e.player_id))
                    after_restart.discard(e.possession_id)
                elif record.event_id in take_ons:
                    chain.append(("take_on", e.player_id))
            previous = record
        return result

    # ----------------------------------------------------------- pass networks
    def pass_networks(self) -> dict[str, PassNetwork]:
        result = {}
        for team in self.teams:
            spots: dict[str, list[tuple[float, float]]] = {}
            made: dict[str, int] = {}
            received: dict[str, int] = {}
            pairs: dict[tuple[str, str], int] = {}
            for player, side, x, y, _t, kind in self._touches:
                if side == team and kind in ("pass", "received"):
                    spots.setdefault(player, []).append((x, y))
            completed = 0
            for record in self.ordered:
                e = record.payload
                if e.kind == "PASS" and e.team_id == team and e.detail.completed and e.detail.recipient_id != e.player_id:
                    completed += 1
                    made[e.player_id] = made.get(e.player_id, 0) + 1
                    received[e.detail.recipient_id] = received.get(e.detail.recipient_id, 0) + 1
                    pairs[(e.player_id, e.detail.recipient_id)] = pairs.get((e.player_id, e.detail.recipient_id), 0) + 1
            nodes = [NetworkNode(player_id=pid, x=round(sum(p[0] for p in pts) / len(pts), 1), y=round(sum(p[1] for p in pts) / len(pts), 1),
                                 touches=len(pts), passes=made.get(pid, 0), received=received.get(pid, 0))
                     for pid, pts in sorted(spots.items())]
            edges = []
            for a, b in sorted({tuple(sorted(k)) for k in pairs}):
                total = pairs.get((a, b), 0) + pairs.get((b, a), 0)
                if total >= NETWORK_MIN_PASSES:
                    edges.append(NetworkEdge(a=a, b=b, passes=total, a_to_b=pairs.get((a, b), 0)))
            edges.sort(key=lambda edge: (-edge.passes, edge.a, edge.b))
            outfield = [n for n in nodes if role(n.player_id) != "GK"]
            width = round((max(n.y for n in outfield) - min(n.y for n in outfield)) * .68, 1) if len(outfield) > 1 else None
            depth = round((max(n.x for n in outfield) - min(n.x for n in outfield)) * X_M, 1) if len(outfield) > 1 else None
            result[team] = PassNetwork(team_id=team, completed_passes=completed, nodes=nodes, edges=edges, width_m=width, depth_m=depth)
        return result

    # ------------------------------------------------------- defensive actions
    def defensive_actions(self) -> list[DefensiveRow]:
        minutes = self.playhead / 60_000
        rows = {p.player_id: {"tackles_won": 0, "tackles_lost": 0, "aerials_won": 0, "interceptions": 0, "recoveries": 0,
                              "thirds": {"defensive": 0, "middle": 0, "final": 0}} for p in self.match.roster}
        for record in self.ordered:
            e = record.payload
            if e.kind == "TACKLE":
                row = rows[e.player_id]
                if e.detail.contest == "aerial":
                    if not e.detail.successful:
                        continue
                    row["aerials_won"] += 1
                else:
                    row["tackles_won" if e.detail.successful else "tackles_lost"] += 1
                row["thirds"][third(e.detail.position.x)] += 1
            elif e.kind == "POSSESSION" and record.event_id in self._regains:
                how, _player = self._regains[record.event_id]
                if how == "tackle":
                    continue
                row = rows[e.player_id]
                row["interceptions" if how == "interception" else "recoveries"] += 1
                row["thirds"][third(e.detail.start.x)] += 1
        result = []
        for p in self.match.roster:
            row = rows[p.player_id]
            total = row["tackles_won"] + row["tackles_lost"] + row["aerials_won"] + row["interceptions"] + row["recoveries"]
            result.append(DefensiveRow(player_id=p.player_id, team_id=p.team_id, minutes=round(minutes, 1), tackles_won=row["tackles_won"],
                tackles_lost=row["tackles_lost"], aerials_won=row["aerials_won"], interceptions=row["interceptions"], recoveries=row["recoveries"],
                total=total, per90=round(total / minutes * 90, 1) if minutes >= PER90_MIN_MINUTES else None, by_third=row["thirds"]))
        result.sort(key=lambda r: (-r.total, r.player_id))
        return result

    # -------------------------------------------------------------- heatmaps
    def heatmaps(self) -> Heatmaps:
        grids: dict[tuple[str, str], list[int]] = {}

        def bump(subject: str, kind: str, x: float, y: float, amount: int = 1):
            grid = grids.setdefault((subject, kind), [0] * (GRID_X * GRID_Y))
            grid[cell(x, y)] += amount

        team_of = {p.player_id: p.team_id for p in self.match.roster}
        for player, team, x, y, _t, kind in self._touches:
            for subject in (player, team):
                bump(subject, "touches", x, y)
                if kind == "received":
                    bump(subject, "received", x, y)
        regains = self._interceptions
        for record in self.ordered:
            e = record.payload
            if e.kind == "TACKLE":
                for subject in (e.player_id, e.team_id):
                    bump(subject, "defensive", e.detail.position.x, e.detail.position.y)
            elif e.kind == "POSSESSION" and record.event_id in regains:
                for subject in (e.player_id, e.team_id):
                    bump(subject, "defensive", e.detail.start.x, e.detail.start.y)
        if self.movement:
            home = self.teams[0]
            for player in self.match.roster:
                counts = [0] * (GRID_X * GRID_Y)
                for index in self.movement.cells[player.player_id][1:self.second + 1]:
                    if player.team_id != home:
                        cx, cy = divmod(index, GRID_Y)
                        index = (GRID_X - 1 - cx) * GRID_Y + (GRID_Y - 1 - cy)
                    counts[index] += 1
                grids[(player.player_id, "tracking")] = counts
                team_grid = grids.setdefault((player.team_id, "tracking"), [0] * (GRID_X * GRID_Y))
                for i, value in enumerate(counts):
                    team_grid[i] += value
        maps = []
        subjects = list(self.teams) + [p.player_id for p in self.match.roster]
        for subject in subjects:
            team = subject if subject in self.teams else team_of[subject]
            for kind in ("touches", "tracking", "received", "defensive"):
                if kind == "tracking" and not self.movement:
                    continue
                cells = grids.get((subject, kind), [0] * (GRID_X * GRID_Y))
                maps.append(Heatmap(subject_id=subject, team_id=team, kind=kind, total=sum(cells), cells=cells))
        return Heatmaps(grid_x=GRID_X, grid_y=GRID_Y, maps=maps)

    # ----------------------------------------------------------- goalkeeping
    def goalkeeping(self, shots) -> Goalkeeping:
        keepers, shooting = [], {}
        for team in self.teams:
            rival = self.other(team)
            on_target = [s for s in shots if s.team_id == rival and s.outcome in ("goal", "saved")]
            placed = [s for s in on_target if s.xgot is not None]
            goals = sum(s.outcome == "goal" for s in placed)
            keeper = next(p.player_id for p in self.match.roster if p.team_id == team and role(p.player_id) == "GK")
            xgot = sum(s.xgot for s in placed)
            keepers.append(KeeperRow(player_id=keeper, team_id=team, shots_on_target=len(on_target), saves=sum(s.outcome == "saved" for s in on_target),
                goals_conceded=sum(s.outcome == "goal" for s in on_target), xg_faced=round(sum(s.xg for s in on_target), 2),
                xgot_faced=round(xgot, 2), xg_prevented=round(xgot - goals, 2),
                save_pct=ratio(100 * sum(s.outcome == "saved" for s in on_target), len(on_target), 1)))
            own = [s for s in shots if s.team_id == team and s.xgot is not None]
            shooting[team] = TeamShooting(team_id=team, shots_on_target=len(own), xg_on_target=round(sum(s.xg for s in own), 2),
                xgot=round(sum(s.xgot for s in own), 2), placement_added=round(sum(s.xgot - s.xg for s in own), 2))
        return Goalkeeping(keepers=keepers, shooting=shooting)

    # ----------------------------------------------------------------- tempo
    def possessions(self) -> list[dict]:
        """Each observed possession: team, start/end time, start spot, ordered own on-ball events, open-play regain or not."""
        result, current, previous = [], None, None
        for record in self.ordered:
            e = record.payload
            if e.kind in ("POSSESSION", "STOPPAGE", "PERIOD_END", "PERIOD_START"):
                if current:
                    current["end"] = e.event_time_ms
                    result.append(current)
                    current = None
                if e.kind == "POSSESSION":
                    regain = previous is not None and previous.kind not in ("STOPPAGE", "PERIOD_START") and previous.team_id not in (None, e.team_id)
                    current = {"team": e.team_id, "id": e.possession_id, "start": e.event_time_ms, "spot": (e.detail.start.x, e.detail.start.y),
                               "events": [], "regain": regain}
            elif current and e.possession_id == current["id"] and e.team_id == current["team"] and e.kind in ("PASS", "CARRY", "SHOT"):
                current["events"].append(e)
            if e.kind != "TACKLE":
                previous = e
        if current:
            last = current["events"][-1].event_time_ms if current["events"] else current["start"]
            current["end"] = max(last, min(self.playhead, last + 2_000))
            result.append(current)
        return result

    def tempo_figures(self, team: str, keep=lambda t: True) -> TempoFigures:
        own = [p for p in self._possessions if p["team"] == team and keep(p["start"])]
        gained = seconds = 0.0
        entries, entry_passes = 0, []
        durations = {"defensive": [], "middle": [], "final": []}
        regain_times = []
        for p in own:
            duration = (p["end"] - p["start"]) / 1000
            x = p["spot"][0]
            durations[third(x)].append(duration)
            if duration <= 0:
                continue
            last_x, passes, entered = x, 0, x >= 66.67
            first_progressive = None
            for e in p["events"]:
                if e.kind == "PASS":
                    if not e.detail.completed:
                        break
                    passes += 1
                    last_x = e.detail.end.x
                    if first_progressive is None and progressive(e.detail.start, e.detail.end):
                        first_progressive = e.event_time_ms
                elif e.kind == "CARRY":
                    last_x = e.detail.end.x
                if not entered and last_x >= 66.67:
                    entered = True
                    entries += 1
                    entry_passes.append(passes)
            gained += (last_x - x) * X_M
            seconds += duration
            if p["regain"] and first_progressive is not None:
                regain_times.append((first_progressive - p["start"]) / 1000)
        passes = [e for p in own for e in p["events"] if e.kind == "PASS"]
        depth = [(e.detail.end.x - e.detail.start.x) * X_M for e in passes]
        forward = sum(d >= FORWARD_M for d in depth)
        backward = sum(d <= -FORWARD_M for d in depth)
        lateral = len(depth) - forward - backward
        return TempoFigures(possessions=len(own), vertical_mps=ratio(gained, seconds), final_third_entries=entries,
            passes_per_entry=ratio(sum(entry_passes), len(entry_passes), 1), forward_passes=forward, lateral_passes=lateral, backward_passes=backward,
            directness=ratio(forward, lateral + backward), possession_s={k: ratio(sum(v), len(v), 1) for k, v in durations.items()},
            progressive_passes=sum(1 for e in passes if e.detail.completed and progressive(e.detail.start, e.detail.end)),
            regain_to_progressive_s=r2(median(regain_times)) if regain_times else None)

    def tempo(self) -> dict[str, TeamTempo]:
        result = {}
        for team in self.teams:
            intervals = []
            for start in range(0, self.playhead, INTERVAL_MS):
                end = min(start + INTERVAL_MS, self.playhead)
                figures = self.tempo_figures(team, lambda t, a=start, b=end: a < t <= b or (a == 0 and t == 0))
                intervals.append(TempoInterval(start_ms=start, end_ms=end, vertical_mps=figures.vertical_mps, directness=figures.directness,
                                               passes_per_entry=figures.passes_per_entry))
            result[team] = TeamTempo(team_id=team, match=self.tempo_figures(team), intervals=intervals)
        return result

    # -------------------------------------------------------------- pressing
    def pressing_counts(self, team: str, keep=lambda t: True) -> tuple[int, int]:
        rival = self.other(team)
        passes = actions = 0
        for record in self.ordered:
            e = record.payload
            if not keep(e.event_time_ms):
                continue
            if e.kind == "PASS" and e.team_id == rival and e.detail.start.x < PPDA_ZONE_X:
                passes += 1
            elif e.kind == "TACKLE" and e.team_id == team and e.detail.position.x >= 100 - PPDA_ZONE_X:
                actions += 1
            elif e.kind == "POSSESSION" and e.team_id == team and record.event_id in self._interceptions and e.detail.start.x >= 100 - PPDA_ZONE_X:
                actions += 1
        return passes, actions

    def pressing(self) -> dict[str, Pressing]:
        result = {}
        for team in self.teams:
            passes, actions = self.pressing_counts(team)
            result[team] = Pressing(team_id=team, ppda=ratio(passes, actions, 1), opponent_passes=passes, defensive_actions=actions)
        return result

    # -------------------------------------------------------------- creation
    def creation(self, shots, quality, creating) -> tuple[dict[str, TeamCreation], list[PlayerCreation]]:
        players = {p.player_id: {"box": 0, "z14": 0, "kp": 0, "assists": 0, "xa": 0.0, "shots": 0, "xg": 0.0, "prog": 0, "sca": 0, "gca": 0}
                   for p in self.match.roster}
        teams = {team: {"box": 0, "entries": 0, "z14": 0, "z14_entries": 0, "kp": 0, "first_time": 0, "assists": 0, "xa": 0.0,
                        "types": {}, "origins": {"wide": 0, "central": 0},
                        "prog": 0, "sca": 0, "gca": 0, "sca_types": {}, "gca_types": {}} for team in self.teams}
        for a in creating:
            for row in (players[a.player_id], teams[a.team_id]):
                row["sca"] += 1
                row["gca"] += a.goal
            side = teams[a.team_id]
            side["sca_types"][a.kind] = side["sca_types"].get(a.kind, 0) + 1
            if a.goal:
                side["gca_types"][a.kind] = side["gca_types"].get(a.kind, 0) + 1
        for player, team, x, y, _t, _kind in self._touches:
            if in_box(x, y):
                players[player]["box"] += 1
                teams[team]["box"] += 1
            if in_zone14(x, y):
                players[player]["z14"] += 1
                teams[team]["z14"] += 1
        for record in self.ordered:
            e = record.payload
            if e.kind == "PASS" and e.detail.completed and progressive(e.detail.start, e.detail.end):
                players[e.player_id]["prog"] += 1
                teams[e.team_id]["prog"] += 1
            if e.kind == "CARRY" or (e.kind == "PASS" and e.detail.completed):
                a, b = e.detail.start, e.detail.end
                if in_box(b.x, b.y) and not in_box(a.x, a.y):
                    teams[e.team_id]["entries"] += 1
                if in_zone14(b.x, b.y) and not in_zone14(a.x, a.y):
                    teams[e.team_id]["z14_entries"] += 1
        for s in shots:
            players[s.player_id]["shots"] += 1
            players[s.player_id]["xg"] += s.xg
        for q in quality.values():
            if not q.passer_id:
                continue
            row, side = players[q.passer_id], teams[q.team_id]
            goal = q.outcome == "goal"
            row["kp"] += 1
            row["assists"] += goal
            row["xa"] += q.xg
            side["kp"] += 1
            side["assists"] += goal
            side["xa"] += q.xg
            side["first_time"] += q.first_time
            side["types"][q.key_pass_type] = side["types"].get(q.key_pass_type, 0) + 1
            side["origins"]["wide" if not 33.3 <= q.key_pass_start[1] <= 66.7 else "central"] += 1
        result = {}
        for team, row in teams.items():
            xg = sum(s.xg for s in shots if s.team_id == team)
            result[team] = TeamCreation(team_id=team, box_touches=row["box"], box_entries=row["entries"], zone14_touches=row["z14"],
                zone14_entries=row["z14_entries"], key_passes=row["kp"], first_time_key_passes=row["first_time"], assists=row["assists"], xa=round(row["xa"], 2),
                key_pass_types=dict(sorted(row["types"].items())), key_pass_origins=row["origins"], xg_per_box_touch=ratio(xg, row["box"], 3),
                progressive_passes=row["prog"], sca=row["sca"], gca=row["gca"], sca_types=dict(sorted(row["sca_types"].items())),
                gca_types=dict(sorted(row["gca_types"].items())))
        rows = [PlayerCreation(player_id=p.player_id, team_id=p.team_id, box_touches=players[p.player_id]["box"], zone14_touches=players[p.player_id]["z14"],
                key_passes=players[p.player_id]["kp"], assists=players[p.player_id]["assists"], xa=round(players[p.player_id]["xa"], 2),
                shots=players[p.player_id]["shots"], xg=round(players[p.player_id]["xg"], 2), progressive_passes=players[p.player_id]["prog"],
                sca=players[p.player_id]["sca"], gca=players[p.player_id]["gca"]) for p in self.match.roster]
        rows = [r for r in rows if r.box_touches or r.zone14_touches or r.key_passes or r.shots or r.sca or r.progressive_passes]
        rows.sort(key=lambda r: (-r.sca, -r.xa, -r.key_passes, -r.box_touches, r.player_id))
        return result, rows

    # --------------------------------------------------------------- packing
    def packing(self) -> tuple[dict[str, TeamPacking], list[PlayerPacking], list[PackingAction]]:
        home = self.teams[0]
        actions: list[PackingAction] = []
        attempts = {p.player_id: {"pass": 0, "carry": 0} for p in self.match.roster}
        for record in self.ordered:
            e = record.payload
            if e.kind not in ("PASS", "CARRY"):
                continue
            kind = e.kind.lower()
            attempts[e.player_id][kind] += 1
            snapshot = self.movement.snapshots.get(record.event_id) if self.movement else None
            if snapshot is None or (kind == "pass" and not e.detail.completed):
                continue
            a, b = e.detail.start.x, e.detail.end.x
            if b <= a:
                continue
            packed = defenders = 0
            for pid, (x, _y) in snapshot.items():
                if self.team_of[pid] == e.team_id or role(pid) == "GK":
                    continue
                depth = x if e.team_id == home else 100 - x
                if a < depth < b:
                    packed += 1
                    defenders += role(pid) in BACK_FOUR
            if packed:
                actions.append(PackingAction(event_ref=record.ref, time_ms=e.event_time_ms, team_id=e.team_id, player_id=e.player_id, action=kind,
                    packed=packed, defenders_packed=defenders, start={"x": e.detail.start.x, "y": e.detail.start.y},
                    end={"x": e.detail.end.x, "y": e.detail.end.y}))
        players = []
        for p in self.match.roster:
            own = [x for x in actions if x.player_id == p.player_id]
            by_pass = sum(x.packed for x in own if x.action == "pass")
            by_carry = sum(x.packed for x in own if x.action == "carry")
            tries = attempts[p.player_id]
            if not tries["pass"] and not tries["carry"]:
                continue
            players.append(PlayerPacking(player_id=p.player_id, team_id=p.team_id, passes=tries["pass"], packed_by_passes=by_pass,
                carries=tries["carry"], packed_by_carries=by_carry, passing_rate=ratio(by_pass, tries["pass"]),
                dribbling_rate=ratio(by_carry, tries["carry"]), defenders_packed=sum(x.defenders_packed for x in own)))
        players.sort(key=lambda r: (-(r.packed_by_passes + r.packed_by_carries), r.player_id))
        teams = {}
        for team in self.teams:
            rows = [r for r in players if r.team_id == team]
            own = [x for x in actions if x.team_id == team]
            passes, carries = sum(r.passes for r in rows), sum(r.carries for r in rows)
            by_pass, by_carry = sum(r.packed_by_passes for r in rows), sum(r.packed_by_carries for r in rows)
            teams[team] = TeamPacking(team_id=team, passes=passes, packed_by_passes=by_pass, carries=carries, packed_by_carries=by_carry,
                passing_rate=ratio(by_pass, passes), dribbling_rate=ratio(by_carry, carries),
                defenders_packed=sum(r.defenders_packed for r in rows), line_breaking=sum(x.packed >= LINE_BREAKING for x in own))
        top = sorted(actions, key=lambda x: (-x.packed, -x.defenders_packed, x.time_ms))[:TOP_PACKING]
        return teams, players, top
