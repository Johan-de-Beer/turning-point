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


class ShotDetail(StrictModel):
    position: Point
    outcome: Literal["goal", "saved", "blocked", "off_target"]
    # Synthetic recorded endpoint, supplied only once this shot is observed.
    # Legacy stored shots can remain source-only; never infer a missing target.
    target: Point | None = None


class TackleDetail(StrictModel):
    position: Point
    successful: bool = Field(strict=True)


class StoppageDetail(StrictModel):
    reason: Literal["ball_out", "foul", "goal", "interval"]


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
