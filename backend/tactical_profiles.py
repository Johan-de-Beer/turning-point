"""Synthetic tactical profiles for the fictional squads.

Public attributes (role, preferred foot) describe the fictional players and may be
shown. ``_TENDENCIES`` is the server-only behaviour plan the synthetic generator
uses to move players. It never leaves the server and the tactical analysis never
reads it: every reported tendency is re-measured from released tracking frames
and events, so tests can check that the analysis recovers what was planted.
"""
from __future__ import annotations

ROLES = {1: "GK", 2: "RB", 3: "LB", 4: "RCB", 5: "LCB", 6: "DM", 7: "RCM", 8: "LCM", 9: "ST", 10: "RW", 11: "LW"}
BACK_FOUR = ("RB", "RCB", "LCB", "LB")
FORWARDS = ("RW", "ST", "LW")
MIDFIELD = ("RCM", "DM", "LCM")

LEFT_FOOTED = {"harbor_03", "harbor_08", "harbor_11", "vale_03", "vale_11"}

# Corner sides are named from the attacking team's view: "left" is the corner on
# its left touchline (y = 0 in its attacking frame), "right" is y = 100.
CORNER_TAKERS = {
    "harbor": {"left": "harbor_07", "right": "harbor_11"},
    "vale": {"left": "vale_08", "right": "vale_08"},
}
TARGET_MEN = {"harbor": ("harbor_04", "harbor_09", "harbor_05"), "vale": ("vale_04", "vale_09", "vale_05")}


def number(player_id: str) -> int:
    return int(player_id.rsplit("_", 1)[1])


def role(player_id: str) -> str:
    return ROLES[number(player_id)]


def foot(player_id: str) -> str:
    return "left" if player_id in LEFT_FOOTED else "right"


def player_for(team_id: str, role_name: str) -> str:
    return f"{team_id}_{next(n for n, r in ROLES.items() if r == role_name):02d}"


def other(team_id: str) -> str:
    return "vale" if team_id == "harbor" else "harbor"


_TENDENCIES = {
    "harbor": {
        "trap_rate": .35, "step_lag_ms": {"harbor_02": 160}, "follow_runner": .25, "follow_lag_ms": {},
        "early_release": {"harbor_06": .65}, "shift_lag_ms": {"harbor_03": 900},
        "run_rate": {"harbor_10": .85, "harbor_09": .55, "harbor_11": .3},
        "press": {"base": .45, "target": "vale_05", "target_bonus": .45, "force_back": .6,
                  "triggers": {"harbor_09": .6, "harbor_11": .25, "harbor_10": .15}, "reaction_ms": 300, "speed_mps": 7.2},
        "short_build_up": .85, "pass_speed_mps": 18.0,
        "corner": {"accuracy": {"harbor_07": 1.4, "harbor_11": 2.0}, "speed_mps": {"harbor_07": 24.0, "harbor_11": 22.0},
                   "onset_ms": {"harbor_04": -450, "harbor_09": 250, "harbor_05": -100}},
    },
    "vale": {
        "trap_rate": .7, "step_lag_ms": {"vale_03": 440}, "follow_runner": .8, "follow_lag_ms": {"vale_04": 650},
        "early_release": {}, "shift_lag_ms": {},
        "run_rate": {"vale_09": .6, "vale_11": .45, "vale_10": .2},
        "press": {"base": .3, "target": "harbor_04", "target_bonus": .35, "force_back": .4,
                  "triggers": {"vale_10": .55, "vale_09": .45}, "reaction_ms": 650, "speed_mps": 5.9},
        "short_build_up": .15, "pass_speed_mps": 15.0,
        "corner": {"accuracy": {"vale_08": 3.2}, "speed_mps": {"vale_08": 18.5},
                   "onset_ms": {"vale_04": -150, "vale_09": 400, "vale_05": 0}},
    },
}


def tendencies(team_id: str) -> dict:
    return _TENDENCIES[team_id]


def expected_swing(taker_foot: str, side: str) -> str:
    """A right-footed delivery from the left corner curls toward goal (inswinger);
    from the right corner it curls away (outswinger). Left-footed is the mirror."""
    return "inswinger" if (taker_foot == "right") == (side == "left") else "outswinger"
