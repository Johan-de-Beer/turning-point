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
# Public playing positions shown with every event (standard broadcast abbreviations).
# Both sides line up 4-3-3; Vale's left-sided eight plays as an attacking midfielder.
POSITIONS = {"GK": "GK", "RB": "RB", "LB": "LB", "RCB": "CB", "LCB": "CB", "DM": "CDM", "RCM": "CM", "LCM": "CM",
             "ST": "ST", "RW": "RW", "LW": "LW"}
POSITION_OVERRIDES = {"vale_08": "CAM"}
FORWARDS = ("RW", "ST", "LW")
MIDFIELD = ("RCM", "DM", "LCM")
# The formation each side names on its team sheet (public). How the shape changes in and out of
# possession is not public: the analysis measures it from the positions.
TEAM_SHEET = {"harbor": "4-3-3", "vale": "4-3-3"}

# Harbor's right winger is left-footed: an inverted winger who cuts inside onto the stronger foot.
LEFT_FOOTED = {"harbor_03", "harbor_08", "harbor_10", "harbor_11", "vale_03", "vale_11"}

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


def position(player_id: str) -> str:
    return POSITION_OVERRIDES.get(player_id, POSITIONS[role(player_id)])


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
        # Share of short goal-kick build-ups played through a third man: the keeper lays the ball into
        # the dropping holding midfielder, who sets it first time for the centre-back.
        "lay_off_rate": .75,
        "corner": {"accuracy": {"harbor_07": 1.4, "harbor_11": 2.0}, "speed_mps": {"harbor_07": 24.0, "harbor_11": 22.0},
                   "onset_ms": {"harbor_04": -450, "harbor_09": 250, "harbor_05": -100}},
        # Continuous movement: back-four depth (units from own goal) with the ball at halfway,
        # each player's speed in the 5 s after the ball changes hands, their usual speed when
        # repositioning off the ball, late-match fades (start time, share of pace lost) and how
        # far the line drops (units) while protecting a lead.
        "movement": {"line_base": 42.0, "transition_mps": {"harbor_02": 7.4, "harbor_10": 7.0, "harbor_09": 6.0},
                     "cruise_mps": {"harbor_02": 4.2}, "fade": {}, "lead_drop": 8.0,
                     # Phases round: how many of the nearest outfield players hunt the ball after a loss
                     # (within reach, for the window), each full-back's habit in possession, positional
                     # rotations, and whether the keeper sweeps behind a high line.
                     "counter_press": {"players": 3, "window_ms": 4_000, "reach_m": 30.0, "rate": .8},
                     "fullbacks": {"harbor_02": "overlap", "harbor_03": "invert"},
                     "rotations": {"harbor_06": "drop_in"}, "sweeper": True,
                     # Principles round: winger habits, the rest-defence shape held behind the ball in the
                     # final third (a base line and a screen in front of it), a striker's drop-and-sprint
                     # counter-movement, midfield man-marking against the opponent's build-up, and pressing
                     # triggers (the nearest players hunt the receiver of certain passes in its own half).
                     "winger_habits": {"harbor_10": "invert"},
                     "rest_shape": {"base": ("harbor_04", "harbor_05"), "screen": ("harbor_07", "harbor_06", "harbor_03")},
                     "drop_sprint": {"harbor_09": {"cycle_ms": 25_000, "drop_ms": 1_200, "sprint_ms": 2_400}},
                     "man_marking": {},
                     "trigger_hunt": {"on": ("back_pass_keeper", "to_centre_back"), "players": 2, "window_ms": 3_500, "rate": .85},
                     # Formations round: the out-of-possession shape (line and lateral spot of the players who
                     # leave their 4-3-3 places; the left eight steps up beside the striker and the wingers drop
                     # into a midfield four, a 4-4-2) and how far the back four drops (units) when nobody is
                     # pressing the ball: Harbor's high line steps off when the pressure on the ball is late.
                     "defensive_shape": {"harbor_08": ("front", -5), "harbor_09": ("front", 5), "harbor_11": ("midfield", -25),
                                         "harbor_06": ("midfield", -8), "harbor_07": ("midfield", 8), "harbor_10": ("midfield", 25)},
                     "free_ball_drop": 8.0,
                     # In the final third the left eight joins the front line (depth ahead of the ball, lateral spot):
                     # with the inverted left-back beside the holding midfielder, the 4-3-3 attacks as a 2-3-5.
                     "attack_shape": {"harbor_08": (6.0, -12.0)}},
        # Share of the saves this side's goalkeeper makes from well-placed, hard-hit shots.
        "goalkeeping": {"hard_save_rate": .55},
    },
    "vale": {
        "trap_rate": .7, "step_lag_ms": {"vale_03": 440}, "follow_runner": .8, "follow_lag_ms": {"vale_04": 650},
        "early_release": {}, "shift_lag_ms": {},
        "run_rate": {"vale_09": .6, "vale_11": .45, "vale_10": .2},
        "press": {"base": .3, "target": "harbor_04", "target_bonus": .35, "force_back": .4,
                  "triggers": {"vale_10": .55, "vale_09": .45}, "reaction_ms": 650, "speed_mps": 5.9},
        "short_build_up": .15, "pass_speed_mps": 15.0, "lay_off_rate": 0.0,
        "corner": {"accuracy": {"vale_08": 3.2}, "speed_mps": {"vale_08": 18.5},
                   "onset_ms": {"vale_04": -150, "vale_09": 400, "vale_05": 0}},
        "movement": {"line_base": 25.0, "transition_mps": {"vale_11": 3.4, "vale_03": 6.2},
                     "cruise_mps": {"vale_11": 2.4}, "fade": {"vale_08": (3_000_000, .65)}, "lead_drop": 0.0,
                     "counter_press": {"players": 1, "window_ms": 1_200, "reach_m": 10.0, "rate": .4},
                     "fullbacks": {"vale_03": "underlap", "vale_02": "hold"},
                     "rotations": {"vale_09": "drop_deep"}, "sweeper": False,
                     "winger_habits": {"vale_11": "hug"},
                     "rest_shape": {"base": ("vale_02", "vale_04", "vale_05"), "screen": ("vale_07", "vale_06")},
                     "drop_sprint": {},
                     # Vale's two central midfielders follow Harbor's two central midfielders while Harbor
                     # builds in its own half; the front three and the back four stay zonal (a hybrid press).
                     "man_marking": {"vale_07": "LCM", "vale_08": "RCM"},
                     "trigger_hunt": {"on": (), "players": 0, "window_ms": 0, "rate": 0.0},
                     # The wingers drop level with the midfield three (a 4-5-1); the low line stays put either way.
                     "defensive_shape": {"vale_11": ("midfield", -26), "vale_10": ("midfield", 26)},
                     "free_ball_drop": 0.0,
                     # Behind a back three (the held right-back and the centre-backs) the left-back and the attacking
                     # midfielder push into the half-spaces beside the striker: a 3-2-5 in the final third.
                     "attack_shape": {"vale_03": (8.0, -14.0), "vale_08": (6.0, 12.0)}},
        "goalkeeping": {"hard_save_rate": .15},
    },
}


def tendencies(team_id: str) -> dict:
    return _TENDENCIES[team_id]


def expected_swing(taker_foot: str, side: str) -> str:
    """A right-footed delivery from the left corner curls toward goal (inswinger);
    from the right corner it curls away (outswinger). Left-footed is the mirror."""
    return "inswinger" if (taker_foot == "right") == (side == "left") else "outswinger"
