"""Versioned, strict contracts. No provider can supply football measurements."""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"
RULES_VERSION = "rules_v1"
PERIOD_MS = 2_700_000
WINDOW_MS = 180_000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, validate_assignment=True)


class Team(StrictModel):
    team_id: str = Field(min_length=1, max_length=40)
    display_name: str = Field(min_length=1, max_length=80)
    short_name: str = Field(min_length=1, max_length=12)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class Player(StrictModel):
    player_id: str
    team_id: str
    display_name: str = Field(min_length=1, max_length=80)
    shirt_number: int = Field(ge=1, le=99, strict=True)
    position: Literal["GK", "DEF", "MID", "FWD"]
    # Specific playing position (e.g. ST, CAM, CDM). Optional for legacy fixtures.
    role: Literal["GK", "RB", "CB", "LB", "RWB", "LWB", "CDM", "CM", "CAM", "RM", "LM", "RW", "LW", "CF", "ST"] | None = None


class MatchMetadata(StrictModel):
    match_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    provenance: Literal["synthetic"] = "synthetic"
    home: Team
    away: Team
    roster: list[Player]
    period_lengths_ms: tuple[int, int] = (PERIOD_MS, PERIOD_MS)

    @field_validator("period_lengths_ms", mode="before")
    @classmethod
    def json_period_lengths(cls, value):
        # JSON represents tuples as arrays; preserve strict element types.
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def references(self):
        teams = {self.home.team_id, self.away.team_id}
        if len(teams) != 2 or len({p.player_id for p in self.roster}) != len(self.roster):
            raise ValueError("Teams and player IDs must be unique")
        if any(p.team_id not in teams for p in self.roster):
            raise ValueError("Unknown roster team")
        for team in teams:
            numbers = [p.shirt_number for p in self.roster if p.team_id == team]
            if len(numbers) != len(set(numbers)):
                raise ValueError("Duplicate shirt number within a team")
        if self.period_lengths_ms != (PERIOD_MS, PERIOD_MS):
            raise ValueError("P0 has two 45-minute periods")
        return self


class Match(MatchMetadata):
    seed: int = Field(strict=True)
    fixture_version: str

    def public(self) -> MatchMetadata:
        return MatchMetadata.model_validate(self.model_dump(exclude={"seed", "fixture_version"}))


class Point(StrictModel):
    x: float = Field(ge=0, le=100, strict=True)
    y: float = Field(ge=0, le=100, strict=True)


class EmptyDetail(StrictModel):
    pass


class PossessionDetail(StrictModel):
    start: Point


class PassDetail(StrictModel):
    recipient_id: str
    completed: bool = Field(strict=True)
    start: Point
    end: Point


class CarryDetail(StrictModel):
    start: Point
    end: Point


class ShotPlacement(StrictModel):
    """Where an on-target shot crossed the goal line, from the shooter's view, and how hard it was hit."""
    y_m: float = Field(ge=-3.66, le=3.66, strict=True)   # metres from the goal centre, positive to the shooter's right (y = 100)
    z_m: float = Field(ge=0, le=2.44, strict=True)       # height above the ground
    speed_mps: float = Field(ge=0, le=45, strict=True)


class ShotDetail(StrictModel):
    position: Point
    outcome: Literal["goal", "saved", "blocked", "off_target"]
    # Synthetic recorded endpoint, supplied only once this shot is observed.
    # Legacy stored shots can remain source-only; never infer a missing target.
    target: Point | None = None
    # Synthetic recorded body part; absent on legacy shots and then treated as a foot.
    body_part: Literal["right_foot", "left_foot", "head"] | None = None
    # Synthetic recorded placement in the goal mouth, on goals and saved shots only.
    placement: ShotPlacement | None = None


class TackleDetail(StrictModel):
    position: Point
    successful: bool = Field(strict=True)
    # A ground challenge or an aerial contest. The actor is always the defending player;
    # ``successful`` means the defender won the duel.
    contest: Literal["ground", "aerial"] = "ground"


class StoppageDetail(StrictModel):
    reason: Literal["ball_out", "corner", "foul", "goal", "interval"]


class EventBase(StrictModel):
    match_id: str
    event_time_ms: int = Field(ge=0, le=2 * PERIOD_MS, strict=True)
    period: Literal[1, 2]
    team_id: str | None = None
    player_id: str | None = None
    possession_id: str | None = None

    @field_validator("period", mode="before")
    @classmethod
    def strict_period(cls, value):
        if type(value) is not int:
            raise ValueError("Period must be an integer")
        return value

    @model_validator(mode="after")
    def period_time(self):
        start = (self.period - 1) * PERIOD_MS
        if not start <= self.event_time_ms <= start + PERIOD_MS:
            raise ValueError("Event time is outside its period")
        if self.kind in ("PERIOD_START", "PERIOD_END"):
            expected = start if self.kind == "PERIOD_START" else start + PERIOD_MS
            if self.event_time_ms != expected or self.team_id or self.player_id or self.possession_id:
                raise ValueError("Invalid period marker")
        elif self.kind == "STOPPAGE":
            if self.player_id:
                raise ValueError("Stoppage has no player actor")
        elif not self.team_id or not self.player_id or not self.possession_id:
            raise ValueError("An in-play event requires team, actor and possession")
        return self


class PeriodStart(EventBase):
    kind: Literal["PERIOD_START"]
    detail: EmptyDetail = Field(default_factory=EmptyDetail)


class PeriodEnd(EventBase):
    kind: Literal["PERIOD_END"]
    detail: EmptyDetail = Field(default_factory=EmptyDetail)


