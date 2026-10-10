"""Chance quality (xG and post-shot xGoT) and a location value surface for possession value.

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
# Post-shot (xGoT) coefficients: pre-shot log-odds weight, placement reach, pace per m/s above 20.
XGOT_INTERCEPT, XGOT_PRE_COEF, XGOT_REACH_COEF, XGOT_SPEED_COEF = -2.4, .5, 2.0, .1
KEEPER_HEIGHT_M, CROSSBAR_M = 1.0, 2.44

DEFINITIONS = {
    "xg": "Expected goals: a heuristic probability (0–1) that a shot is scored, from distance to goal, the angle the goal mouth subtends, how the shot was set up and the body part. Coefficients are illustrative, not fitted to data.",
    "xg_against": "The xG of shots the opponent took.",
    "chance_type": f"Major when the shot's xG is at least {MAJOR_CHANCE_XG:.2f} (a chance a player would usually be expected to score), minor below that or when the box was entered without a shot.",
    "assist_type": "From the event before the shot in the same possession: corner (set piece), cross (from a wide channel of the final third into the box), cutback (from near the byline back toward goal), through ball (forward pass of at least 12 units ending centrally beyond x = 80), other pass, or individual (carry or no assist).",
    "xgot": "Expected goals on target (post-shot xG): a heuristic probability that an on-target shot beats an average keeper, from its pre-shot xG plus where it crossed the goal line (how far from a keeper standing centrally) and how hard it was hit. Off-target and blocked shots have none. Coefficients are illustrative.",
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


def placement_reach(y_m: float, z_m: float) -> float:
    """How far from a central keeper's hands the ball crossed the line: 0 at the keeper, about 1.3 in a top corner."""
    return math.hypot(abs(y_m) / GOAL_HALF_WIDTH_M, abs(z_m - KEEPER_HEIGHT_M) / (CROSSBAR_M - KEEPER_HEIGHT_M))


def xgot(pre_shot_xg: float, y_m: float, z_m: float, speed_mps: float) -> float:
    pre = math.log(pre_shot_xg / (1 - pre_shot_xg))
    logit = XGOT_INTERCEPT + XGOT_PRE_COEF * pre + XGOT_REACH_COEF * placement_reach(y_m, z_m) + XGOT_SPEED_COEF * (speed_mps - 20)
    return min(.97, max(.02, 1 / (1 + math.exp(-logit))))


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
    xgot: float | None = None
    placement: object | None = None
    passer_id: str | None = None      # the key pass: the completed pass straight to the shooter
    key_pass_ref: str | None = None
    key_pass_start: tuple[float, float] | None = None
    first_time: bool = False          # the shot came straight off the key pass, with no carry in between
    key_pass_type: str | None = None  # cross, cutback, through ball, pass or corner (set piece)


def shot_quality(records: dict[str, EventEnvelope], ordered: list[EventEnvelope] | None = None) -> dict[str, ShotQuality]:
    """xG for every observed shot, keyed by event id."""
    ordered = ordered if ordered is not None else canonical_order(records)
    result: dict[str, ShotQuality] = {}
    last: dict[str, EventEnvelope] = {}
    # The last completed pass in each possession, while only its receiver has carried the ball since.
    feed: dict[str, EventEnvelope | None] = {}
    corner_possessions: set[str] = set()
    for record in ordered:
        e = record.payload
        if e.kind == "POSSESSION" and e.detail.start.x >= 99:
            corner_possessions.add(e.possession_id)
        if e.kind == "SHOT":
            p = e.detail.position
            previous = last.get(e.possession_id)
            before = previous.payload if previous else None
            assist = assist_type(before, e.player_id, e.possession_id in corner_possessions)
            body = e.detail.body_part or "right_foot"
            value = round(xg(p.x, p.y, assist, body), 3)
            fed = feed.get(e.possession_id)
            # A key pass reaches the shooter in the final third, or the shot is first time.
            key = fed is not None and fed.payload.detail.recipient_id == e.player_id and (fed.payload.detail.end.x >= 66.67 or before is fed.payload)
            placed = e.detail.placement if e.detail.outcome in ("goal", "saved") else None
            post = round(xgot(value, placed.y_m, placed.z_m, placed.speed_mps), 3) if placed else None
            result[record.event_id] = ShotQuality(record.event_id, record.ref, e.event_time_ms, e.team_id, e.player_id, e.detail.outcome,
                value, round(distance_m(p.x, p.y), 1), round(math.degrees(goal_angle(p.x, p.y)), 1), assist, body, chance_type(value),
                post, placed, fed.payload.player_id if key else None, fed.ref if key else None,
                (fed.payload.detail.start.x, fed.payload.detail.start.y) if key else None, key and before is fed.payload,
                assist_type(fed.payload, e.player_id, e.possession_id in corner_possessions) if key else None)
        if e.kind in ("PASS", "CARRY", "SHOT") and e.possession_id:
            last[e.possession_id] = record
            fed = feed.get(e.possession_id)
            if e.kind == "PASS":
                feed[e.possession_id] = record if e.detail.completed else None
            elif e.kind == "SHOT" or (fed is not None and e.player_id != fed.payload.detail.recipient_id):
                feed[e.possession_id] = None
    return result
