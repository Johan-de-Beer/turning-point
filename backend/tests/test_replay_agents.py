import asyncio
import json
import time

import pytest

from backend.agents import AnalystProposal, EditorResult, MockProvider, bundle_for, templates, validate_editor, validate_proposal
from backend.generator import generate_fixture
from backend.metrics import score
from backend.models import Control, MetricSnapshot, Preferences, PreferencesPatch, SessionCreate
from backend.replay import FakeClock, ReplayService, ServiceError
from backend.storage import Storage

CAP = "s" * 64


def create(service, preferences=None, speed=60):
    return service.create(SessionCreate(match_id=service.match.match_id, preferences=preferences or Preferences(), speed=speed), CAP)


def play(service, session):
    service.controls(session, Control(action="play", expected_generation=session.generation))


def test_pause_speed_monotonic_reconnect_restart_and_isolation(service):
    replay, clock = service
    first, second = create(replay), create(replay)
    play(replay, first)
    clock.advance(1)
    assert replay.state(first).playhead_ms == 60_000 and replay.state(second).playhead_ms == 0
    replay.controls(first, Control(action="pause", expected_generation=1))
    clock.advance(50)
    assert replay.state(first).playhead_ms == 60_000
    replay.controls(first, Control(action="set_speed", speed=12, expected_generation=1))
    play(replay, first)
    clock.advance(1)
    assert replay.state(first).playhead_ms == 72_000
    replay.preferences(first, PreferencesPatch(mode="analyst", expected_preferences_version=1))
    assert second.preferences.mode == "casual"
    replay.controls(first, Control(action="restart", expected_generation=1))
    state = replay.state(first)
    assert state.generation == 2 and state.status == "ready" and state.playhead_ms == 0
    assert state.insights == [] and state.events == [] and state.overlay is None
    with pytest.raises(ServiceError):
        replay.controls(first, Control(action="play", expected_generation=1))


def test_backend_recovery_pauses_and_restores_observed_prefix(fixture, tmp_path):
    match, events = fixture
    path = str(tmp_path / "sessions.sqlite3")
    clock = FakeClock()
    first = ReplayService(match, events, Storage(path), clock=clock)
    session = create(first)
    play(first, session)
    clock.advance(2)
    first.state(session)
    sid = session.session_id
    first.storage.close()
    clock.advance(1000)
    recovered = ReplayService(match, events, Storage(path), clock=clock)
    restored = recovered.authorize(sid, CAP)
    state = recovered.state(restored)
    assert state.status == "paused" and state.playhead_ms == 120_000
    assert len(state.events) == len(session.ingestor.records)
    database_bytes = (tmp_path / "sessions.sqlite3").read_bytes()
    assert CAP.encode() not in database_bytes


def test_idle_session_expires_during_live_process(service):
    replay, _ = service
    session = create(replay)
    session.last_access_at = time.time() - 86401
    with pytest.raises(ServiceError) as error:
        replay.authorize(session.session_id, CAP)
    assert error.value.status == 404
    assert session.session_id not in replay.sessions
    assert replay.storage.sessions() == []


def test_rejected_critical_state_transition_blocks_coverage_until_resolved(service):
    from backend.models import EventEnvelope
    replay, clock = service
    invalid = next(e for e in replay.fixture if e.payload.kind == "POSSESSION").model_dump()
    invalid.update(event_id="invalid_state", delivery_seq=9000, available_at_ms=100_000)
    invalid["payload"].update(event_time_ms=100_000, player_id="vale_08")
    replay.fixture = sorted([*replay.fixture, EventEnvelope.model_validate(invalid)], key=lambda e: (e.available_at_ms, e.delivery_seq))
    session = create(replay)
    play(replay, session)
    clock.advance(3)
    state = replay.state(session)
    assert state.diagnostics.ingestion_errors
    assert state.snapshot.coverage.unknown_state_ms == 20_000
    assert not state.snapshot.coverage.state_valid and not state.snapshot.coverage.eligible
    clock.advance(2)
    clean = replay.state(session)
    assert clean.snapshot.coverage.unknown_state_ms == 0 and clean.snapshot.coverage.eligible


def test_backend_recovery_does_not_reset_pending_overlay_expiry(fixture, tmp_path):
    async def run():
        match, events = fixture
        path = str(tmp_path / "pending.sqlite3")
        clock = FakeClock()
        replay = ReplayService(match, events, Storage(path), clock=clock, provider=MockProvider(delay=.05))
        session = create(replay)
        play(replay, session)
        clock.advance(6)
        replay.state(session)
        await asyncio.sleep(.001)
        clock.advance(2)
        replay.state(session)
        sid = session.session_id
        await replay.shutdown()
        replay.storage.close()
        recovered = ReplayService(match, events, Storage(path), clock=clock, provider=MockProvider(delay=0))
        restored = recovered.authorize(sid, CAP)
        assert restored.status == "paused"
        play(recovered, restored)
        await recovered.drain()
        assert recovered.state(restored).overlay is None
        assert all(i.status == "expired" and not i.variants for i in restored.insights)
    asyncio.run(run())