class Possession(EventBase):
    kind: Literal["POSSESSION"]
    detail: PossessionDetail


class Pass(EventBase):
    kind: Literal["PASS"]
    detail: PassDetail


class Carry(EventBase):
    kind: Literal["CARRY"]
    detail: CarryDetail


class Shot(EventBase):
    kind: Literal["SHOT"]
    detail: ShotDetail


class Tackle(EventBase):
    kind: Literal["TACKLE"]
    detail: TackleDetail


class Stoppage(EventBase):
    kind: Literal["STOPPAGE"]
    detail: StoppageDetail


Event = Annotated[PeriodStart | PeriodEnd | Possession | Pass | Carry | Shot | Tackle | Stoppage, Field(discriminator="kind")]


class EventEnvelope(StrictModel):
    delivery_seq: int = Field(ge=1, strict=True)
    available_at_ms: int = Field(ge=0, le=2 * PERIOD_MS, strict=True)
    event_id: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=1, strict=True)
    operation: Literal["upsert", "delete"] = "upsert"
    payload: Event | None

    @model_validator(mode="after")
    def envelope(self):
        if self.operation == "upsert" and self.payload is None:
            raise ValueError("Upsert requires a payload")
        if self.operation == "delete" and self.payload is not None:
            raise ValueError("Tombstone payload must be null")
        if self.payload and self.available_at_ms < self.payload.event_time_ms:
            raise ValueError("An event cannot be delivered before it occurred")
        return self

    @property
    def ref(self) -> str:
        return f"{self.event_id}@{self.revision}"


class Preferences(StrictModel):
    mode: Literal["casual", "analyst"] = "casual"
    favorite_team_id: str | None = None
    favorite_player_id: str | None = None
    language: Literal["en"] = "en"
    pause_on_insight: bool = Field(default=False, strict=True)


class SessionCreate(StrictModel):
    match_id: str = Field(max_length=80)
    preferences: Preferences = Field(default_factory=Preferences)
    speed: Literal[1, 12, 60] = 60

    @field_validator("speed", mode="before")
    @classmethod
    def strict_speed(cls, value):
        if type(value) is not int:
            raise ValueError("Speed must be an integer")
        return value


class Control(StrictModel):
    action: Literal["play", "pause", "continue_half", "restart", "set_speed"]
    expected_generation: int = Field(ge=1, strict=True)
    speed: Literal[1, 12, 60] | None = None

    @field_validator("speed", mode="before")
    @classmethod
    def strict_speed(cls, value):
        if value is not None and type(value) is not int:
            raise ValueError("Speed must be an integer")
        return value

    @model_validator(mode="after")
    def speed_for_action(self):
        if (self.action == "set_speed") != (self.speed is not None):
            raise ValueError("Speed is required only for set_speed")
        return self


class PreferencesPatch(StrictModel):
    expected_preferences_version: int = Field(ge=1, strict=True)
    mode: Literal["casual", "analyst"] | None = None
    favorite_team_id: str | None = None
    favorite_player_id: str | None = None
    language: Literal["en"] | None = None
    pause_on_insight: bool | None = None


class Window(StrictModel):
    start_ms: int
    end_ms: int


class Coverage(StrictModel):
    status: Literal["warming_up", "eligible", "insufficient_evidence"]
    eligible: bool
    known_in_play_ms: int
    owned_in_play_ms: dict[str, int]
    stoppage_ms: int
    unknown_state_ms: int
    state_valid: bool


class TeamMetrics(StrictModel):
    shots: int
    on_target: int
    completed_passes: int
    attempted_passes: int
    pass_accuracy: float | None
    final_third_entries: int
    box_entries: int
    possession_share: float | None
    goals: int
    duels: int = 0
    duels_won: int = 0
    final_third_passes: int = 0
    field_tilt: float | None = None
    xg: float = 0.0


class Baseline(StrictModel):
    window: Window
    coverage: Coverage
    team_metrics: dict[str, TeamMetrics]
    live_turnovers: int


class MetricSnapshot(StrictModel):
    snapshot_id: str
    session_id: str
    generation: int
    data_epoch: int
    as_of_ms: int
    delivery_cursor: int
    period: Literal[1, 2]
    window: Window
    coverage: Coverage
    team_metrics: dict[str, TeamMetrics]
    live_turnovers: int
    baseline: Baseline | None
    evidence_refs: list[str]
    rules_version: Literal["rules_v1"] = RULES_VERSION


class EvidenceFact(StrictModel):
    fact_id: str
    metric: str
    subject_id: str
    numeric_value: float
    unit: Literal["count", "percent", "milliseconds"]
    window: Window
    source_event_refs: list[str]
    derivation_version: Literal["metrics_v1"] = "metrics_v1"


class NarrativeVariant(StrictModel):
    insight_id: str
    mode: Literal["casual", "analyst"]
    language: Literal["en"] = "en"
    preferences_version: int
    headline: str = Field(max_length=100)
    explanation: str = Field(max_length=1000)
    fact_ids: list[str]
    player_focus_ids: list[str]
    provenance: Literal["mock_template", "deterministic_fallback", "microsoft_foundry"]


class RuleCondition(StrictModel):
    metric: str
    subject_id: str
    operator: str
    threshold: float
    actual: float | None
    passed: bool


