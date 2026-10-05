"""Server-only seeded football state machine. Macro phases never leave this module.

Coordinates describe discrete events, not player tracking. No measured distances or
expected-goals model exists. The fictional adults and original assets are synthetic.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from .models import EventEnvelope, Match, PERIOD_MS

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "server_data" / "fixtures" / "tp_demo_01.json"


def fixture_match(seed: int = 24017) -> Match:
    names = {
        "harbor": ["Milo Arden", "Jules Carden", "Noah Fen", "Eli Rowan", "Theo Vale", "Leon Reed", "Asher Pike", "Rafi Moss", "Callum Wren", "Dario Finch", "Kai Lorne"],
        "vale": ["Tomas Hale", "Oren Clay", "Luca Briar", "Niko Ash", "Finn Alder", "Emil Stone", "Sami North", "Ivo Brook", "Jasper Dale", "Ruben Hart", "Felix Cove"],
    }
    return Match.model_validate({
        "match_id": "tp_demo_01", "seed": seed, "fixture_version": "synthetic_v2",
        "home": {"team_id": "harbor", "display_name": "Harbor Athletic", "short_name": "HBR", "color": "#38BDF8"},
        "away": {"team_id": "vale", "display_name": "Vale United", "short_name": "VAL", "color": "#FBBF24"},
        "roster": [{"player_id": f"{team}_{i:02d}", "team_id": team, "display_name": name,
                    "shirt_number": i, "position": "GK" if i == 1 else "DEF" if i <= 5 else "MID" if i <= 8 else "FWD"}
                   for team, roster in names.items() for i, name in enumerate(roster, 1)],
    })


class Generator:
    def __init__(self, seed: int):
        self.match = fixture_match(seed)
        self.rng = random.Random(seed)
        self.events: list[EventEnvelope] = []
        self.seq = 0
        self.possession = 0
        self.owner: str | None = None
        self.live = False
        self.period = 1
        self.ball: dict | None = None
        self.holder: str | None = None
        self.last_stoppage: str | None = None

    def point(self, x: float, y: float = 50) -> dict:
        return {"x": round(x, 2), "y": round(y, 2)}

    def actor(self, team: str, point: dict | None = None, exclude: str | None = None) -> str:
        x = point["x"] if point else 50
        numbers = [1] if x < 18 else [2, 3, 4, 5] if x < 38 else [6, 7, 8] if x < 72 else [9, 10, 11]
        eligible = [f"{team}_{i:02d}" for i in numbers if f"{team}_{i:02d}" != exclude]
        if not eligible:
            eligible = [f"{team}_{i:02d}" for i in [2, 3, 4, 5] if f"{team}_{i:02d}" != exclude]
        return self.rng.choice(eligible)

    def destination(self, low_x: float, high_x: float, low_y: float = 20, high_y: float = 80) -> dict:
        return self.point(self.rng.uniform(low_x, high_x), self.rng.uniform(low_y, high_y))

    def emit(self, time_ms: int, kind: str, team: str | None = None, detail: dict | None = None, actor: str | None = None):
        self.seq += 1
        marker = kind in ("PERIOD_START", "PERIOD_END", "STOPPAGE")
        self.events.append(EventEnvelope.model_validate({
            "delivery_seq": self.seq, "available_at_ms": time_ms, "event_id": f"evt_{self.seq:05d}", "revision": 1,
            "operation": "upsert", "payload": {"match_id": self.match.match_id, "event_time_ms": time_ms,
            "period": self.period, "kind": kind, "team_id": team, "player_id": None if marker else actor or self.actor(team),
            "possession_id": None if marker else f"pos_{self.possession:05d}", "detail": detail or {}},
        }))

    def possess(self, t: int, team: str):
        if self.live and self.ball:
            # Invert both axes when possession changes: the physical ball stays
            # at the same location despite the team's attacking coordinate frame.
            start = self.ball if team == self.owner else self.point(100 - self.ball["x"], 100 - self.ball["y"])
        elif self.last_stoppage == "ball_out":
            start = self.destination(6, 14, 38, 62)  # recorded goal-kick restart
        else:
            start = self.point(50, 50)  # period start or restart after a goal
        self.possession += 1
        self.owner, self.live = team, True
        self.ball, self.holder, self.last_stoppage = start, self.actor(team, start), None
        self.emit(t, "POSSESSION", team, {"start": start}, self.holder)

    def pass_ball(self, t: int, end: dict, completed: bool = True):
        assert self.live and self.owner and self.ball and self.holder
        recipient = self.actor(self.owner, end, exclude=self.holder)
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
        self.ball = end

    def shoot(self, t: int, outcome: str):
        assert self.live and self.owner and self.ball and self.holder
        if outcome == "goal":
            target = self.destination(100, 100, 46, 54)
        elif outcome == "saved":
            target = self.destination(97, 99, 45, 55)
        elif outcome == "blocked":
            target = self.point(min(95, self.ball["x"] + self.rng.uniform(3, 8)),
                                min(85, max(15, self.ball["y"] + self.rng.uniform(-6, 6))))
        else:
            target = self.destination(100, 100, 22, 39) if self.rng.random() < .5 else self.destination(100, 100, 61, 78)
        self.emit(t, "SHOT", self.owner, {"position": self.ball, "target": target, "outcome": outcome}, self.holder)
        self.ball = target

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
                self.shoot(t + 14_000, self.rng.choice(["saved", "blocked"]))
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
                self.possess(t, dominant)
                self.pass_ball(t + 7_000, self.destination(43, 57, 14, 86))
                self.pass_ball(t + 18_000, self.destination(54, 65, 20, 80), completed=self.rng.random() > .12)
                self.possess(t + 30_000, opponent)
                self.pass_ball(t + 37_000, self.destination(44, 61, 14, 86))
                # A sparse shot is insufficient to create an end-to-end episode.
                if (t // 60_000) % 5 == 0:
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