def test_complete_fake_clock_replay_all_patterns_recaps_and_evidence(service):
    async def run():
        replay, clock = service
        replay.provider = MockProvider(delay=0)
        session = create(replay, Preferences(favorite_team_id="harbor", favorite_player_id="harbor_10"))
        play(replay, session)
        timings = []
        for half in (1, 2):
            for minute in range(45):
                clock.advance(1)
                started = time.perf_counter()
                state = replay.state(session)
                timings.append(time.perf_counter() - started)
                await replay.drain()
                for e in state.events:
                    assert e.available_at_ms <= state.playhead_ms
                    assert e.payload is None or e.payload.event_time_ms <= state.playhead_ms
                if half == 1:
                    assert state.recaps["full_time"].status == "locked"
            if half == 1:
                assert session.status == "half_time" and session.playhead_ms == 2_700_000
                assert score(replay.match, session.ingestor.records) == {"harbor": 1, "vale": 1}
                assert {i.pattern for i in session.insights if i.status == "ready"} == {"sustained_pressure", "sterile_possession", "end_to_end"}
                replay.controls(session, Control(action="continue_half", expected_generation=1))
        state = replay.state(session)
        assert state.status == "ended" and state.score == {"harbor": 2, "vale": 1}
        assert {i.pattern for i in state.insights if i.status == "ready"} == {"sustained_pressure", "sterile_possession", "end_to_end"}
        assert len([i for i in state.insights if i.status == "ready"]) >= 6
        assert state.overlay is None
        assert replay.provider.calls["football_analyst"] == replay.provider.calls["evidence_editor"]
        for insight in state.insights:
            if insight.status != "ready":
                continue
            assert insight.variants["casual"].fact_ids == insight.variants["analyst"].fact_ids
            assert insight.variants["casual"].explanation != insight.variants["analyst"].explanation
            evidence = replay.evidence(session, insight.insight_id)
            refs = {e.ref for e in evidence["events"]}
            assert all(set(f.source_event_refs) <= refs for f in insight.facts)
            assert all(e.available_at_ms <= state.playhead_ms for e in evidence["events"])
        for recap in state.recaps.values():
            assert recap.status == "ready" and len(recap.story_beats) <= 3
            assert set(recap.fact_ids) == {f.fact_id for f in recap.facts}
        # Measure actual duration; this is a broad local regression budget, not an SLA.
        assert max(timings) < 2
        print(f"Fake replay: {len(replay.fixture)} envelopes,90 observations,max={max(timings)*1000:.1f}ms")
    asyncio.run(run())


def test_overlay_pause_expiry_and_pause_on_insight(service):
    async def run():
        replay, clock = service
        replay.provider = MockProvider(delay=0)
        session = create(replay, Preferences(pause_on_insight=True))
        play(replay, session)
        clock.advance(6)
        replay.state(session)
        await replay.drain()
        state = replay.state(session)
        assert state.status == "paused" and state.overlay
        before = state.playhead_ms
        clock.advance(10)
        assert replay.state(session).playhead_ms == before and replay.state(session).overlay
        replay.preferences(session, PreferencesPatch(pause_on_insight=False, expected_preferences_version=1))
        play(replay, session)
        clock.advance(2)
        assert replay.state(session).overlay is None
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["wrong_number", "invented_goal", "causal", "unsupported_player", "future_reference", "invalid_json", "timeout", "transient"])
def test_provider_failure_rejected_and_transparent_fallback(service, failure):
    async def run():
        replay, clock = service
        replay.timeout_seconds = .015
        replay.provider = MockProvider(failure=failure, delay=0)
        session = create(replay)
        play(replay, session)
        clock.advance(6)
        replay.state(session)
        await replay.drain()
        insight = next(i for i in session.insights if i.status == "ready")
        assert set(insight.variants) == {"casual", "analyst"}
        expected = "mock_template" if failure == "transient" else "deterministic_fallback"
        assert insight.variants["casual"].provenance == expected
        assert not any("98765" in v.explanation for v in insight.variants.values())
        assert session.runs
        if failure != "transient":
            assert any(r.fallback_reason for r in session.runs)
    asyncio.run(run())