class Insight(StrictModel):
    insight_id: str
    pattern: Literal["sustained_pressure", "sterile_possession", "end_to_end"]
    subject_ids: list[str]
    anchor_snapshot_id: str
    facts: list[EvidenceFact]
    evidence_quality: Literal["complete", "insufficient"] = "complete"
    observed_window: Window
    interpretation: str
    limitations: list[str]
    status: Literal["pending", "ready", "corrected", "retracted", "expired", "rejected"]
    supersedes_id: str | None = None
    variants: dict[str, NarrativeVariant] = Field(default_factory=dict)
    conditions: list[RuleCondition]
    supported_player_ids: list[str]
    generation: int
    data_epoch: int
    episode_id: str


class OverlayDisplay(StrictModel):
    headline: str = Field(max_length=100)
    subline: str = Field(max_length=160)


class Overlay(StrictModel):
    overlay_id: str
    insight_id: str | None
    session_id: str
    generation: int
    data_epoch: int
    mode: Literal["casual", "analyst"]
    language: Literal["en"] = "en"
    valid_from_ms: int
    valid_until_ms: int
    priority: int
    display: OverlayDisplay
    fact_ids: list[str]
    status: Literal["active"] = "active"


class StoryBeat(StrictModel):
    insight_id: str
    headline: str
    explanation: str
    fact_ids: list[str]
    observed_window: Window


class RecapVariant(StrictModel):
    headline: str
    explanation: str
    story_beats: list[StoryBeat]
    fact_ids: list[str]
    player_summary: str | None


class Recap(StrictModel):
    recap_id: str
    phase: Literal["half_time", "full_time"]
    cutoff_snapshot_id: str | None
    generation: int
    data_epoch: int
    score: dict[str, int]
    story_beats: list[StoryBeat]
    facts: list[EvidenceFact]
    fact_ids: list[str]
    variants: dict[str, RecapVariant]
    status: Literal["locked", "pending", "ready", "corrected"]
    correction_notice: str | None = None
    cutoff_ms: int | None = None


class PlayerStats(StrictModel):
    player_id: str
    team_id: str
    involvement: int
    touches: int
    passes_attempted: int
    passes_completed: int
    passes_received: int
    carries: int
    shots: int
    on_target: int
    goals: int
    tackles: int
    duels: int = 0
    duels_won: int = 0
    event_refs: list[str]


class AgentRun(StrictModel):
    run_id: str
    role: Literal["football_analyst", "evidence_editor"]
    provider: str
    input_fingerprint: str
    session_id: str
    generation: int
    data_epoch: int
    snapshot_id: str
    rules_version: str
    preferences_version: int
    mode: str
    language: str
    status: Literal["queued", "running", "approved", "rejected", "timeout", "fallback", "discarded", "recoverable"]
    fact_ids: list[str]
    validation_errors: list[str]
    duration_ms: int
    fallback_reason: str | None = None


class Diagnostics(StrictModel):
    provider: str
    provider_status: str
    pipeline: dict[str, str]
    agent_runs: list[AgentRun]
    ingestion_errors: list[str]
    suppressed_candidates: list[str]
    correction_notice: str | None
    pending_jobs: int
    rules_version: str = RULES_VERSION
    definitions: dict[str, str]


