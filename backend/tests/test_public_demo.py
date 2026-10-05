import asyncio
import json
import secrets
import time

import pytest
from fastapi.testclient import TestClient

from backend.http_safety import DemoSafetyMiddleware, TokenBuckets
from backend.limits import ReplayLimits
from backend.main import create_app, make_provider
from backend.models import Control, Preferences, SessionCreate
from backend.replay import ServiceError
from backend.storage import Storage

ORIGIN = "https://football.thedebeer.co.za"
CAP = "p" * 64


def public_environment(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    monkeypatch.setenv("ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setenv("ALLOWED_HOSTS", "football.thedebeer.co.za,localhost,127.0.0.1,backend")
    monkeypatch.setenv("PROVIDER", "mock")


def headers(key=None):
    result = {"Authorization": "Bearer " + CAP, "Origin": ORIGIN}
    if key:
        result["Idempotency-Key"] = key
    return result


def test_public_demo_is_same_origin_mock_and_hides_docs(service, monkeypatch):
    public_environment(monkeypatch)
    replay, _ = service
    with TestClient(create_app(replay, background_clock=False), base_url=ORIGIN) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        response = client.get("/api/matches")
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        blocked = client.get("/api/matches", headers={"Origin": "https://other.example"})
        assert blocked.status_code == 403
        assert client.get("/api/health", headers={"Host": "other.example"}).status_code == 400
    monkeypatch.setenv("PROVIDER", "microsoft")
    with pytest.raises(RuntimeError, match="external inference"):
        make_provider()


def test_public_configuration_rejects_wildcard_and_insecure_origins(service, monkeypatch):
    public_environment(monkeypatch)
    replay, _ = service
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://football.thedebeer.co.za")
    with pytest.raises(RuntimeError, match="HTTPS"):
        create_app(replay)
    monkeypatch.setenv("ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        create_app(replay)


def test_create_limit_is_client_scoped_and_bounded(service, monkeypatch):
    public_environment(monkeypatch)
    replay, _ = service
    with TestClient(create_app(replay, background_clock=False), base_url=ORIGIN) as client:
        for _ in range(6):
            response = client.post("/api/sessions", headers=headers(secrets.token_hex(16)), json={"match_id": "tp_demo_01"})
            assert response.status_code == 200
        limited = client.post("/api/sessions", headers=headers(secrets.token_hex(16)), json={"match_id": "tp_demo_01"})
        assert limited.status_code == 429 and limited.json()["retryable"]
        assert limited.headers["Retry-After"] == "20"


def test_request_limits_for_headers_urls_and_streamed_body(service, monkeypatch):
    public_environment(monkeypatch)
    replay, _ = service
    with TestClient(create_app(replay, background_clock=False), base_url=ORIGIN) as client:
        assert client.get("/api/health?value=" + "x" * 2100).status_code == 414
        assert client.get("/api/health", headers={"X-Long": "x" * 17000}).status_code == 431
        assert client.post("/api/sessions", content=b"x" * 17000, headers=headers(secrets.token_hex(16))).status_code == 413

    async def run():
        dispatched = False
        async def app(scope, receive, send):
            nonlocal dispatched
            dispatched = True
        middleware = DemoSafetyMiddleware(app, public=False, origins=[])
        messages = iter([{"type": "http.request", "body": b"x" * 9000, "more_body": True},
                         {"type": "http.request", "body": b"x" * 9000, "more_body": True}])
        async def receive():
            return next(messages)
        sent = []
        async def send(message):
            sent.append(message)
        await middleware({"type": "http", "method": "POST", "path": "/api/sessions", "headers": []}, receive, send)
        assert not dispatched and sent[0]["status"] == 413
    asyncio.run(run())


def test_rate_bucket_memory_and_refill_are_bounded():
    now = [0.0]
    buckets = TokenBuckets(maximum=4, clock=lambda: now[0])
    assert buckets.take("owner", 2, 1) and buckets.take("owner", 2, 1)
    assert not buckets.take("owner", 2, 1)
    now[0] += 1
    assert buckets.take("owner", 2, 1)
    for i in range(20):
        buckets.take(str(i), 1, 1)
    assert len(buckets.buckets) == 4


def test_only_explicit_gateway_may_supply_real_ip(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_NETWORKS", "10.203.77.2/32")
    middleware = DemoSafetyMiddleware(None, public=True, origins=[ORIGIN])
    assert middleware.client_ip({"client": ("10.203.77.2", 100)}, {"x-real-ip": "203.0.113.5"}) == "203.0.113.5"
    assert middleware.client_ip({"client": ("10.203.77.9", 100)}, {"x-real-ip": "203.0.113.5"}) == "10.203.77.9"
    assert middleware.client_ip({"client": ("10.203.77.2", 100)}, {"x-real-ip": "invalid"}) == "10.203.77.2"
    monkeypatch.setenv("TRUSTED_PROXY_NETWORKS", "0.0.0.0/0")
    with pytest.raises(RuntimeError, match="every address"):
        DemoSafetyMiddleware(None, public=True, origins=[])


def test_limits_session_capacity_playing_and_absolute_expiry(service):
    replay, _ = service
    replay.limits = ReplayLimits(max_sessions=2, max_playing=1, idle_seconds=1800, max_age_seconds=21600)
    first = replay.create(SessionCreate(match_id=replay.match.match_id), CAP)
    second = replay.create(SessionCreate(match_id=replay.match.match_id), "s" * 64)
    with pytest.raises(ServiceError) as full:
        replay.create(SessionCreate(match_id=replay.match.match_id), "t" * 64)
    assert full.value.status == 429
    replay.controls(first, Control(action="play", expected_generation=1))
    with pytest.raises(ServiceError) as playing:
        replay.controls(second, Control(action="play", expected_generation=1))
    assert playing.value.code == "playing_limit"
    first.created_at = time.time() - 21601
    replay.maintenance()
    assert first.session_id not in replay.sessions
    assert replay.authorize(second.session_id, "s" * 64) == second


def test_idempotency_compression_capacity_ttl_and_expiry_cleanup():
    storage = Storage(":memory:", idempotency_seconds=60, max_idempotency_entries=3, max_idempotency_per_scope=2)
    large = {"observed": "event " * 10000}
    storage.check_idempotency_capacity("control:a:session")
    storage.save_idempotent("control:a:session", "first", "digest", large)
    stored = storage.db.execute("SELECT result FROM idempotency").fetchone()[0]
    assert isinstance(stored, bytes) and len(stored) < len(json.dumps(large)) / 10
    assert storage.idempotent("control:a:session", "first", "digest") == large
    storage.save_idempotent("control:a:session", "second", "digest", large)
    with pytest.raises(OverflowError):
        storage.check_idempotency_capacity("control:a:session")
    storage.db.execute("UPDATE idempotency SET created_at=?", (time.time() - 61,))
    assert storage.idempotent("control:a:session", "first", "digest") is None
    storage.cleanup(set())
    assert storage.db.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0] == 0


def test_restart_prunes_obsolete_derived_storage(service):
    replay, clock = service
    session = replay.create(SessionCreate(match_id=replay.match.match_id), CAP)
    replay.controls(session, Control(action="play", expected_generation=1))
    clock.advance(6)
    replay.state(session)
    assert replay.storage.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] > 60
    replay.controls(session, Control(action="restart", expected_generation=1))
    assert replay.storage.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1


def test_abandoned_ready_and_disconnected_playing_slots_release(service):
    replay, _ = service
    replay.limits = ReplayLimits(ready_seconds=120, disconnected_pause_seconds=30, ended_seconds=900)
    ready = replay.create(SessionCreate(match_id=replay.match.match_id), CAP)
    ready.created_at = time.time() - 121
    ready.ready_at = ready.created_at
    playing = replay.create(SessionCreate(match_id=replay.match.match_id), "q" * 64)
    replay.controls(playing, Control(action="play", expected_generation=1))
    playing.last_access_at = time.time() - 31
    replay.maintenance()
    assert ready.session_id not in replay.sessions and playing.status == "paused"
    playing.status = "ended"
    playing.completed_at = time.time() - 901
    replay.maintenance()
    assert playing.session_id not in replay.sessions


def test_restart_renews_ready_lease_without_extending_absolute_age(service):
    replay, _ = service
    replay.limits = ReplayLimits(ready_seconds=120, max_age_seconds=21600, ended_seconds=900)
    sessions = [replay.create(SessionCreate(match_id=replay.match.match_id), str(i) * 64) for i in (1, 2)]
    for session in sessions:
        session.created_at = time.time() - 150
        session.ready_at = session.created_at
        session.status = "ended"
        session.completed_at = time.time()
        original_created = session.created_at
        restarted_at = time.time()
        replay.controls(session, Control(action="restart", expected_generation=1))
        assert session.ready_at >= restarted_at and session.created_at == original_created
        assert session.status == "ready" and session.generation == 2
    first, waiting = sessions
    assert replay.authorize(first.session_id, "1" * 64) == first
    replay.controls(first, Control(action="play", expected_generation=2))
    assert first.status == "playing"
    waiting.ready_at = time.time() - 121
    with pytest.raises(ServiceError) as expired:
        replay.authorize(waiting.session_id, "2" * 64)
    assert expired.value.status == 404
    first.created_at = time.time() - 21601
    with pytest.raises(ServiceError):
        replay.authorize(first.session_id, "1" * 64)


def test_old_storage_ready_lease_has_safe_compatible_fallback(fixture):
    from backend.replay import FakeClock, ReplayService
    match, events = fixture
    storage = Storage(":memory:")
    limits = ReplayLimits(ready_seconds=120, max_age_seconds=21600)
    old = ReplayService(match, events, storage, clock=FakeClock(), limits=limits)
    waiting = old.create(SessionCreate(match_id=match.match_id), CAP)
    waiting.created_at = time.time() - 121
    raw = waiting.serialize()
    raw.pop("ready_at")
    storage.save_session(waiting.session_id, waiting.capability_hash, raw)
    completed = old.create(SessionCreate(match_id=match.match_id), "q" * 64)
    completed.created_at = time.time() - 150
    completed.status = "ended"
    completed.completed_at = time.time()
    raw = completed.serialize()
    raw.pop("ready_at")
    storage.save_session(completed.session_id, completed.capability_hash, raw)
    recovered = ReplayService(match, events, storage, clock=FakeClock(), limits=limits)
    assert waiting.session_id not in recovered.sessions
    restored = recovered.authorize(completed.session_id, "q" * 64)
    assert restored.ready_at == restored.created_at
    replay_start = time.time()
    recovered.controls(restored, Control(action="restart", expected_generation=1))
    assert restored.ready_at >= replay_start
    assert recovered.authorize(restored.session_id, "q" * 64) == restored


def test_four_public_sessions_finish_independently_with_bounded_work(service):
    async def run():
        replay, clock = service
        replay.limits = ReplayLimits(max_sessions=32, max_playing=4, idle_seconds=1800,
            max_age_seconds=21600, persist_interval_seconds=.5, ready_seconds=120,
            ended_seconds=900, disconnected_pause_seconds=30)
        sessions = [replay.create(SessionCreate(match_id=replay.match.match_id), str(i) * 64) for i in range(4)]
        for session in sessions:
            replay.controls(session, Control(action="play", expected_generation=1))
        maximum = 0
        for half in (1, 2):
            for minute in range(45):
                clock.advance(1)
                started = time.perf_counter()
                for session in sessions:
                    replay.state(session)
                maximum = max(maximum, time.perf_counter() - started)
                await replay.drain()
            if half == 1:
                for session in sessions:
                    replay.controls(session, Control(action="continue_half", expected_generation=1))
        for session in sessions:
            state = replay.state(session)
            assert state.status == "ended" and state.recaps["full_time"].status == "ready"
            assert len([i for i in state.insights if i.status == "ready"]) >= 6
        assert maximum < 2
        assert len(replay.tasks) == 0
        print(f"Four-session replay: maximum batch update {maximum*1000:.1f}ms")
    asyncio.run(run())