def test_hard_validation_binds_numbers_subjects_and_player_names(service):
    async def run():
        replay, clock = service
        replay.provider = MockProvider(delay=0)
        session = create(replay)
        play(replay, session)
        clock.advance(6)
        replay.state(session)
        await replay.drain()
        insight = next(i for i in session.insights if i.status == "ready")
        snap = MetricSnapshot.model_validate(replay.storage.get_snapshot(insight.anchor_snapshot_id))
        bundle = bundle_for(insight, replay.match, snap, session.preferences, 1)
        proposal = await replay.provider.analyst(bundle)
        # Wrong metric but number is present elsewhere in the fact set.
        entries = next(f.numeric_value for f in bundle.facts if f.metric == "final_third_entries")
        proposal.narrative_proposal = f"Harbor Athletic have {entries:g} shots."
        assert validate_proposal(bundle, proposal)
        proposal.narrative_proposal = "Imaginary Star controlled Harbor's pressure."
        assert validate_proposal(bundle, proposal)
        variants, overlay = templates(bundle)
        result = EditorResult(accepted=True, validation_errors=[], variants=variants, overlay=overlay)
        result.variants["casual"].explanation = "Vale United have 4 shots and will win."
        assert validate_editor(bundle, result)
    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["restart", "preferences", "expiry"])
def test_slow_reversed_jobs_never_publish_stale_variants(service, mutation):
    async def run():
        replay, clock = service
        replay.provider = MockProvider(delay=.02)
        session = create(replay)
        play(replay, session)
        clock.advance(6)
        replay.state(session)
        await asyncio.sleep(.005)
        if mutation == "restart":
            replay.controls(session, Control(action="restart", expected_generation=1))
        elif mutation == "preferences":
            # A newer fast job completes before the older slow proposal.
            replay.provider.delay = 0
            replay.preferences(session, PreferencesPatch(mode="analyst", expected_preferences_version=1))
        else:
            clock.advance(2)
            replay.state(session)
        await replay.drain()
        state = replay.state(session)
        assert any(r.status == "discarded" for r in session.runs)
        if mutation == "restart":
            assert state.insights == [] and state.overlay is None and state.generation == 2
        elif mutation == "preferences":
            assert all(v.preferences_version == 2 for i in state.insights for v in i.variants.values())
            assert state.overlay is None or state.overlay.mode == "analyst"
        else:
            assert state.overlay is None and all(i.status != "ready" for i in state.insights)
    asyncio.run(run())


def test_correction_not_delivered_early_retracts_score_overlay_and_recaps():
    async def run():
        match, fixture = generate_fixture(correction=True)
        clock = FakeClock()
        replay = ReplayService(match, fixture, Storage(":memory:"), clock=clock, provider=MockProvider(delay=0))
        session = create(replay)
        play(replay, session)
        clock.advance(6)
        replay.state(session)
        await replay.drain()
        old_insight = next(i.insight_id for i in session.insights if i.status == "ready")
        clock.advance(4.3)
        before = replay.state(session)
        assert before.score["harbor"] == 1 and before.data_epoch == 1
        assert all(e.revision == 1 for e in before.events)
        clock.advance(1.5)
        after = replay.state(session)
        await replay.drain()
        assert after.data_epoch == 2 and after.score["harbor"] == 0
        assert next(i for i in session.insights if i.insight_id == old_insight).status == "retracted"
        assert all(o.data_epoch == 2 for o in session.overlays)
        # Reach half-time, then simulate an internal late revision at the known cutoff.
        clock.advance(100)
        replay.state(session)
        assert session.recaps["half_time"].score["harbor"] == 0
        goal = next(e for e in session.ingestor.records.values() if e.payload and e.payload.kind == "SHOT" and e.payload.detail.outcome == "goal")
        revision = goal.model_dump()
        revision.update(revision=2, delivery_seq=9000, available_at_ms=2_700_000)
        revision["payload"]["detail"]["outcome"] = "saved"
        from backend.models import EventEnvelope
        replay.fixture.append(EventEnvelope.model_validate(revision))
        replay._release(session, 2_700_000)
        replay._refresh_recaps(session, corrected=True)
        assert session.recaps["half_time"].status == "corrected"
        assert session.recaps["half_time"].score == {"harbor": 0, "vale": 0}
    asyncio.run(run())


def test_favorites_keep_global_metrics_context_and_fact_ids(service):
    async def run():
        replay, clock = service
        replay.provider = MockProvider(delay=0)
        session = create(replay)
        play(replay, session)
        clock.advance(6)
        before = replay.state(session)
        await replay.drain()
        canonical_facts = {i.insight_id: [f.model_dump() for f in i.facts] for i in session.insights}
        replay.preferences(session, PreferencesPatch(mode="analyst", favorite_team_id="vale", favorite_player_id="vale_01", expected_preferences_version=1))
        after = replay.state(session)
        assert before.snapshot.team_metrics == after.snapshot.team_metrics and before.score == after.score
        assert canonical_facts == {i.insight_id: [f.model_dump() for f in i.facts] for i in session.insights}
        assert after.insights  # team match context stays visible
        assert all("vale_01" not in v.player_focus_ids for i in after.insights for v in i.variants.values())
    asyncio.run(run())
