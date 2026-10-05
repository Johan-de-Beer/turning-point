import json
import secrets

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.models import SessionCreate

CAP = "c" * 64


def headers(cap=CAP, key=None):
    result = {"Authorization": "Bearer " + cap}
    if key:
        result["Idempotency-Key"] = key
    return result


@pytest.fixture
def client(service):
    replay, clock = service
    with TestClient(create_app(replay, background_clock=False)) as test_client:
        yield test_client, replay, clock


def create(client, cap=CAP, key=None):
    return client.post("/api/sessions", json={"match_id": "tp_demo_01", "speed": 60},
                       headers=headers(cap, key or secrets.token_hex(16)))


def control(client, sid, action, generation=1, cap=CAP, **kwargs):
    return client.post(f"/api/sessions/{sid}/controls", headers=headers(cap, secrets.token_hex(16)),
        json={"action": action, "expected_generation": generation, **kwargs})


def test_health_metadata_initial_state_and_no_spoilers(client):
    app, _, _ = client
    assert app.get("/api/health").json()["status"] == "ok"
    metadata = app.get("/api/matches").json()
    assert set(metadata) == {"matches"} and len(metadata["matches"][0]["roster"]) == 22
    assert not {"seed", "fixture_version", "events", "score", "phase_plan"} & set(metadata["matches"][0])
    response = create(app)
    assert response.status_code == 200
    state = response.json()
    assert state["status"] == "ready" and state["playhead_ms"] == 0 and state["events"] == []
    assert state["score"] == {"harbor": 0, "vale": 0}
    assert state["recaps"]["full_time"]["status"] == "locked"
    assert state["recaps"]["full_time"]["score"] == {}
    assert CAP not in response.text
    for prohibited in ("seed", "phase_plan", "fixture_version"):
        assert f'"{prohibited}"' not in response.text


def test_capabilities_isolate_data_control_evidence_overlay_and_recaps(client):
    app, _, _ = client
    sid = create(app).json()["session_id"]
    paths = [f"/api/sessions/{sid}/state", f"/api/sessions/{sid}/updates", f"/api/sessions/{sid}/overlay",
             f"/api/sessions/{sid}/recaps/full_time", f"/api/sessions/{sid}/insights/invented/evidence"]
    for path in paths:
        missing = app.get(path)
        wrong = app.get(path, headers=headers("w" * 64))
        assert missing.status_code == wrong.status_code == 404
        assert missing.json()["message"] == wrong.json()["message"]
    assert control(app, sid, "play", cap="w" * 64).status_code == 404
    assert app.patch(f"/api/sessions/{sid}/preferences", json={"mode": "analyst", "expected_preferences_version": 1}, headers=headers("w" * 64)).status_code == 404


def test_create_and_control_idempotency_and_conflicts(client):
    app, _, clock = client
    key = secrets.token_hex(16)
    first = create(app, key=key)
    assert create(app, key=key).json() == first.json()
    conflict = app.post("/api/sessions", json={"match_id": "tp_demo_01", "speed": 12}, headers=headers(key=key))
    assert conflict.status_code == 409
    sid = first.json()["session_id"]
    key = secrets.token_hex(16)
    body = {"action": "play", "expected_generation": 1}
    a = app.post(f"/api/sessions/{sid}/controls", json=body, headers=headers(key=key))
    clock.advance(2)
    b = app.post(f"/api/sessions/{sid}/controls", json=body, headers=headers(key=key))
    assert a.json() == b.json()
    body["action"] = "pause"
    assert app.post(f"/api/sessions/{sid}/controls", json=body, headers=headers(key=key)).status_code == 409


def test_invalid_api_input_uniform_errors_and_no_arbitrary_cutoff(client):
    app, _, _ = client
    for body in [{"match_id": "tp_demo_01", "speed": True}, {"match_id": "tp_demo_01", "speed": 2},
                 {"match_id": "tp_demo_01", "playhead_ms": 5_400_000},
                 {"match_id": "tp_demo_01", "preferences": {"language": "fr"}}]:
        response = app.post("/api/sessions", json=body, headers=headers(key=secrets.token_hex(16)))
        assert response.status_code == 422
        assert set(response.json()) == {"code", "message", "retryable", "correlation_id"}
    sid = create(app).json()["session_id"]
    state = app.get(f"/api/sessions/{sid}/state?cutoff_ms=5400000", headers=headers()).json()
    assert state["playhead_ms"] == 0 and state["events"] == []
    assert control(app, sid, "seek", playhead_ms=5_400_000).status_code == 422


def test_updates_cursors_scope_restart_resync_and_cutoff(client):
    app, _, clock = client
    a = create(app).json()
    b = create(app, cap="b" * 64).json()
    sid = a["session_id"]
    control(app, sid, "play")
    clock.advance(1)
    update = app.get(f"/api/sessions/{sid}/updates", params={"cursor": a["next_cursor"]}, headers=headers()).json()
    assert update["playhead_ms"] == 60_000
    assert update["events"] and all(e["available_at_ms"] <= update["playhead_ms"] for e in update["events"])
    wrong = app.get(f"/api/sessions/{sid}/updates", params={"cursor": b["next_cursor"]}, headers=headers()).json()
    assert wrong["resync_required"]
    current = control(app, sid, "restart").json()
    assert current["generation"] == 2
    resync = app.get(f"/api/sessions/{sid}/updates", params={"cursor": update["next_cursor"]}, headers=headers()).json()
    assert resync["resync_required"] and resync["events"] == []
    assert control(app, sid, "play", generation=1).status_code == 409


def test_half_boundary_and_full_recap_locked(client):
    app, _, clock = client
    sid = create(app).json()["session_id"]
    control(app, sid, "play")
    clock.advance(1000)
    state = app.get(f"/api/sessions/{sid}/state", headers=headers()).json()
    assert state["status"] == "half_time" and state["playhead_ms"] == 2_700_000 and state["period"] == 1
    assert all(e["payload"]["period"] == 1 for e in state["events"] if e["payload"])
    assert state["recaps"]["half_time"]["status"] == "ready"
    assert app.get(f"/api/sessions/{sid}/recaps/full_time", headers=headers()).json()["recap"]["status"] == "locked"
    second = control(app, sid, "continue_half").json()
    assert second["period"] == 2 and second["playhead_ms"] == 2_700_000
    assert any(e["payload"]["kind"] == "PERIOD_START" and e["payload"]["period"] == 2 for e in second["events"])
    clock.advance(1000)
    end = app.get(f"/api/sessions/{sid}/state", headers=headers()).json()
    assert end["status"] == "ended" and end["playhead_ms"] == 5_400_000
    assert end["recaps"]["full_time"]["status"] == "ready"


def test_local_cors_is_explicit_and_input_size_bounded(client):
    app, _, _ = client
    response = app.options("/api/sessions", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in response.headers
    response = app.post("/api/sessions", content="x" * 17000, headers=headers(key=secrets.token_hex(16)))
    assert response.status_code == 413