class SessionState(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    session_id: str
    match_id: str
    generation: int
    data_epoch: int
    preferences_version: int
    status: Literal["ready", "playing", "paused", "half_time", "ended"]
    playhead_ms: int
    observed_high_water_ms: int
    period: Literal[1, 2]
    speed: Literal[1, 12, 60]
    last_delivery_seq: int
    next_cursor: str
    resync_required: bool = False
    preferences: Preferences
    score: dict[str, int]
    events: list[EventEnvelope]
    snapshot: MetricSnapshot
    insights: list[Insight]
    overlay: Overlay | None
    recaps: dict[str, Recap]
    player_stats: dict[str, PlayerStats]
    diagnostics: Diagnostics


class EvidenceResponse(StrictModel):
    session_id: str
    generation: int
    data_epoch: int
    playhead_ms: int
    next_cursor: str
    insight: Insight
    snapshot: MetricSnapshot
    facts: list[EvidenceFact]
    conditions: list[RuleCondition]
    events: list[EventEnvelope]
    metric_definitions: dict[str, str]


class OverlayResponse(StrictModel):
    session_id: str
    generation: int
    data_epoch: int
    playhead_ms: int
    next_cursor: str
    status: Literal["active", "empty"]
    overlay: Overlay | None


class RecapResponse(StrictModel):
    session_id: str
    generation: int
    data_epoch: int
    playhead_ms: int
    next_cursor: str
    recap: Recap


# ---------------------------------------------------------------- tactics_v1
TACTICS_VERSION = "tactics_v1"


class TacticalEvidence(StrictModel):
    episode_ids: list[str]
    event_refs: list[str]


class DefenderStep(StrictModel):
    player_id: str
    traps: int
    steps: int
    late_steps: int
    mean_lag_ms: float | None
    mean_depth_at_pass_m: float | None
    runners_played_onside: int


class OffsideTrap(StrictModel):
    attacks_faced: int
    traps: int
    caught_offside: int
    broken: int
    mean_step_speed_mps: float | None
    mean_line_height_m: float | None
    mean_line_spread_m: float | None
    defenders: list[DefenderStep]


class ShiftLag(StrictModel):
    player_id: str
    shifts: int
    mean_lag_ms: float


class MarkingRecord(StrictModel):
    player_id: str
    assignments: int
    early_releases: int
    runs_faced: int
    tracked: int
    late_reactions: int
    mean_reaction_ms: float | None


class ShapeShift(StrictModel):
    attacks_faced: int
    mean_width_before_m: float | None
    mean_width_at_pass_m: float | None
    mean_length_before_m: float | None
    mean_length_at_pass_m: float | None
    mean_shift_to_ball_m: float | None
    shift_lags: list[ShiftLag]
    marking_system: Literal["man_oriented", "zonal", "mixed", "insufficient_evidence"]
    follow_rate: float | None
    marking: list[MarkingRecord]


class PressTrigger(StrictModel):
    player_id: str
    presses: int
    mean_time_to_pressure_ms: float | None
    mean_closing_speed_mps: float | None


class PressTarget(StrictModel):
    player_id: str
    possessions: int
    presses: int
    press_rate: float


class PressOutcomes(StrictModel):
    possessions: int
    regained: int
    forced_to_keeper: int
    played_through: int
    stoppage: int
    retained: int
    mean_time_to_keeper_ms: float | None
    mean_time_to_regain_ms: float | None


class Press(StrictModel):
    opportunities: int
    presses: int
    triggers: list[PressTrigger]
    targets: list[PressTarget]
    when_pressing: PressOutcomes
    when_not_pressing: PressOutcomes
    mean_time_to_pressure_ms: float | None
    mean_closing_speed_mps: float | None


class Runner(StrictModel):
    player_id: str
    runs: int
    in_behind: int
    targeted: int
    offside: int
    drew_defender: int
    drag_rate: float | None


class Creator(StrictModel):
    player_id: str
    attacks_started: int
    chances: int
    mean_time_to_chance_ms: float | None


class DecisivePass(StrictModel):
    event_ref: str
    time_ms: int
    passer_id: str
    recipient_id: str
    completed: bool
    length_m: float
    speed_mps: float | None
    through_ball: bool | None
    recipient_ran: bool | None
    led_to_chance: bool
    # Major or minor by the xG of the shot that followed; None when no chance followed.
    chance: Literal["major", "minor"] | None
    xg: float | None
    shot_ref: str | None


class BuildUp(StrictModel):
    sequences: int
    short_starts: int
    long_starts: int
    reached_middle_third: int
    reached_final_third: int
    mean_time_to_middle_ms: float | None
    mean_time_to_final_ms: float | None
    passes_attempted: int
    passes_completed: int
    pass_accuracy: float | None
    lines_broken: int
    mean_lines_broken: float | None
    lost_in_own_half: int


class CornerDelivery(StrictModel):
    event_ref: str
    time_ms: int
    taker_id: str
    foot: Literal["left", "right"]
    side: Literal["left", "right"]
    swing: Literal["inswinger", "outswinger"]
    expected_swing: Literal["inswinger", "outswinger"]
    curve_m: float
    flight_ms: int
    speed_mps: float
    zone: Literal["near_post", "far_post", "penalty_spot", "six_yard", "other"]
    target_id: str
    accuracy_m: float
    time_to_spot_ms: int | None
    arrival_vs_ball_ms: int | None
    first_contact: Literal["attack", "defence"]
    attackers_in_box: int


class TargetMan(StrictModel):
    player_id: str
    deliveries: int
    reached_spot: int
    mean_time_to_spot_ms: float | None
    mean_arrival_vs_ball_ms: float | None
    first_contacts: int


class Corners(StrictModel):
    corners: int
    deliveries: list[CornerDelivery]
    target_men: list[TargetMan]


class TeamTactics(StrictModel):
    team_id: str
    offside_trap: OffsideTrap
    shape: ShapeShift
    press: Press
    runs: list[Runner]
    creators: list[Creator]
    decisive_passes: list[DecisivePass]
    build_up: BuildUp
    corners: Corners


class TacticalObservation(StrictModel):
    observation_id: str
    category: Literal["offside_trap", "shape", "marking", "press", "runs", "chance_creation", "build_up", "corners"]
    kind: Literal["tendency", "opportunity"]
    subject_team_id: str
    for_team_id: str
    headline: str = Field(max_length=140)
    detail: str = Field(max_length=600)
    player_ids: list[str]
    sample_size: int
    evidence: TacticalEvidence
    moment_id: str | None = None


class MomentPlayer(StrictModel):
    player_id: str
    team_id: str
    x: float
    y: float


class KeyMoment(StrictModel):
    moment_id: str
    category: str
    time_ms: int
    period: Literal[1, 2]
    team_id: str
    title: str = Field(max_length=140)
    ball: Point
    players: list[MomentPlayer]
    offside_line_x: float | None
    highlight_ids: list[str]
    path: list[Point]
    event_ref: str


class TacticalReport(StrictModel):
    session_id: str
    generation: int
    data_epoch: int
    playhead_ms: int
    next_cursor: str
    engine_version: Literal["tactics_v1"] = TACTICS_VERSION
    provenance: Literal["synthetic_tracking"] = "synthetic_tracking"
    episodes_observed: int
    teams: dict[str, TeamTactics]
    observations: list[TacticalObservation]
    key_moments: list[KeyMoment]
    definitions: dict[str, str]
    limitations: list[str]


# -------------------------------------------------------------- analytics_v2
ANALYTICS_VERSION = "analytics_v2"
GameStateName = Literal["winning", "drawing", "losing"]


class TerritoryWindow(StrictModel):
    start_ms: int
    end_ms: int
    final_third_passes: dict[str, int]
    field_tilt: dict[str, float | None]
    possession_share: dict[str, float | None]


class Territory(StrictModel):
    match: TerritoryWindow
    recent: TerritoryWindow
    intervals: list[TerritoryWindow]


class ShotValue(StrictModel):
    event_ref: str
    time_ms: int
    team_id: str
    player_id: str
    outcome: Literal["goal", "saved", "blocked", "off_target"]
    xg: float
    distance_m: float
    angle_deg: float
    assist: Literal["through_ball", "cutback", "pass", "individual", "cross", "set_piece"]
    body_part: Literal["right_foot", "left_foot", "head"]
    chance: Literal["major", "minor"]
    xgot: float | None
    placement: ShotPlacement | None
    key_passer_id: str | None
    game_state: GameStateName


class TeamChances(StrictModel):
    team_id: str
    shots: int
    on_target: int
    goals: int
    xg: float
    xg_against: float
    major_chances: int
    xg_per_shot: float | None
    goals_against: int
    # Goals conceded minus xG conceded: negative means fewer goals let in than the chances allowed.
    goals_minus_xg_against: float


class LineFigures(StrictModel):
    seconds: float
    deepest_m: float | None
    back_four_m: float | None
    centroid_m: float | None
    gap_m: float | None
    width_m: float | None


class LineInterval(StrictModel):
    start_ms: int
    end_ms: int
    seconds: float
    back_four_m: float | None
    deepest_m: float | None


class DefensiveLine(StrictModel):
    team_id: str
    block: Literal["high", "mid", "low", "insufficient_evidence"]
    match: LineFigures
    recent: LineFigures
    settled: LineFigures
    after_loss: LineFigures
    before_shots: LineFigures
    shots_faced: int
    intervals: list[LineInterval]


class PlayerWorkload(StrictModel):
    player_id: str
    team_id: str
    minutes: float
    distance_m: float
    hsr_m: float
    sprint_m: float
    sprints: int
    accelerations: int
    decelerations: int
    load: float
    top_speed_mps: float
    metres_per_min: float | None
    recent_metres_per_min: float | None
    trend_pct: float | None
    flag: Literal["intensity_drop"] | None


class ValuedAction(StrictModel):
    event_ref: str
    time_ms: int
    team_id: str
    player_id: str
    action: Literal["pass", "carry", "shot", "lost_pass", "dispossessed", "tackle_won", "interception"]
    start: Point
    end: Point | None
    value_before: float
    value_after: float
    pv: float
    # VAEP-style: change in the scoring chance minus change in the conceding chance.
    scoring_delta: float
    conceding_delta: float
    vaep: float


class PlayerValue(StrictModel):
    player_id: str
    team_id: str
    actions: int
    pv: float
    positive_actions: int
    best_ref: str | None
    vaep: float
    defensive_vaep: float


class TeamValue(StrictModel):
    team_id: str
    actions: int
    possessions: int
    pv: float
    pv_per_action: float | None
    by_action: dict[str, float]
    vaep: float
    vaep_by_action: dict[str, float]


class ScoreSegment(StrictModel):
    start_ms: int
    end_ms: int
    score: dict[str, int]


class GameStateRow(StrictModel):
    state: GameStateName
    minutes: float
    possession_share: float | None
    field_tilt: float | None
    passes: int
    shots: int
    xg: float
    xg_per_shot: float | None
    goals: int
    box_touches: int
    xova: float
    vaep: float
    vaep_per_action: float | None
    ppda: float | None
    vertical_mps: float | None
    directness: float | None
    back_four_m: float | None


class TeamGameState(StrictModel):
    team_id: str
    current: GameStateName
    rows: list[GameStateRow]


class GameState(StrictModel):
    score: dict[str, int]
    segments: list[ScoreSegment]
    teams: dict[str, TeamGameState]


class Heatmap(StrictModel):
    subject_id: str          # a team id or a player id
    team_id: str
    kind: Literal["touches", "tracking", "received", "defensive"]
    total: int               # events, or seconds for tracking
    cells: list[int]         # GRID_X x GRID_Y, x-major, in the team's attacking frame


class Heatmaps(StrictModel):
    grid_x: int
    grid_y: int
    maps: list[Heatmap]


class KeeperRow(StrictModel):
    player_id: str
    team_id: str
    shots_on_target: int
    saves: int
    goals_conceded: int
    xg_faced: float
    xgot_faced: float
    xg_prevented: float
    save_pct: float | None


class TeamShooting(StrictModel):
    team_id: str
    shots_on_target: int
    xg_on_target: float
    xgot: float
    placement_added: float


class Goalkeeping(StrictModel):
    keepers: list[KeeperRow]
    shooting: dict[str, TeamShooting]


class TempoFigures(StrictModel):
    possessions: int
    vertical_mps: float | None
    final_third_entries: int
    passes_per_entry: float | None
    forward_passes: int
    lateral_passes: int
    backward_passes: int
    directness: float | None
    possession_s: dict[str, float | None]
    progressive_passes: int
    regain_to_progressive_s: float | None


class TempoInterval(StrictModel):
    start_ms: int
    end_ms: int
    vertical_mps: float | None
    directness: float | None
    passes_per_entry: float | None


class TeamTempo(StrictModel):
    team_id: str
    match: TempoFigures
    intervals: list[TempoInterval]


class Pressing(StrictModel):
    team_id: str
    ppda: float | None
    opponent_passes: int
    defensive_actions: int


class PlayerCreation(StrictModel):
    player_id: str
    team_id: str
    box_touches: int
    zone14_touches: int
    key_passes: int
    assists: int
    xa: float
    shots: int
    xg: float
    progressive_passes: int
    sca: int
    gca: int


class TeamCreation(StrictModel):
    team_id: str
    box_touches: int
    box_entries: int
    zone14_touches: int
    zone14_entries: int
    key_passes: int
    first_time_key_passes: int
    assists: int
    xa: float
    key_pass_types: dict[str, int]
    key_pass_origins: dict[str, int]
    xg_per_box_touch: float | None
    progressive_passes: int
    sca: int
    gca: int
    sca_types: dict[str, int]
    gca_types: dict[str, int]


class CreatingAction(StrictModel):
    """One of the (up to) two offensive actions directly before a shot: a shot- or goal-creating action."""
    shot_ref: str
    time_ms: int
    team_id: str
    player_id: str
    kind: Literal["pass_live", "pass_dead", "take_on", "shot", "defensive"]
    goal: bool


class NetworkNode(StrictModel):
    player_id: str
    x: float
    y: float
    touches: int
    passes: int
    received: int


class NetworkEdge(StrictModel):
    a: str
    b: str
    passes: int     # completed passes between the two, both directions
    a_to_b: int


class PassNetwork(StrictModel):
    team_id: str
    completed_passes: int
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]
    width_m: float | None   # spread of the average positions across the pitch
    depth_m: float | None   # and along it


