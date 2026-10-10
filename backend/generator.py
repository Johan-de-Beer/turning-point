"""Server-only seeded football state machine. Macro phases never leave this module.

Coordinates describe discrete events, not player tracking. No measured distances or
expected-goals model exists. The fictional adults and original assets are synthetic.

Tactical additions (corners, presses that force a recycle to the keeper, short
goal-kick build-up) draw from a separate seeded stream so the open-play stream
keeps its shape. Their server-only plans feed the synthetic tracking layer.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from .models import EventEnvelope, Match, PERIOD_MS
from .tactical_profiles import CORNER_TAKERS, TARGET_MEN, foot, other, player_for, position, tendencies

TACTICAL_SALT = 0x7AC71C
DUEL_SALT = 0xD0E1
PLACEMENT_SALT = 0x5A7E

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "server_data" / "fixtures" / "tp_demo_01.json"


def fixture_match(seed: int = 24017) -> Match:
    names = {
        "harbor": ["Milo Arden", "Jules Carden", "Noah Fen", "Eli Rowan", "Theo Vale", "Leon Reed", "Asher Pike", "Rafi Moss", "Callum Wren", "Dario Finch", "Kai Lorne"],
        "vale": ["Tomas Hale", "Oren Clay", "Luca Briar", "Niko Ash", "Finn Alder", "Emil Stone", "Sami North", "Ivo Brook", "Jasper Dale", "Ruben Hart", "Felix Cove"],
    }
    return Match.model_validate({
        "match_id": "tp_demo_01", "seed": seed, "fixture_version": "synthetic_v4",
        "home": {"team_id": "harbor", "display_name": "Harbor Athletic", "short_name": "HBR", "color": "#38BDF8"},
        "away": {"team_id": "vale", "display_name": "Vale United", "short_name": "VAL", "color": "#FBBF24"},
        "roster": [{"player_id": f"{team}_{i:02d}", "team_id": team, "display_name": name,
                    "shirt_number": i, "position": "GK" if i == 1 else "DEF" if i <= 5 else "MID" if i <= 8 else "FWD",
                    "role": position(f"{team}_{i:02d}")}
                   for team, roster in names.items() for i, name in enumerate(roster, 1)],
    })


class Generator:
    def __init__(self, seed: int):
        self.match = fixture_match(seed)
        self.rng = random.Random(seed)
        self.events: list[EventEnvelope] = []
        self.seq = 0
        # Duels carry their own id series so adding them never renumbers the other events
        # (the synthetic tracking is seeded per event id).
        self.ids = {"evt": 0, "duel": 0}
        self.possession = 0
        self.owner: str | None = None
        self.live = False
        self.period = 1
        self.ball: dict | None = None
        self.holder: str | None = None
        self.last_stoppage: str | None = None
        # Tactical decisions use their own stream; ``plans`` stays server-side.
        self.tactics = random.Random(seed ^ TACTICAL_SALT)
        self.plans: dict[str, dict] = {}
        self.corner_flag: dict | None = None
        self.corner_count = {"harbor": 0, "vale": 0}
        # Duels draw from a third stream so the open-play and tactical streams keep their shape.
        self.duels = random.Random(seed ^ DUEL_SALT)
        # Shot placement in the goal mouth draws from a fourth stream for the same reason.
        self.placements = random.Random(seed ^ PLACEMENT_SALT)
        self.header_next = False

    def point(self, x: float, y: float = 50) -> dict:
        return {"x": round(x, 2), "y": round(y, 2)}

    def actor(self, team: str, point: dict | None = None, exclude: str | None = None) -> str:
        x = point["x"] if point else 50
        numbers = [1] if x < 18 else [2, 3, 4, 5] if x < 38 else [6, 7, 8] if x < 72 else [9, 10, 11]
        eligible = [f"{team}_{i:02d}" for i in numbers if f"{team}_{i:02d}" != exclude]
        if not eligible:
            eligible = [f"{team}_{i:02d}" for i in [2, 3, 4, 5] if f"{team}_{i:02d}" != exclude]
        return self.rng.choice(eligible)

    def destination(self, low_x: float, high_x: float, low_y: float = 20, high_y: float = 80, rng: random.Random | None = None) -> dict:
        rng = rng or self.rng
        return self.point(rng.uniform(low_x, high_x), rng.uniform(low_y, high_y))

    def emit(self, time_ms: int, kind: str, team: str | None = None, detail: dict | None = None, actor: str | None = None) -> str:
        self.seq += 1
        series = "duel" if kind == "TACKLE" else "evt"
        self.ids[series] += 1
        event_id = f"evt_{self.ids[series]:05d}" if series == "evt" else f"duel_{self.ids[series]:04d}"
        marker = kind in ("PERIOD_START", "PERIOD_END", "STOPPAGE")
        self.events.append(EventEnvelope.model_validate({
            "delivery_seq": self.seq, "available_at_ms": time_ms, "event_id": event_id, "revision": 1,
            "operation": "upsert", "payload": {"match_id": self.match.match_id, "event_time_ms": time_ms,
            "period": self.period, "kind": kind, "team_id": team, "player_id": None if marker else actor or self.actor(team),
            "possession_id": None if marker else f"pos_{self.possession:05d}", "detail": detail or {}},
        }))
        return event_id

    def challenger(self, team: str, point: dict) -> str:
        """The defending player nearest the line of a duel, drawn from the duel stream."""
        x = point["x"]
        roles = ("RCB", "LCB", "RB", "LB") if x < 38 else ("DM", "RCM", "LCM") if x < 72 else ("ST", "RW", "LW", "RCM")
        return player_for(team, self.duels.choice(roles))

    def mirror(self, point: dict) -> dict:
        return self.point(100 - point["x"], 100 - point["y"])

    def duel(self, t: int, defending: str, where: dict, won: bool, contest: str = "ground", defender: str | None = None):
        """A contest inside the attacking team's possession; ``where`` is in the attackers' frame."""
        spot = self.mirror(where)
        self.emit(t, "TACKLE", defending, {"position": spot, "successful": won, "contest": contest},
                  defender or self.challenger(defending, spot))

    def possess(self, t: int, team: str, holder: str | None = None) -> str:
        if self.live and self.ball and self.owner and self.owner != team and self.holder:
            # The new side won the ball off a player in possession: a ground duel.
            self.duel(t - 400, team, self.ball, True)
        if self.live and self.ball:
            # Invert both axes when possession changes: the physical ball stays
            # at the same location despite the team's attacking coordinate frame.
            start = self.ball if team == self.owner else self.point(100 - self.ball["x"], 100 - self.ball["y"])
        elif self.last_stoppage == "corner" and self.corner_flag:
            start = self.corner_flag
        elif self.last_stoppage == "ball_out":
            start = self.destination(6, 14, 38, 62)  # recorded goal-kick restart
        else:
            start = self.point(50, 50)  # period start or restart after a goal
        self.possession += 1
        self.header_next = False
        self.owner, self.live = team, True
        restart = self.last_stoppage
        self.ball, self.holder, self.last_stoppage = start, holder or self.actor(team, start), None
        event_id = self.emit(t, "POSSESSION", team, {"start": start}, self.holder)
        self.plan_press(event_id, team, start, restart)
        return event_id

    def plan_press(self, event_id: str, team: str, start: dict, restart: str | None):
        """Decide (server-only) whether the opponent presses a possession won or
        restarted in the team's own half. Centre kick-offs and corners are excluded."""
        if start["x"] >= 55 or restart in ("goal", "interval", "corner") or (start["x"] == 50 and start["y"] == 50):
            return
        press = tendencies(other(team))["press"]
        chance = press["base"] + (press["target_bonus"] if self.holder == press["target"] else 0)
        self.plans[event_id] = {"type": "possession", "pressed": self.tactics.random() < chance}

    def pass_to(self, t: int, recipient: str, end: dict, completed: bool = True) -> str:
        """A scripted pass with an explicit recipient, outside the open-play stream."""
        assert self.live and self.owner and self.ball and self.holder
        self.header_next = False
        event_id = self.emit(t, "PASS", self.owner, {"recipient_id": recipient, "completed": completed,
                             "start": self.ball, "end": end}, self.holder)
        self.ball = end
        self.holder = recipient if completed else None
        return event_id

    def recycle_to_keeper(self, t: int) -> int:
        """A pressed team plays back to its goalkeeper; returns the keeper's receive time."""
        team = self.owner
        keeper = player_for(team, "GK")
        if self.holder == keeper:
            return t
        rng = self.tactics
        if self.ball["x"] > 30 or self.holder.endswith(("_06", "_07", "_08", "_09", "_10", "_11")):
            defender = rng.choice([p for p in (player_for(team, "RCB"), player_for(team, "LCB")) if p != self.holder])
            self.pass_to(t + 1_800, defender, self.destination(17, 25, 30, 70, rng))
            t += 1_800
        self.pass_to(t + 1_700, keeper, self.destination(4, 8, 40, 60, rng))
        return t + 1_700

    def short_build_up(self, t: int):
        """Goalkeeper plays short to a centre-back split wide in the box."""
        team = self.owner
        rng = self.tactics
        side = rng.choice(("RCB", "LCB"))
        y = rng.uniform(64, 80) if side == "RCB" else rng.uniform(20, 36)
        self.pass_to(t, player_for(team, side), self.point(rng.uniform(15, 22), y))

    def pressed_and_forced_back(self, possession_event: str) -> bool:
        plan = self.plans.get(possession_event)
        return bool(plan and plan["pressed"] and self.tactics.random() < tendencies(other(self.owner))["press"]["force_back"])

    def corner(self, t: int, team: str) -> bool:
        """A corner: stoppage, the taker's restart and the delivery. Returns whether
        the attacking team won first contact."""
        rng = self.tactics
        self.stop(t, "corner")
        side = "left" if self.corner_count[team] % 2 == 0 else "right"
        self.corner_count[team] += 1
        self.corner_flag = self.point(99.5, 0.5 if side == "left" else 99.5)
        taker = CORNER_TAKERS[team][side]
        self.possess(t + 3_000, team, holder=taker)
        profile = tendencies(team)["corner"]
        target = rng.choice(TARGET_MEN[team])
        near = 42 if side == "left" else 58
        zone, centre = rng.choice([("near_post", (95.0, near)), ("penalty_spot", (89.5, 50.0)), ("far_post", (94.5, 100 - near))])
        sd = profile["accuracy"][taker]
        landing = self.point(min(99.0, max(83.0, centre[0] + rng.gauss(0, sd))), min(80.0, max(20.0, centre[1] + rng.gauss(0, sd * 1.4))))
        miss = ((landing["x"] - centre[0]) ** 2 + ((landing["y"] - centre[1]) * .68 / 1.05) ** 2) ** .5
        won = rng.random() < (.6 if miss < 2.5 else .3)
        delivery = self.pass_to(t + 5_000, target, landing, completed=won)
        self.plans[delivery] = {"type": "corner", "side": side, "target_id": target, "zone": zone}
        # The aerial contest at the delivery: the first defender to it challenges the target.
        self.duel(t + 5_700, other(team), landing, not won, "aerial", player_for(other(team), self.duels.choice(("RCB", "LCB"))))
        self.header_next = won
        return won

    def clear_corner(self, t: int, defending: str, attacking: str | None):
        """The defending team clears a lost delivery; optionally the attackers recover the second ball."""
        rng = self.tactics
        self.possess(t, defending, holder=player_for(defending, rng.choice(("RCB", "LCB"))))
        self.pass_to(t + 800, player_for(defending, rng.choice(("ST", "RW", "LW"))), self.destination(28, 42, 20, 80, rng), completed=attacking is None)
        if attacking:
            self.possess(t + 2_200, attacking, holder=player_for(attacking, rng.choice(("RCM", "DM", "LCM"))))

    def pass_ball(self, t: int, end: dict, completed: bool = True):
        assert self.live and self.owner and self.ball and self.holder
        recipient = self.actor(self.owner, end, exclude=self.holder)
        self.header_next = False
        self.emit(t, "PASS", self.owner, {"recipient_id": recipient, "completed": completed,
                  "start": self.ball, "end": end}, self.holder)
        self.ball = end
        self.holder = recipient if completed else None

    def carry(self, t: int, end: dict):
        assert self.live and self.owner and self.ball and self.holder
        # A carry changes channel gradually; broad cross-field switches are
        # passes. Keep the fictional event spacing plausible for a ball holder.
        end = self.point(end["x"], min(self.ball["y"] + 18, max(self.ball["y"] - 18, end["y"])))
        self.emit(t, "CARRY", self.owner, {"start": self.ball, "end": end}, self.holder)
        if self.duels.random() < .45:
            # The carrier rides a challenge on the way: a ground duel the defender loses.
            midway = self.point((self.ball["x"] + end["x"]) / 2, (self.ball["y"] + end["y"]) / 2)
            self.duel(t + 800, other(self.owner), midway, False)
        self.ball = end

    def shoot(self, t: int, outcome: str, rng: random.Random | None = None):
        assert self.live and self.owner and self.ball and self.holder
        rng = rng or self.rng
        if outcome == "goal":
            target = self.destination(100, 100, 46, 54, rng)
        elif outcome == "saved":
            target = self.destination(97, 99, 45, 55, rng)
        elif outcome == "blocked":
            target = self.point(min(95, self.ball["x"] + rng.uniform(3, 8)),
                                min(85, max(15, self.ball["y"] + rng.uniform(-6, 6))))
        else:
            target = self.destination(100, 100, 22, 39, rng) if rng.random() < .5 else self.destination(100, 100, 61, 78, rng)
        body = "head" if self.header_next else f"{foot(self.holder)}_foot"
        self.header_next = False
        detail = {"position": self.ball, "target": target, "outcome": outcome, "body_part": body}
        if outcome in ("goal", "saved"):
            detail["placement"] = self.placement(target, outcome, body)
        self.emit(t, "SHOT", self.owner, detail, self.holder)
        self.ball = target

    def placement(self, target: dict, outcome: str, body: str) -> dict:
        """Height and pace of an on-target shot; the lateral spot follows the recorded target.
        Goals mostly find the corners. Saves are hard (corner, hit hard) at the rate the
        goalkeeper's hidden profile plants, otherwise near the keeper and softer."""
        rng = self.placements
        keeper = tendencies(other(self.owner))["goalkeeping"]
        hard = rng.random() < (.8 if outcome == "goal" else keeper["hard_save_rate"])
        if hard:
            z = rng.uniform(1.75, 2.35) if rng.random() < .55 else rng.uniform(.05, .45)
            speed = rng.uniform(24, 31)
        else:
            z = rng.uniform(.5, 1.6)
            speed = rng.uniform(13, 21)
        if body == "head":
            speed *= .6
        y = (target["y"] - 50) * .68
        if hard and outcome == "saved":
            # A hard save is also wide of the keeper.
            y = (1 if y >= 0 else -1) * rng.uniform(2.2, 3.4)
        return {"y_m": round(max(-3.6, min(3.6, y)), 2), "z_m": round(z, 2), "speed_mps": round(speed, 1)}

    def stop(self, t: int, reason: str):
        self.emit(t, "STOPPAGE", detail={"reason": reason})
        self.live, self.owner = False, None
        self.ball, self.holder, self.last_stoppage = None, None, reason

    def block(self, start: int, length: int, pattern: str, dominant: str = "harbor"):
        opponent = "vale" if dominant == "harbor" else "harbor"
        if pattern == "pressure":
            for t in range(start, start + length, 40_000):
                self.possess(t, dominant)
                self.pass_ball(t + 4_000, self.destination(70, 78, 18, 82))
                # Recycle the ball before the second forward entry; the carry
                # now starts where the preceding back-pass actually finished.
                self.pass_ball(t + 6_000, self.destination(56, 64, 25, 75))
                self.carry(t + 12_000, self.destination(84, 91, 24, 76))
                outcome = self.rng.choice(["saved", "blocked"])
                self.shoot(t + 14_000, outcome)
                # A parried shot goes behind for a corner; a lost delivery is cleared
                # and the pressing side recovers the second ball.
                if outcome == "saved" and not self.corner(t + 15_000, dominant):
                    self.clear_corner(t + 21_000, opponent, dominant)
                self.pass_ball(t + 24_000, self.destination(72, 81, 15, 85))
                self.possess(t + 30_000, opponent)
                self.pass_ball(t + 35_000, self.destination(43, 55, 22, 78))
        elif pattern == "sterile":
            for t in range(start, start + length, 40_000):
                self.possess(t, dominant)
                for dt in (3, 7, 11, 15, 19, 23):
                    self.pass_ball(t + dt * 1000, self.destination(40, 62, 18, 82))
                self.possess(t + 30_000, opponent)
                self.pass_ball(t + 35_000, self.destination(42, 56, 22, 78))
        elif pattern == "end_to_end":
            for t in range(start, start + length, 40_000):
                self.possess(t, dominant)
                self.pass_ball(t + 4_000, self.destination(70, 81, 20, 80))
                self.carry(t + 8_000, self.destination(84, 92, 28, 72))
                self.shoot(t + 12_000, self.rng.choice(["saved", "blocked"]))
                self.possess(t + 20_000, opponent)
                self.pass_ball(t + 24_000, self.destination(72, 82, 20, 80))
                self.carry(t + 28_000, self.destination(84, 92, 28, 72))
                self.shoot(t + 32_000, self.rng.choice(["saved", "blocked"]))
        else:
            for t in range(start, start + length, 60_000):
                goal_kick = self.last_stoppage == "ball_out"
                possession = self.possess(t, dominant)
                if goal_kick and self.tactics.random() < tendencies(dominant)["short_build_up"]:
                    self.short_build_up(t + 3_000)
                elif self.pressed_and_forced_back(possession):
                    self.recycle_to_keeper(t)
                    self.short_build_up(t + 5_200)
                self.pass_ball(t + 7_000, self.destination(43, 57, 14, 86))
                self.pass_ball(t + 18_000, self.destination(54, 65, 20, 80), completed=self.rng.random() > .12)
                possession = self.possess(t + 30_000, opponent)
                if self.pressed_and_forced_back(possession):
                    self.recycle_to_keeper(t + 30_000)
                self.pass_ball(t + 37_000, self.destination(44, 61, 14, 86))
                # A sparse shot is insufficient to create an end-to-end episode.
                if (t // 60_000) % 10 == 5:
                    # A parried effort becomes a corner. The discarded draw keeps the
                    # seeded open-play stream aligned with an off-target shot.
                    self.carry(t + 43_000, self.destination(80, 89, 30, 70))
                    self.rng.random()
                    self.shoot(t + 48_000, "saved")
                    if self.corner(t + 49_000, opponent):
                        outcome = self.tactics.choice(["saved", "blocked", "off_target"])
                        self.shoot(t + 55_200, outcome, self.tactics)
                        if outcome == "off_target":
                            self.stop(t + 56_000, "ball_out")
                    else:
                        self.clear_corner(t + 55_000, dominant, None)
                elif (t // 60_000) % 5 == 0:
                    self.carry(t + 43_000, self.destination(80, 89, 30, 70))
                    self.shoot(t + 48_000, "off_target")
                    self.stop(t + 49_000, "ball_out")
                else:
                    self.pass_ball(t + 48_000, self.destination(52, 64, 20, 80))

    def goal_minute(self, start: int, team: str):
        self.possess(start, team)
        self.pass_ball(start + 8_000, self.destination(84, 92, 34, 66))
        self.shoot(start + 15_000, "goal")
        self.stop(start + 16_000, "goal")
        self.possess(start + 35_000, "vale" if team == "harbor" else "harbor")
        self.pass_ball(start + 44_000, self.destination(40, 55, 20, 80))

    def generate(self) -> list[EventEnvelope]:
        # Server-only phase plan. Production clients receive eligible envelopes only.
        phases = {
            1: [(0, 3, "neutral"), (3, 7, "pressure"), (7, 10, "neutral"), (10, 11, "goal_harbor"),
                (11, 12, "neutral"), (12, 18, "sterile"), (18, 21, "neutral"), (21, 25, "end_to_end"),
                (25, 42, "neutral"), (42, 43, "goal_vale"), (43, 45, "neutral")],
            2: [(0, 7, "neutral"), (7, 11, "pressure"), (11, 13, "neutral"), (13, 14, "goal_harbor"),
                (14, 18, "neutral"), (18, 24, "sterile"), (24, 29, "neutral"), (29, 33, "end_to_end"), (33, 45, "neutral")],
        }
        for period in (1, 2):
            self.period = period
            origin = (period - 1) * PERIOD_MS
            self.emit(origin, "PERIOD_START")
            for start, end, pattern in phases[period]:
                if pattern.startswith("goal_"):
                    self.goal_minute(origin + start * 60_000, pattern[5:])
                else:
                    dominant = "vale" if period == 2 and pattern == "pressure" else "harbor"
                    self.block(origin + start * 60_000, (end - start) * 60_000, pattern, dominant)
            self.emit(origin + PERIOD_MS, "PERIOD_END")
            self.live, self.owner = False, None
            self.ball, self.holder, self.last_stoppage = None, None, None
        return self.events


def generate_plans(seed: int = 24017) -> dict[str, dict]:
    """Server-only tactical plans keyed by event id, for the synthetic tracking layer."""
    generator = Generator(seed)
    generator.generate()
    return generator.plans


def generate_fixture(seed: int = 24017, correction: bool = False) -> tuple[Match, list[EventEnvelope]]:
    generator = Generator(seed)
    events = generator.generate()
    if correction:
        original = next(e for e in events if e.payload.kind == "SHOT" and e.payload.detail.outcome == "goal")
        revised = original.payload.model_dump()
        revised["detail"]["outcome"] = "saved"
        revised["detail"]["target"]["x"] = 98.0
        events.append(EventEnvelope.model_validate({"delivery_seq": len(events) + 1,
            "available_at_ms": original.available_at_ms + 90_000, "event_id": original.event_id,
            "revision": 2, "operation": "upsert", "payload": revised}))
    from .ingest import validate_fixture
    validate_fixture(generator.match, events)
    return generator.match, sorted(events, key=lambda e: (e.available_at_ms, e.delivery_seq))


def write_fixture(path: Path = FIXTURE_PATH):
    match, events = generate_fixture()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"match": match.model_dump(), "events": [e.model_dump() for e in events]}, indent=2), encoding="utf-8")


def load_fixture(correction: bool = False) -> tuple[Match, list[EventEnvelope]]:
    if correction:
        return generate_fixture(correction=True)
    if not FIXTURE_PATH.exists():
        write_fixture()
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    match = Match.model_validate(raw["match"])
    events = [EventEnvelope.model_validate(e) for e in raw["events"]]
    from .ingest import validate_fixture
    validate_fixture(match, events)
    return match, sorted(events, key=lambda e: (e.available_at_ms, e.delivery_seq))
