"""Chance quality (xG) and a location value surface for possession value.

Both are transparent heuristics, not models fitted to shot data: the synthetic fixture
has no real shots to learn from. The coefficients were chosen so that familiar
reference shots land near textbook values (an open-play shot from the penalty spot is
about 0.27 xG, one from the six-yard line about 0.6, one from 30 m about 0.02). They
rank chances consistently within this sample; they are not calibrated probabilities.

All coordinates are team-relative: the shooting team attacks toward x = 100 and the
goal centre is (100, 50) on a nominal 105 x 68 m pitch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .ingest import canonical_order
from .models import EventEnvelope

X_M, Y_M = 1.05, .68
GOAL_HALF_WIDTH_M = 3.66
MAJOR_CHANCE_XG = .30

# Logistic coefficients. Distance in metres, goal-mouth angle in radians.
INTERCEPT, ANGLE_COEF, DISTANCE_COEF = -.6, 1.4, -.12
ASSIST_COEF = {"through_ball": .45, "cutback": .35, "pass": 0.0, "individual": -.1, "cross": -.35, "set_piece": -.25}
HEADER_COEF = -.9

DEFINITIONS = {
    "xg": "Expected goals: a heuristic probability (0–1) that a shot is scored, from distance to goal, the angle the goal mouth subtends, how the shot was set up and the body part. Coefficients are illustrative, not fitted to data.",
    "xg_against": "The xG of shots the opponent took.",
    "chance_type": f"Major when the shot's xG is at least {MAJOR_CHANCE_XG:.2f} (a chance a player would usually be expected to score), minor below that or when the box was entered without a shot.",
    "assist_type": "From the event before the shot in the same possession: corner (set piece), cross (from a wide channel of the final third into the box), cutback (from near the byline back toward goal), through ball (forward pass of at least 12 units ending centrally beyond x = 80), other pass, or individual (carry or no assist).",
    "possession_value": "Change in the location value surface caused by an action: value after minus value before. A lost ball scores minus the value it had; a shot scores its xG minus the value of where it was taken. Defensive actions are not valued.",
    "location_value": "Heuristic chance that a possession at this spot ends in a goal: a baseline plus the open-play xG of a shot from there, weighted by how often play near that depth reaches a shot. Analogous to expected threat (xT), not trained.",
}


def distance_m(x: float, y: float) -> float:
    return math.hypot((100 - x) * X_M, (y - 50) * Y_M)


def goal_angle(x: float, y: float) -> float:
    """The angle (radians) between the lines from the point to the two posts."""
    dx = max(.01, (100 - x) * X_M)
    dy = (y - 50) * Y_M
    a = math.atan2(GOAL_HALF_WIDTH_M - dy, dx)
    b = math.atan2(-GOAL_HALF_WIDTH_M - dy, dx)
    return abs(a - b)


def xg(x: float, y: float, assist: str = "pass", body_part: str | None = None) -> float:
    logit = INTERCEPT + ANGLE_COEF * goal_angle(x, y) + DISTANCE_COEF * distance_m(x, y) + ASSIST_COEF[assist]
    if body_part == "head":
        logit += HEADER_COEF
    return min(.95, max(.01, 1 / (1 + math.exp(-logit))))


def location_value(x: float, y: float) -> float:
    reach = 1 / (1 + math.exp(-(x - 78) / 5))
    return .006 + .75 * xg(x, y) * reach


def chance_type(value: float | None) -> str:
    return "major" if value is not None and value >= MAJOR_CHANCE_XG else "minor"


def in_box(x: float, y: float) -> bool:
    return x >= 83 and 20 <= y <= 80


def assist_type(previous, shooter: str, corner: bool) -> str:
    if corner:
        return "set_piece"
    if previous is None or previous.kind != "PASS" or not previous.detail.completed or previous.detail.recipient_id != shooter:
        return "individual"
    s, e = previous.detail.start, previous.detail.end
    if s.x >= 66.67 and (s.y < 20 or s.y > 80) and in_box(e.x, e.y):
        return "cross"
    if s.x >= 88 and e.x < s.x - 2 and in_box(e.x, e.y):
        return "cutback"
    if e.x - s.x >= 12 and e.x >= 80 and 25 <= e.y <= 75:
        return "through_ball"
    return "pass"


@dataclass
class ShotQuality:
    event_id: str
    ref: str
    time_ms: int
    team_id: str
    player_id: str
    outcome: str
    xg: float
    distance_m: float
    angle_deg: float
    assist: str
    body_part: str
    chance: str


def shot_quality(records: dict[str, EventEnvelope], ordered: list[EventEnvelope] | None = None) -> dict[str, ShotQuality]:
    """xG for every observed shot, keyed by event id."""
    ordered = ordered if ordered is not None else canonical_order(records)
    result: dict[str, ShotQuality] = {}
    last: dict[str, object] = {}
    corner_possessions: set[str] = set()
    for record in ordered:
        e = record.payload
        if e.kind == "POSSESSION" and e.detail.start.x >= 99:
            corner_possessions.add(e.possession_id)
        if e.kind == "SHOT":
            p = e.detail.position
            assist = assist_type(last.get(e.possession_id), e.player_id, e.possession_id in corner_possessions)
            body = e.detail.body_part or "right_foot"
            value = round(xg(p.x, p.y, assist, body), 3)
            result[record.event_id] = ShotQuality(record.event_id, record.ref, e.event_time_ms, e.team_id, e.player_id, e.detail.outcome,
                value, round(distance_m(p.x, p.y), 1), round(math.degrees(goal_angle(p.x, p.y)), 1), assist, body, chance_type(value))
        if e.kind in ("PASS", "CARRY", "SHOT") and e.possession_id:
            last[e.possession_id] = e
    return result