class DefensiveRow(StrictModel):
    player_id: str
    team_id: str
    minutes: float
    tackles_won: int
    tackles_lost: int
    aerials_won: int
    interceptions: int
    recoveries: int
    total: int
    per90: float | None
    by_third: dict[str, int]


class PackingAction(StrictModel):
    event_ref: str
    time_ms: int
    team_id: str
    player_id: str
    action: Literal["pass", "carry"]
    packed: int
    defenders_packed: int
    start: Point
    end: Point


class PlayerPacking(StrictModel):
    player_id: str
    team_id: str
    passes: int
    packed_by_passes: int
    carries: int
    packed_by_carries: int
    passing_rate: float | None
    dribbling_rate: float | None
    defenders_packed: int


class TeamPacking(StrictModel):
    team_id: str
    passes: int
    packed_by_passes: int
    carries: int
    packed_by_carries: int
    passing_rate: float | None
    dribbling_rate: float | None
    defenders_packed: int
    line_breaking: int


class MatchAnalytics(StrictModel):
    session_id: str
    generation: int
    data_epoch: int
    playhead_ms: int
    next_cursor: str
    engine_version: Literal["analytics_v2"] = ANALYTICS_VERSION
    provenance: Literal["synthetic_events_and_tracking"] = "synthetic_events_and_tracking"
    territory: Territory
    chances: dict[str, TeamChances]
    shots: list[ShotValue]
    defensive_line: dict[str, DefensiveLine]
    workload: list[PlayerWorkload]
    team_value: dict[str, TeamValue]
    player_value: list[PlayerValue]
    top_actions: list[ValuedAction]
    top_vaep: list[ValuedAction]
    game_state: GameState
    heatmaps: Heatmaps
    goalkeeping: Goalkeeping
    tempo: dict[str, TeamTempo]
    pressing: dict[str, Pressing]
    creation: dict[str, TeamCreation]
    player_creation: list[PlayerCreation]
    packing: dict[str, TeamPacking]
    player_packing: list[PlayerPacking]
    top_packing: list[PackingAction]
    creating_actions: list[CreatingAction]
    pass_networks: dict[str, PassNetwork]
    defensive_actions: list[DefensiveRow]
    definitions: dict[str, str]
    limitations: list[str]


