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
