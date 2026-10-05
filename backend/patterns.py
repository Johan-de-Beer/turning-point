"""Conservative, configurable football heuristics; never causal or predictive."""
from __future__ import annotations

from dataclasses import dataclass

from .models import MetricSnapshot, RuleCondition

# Priority is deterministic should a future threshold edit create overlaps.
PRIORITY = ("end_to_end", "sustained_pressure", "sterile_possession")
THRESHOLDS = {
    "sustained_pressure": {"possession_share": 60, "final_third_entries": 5, "shots": 3, "opponent_shots_max": 1},
    "sterile_possession": {"possession_share": 65, "completed_passes": 15, "shots_max": 1, "box_entries_max": 1},
    "end_to_end": {"shots": 2, "live_turnovers": 6, "share_min": 35, "share_max": 65},
}


@dataclass
class Candidate:
    pattern: str
    subject_ids: list[str]
    conditions: list[RuleCondition]
    episode_id: str


def conditions_for(snap: MetricSnapshot, pattern: str, team: str | None) -> list[RuleCondition]:
    teams = list(snap.team_metrics)
    rows = []
    def check(subject: str, metric: str, operator: str, threshold: float):
        actual = snap.live_turnovers if metric == "live_turnovers" else getattr(snap.team_metrics[subject], metric)
        passed = actual is not None and (actual >= threshold if operator == ">=" else actual <= threshold)
        rows.append(RuleCondition(metric=metric, subject_id=subject, operator=operator, threshold=threshold, actual=actual, passed=passed))
    t = THRESHOLDS[pattern]
    if pattern == "sustained_pressure":
        check(team, "possession_share", ">=", t["possession_share"])
        check(team, "final_third_entries", ">=", t["final_third_entries"])
        check(team, "shots", ">=", t["shots"])
        check(next(other for other in teams if other != team), "shots", "<=", t["opponent_shots_max"])
    elif pattern == "sterile_possession":
        check(team, "possession_share", ">=", t["possession_share"])
        check(team, "completed_passes", ">=", t["completed_passes"])
        check(team, "shots", "<=", t["shots_max"])
        check(team, "box_entries", "<=", t["box_entries_max"])
    else:
        for subject in teams:
            check(subject, "shots", ">=", t["shots"])
            check(subject, "possession_share", ">=", t["share_min"])
            check(subject, "possession_share", "<=", t["share_max"])
        check("match", "live_turnovers", ">=", t["live_turnovers"])
    return rows


class PatternEngine:
    def __init__(self):
        self.period = None
        self.states: dict[str, dict] = {}
        self.suppressed: list[str] = []

    def evaluate(self, snap: MetricSnapshot) -> list[Candidate]:
        if self.period != snap.period:
            self.states.clear()
            self.period = snap.period
        entries = []
        passing = []
        for pattern in PRIORITY:
            subjects = [None] if pattern == "end_to_end" else list(snap.team_metrics)
            for team in subjects:
                key = f"{pattern}:{team or 'match'}"
                conditions = conditions_for(snap, pattern, team)
                passes = snap.coverage.eligible and all(c.passed for c in conditions)
                state = self.states.setdefault(key, {"pass": 0, "fail": 0, "active": False, "episodes": 0})
                if passes:
                    state["pass"] += 1
                    state["fail"] = 0
                    passing.append(key)
                    if state["pass"] >= 2 and not state["active"]:
                        state["active"] = True
                        state["episodes"] += 1
                        entries.append(Candidate(pattern, list(snap.team_metrics) if team is None else [team], conditions,
                            f"episode_p{snap.period}_{key}_{state['episodes']}"))
                else:
                    state["pass"] = 0
                    state["fail"] += 1
                    if state["fail"] >= 2:
                        state["active"] = False
        self.suppressed = []
        if len(entries) > 1:
            # Highest priority first; expose every suppressed candidate in diagnostics.
            chosen = min(entries, key=lambda c: PRIORITY.index(c.pattern))
            self.suppressed = [c.episode_id for c in entries if c is not chosen]
            return [chosen]
        return entries