# ---------------------------------------------------------------- game phases (phases_v1)
PHASES_VERSION = "phases_v1"
PhaseName = Literal["attacking", "attacking_transition", "attacking_set_piece", "defending", "defensive_transition", "defending_set_piece"]
BlockName = Literal["high", "mid", "low"]


class Moment(StrictModel):
    """A moment to watch on the replay: the numbers point to it, the pictures explain it."""
    time_ms: int
    event_ref: str | None
    label: str


class PhaseRow(StrictModel):
    phase: PhaseName
    seconds: float
    share: float | None            # of the team's live-ball time
    passes: int
    final_third_entries: int
    xt: float
    shots_for: int
    xg_for: float
    goals_for: int
    shots_against: int
    xg_against: float
    goals_against: int


class TeamPhases(StrictModel):
    team_id: str
    live_seconds: float
    rows: list[PhaseRow]
    restarts: dict[str, int]       # restarts taken by type: corner, free_kick, goal_kick, throw_in


class AttackingTransitions(StrictModel):
    regains: int
    counters: int                  # reached the final third within the counter window
    counter_shots: int
    counter_xg: float
    recycled: int                  # first action sideways or backward
    lost_quickly: int
    median_to_final_third_s: float | None
    by_third: dict[str, int]       # regains by where the ball was won
    counters_by_third: dict[str, int]
    moments: list[Moment]


class CounterPress(StrictModel):
    losses: int
    tracked: int                   # losses with synthetic positions
    pressed: int                   # pressure within the window by someone other than the player who lost it
    press_rate: float | None
    median_pressure_s: float | None
    pack_2s: float | None          # mean players within 10 m of the ball 2 s after the loss
    regained_5s: int
    regained_10s: int
    bypassed: int                  # the opponent moved the ball 20 m or more upfield within 10 s
    shots_conceded: int            # within 15 s of the loss
    xg_conceded: float
    rest_defence: float | None     # mean outfield players goal-side of the ball at the loss
    rest_defenders: float | None   # of whom back-four defenders
    by_third: dict[str, int]       # losses by where the ball was lost
    moments: list[Moment]


class TeamTransitions(StrictModel):
    team_id: str
    attacking: AttackingTransitions
    defensive: CounterPress


