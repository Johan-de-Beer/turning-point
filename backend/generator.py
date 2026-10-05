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
        "match_id": "tp_demo_01", "seed": seed, "fixture_version": "synthetic_v1",
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

    def point(self, x: float, y: float = 50) -> dict:
        return {"x": round(x, 2), "y": round(y, 2)}

    def actor(self, team: str, forward: bool = False) -> str:
        return f"{team}_{self.rng.choice([9, 10, 11] if forward else [6, 7, 8, 9, 10]):02d}"

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
        self.possession += 1
        self.owner, self.live = team, True
        self.emit(t, "POSSESSION", team, {"start": self.point(34 + self.rng.randrange(20), 35 + self.rng.randrange(30))})

    def pass_ball(self, t: int, x1: float, x2: float, completed: bool = True, y2: float = 50):
        assert self.live and self.owner
        actor = self.actor(self.owner)
        recipients = [p.player_id for p in self.match.roster if p.team_id == self.owner and p.player_id != actor]
        self.emit(t, "PASS", self.owner, {"recipient_id": self.rng.choice(recipients), "completed": completed,
                  "start": self.point(x1, 40 + self.rng.randrange(20)), "end": self.point(x2, y2)}, actor)

    def shoot(self, t: int, outcome: str):
        assert self.live and self.owner
        self.emit(t, "SHOT", self.owner, {"position": self.point(82 + self.rng.randrange(10), 30 + self.rng.randrange(40)), "outcome": outcome}, self.actor(self.owner, True))

    def stop(self, t: int, reason: str):
        self.emit(t, "STOPPAGE", detail={"reason": reason})
        self.live, self.owner = False, None

    def block(self, start: int, length: int, pattern: str, dominant: str = "harbor"):
        opponent = "vale" if dominant == "harbor" else "harbor"
        if pattern == "pressure":
            for t in range(start, start + length, 40_000):
                self.possess(t, dominant)
                self.pass_ball(t + 4_000, 59, 74)
                self.emit(t + 8_000, "CARRY", dominant, {"start": self.point(60, 65), "end": self.point(86, 65)})
                self.shoot(t + 14_000, self.rng.choice(["saved", "blocked", "off_target"]))
                self.pass_ball(t + 24_000, 74, 80)
                self.possess(t + 30_000, opponent)
                self.pass_ball(t + 35_000, 35, 47)
        elif pattern == "sterile":
            for t in range(start, start + length, 40_000):
                self.possess(t, dominant)
                for dt in (3, 7, 11, 15, 19, 23):
                    self.pass_ball(t + dt * 1000, 42 + self.rng.randrange(15), 42 + self.rng.randrange(15))
                self.possess(t + 30_000, opponent)
                self.pass_ball(t + 35_000, 36, 48)
        elif pattern == "end_to_end":
            for t in range(start, start + length, 40_000):
                self.possess(t, dominant)
                self.pass_ball(t + 4_000, 58, 78)
                self.shoot(t + 12_000, self.rng.choice(["saved", "blocked", "off_target"]))
                self.possess(t + 20_000, opponent)
                self.pass_ball(t + 24_000, 61, 82)
                self.shoot(t + 32_000, self.rng.choice(["saved", "blocked", "off_target"]))
        else:
            for t in range(start, start + length, 60_000):
                self.possess(t, dominant)
                self.pass_ball(t + 7_000, 40, 53)
                self.pass_ball(t + 18_000, 56, 63, completed=self.rng.random() > .12)
                self.possess(t + 30_000, opponent)
                self.pass_ball(t + 37_000, 40, 55)
                # A sparse shot is insufficient to create an end-to-end episode.
                if (t // 60_000) % 5 == 0:
                    self.shoot(t + 48_000, "off_target")
                else:
                    self.pass_ball(t + 48_000, 53, 61)

    def goal_minute(self, start: int, team: str):
        self.possess(start, team)
        self.pass_ball(start + 8_000, 64, 87)
        self.shoot(start + 15_000, "goal")
        self.stop(start + 16_000, "goal")
        self.possess(start + 35_000, "vale" if team == "harbor" else "harbor")
        self.pass_ball(start + 44_000, 35, 47)

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
        return self.events


def generate_fixture(seed: int = 24017, correction: bool = False) -> tuple[Match, list[EventEnvelope]]:
    generator = Generator(seed)
    events = generator.generate()
    if correction:
        original = next(e for e in events if e.payload.kind == "SHOT" and e.payload.detail.outcome == "goal")
        revised = original.payload.model_dump()
        revised["detail"]["outcome"] = "saved"
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
