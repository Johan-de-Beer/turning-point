"""Server-owned clocks, session isolation, correction handling and async publication."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .agents import EditorResult, EvidenceBundle, MockProvider, bundle_for, fingerprint, templates, validate_editor, validate_proposal
from .ingest import IngestionError, Ingestor, canonical_order
from .limits import ReplayLimits
from .metrics import DEFINITIONS, facts_for_snapshot, player_statistics, score, snapshot
from .models import AgentRun, Diagnostics, EventEnvelope, Insight, MetricSnapshot, Overlay, OverlayDisplay, PERIOD_MS, Preferences, Recap, RULES_VERSION, SessionState, TacticalReport
from .patterns import Candidate, PatternEngine, conditions_for
from .recaps import build_recap, locked_recap
from .storage import Storage
from .tactics import TacticalEngine


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, retryable: bool = False):
        self.code, self.message, self.status, self.retryable = code, message, status, retryable


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds: float):
        if seconds < 0:
            raise ValueError("A monotonic clock cannot move backwards")
        self.now += seconds


@dataclass
class Session:
    session_id: str
    capability_hash: str
    match_id: str
    preferences: Preferences
    speed: int
    ingestor: Ingestor
    generation: int = 1
    data_epoch: int = 1
    preferences_version: int = 1
    status: str = "ready"
    playhead_ms: int = 0
    fraction_ms: float = 0
    observed_high_water_ms: int = 0
    period: int = 1
    half_continued: bool = False
    last_delivery_seq: int = 0
    last_clock: float = 0
    next_evaluation_ms: int = 5000
    transport_version: int = 1
    delivered_seqs: set[int] = field(default_factory=set)
    history: list[tuple[int, EventEnvelope]] = field(default_factory=list)
    snapshot: MetricSnapshot | None = None
    insights: list[Insight] = field(default_factory=list)
    overlays: list[Overlay] = field(default_factory=list)
    recaps: dict[str, Recap] = field(default_factory=dict)
    runs: list[AgentRun] = field(default_factory=list)
    ingestion_errors: list[str] = field(default_factory=list)
    correction_notice: str | None = None
    pattern_engine: PatternEngine = field(default_factory=PatternEngine)
    queued_fingerprints: set[str] = field(default_factory=set)
    last_access_at: float = field(default_factory=time.time)
    invalid_state_transitions: list[tuple[int, int, int]] = field(default_factory=list)
    job_deadlines: dict[str, int] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    ready_at: float = field(default_factory=time.time)
    fixture_version: str = "synthetic_v1"

    def serialize(self) -> dict:
        return {"session_id": self.session_id, "capability_hash": self.capability_hash, "match_id": self.match_id,
            "preferences": self.preferences.model_dump(), "speed": self.speed, "generation": self.generation,
            "data_epoch": self.data_epoch, "preferences_version": self.preferences_version, "status": self.status,
            "playhead_ms": self.playhead_ms, "fraction_ms": self.fraction_ms, "observed_high_water_ms": self.observed_high_water_ms,
            "period": self.period, "half_continued": self.half_continued, "last_delivery_seq": self.last_delivery_seq,
            "next_evaluation_ms": self.next_evaluation_ms, "transport_version": self.transport_version,
            "delivered_seqs": sorted(self.delivered_seqs), "history": [[v, e.model_dump()] for v, e in self.history[-4096:]],
            "records": {k: v.model_dump() for k, v in self.ingestor.records.items()},
            "revisions": {k: v.model_dump() for k, v in self.ingestor.revisions.items()},
            "snapshot": self.snapshot.model_dump() if self.snapshot else None,
            "insights": [i.model_dump() for i in self.insights], "overlays": [o.model_dump() for o in self.overlays[-64:]],
            "recaps": {k: v.model_dump() for k, v in self.recaps.items()}, "runs": [r.model_dump() for r in self.runs[-64:]],
            "ingestion_errors": self.ingestion_errors[-20:], "correction_notice": self.correction_notice,
            "pattern_period": self.pattern_engine.period, "pattern_states": self.pattern_engine.states,
            "last_access_at": self.last_access_at,
            "invalid_state_transitions": self.invalid_state_transitions,
            "job_deadlines": self.job_deadlines,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "ready_at": self.ready_at,
            "fixture_version": self.fixture_version}


class ReplayService:
    def __init__(self, match, fixture: list[EventEnvelope], storage: Storage, clock: Callable[[], float] = time.monotonic,
                 provider=None, timeout_seconds: float = 3, limits: ReplayLimits | None = None):
        self.match, self.fixture, self.storage, self.clock = match, fixture, storage, clock
        self.provider = provider or MockProvider()
        self.timeout_seconds = max(.01, min(timeout_seconds, 30))
        self.limits = limits or ReplayLimits.environment()
        self.sessions: dict[str, Session] = {}
        self.lock = threading.RLock()
        self.tasks: dict[str, asyncio.Task] = {}
        self.semaphore = asyncio.Semaphore(2)
        self.last_persisted: dict[str, float] = {}
        # Synthetic tracking is built lazily (or warmed at startup) and released by playhead.
        self.tactics = TacticalEngine(match, fixture)
        self.restore()

    def restore(self):
        for raw in sorted(self.storage.sessions(), key=lambda r: r.get("last_access_at", 0), reverse=True):
            # Sequence IDs belong to one private fixture revision. Mixing a
            # restored older prefix with new deliveries corrupts paths/facts.
            if raw.get("fixture_version", "synthetic_v1") != self.match.fixture_version:
                self.storage.expire_session(raw["session_id"])
                continue
            raw.setdefault("created_at", raw.get("last_access_at", time.time()))
            # Existing records do not get a fresh unstarted lease merely because
            # the backend was upgraded; restart explicitly renews that lease.
            raw.setdefault("ready_at", raw["created_at"])
            if (len(self.sessions) >= self.limits.max_sessions or time.time() - raw.get("last_access_at", 0) > self.limits.idle_seconds
                    or time.time() - raw["created_at"] > self.limits.max_age_seconds):
                self.storage.expire_session(raw["session_id"])
                continue
            records = {k: EventEnvelope.model_validate(v) for k, v in raw.pop("records").items()}
            revisions = {k: EventEnvelope.model_validate(v) for k, v in raw.pop("revisions").items()}
            pattern_period, pattern_states = raw.pop("pattern_period", None), raw.pop("pattern_states", {})
            raw["preferences"] = Preferences.model_validate(raw["preferences"])
            raw["delivered_seqs"] = set(raw["delivered_seqs"])
            raw["history"] = [(v, EventEnvelope.model_validate(e)) for v, e in raw["history"]]
            raw["snapshot"] = MetricSnapshot.model_validate(raw["snapshot"]) if raw["snapshot"] else None
            raw["insights"] = [Insight.model_validate(i) for i in raw["insights"]]
            raw["overlays"] = [Overlay.model_validate(o) for o in raw["overlays"]]
            raw["recaps"] = {k: Recap.model_validate(v) for k, v in raw["recaps"].items()}
            raw["runs"] = [AgentRun.model_validate(r) for r in raw["runs"]]
            session = Session(**raw, ingestor=Ingestor(self.match, records, revisions), last_clock=self.clock())
            if self.expired(session):
                self.storage.expire_session(session.session_id)
                continue
            session.pattern_engine.period, session.pattern_engine.states = pattern_period, pattern_states
            if session.status not in ("half_time", "ended"):
                session.status = "paused"
            for run in session.runs:
                if run.status in ("queued", "running"):
                    run.status = "recoverable"
                    run.fallback_reason = "Backend restart interrupted this job; resume on user action"
                    self.storage.save_run(run)
            session.transport_version += 1
            self.sessions[session.session_id] = session
            self.persist(session, force=True)

    def expired(self, session: Session) -> bool:
        now = time.time()
        return (now - session.last_access_at > self.limits.idle_seconds or now - session.created_at > self.limits.max_age_seconds
                or (session.status == "ready" and now - session.ready_at > self.limits.ready_seconds)
                or (session.status == "ended" and now - (session.completed_at or session.last_access_at) > self.limits.ended_seconds))

    def expire(self, session_id: str):
        for key, task in list(self.tasks.items()):
            if key.startswith(session_id + ":"):
                task.cancel()
        self.storage.expire_session(session_id)
        self.sessions.pop(session_id, None)
        self.last_persisted.pop(session_id, None)

    def maintenance(self):
        for sid, session in list(self.sessions.items()):
            if self.expired(session):
                self.expire(sid)
            elif session.status == "playing" and time.time() - session.last_access_at > self.limits.disconnected_pause_seconds:
                session.status = "paused"
                session.last_clock = self.clock()
                session.transport_version += 1
                self.persist(session, force=True)
        self.storage.cleanup(set(self.sessions))

    @staticmethod
    def capability_hash(capability: str) -> str:
        return hashlib.sha256(capability.encode()).hexdigest()

    def authorize(self, session_id: str, capability: str) -> Session:
        session = self.sessions.get(session_id)
        if session and self.expired(session):
            self.expire(session_id)
            session = None
        if not session or not hmac.compare_digest(session.capability_hash, self.capability_hash(capability)):
            raise ServiceError("not_found", "Replay session was not found", 404)
        session.last_access_at = time.time()
        return session

    def validate_preferences(self, preferences: Preferences):
        teams = {self.match.home.team_id, self.match.away.team_id}
        players = {p.player_id: p for p in self.match.roster}
        if preferences.favorite_team_id and preferences.favorite_team_id not in teams:
            raise ServiceError("invalid_preferences", "Unknown favorite club", 422)
        if preferences.favorite_player_id and preferences.favorite_player_id not in players:
            raise ServiceError("invalid_preferences", "Unknown favorite player", 422)
        # Club and player may differ: a favorite player can play for another club.

    def create(self, request, capability: str) -> Session:
        if request.match_id != self.match.match_id:
            raise ServiceError("match_not_found", "Synthetic match was not found", 404)
        self.validate_preferences(request.preferences)
        for sid, old in list(self.sessions.items()):
            if self.expired(old):
                self.expire(sid)
        if len(self.sessions) >= self.limits.max_sessions:
            raise ServiceError("session_limit", "The demo is busy. Please try again shortly.", 429, True)
        sid = secrets.token_urlsafe(18)
        session = Session(session_id=sid, capability_hash=self.capability_hash(capability), match_id=request.match_id,
                          preferences=request.preferences, speed=request.speed, ingestor=Ingestor(self.match), last_clock=self.clock(),
                          fixture_version=self.match.fixture_version)
        session.snapshot = snapshot(self.match, {}, sid, 1, 1, 0, 1, 0)
        self.storage.save_snapshot(session.snapshot)
        session.recaps = {phase: locked_recap(session, phase) for phase in ("half_time", "full_time")}
        self.sessions[sid] = session
        self.persist(session, force=True)
        return session

    def persist(self, session: Session, force: bool = False):
        if session.session_id not in self.sessions:
            return
        now = self.clock()
        if not force and now - self.last_persisted.get(session.session_id, float("-inf")) < self.limits.persist_interval_seconds:
            return
        self.storage.save_session(session.session_id, session.capability_hash, session.serialize())
        self.last_persisted[session.session_id] = now

    def cursor(self, session: Session) -> str:
        body = json.dumps([session.session_id, session.generation, session.transport_version], separators=(",", ":")).encode()
        signature = hmac.new(self.storage.cursor_secret, body, hashlib.sha256).digest()[:16]
        return base64.urlsafe_b64encode(body + b"." + signature).decode().rstrip("=")

    def parse_cursor(self, session: Session, cursor: str | None) -> tuple[int | None, bool]:
        if not cursor:
            return None, False
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            body, signature = raw[:-17], raw[-16:]
            if raw[-17:-16] != b"." or not hmac.compare_digest(signature, hmac.new(self.storage.cursor_secret, body, hashlib.sha256).digest()[:16]):
                raise ValueError("Bad signature")
            sid, generation, version = json.loads(body)
            if sid != session.session_id or generation != session.generation or type(version) is not int:
                raise ValueError("Cursor identity mismatch")
            if version > session.transport_version or (session.history and version < session.history[0][0] - 1):
                raise ValueError("Cursor is outside retained history")
            return version, False
        except (ValueError, TypeError, json.JSONDecodeError):
            return None, True

    def reconcile(self, session: Session):
        now = self.clock()
        elapsed = max(0, now - session.last_clock)
        session.last_clock = now
        if session.status != "playing":
            return
        duration = elapsed * 1000 * session.speed + session.fraction_ms
        step = int(duration)
        session.fraction_ms = duration - step
        boundary = PERIOD_MS if not session.half_continued else 2 * PERIOD_MS
        target = min(boundary, session.playhead_ms + step)
        self._advance(session, target)

    def _release(self, session: Session, cutoff: int) -> bool:
        eligible = [e for e in self.fixture if e.delivery_seq not in session.delivered_seqs and e.available_at_ms <= cutoff
                    and (session.half_continued or self._envelope_period(e, session) == 1)]
        corrected = False
        if eligible:
            session.transport_version += 1
        for envelope in eligible:
            try:
                changed, revision = session.ingestor.apply(envelope)
                if changed and envelope.operation == "delete":
                    identity = session.ingestor.identities.get(envelope.event_id)
                    if identity and identity.kind in ("POSSESSION", "STOPPAGE", "PERIOD_START", "PERIOD_END"):
                        session.invalid_state_transitions.append((identity.event_time_ms, identity.period, envelope.delivery_seq))
                corrected |= changed and revision
                session.delivered_seqs.add(envelope.delivery_seq)
                session.last_delivery_seq = max(session.last_delivery_seq, envelope.delivery_seq)
                session.observed_high_water_ms = max(session.observed_high_water_ms, envelope.available_at_ms)
                session.history.append((session.transport_version, envelope))
                if changed and envelope.payload and envelope.payload.kind == "SHOT" and envelope.payload.detail.outcome == "goal":
                    current_score = score(self.match, session.ingestor.records)
                    session.overlays.append(Overlay(overlay_id=f"notice_{session.session_id}_{session.generation}_{session.data_epoch}_{envelope.ref}",
                        insight_id=None, session_id=session.session_id, generation=session.generation, data_epoch=session.data_epoch,
                        mode=session.preferences.mode, valid_from_ms=cutoff, valid_until_ms=cutoff + 90_000,
                        priority=100, display=OverlayDisplay(headline="Goal · observed score updated", subline="Observed goal event · see the scoreboard"),
                        fact_ids=[]))
            except IngestionError as exc:
                # Reject once, retain last valid observed prefix and show diagnostic.
                session.delivered_seqs.add(envelope.delivery_seq)
                session.ingestion_errors.append(f"{envelope.event_id}: {exc}")
                if envelope.payload and envelope.payload.kind in ("POSSESSION", "STOPPAGE", "PERIOD_START", "PERIOD_END"):
                    session.invalid_state_transitions.append((envelope.payload.event_time_ms, envelope.payload.period, envelope.delivery_seq))
        session.history = session.history[-4096:]
        if corrected:
            session.data_epoch += 1
            session.correction_notice = "A delivered synthetic event revision changed the observed data. Prior explanations were retracted and metrics recomputed."
            session.overlays.clear()
            self._correct_insights(session)
        return corrected

    def _envelope_period(self, envelope: EventEnvelope, session: Session) -> int:
        if envelope.payload:
            return envelope.payload.period
        identity = session.ingestor.identities.get(envelope.event_id)
        if identity:
            return identity.period
        original = next((e.payload for e in self.fixture if e.event_id == envelope.event_id and e.payload), None)
        return original.period if original else 2  # Unknown tombstones fail closed at the boundary.

    def _advance(self, session: Session, target: int):
        batch_corrected = False
        while session.next_evaluation_ms <= target:
            cutoff = session.next_evaluation_ms
            session.playhead_ms = cutoff
            corrected = self._release(session, cutoff)
            batch_corrected |= corrected
            session.snapshot = snapshot(self.match, session.ingestor.records, session.session_id, session.generation,
                session.data_epoch, cutoff, session.period, session.last_delivery_seq, session.invalid_state_transitions)
            self.storage.save_snapshot(session.snapshot)
            for candidate in session.pattern_engine.evaluate(session.snapshot):
                self._new_insight(session, candidate, session.snapshot)
            session.next_evaluation_ms += 5000
            if corrected:
                self._refresh_recaps(session, corrected=True)
        if session.playhead_ms != target:
            session.playhead_ms = target
            corrected = self._release(session, target)
            batch_corrected |= corrected
            if corrected:
                session.snapshot = snapshot(self.match, session.ingestor.records, session.session_id, session.generation,
                    session.data_epoch, target // 5000 * 5000, session.period, session.last_delivery_seq, session.invalid_state_transitions)
                self.storage.save_snapshot(session.snapshot)
                self._refresh_recaps(session, corrected=True)
        else:
            batch_corrected |= self._release(session, target)
        # Period-end markers must be delivered before a recap is eligible.
        markers = [e.payload for e in session.ingestor.records.values() if e.payload and e.operation == "upsert" and e.payload.kind == "PERIOD_END"]
        if target == PERIOD_MS and not session.half_continued and any(e.period == 1 for e in markers):
            session.status = "half_time"
            self._make_recap(session, "half_time")
        elif target == 2 * PERIOD_MS and any(e.period == 2 for e in markers):
            session.status = "ended"
            session.completed_at = session.completed_at or time.time()
            self._make_recap(session, "full_time")
        session.transport_version += 1
        self.persist(session, force=batch_corrected or session.status in ("half_time", "ended"))

    def _new_insight(self, session: Session, candidate: Candidate, snap: MetricSnapshot, supersedes: str | None = None):
        metrics = list(dict.fromkeys((condition.subject_id, condition.metric) for condition in candidate.conditions))
        facts = facts_for_snapshot(self.match, session.ingestor.records, snap, metrics)
        source_refs = {ref for fact in facts for ref in fact.source_event_refs}
        players = sorted({e.payload.player_id for e in session.ingestor.revisions.values()
                          if e.ref in source_refs and e.payload and e.payload.player_id and e.payload.team_id in candidate.subject_ids})
        insight_id = f"ins_{session.session_id}_{session.generation}_{session.data_epoch}_{snap.as_of_ms}_{candidate.pattern}"
        if any(i.insight_id == insight_id for i in session.insights):
            return
        insight = Insight(insight_id=insight_id, pattern=candidate.pattern, subject_ids=candidate.subject_ids,
            anchor_snapshot_id=snap.snapshot_id, facts=facts, observed_window=snap.window,
            interpretation="An observed match-window pattern passed deterministic demo thresholds and two consecutive evaluations.",
            limitations=["Synthetic event locations and descriptive heuristics; no prediction or causal claim.",
                         "Possession is integrated in-play time, not event frequency. These thresholds need football-expert review."],
            status="pending", supersedes_id=supersedes, conditions=candidate.conditions, supported_player_ids=players,
            generation=session.generation, data_epoch=session.data_epoch, episode_id=candidate.episode_id)
        session.insights.append(insight)
        self.storage.save_snapshot(snap)
        self.schedule(session, insight, snap)

    def _correct_insights(self, session: Session):
        old = [i for i in session.insights if i.status in ("pending", "ready", "corrected")]
        for insight in old:
            insight.status = "retracted"
            insight.variants.clear()
        session.queued_fingerprints.clear()
        # Re-derive every affected historical episode from the current canonical prefix.
        for previous in old:
            raw = self.storage.get_snapshot(previous.anchor_snapshot_id)
            if not raw:
                continue
            old_snap = MetricSnapshot.model_validate(raw)
            revised = snapshot(self.match, session.ingestor.records, session.session_id, session.generation,
                session.data_epoch, old_snap.as_of_ms, old_snap.period, session.last_delivery_seq, session.invalid_state_transitions)
            conditions = conditions_for(revised, previous.pattern, previous.subject_ids[0] if previous.pattern != "end_to_end" else None)
            if revised.coverage.eligible and all(c.passed for c in conditions):
                self._new_insight(session, Candidate(previous.pattern, previous.subject_ids, conditions, previous.episode_id), revised, previous.insight_id)

    def schedule(self, session: Session, insight: Insight, snap: MetricSnapshot):
        valid_until = session.job_deadlines.setdefault(insight.insight_id, session.playhead_ms + 90_000)
        if session.playhead_ms >= valid_until:
            insight.status = "expired"
            return
        bundle = bundle_for(insight, self.match, snap, session.preferences.model_copy(deep=True), session.preferences_version)
        # Correction evidence can describe an older football window but is known now.
        bundle.observed_cutoff_ms = session.playhead_ms
        key = fingerprint(bundle)
        if key in session.queued_fingerprints:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # Tests may operate synchronously and explicitly schedule later.
        if len(self.tasks) >= 8:
            insight.status = "rejected"
            session.ingestion_errors.append("Explanation queue is full; candidate was omitted")
            return
        session.queued_fingerprints.add(key)
        versions = (session.generation, session.data_epoch, session.preferences_version)
        task_key = f"{session.session_id}:{key}"
        task = loop.create_task(self._run_job(session.session_id, insight.insight_id, bundle, snap.snapshot_id, versions, valid_until))
        self.tasks[task_key] = task
        task.add_done_callback(lambda _task: self.tasks.pop(task_key, None))

    async def _run_job(self, sid: str, insight_id: str, bundle: EvidenceBundle, snapshot_id: str,
                       versions: tuple[int, int, int], valid_until: int):
        runs = []
        errors = []
        fallback = None
        result = None
        async with self.semaphore:
            async def call_role(role, function):
                run = AgentRun(run_id=secrets.token_urlsafe(12), role=role, provider=self.provider.name,
                    input_fingerprint=fingerprint(bundle), session_id=sid, generation=versions[0], data_epoch=versions[1],
                    snapshot_id=snapshot_id, rules_version=RULES_VERSION, preferences_version=versions[2],
                    mode=bundle.preferences.mode, language="en", status="running", fact_ids=[f.fact_id for f in bundle.facts],
                    validation_errors=[], duration_ms=0)
                runs.append(run)
                with self.lock:
                    session = self.sessions.get(sid)
                    if session:
                        session.runs.append(run)
                        session.runs = session.runs[-64:]
                        self.storage.save_run(run)
                        self.persist(session, force=True)
                started = time.perf_counter()
                try:
                    for attempt in range(2):
                        try:
                            output = await asyncio.wait_for(function(), timeout=self.timeout_seconds)
                            run.status = "approved"
                            return output
                        except (TimeoutError, ConnectionError, OSError):
                            if attempt:
                                raise
                    raise RuntimeError("Unreachable retry state")
                except Exception as exc:
                    run.status = "timeout" if isinstance(exc, TimeoutError) else "rejected"
                    run.validation_errors = [type(exc).__name__]
                    raise
                finally:
                    run.duration_ms = round((time.perf_counter() - started) * 1000)
                    self.storage.save_run(run)
            try:
                proposal = await call_role("football_analyst", lambda: self.provider.analyst(bundle))
                result = await call_role("evidence_editor", lambda: self.provider.editor(bundle, proposal))
                errors = validate_proposal(bundle, proposal) + validate_editor(bundle, result)
                if errors:
                    runs[-1].status = "rejected"
                    runs[-1].validation_errors = errors
                    # One bounded analyst revision, then independently review again.
                    proposal = await call_role("football_analyst", lambda: self.provider.analyst(bundle, errors))
                    result = await call_role("evidence_editor", lambda: self.provider.editor(bundle, proposal))
                    errors = validate_proposal(bundle, proposal) + validate_editor(bundle, result)
                if errors:
                    fallback = "Evidence Editor or hard validation rejected the revised explanation"
            except asyncio.CancelledError:
                for run in runs:
                    run.status = "discarded"
                    run.fallback_reason = "Job was cancelled"
                    self.storage.save_run(run)
                return
            except Exception as exc:
                fallback = f"{type(exc).__name__}: provider output unavailable or invalid"
            if fallback:
                variants, overlay = templates(bundle, "deterministic_fallback")
                result = EditorResult(accepted=True, validation_errors=[], variants=variants, overlay=overlay)
                errors = validate_editor(bundle, result)
                for run in runs:
                    run.fallback_reason = fallback
                if errors:
                    result = None
            with self.lock:
                session = self.sessions.get(sid)
                insight = next((i for i in session.insights if i.insight_id == insight_id), None) if session else None
                # These checks and the commit share one lock with all controls/ingestion.
                valid = (session and insight and (session.generation, session.data_epoch, session.preferences_version) == versions
                         and insight.status == "pending" and session.playhead_ms < valid_until)
                if not valid:
                    for run in runs:
                        run.status = "discarded"
                        run.fallback_reason = "Publication version or overlay-validity guard rejected a stale result"
                    if insight and insight.status == "pending" and session.playhead_ms >= valid_until:
                        insight.status = "expired"
                elif result is None:
                    insight.status = "rejected"
                else:
                    insight.variants = result.variants
                    insight.status = "corrected" if insight.supersedes_id else "ready"
                    if fallback:
                        runs[-1].status = "fallback"
                    session.overlays.append(Overlay(overlay_id=f"ov_{insight_id}_{versions[2]}", insight_id=insight_id,
                        session_id=sid, generation=versions[0], data_epoch=versions[1], mode=session.preferences.mode,
                        valid_from_ms=bundle.observed_cutoff_ms, valid_until_ms=valid_until, priority=50,
                        display=result.overlay, fact_ids=[f.fact_id for f in insight.facts]))
                    if session.preferences.pause_on_insight and session.status == "playing":
                        # Freeze at the last authoritative observation cutoff.
                        session.status = "paused"
                        session.last_clock = self.clock()
                    session.transport_version += 1
                    self._refresh_recaps(session, corrected=bool(session.correction_notice))
                for run in runs:
                    self.storage.save_run(run)
                if session:
                    self.persist(session, force=True)

    def _make_recap(self, session: Session, phase: str, corrected: bool = False):
        cutoff = PERIOD_MS if phase == "half_time" else 2 * PERIOD_MS
        marker = next((e for e in session.ingestor.records.values() if e.payload and e.operation == "upsert"
                       and e.payload.kind == "PERIOD_END" and e.payload.event_time_ms == cutoff), None)
        if not marker:
            session.recaps[phase] = locked_recap(session, phase)
            return
        recap_snapshot = snapshot(self.match, session.ingestor.records, session.session_id, session.generation,
            session.data_epoch, cutoff, 1 if phase == "half_time" else 2, session.last_delivery_seq, session.invalid_state_transitions)
        self.storage.save_snapshot(recap_snapshot)
        session.recaps[phase] = build_recap(self.match, session, phase, recap_snapshot, corrected)

    def _refresh_recaps(self, session: Session, corrected: bool = False):
        for phase, recap in session.recaps.items():
            if recap.status != "locked":
                self._make_recap(session, phase, corrected or recap.status == "corrected")

    def controls(self, session: Session, request):
        self.reconcile(session)
        if request.expected_generation != session.generation:
            raise ServiceError("generation_conflict", "Replay was restarted; resynchronize before controlling it")
        action = request.action
        if action in ("play", "continue_half") and session.status != "playing":
            playing = sum(s.status == "playing" for s in self.sessions.values())
            if playing >= self.limits.max_playing:
                raise ServiceError("playing_limit", "All demo replay slots are in use. Please try again shortly.", 429, True)
        if action == "restart":
            self.storage.reset_derived(session.session_id)
            session.generation += 1
            session.data_epoch = 1
            session.status, session.playhead_ms, session.fraction_ms = "ready", 0, 0
            session.completed_at = None
            session.ready_at = time.time()
            session.observed_high_water_ms, session.period, session.last_delivery_seq = 0, 1, 0
            session.half_continued, session.next_evaluation_ms = False, 5000
            session.ingestor = Ingestor(self.match)
            session.delivered_seqs.clear()
            session.history.clear()
            session.insights.clear()
            session.overlays.clear()
            session.runs.clear()
            session.queued_fingerprints.clear()
            session.pattern_engine = PatternEngine()
            session.correction_notice = None
            session.ingestion_errors.clear()
            session.invalid_state_transitions.clear()
            session.job_deadlines.clear()
            session.snapshot = snapshot(self.match, {}, session.session_id, session.generation, 1, 0, 1, 0)
            self.storage.save_snapshot(session.snapshot)
            session.recaps = {phase: locked_recap(session, phase) for phase in ("half_time", "full_time")}
        elif action == "set_speed":
            session.speed = request.speed
        elif action == "pause":
            if session.status == "playing":
                session.status = "paused"
        elif action == "play":
            if session.status in ("half_time", "ended"):
                raise ServiceError("phase_conflict", "Continue at half-time or restart after full-time")
            session.status = "playing"
            self._advance(session, session.playhead_ms)
            for insight in session.insights:
                if insight.status == "pending":
                    raw = self.storage.get_snapshot(insight.anchor_snapshot_id)
                    if raw:
                        self.schedule(session, insight, MetricSnapshot.model_validate(raw))
        elif action == "continue_half":
            if session.status != "half_time":
                raise ServiceError("phase_conflict", "Second period is available only after the first-half marker")
            session.half_continued, session.period, session.status = True, 2, "playing"
            session.next_evaluation_ms = PERIOD_MS + 5000
            self._release(session, PERIOD_MS)
            session.snapshot = snapshot(self.match, session.ingestor.records, session.session_id, session.generation,
                session.data_epoch, PERIOD_MS, 2, session.last_delivery_seq, session.invalid_state_transitions)
            self.storage.save_snapshot(session.snapshot)
        session.last_clock = self.clock()
        session.transport_version += 1
        self.persist(session, force=True)

    def preferences(self, session: Session, request):
        self.reconcile(session)
        if request.expected_preferences_version != session.preferences_version:
            raise ServiceError("preferences_conflict", "Preferences changed; resynchronize and try again")
        patch = request.model_dump(exclude={"expected_preferences_version"}, exclude_unset=True)
        if patch.get("mode", "casual") is None or patch.get("language", "en") is None or patch.get("pause_on_insight", False) is None:
            raise ServiceError("invalid_preferences", "Mode, language and pause-on-insight cannot be null", 422)
        preferences = Preferences.model_validate({**session.preferences.model_dump(), **patch})
        self.validate_preferences(preferences)
        session.preferences = preferences
        session.preferences_version += 1
        session.queued_fingerprints.clear()
        # Facts never change. Re-render approved canonical clauses for both audiences.
        for insight in session.insights:
            raw = self.storage.get_snapshot(insight.anchor_snapshot_id)
            if not raw or insight.status in ("retracted", "rejected", "expired"):
                continue
            snap = MetricSnapshot.model_validate(raw)
            if insight.status == "pending":
                self.schedule(session, insight, snap)
            else:
                bundle = bundle_for(insight, self.match, snap, preferences, session.preferences_version)
                provenance = next(iter(insight.variants.values())).provenance
                insight.variants, _ = templates(bundle, provenance)
        for overlay in session.overlays:
            overlay.mode = preferences.mode
        self._refresh_recaps(session)
        session.transport_version += 1
        self.persist(session, force=True)

    def active_overlay(self, session: Session) -> Overlay | None:
        eligible = [o for o in session.overlays if o.generation == session.generation and o.data_epoch == session.data_epoch
                    and o.mode == session.preferences.mode and o.valid_from_ms <= session.playhead_ms < o.valid_until_ms
                    and (o.insight_id is None or any(i.insight_id == o.insight_id and i.status in ("ready", "corrected") for i in session.insights))]
        return max(eligible, key=lambda o: (o.priority, o.valid_from_ms)) if eligible else None

    def state(self, session: Session, cursor: str | None = None) -> SessionState:
        self.reconcile(session)
        if session.status != "playing":
            self.persist(session)  # keep paused reconnect/access retention durable
        version, resync = self.parse_cursor(session, cursor)
        events = ([e for v, e in session.history if v > version] if version is not None else
                  sorted(session.ingestor.records.values(), key=lambda e: (e.payload.event_time_ms if e.payload else 0, e.delivery_seq)))
        insights = list(session.insights)
        insights.sort(key=lambda i: (session.preferences.favorite_team_id in i.subject_ids,
                                    session.preferences.favorite_player_id in i.supported_player_ids,
                                    i.observed_window.end_ms), reverse=True)
        pending = sum(i.status == "pending" for i in session.insights)
        return SessionState(session_id=session.session_id, match_id=session.match_id, generation=session.generation,
            data_epoch=session.data_epoch, preferences_version=session.preferences_version, status=session.status,
            playhead_ms=session.playhead_ms, observed_high_water_ms=session.observed_high_water_ms, period=session.period,
            speed=session.speed, last_delivery_seq=session.last_delivery_seq, next_cursor=self.cursor(session), resync_required=resync,
            preferences=session.preferences, score=score(self.match, session.ingestor.records), events=events,
            snapshot=session.snapshot, insights=insights, overlay=self.active_overlay(session), recaps=session.recaps,
            player_stats=player_statistics(self.match, session.ingestor.records),
            diagnostics=Diagnostics(provider=self.provider.name,
                provider_status="Deterministic mock roles; no external calls" if self.provider.name == "mock" else "Approved Microsoft Foundry adapter",
                pipeline={"ingest": "observed" if session.delivered_seqs else "waiting", "interpret": session.snapshot.coverage.status,
                          "explain": "pending" if pending else "reviewed" if any(i.variants for i in insights) else "waiting",
                          "render": "overlay_active" if self.active_overlay(session) else "timeline", "personalize": session.preferences.mode},
                agent_runs=session.runs[-12:], ingestion_errors=session.ingestion_errors[-20:],
                suppressed_candidates=session.pattern_engine.suppressed, correction_notice=session.correction_notice,
                pending_jobs=pending, definitions=DEFINITIONS))

    def evidence(self, session: Session, insight_id: str):
        self.reconcile(session)
        insight = next((i for i in session.insights if i.insight_id == insight_id), None)
        if not insight:
            raise ServiceError("not_found", "Observed insight was not found", 404)
        raw = self.storage.get_snapshot(insight.anchor_snapshot_id)
        refs = set(ref for fact in insight.facts for ref in fact.source_event_refs)
        events = [e for ref, e in session.ingestor.revisions.items() if ref in refs]
        # All evidence versions were delivered to this session; retained old versions
        # are explicitly marked retracted through their parent insight status.
        return {"session_id": session.session_id, "generation": session.generation, "data_epoch": session.data_epoch,
            "playhead_ms": session.playhead_ms, "next_cursor": self.cursor(session), "insight": insight,
            "snapshot": MetricSnapshot.model_validate(raw), "facts": insight.facts, "conditions": insight.conditions,
            "events": sorted(events, key=lambda e: (e.payload.event_time_ms if e.payload else 0, e.delivery_seq)), "metric_definitions": DEFINITIONS}

    def tactics_report(self, session: Session) -> TacticalReport:
        self.reconcile(session)
        report = self.tactics.report(session.ingestor.records, session.playhead_ms)
        return TacticalReport(session_id=session.session_id, generation=session.generation, data_epoch=session.data_epoch,
            playhead_ms=session.playhead_ms, next_cursor=self.cursor(session), **report)

    async def drain(self):
        if self.tasks:
            await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    async def shutdown(self):
        # Persist recoverable running status before cancellation. Next startup pauses.
        for session in self.sessions.values():
            self.persist(session, force=True)
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