class BlockRow(StrictModel):
    block: BlockName
    seconds: float
    share: float | None            # of settled defending time
    back_four_m: float | None
    length_m: float | None         # deepest to highest outfield player
    width_m: float | None          # outfield spread across the pitch
    line_gap_m: float | None
    box_defenders: float | None    # own players in the box while the ball is in the defending third
    opponent_entries: int          # opponent entries into its final third
    wide_entry_share: float | None
    opponent_shots: int
    long_shot_share: float | None  # shots from outside the box
    xg_against: float
    goals_against: int
    crosses_faced: int
    ppda: float | None
    regains: int
    counters: int


class LineSnapshot(StrictModel):
    situation: Literal["settled", "opponent_build_up", "high_press"]
    seconds: float
    back_four_m: float | None
    front_line_m: float | None
    length_m: float | None


class Recovery(StrictModel):
    balls_in_behind: int
    tracked: int
    retreat_m: float | None        # back four's mean retreat in the 5 s after
    top_speed_mps: float | None    # fastest back-four recovery speed in those 5 s
    keeper_start_m: float | None   # keeper's distance from the goal line as the ball is played
    keeper_max_m: float | None     # furthest the keeper came within 5 s
    sweeps: int                    # the keeper left the penalty area (16.5 m) within 5 s
    shots_conceded: int            # within 10 s
    moments: list[Moment]


class TeamBlocks(StrictModel):
    team_id: str
    settled_seconds: float
    rows: list[BlockRow]
    snapshots: list[LineSnapshot]
    recovery: Recovery


class PlayerProgression(StrictModel):
    player_id: str
    team_id: str
    progressive_passes: int
    progressive_carries: int
    progressive_carry_m: float
    carries: int
    carries_final_third: int
    carries_box: int
    take_ons: int
    xt_passes: float
    xt_carries: float
    xt: float


class ThreatAction(StrictModel):
    event_ref: str
    time_ms: int
    team_id: str
    player_id: str
    action: Literal["pass", "carry"]
    xt: float
    start: Point
    end: Point


class TeamProgression(StrictModel):
    team_id: str
    progressive_passes: int
    progressive_carries: int
    carry_share: float | None      # progressive carries as a share of progressive actions
    progressive_carry_m: float
    carries_final_third: int
    carries_box: int
    take_ons: int
    xt: float
    xt_passes: float
    xt_carries: float
    xt_by_channel: dict[str, float]  # left, centre, right (where the action started)
    xt_intervals: list[float]        # by 15 minutes


class XtGrid(StrictModel):
    grid_x: int
    grid_y: int
    values: list[float]
    training: dict[str, int | list[int]]


class FullbackRow(StrictModel):
    player_id: str
    team_id: str
    side: Literal["right", "left"]
    style: Literal["overlapping", "underlapping", "inverted", "holding", "balanced", "insufficient_evidence"]
    seconds: float                  # in-possession time measured
    depth_m: float | None           # mean distance from own goal line in possession
    attack_depth_m: float | None    # the same with the ball in the final third
    touchline_m: float | None       # mean distance from own touchline in possession
    inside_share: float | None      # share of build-up time 18 m or more from the touchline
    overlaps: int
    underlaps: int
    depth_at_loss_m: float | None
    crosses: int
    progressive_actions: int
    xt: float
    moments: list[Moment]


class RotationRow(StrictModel):
    kind: Literal["holding_midfielder_drops", "striker_drops", "wide_overlap", "wide_underlap", "fullback_inverts"]
    players: list[str]
    episodes: int
    seconds: float
    possessions: int                # possessions with the rotation
    final_third_rate: float | None  # of those, share reaching the final third
    baseline_rate: float | None     # possessions without it
    moments: list[Moment]


class TeamRotations(StrictModel):
    team_id: str
    rows: list[RotationRow]


class ControlRow(StrictModel):
    team_id: str
    possession_share: float | None
    field_tilt: float | None
    final_third_entries: int
    box_entries: int
    progressive_actions: int
    xg: float
    ppda: float | None
    possessions: int
    purposeful: int                 # reached the final third or a shot
    sterile: int                    # five or more completed passes, no final third, no shot
    sterile_passes: int
    read: Literal["control_with_territory", "possession_without_penetration", "territory_without_the_ball", "pinned_back", "balanced", "insufficient_evidence"]


class PressInterval(StrictModel):
    start_ms: int
    end_ms: int
    ppda: float | None
    opponent_passes: int
    defensive_actions: int
    high_regains: int


class TeamPressing(StrictModel):
    team_id: str
    halves: list[PressInterval]
    intervals: list[PressInterval]
    high_regains: int               # open-play regains in the attacking 40%
    high_regain_shots: int          # shots within 15 s of them
    high_regain_xg: float
    regains_by_third: dict[str, int]


class FinishingRow(StrictModel):
    player_id: str
    team_id: str
    shots: int
    goals: int
    xg: float
    goals_minus_xg: float
    xg_per_shot: float | None


class TeamXg(StrictModel):
    team_id: str
    intervals: list[float]          # xG for by 15 minutes
    intervals_against: list[float]
    against_by_setup: dict[str, float]
    goals_minus_xg: float


class AnalystNote(StrictModel):
    note_id: str
    team_id: str
    topic: str
    quantitative: str               # the numbers, with the sample size
    look_for: str                   # what the replay can show that the numbers cannot
    moments: list[Moment]
    caveat: str | None


class GamePhases(StrictModel):
    session_id: str
    generation: int
    data_epoch: int
    playhead_ms: int
    next_cursor: str
    engine_version: Literal["phases_v1"] = PHASES_VERSION
    provenance: Literal["synthetic_events_and_tracking"] = "synthetic_events_and_tracking"
    phases: dict[str, TeamPhases]
    transitions: dict[str, TeamTransitions]
    blocks: dict[str, TeamBlocks]
    progression: dict[str, TeamProgression]
    player_progression: list[PlayerProgression]
    top_threat: list[ThreatAction]
    xt_grid: XtGrid
    fullbacks: list[FullbackRow]
    rotations: dict[str, TeamRotations]
    control: dict[str, ControlRow]
    pressing: dict[str, TeamPressing]
    finishing: list[FinishingRow]
    xg: dict[str, TeamXg]
    notes: list[AnalystNote]
    definitions: dict[str, str]
    limitations: list[str]


# ------------------------------------------------------------------ principles_v1
PRINCIPLES_VERSION = "principles_v1"
Shape = Literal["5", "1+4", "2+3", "3+2", "4+1"]


class ShapeRow(StrictModel):
    """One structure of the deepest five outfield players: a base line and a screen in front of it."""
    shape: Shape
    seconds: float
    share: float | None
    base: list[str]                 # most common roles in the deeper line
    screen: list[str]               # and in the line in front of it


class RestLossRow(StrictModel):
    shape: Shape
    losses: int                     # open-play losses in the final third with this rest-defence shape
    counters_conceded: int
    shots_conceded: int
    xg_conceded: float


class TeamStructure(StrictModel):
    team_id: str
    build_up_seconds: float
    build_up: list[ShapeRow]
    rest_seconds: float
    rest_defence: list[ShapeRow]
    behind_ball: float | None       # outfield players 10 m or more goal-side of the ball (ball in the final third)
    overcommitted_share: float | None
    losses: list[RestLossRow]
    moments: list[Moment]


class WingerRow(StrictModel):
    player_id: str
    team_id: str
    side: Literal["right", "left"]
    foot: Literal["right", "left"]
    opposite_foot: bool             # plays on the flank opposite its stronger foot
    style: Literal["inverted", "touchline", "balanced", "insufficient_evidence"]
    seconds: float
    touchline_m: float | None
    inside_share: float | None
    cut_ins: int
    shots: int
    central_shots: int
    fullback_width_share: float | None
    xt: float
    moments: list[Moment]


class TeamWidth(StrictModel):
    team_id: str
    width_m: float | None
    entries: int
    central_entry_share: float | None
    crosses: int


class PressUnit(StrictModel):
    unit: Literal["front", "midfield", "back"]
    samples: int
    follow_share: float | None
    distance_m: float | None
    marking: Literal["man", "zonal", "mixed", "insufficient_evidence"]
    markers: list[str]              # players in the unit who follow their man


class TriggerRow(StrictModel):
    trigger: Literal["back_pass_keeper", "to_fullback", "to_centre_back", "into_midfield", "other"]
    passes: int
    tracked: int
    pressured: int
    rate: float | None
    median_s: float | None
    regained_5s: int


class TeamPressSystem(StrictModel):
    team_id: str
    seconds: float                  # opponent build-up time observed
    system: Literal["man_to_man", "zonal", "hybrid", "insufficient_evidence"]
    units: list[PressUnit]
    spare_at_back: float | None
    left_free: str | None
    left_free_share: float | None
    triggers: list[TriggerRow]
    cover_shadow: int
    cover_shadow_tracked: int
    build_ups: int
    forced_wide_share: float | None
    regains_by_channel: dict[str, int]
    moments: list[Moment]


class MarkingBand(StrictModel):
    band: Literal["near", "middle", "far"]
    samples: int
    distance_m: float | None


class FreeReceiver(StrictModel):
    player_id: str
    free: int
    between_lines: int


class TeamMarking(StrictModel):
    team_id: str
    bands: list[MarkingBand]
    receptions: int
    free: int
    free_between_lines: int
    free_players: list[FreeReceiver]
    moments: list[Moment]


class MovementRow(StrictModel):
    kind: Literal["drop_and_sprint", "opposite_runs", "decoy_run", "crisscross"]
    players: list[str]
    episodes: int
    drew: int                       # a defender stepped out or was dragged with it
    found: int                      # the ball went to the runner or into the space within 3 s
    moments: list[Moment]


class TeamMovements(StrictModel):
    team_id: str
    rows: list[MovementRow]
    corners: int
    crisscross_corners: int


class ThirdManRow(StrictModel):
    first: str
    second: str
    third: str
    count: int


class TeamThirdMan(StrictModel):
    team_id: str
    combinations: int
    by_zone: dict[str, int]
    tracked: int
    lane_blocked: int
    receiver_free: int
    progress_m: float | None
    final_third_10s: int
    shots_15s: int
    patterns: list[ThirdManRow]
    moments: list[Moment]


class ReportLine(StrictModel):
    topic: str
    text: str
    moments: list[Moment]


class MatchReportTeam(StrictModel):
    team_id: str
    summary: str
    phases: list[ReportLine]
    strengths: list[ReportLine]
    weaknesses: list[ReportLine]
    key_player: str | None
    key_player_reason: str | None


class PlayPrinciples(StrictModel):
    session_id: str
    generation: int
    data_epoch: int
    playhead_ms: int
    next_cursor: str
    engine_version: Literal["principles_v1"] = PRINCIPLES_VERSION
    provenance: Literal["synthetic_events_and_tracking"] = "synthetic_events_and_tracking"
    structures: dict[str, TeamStructure]
    wingers: list[WingerRow]
    width: dict[str, TeamWidth]
    pressing: dict[str, TeamPressSystem]
    marking: dict[str, TeamMarking]
    movements: dict[str, TeamMovements]
    third_man: dict[str, TeamThirdMan]
    match_report: dict[str, MatchReportTeam]
    definitions: dict[str, str]
    limitations: list[str]
