"""Live local HTTP integration check. Never prints session capabilities."""
from __future__ import annotations

import argparse
import json
import secrets
import time
from pathlib import Path

import httpx


def assert_cutoff(state: dict) -> None:
    prohibited = {"seed", "phase_plan", "assertion_manifest", "final_score", "planned_pattern"}

    def inspect(value):
        if isinstance(value, dict):
            assert not prohibited.intersection(value), "Server-only fixture metadata was exposed"
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    inspect(state)
    assert state["snapshot"]["as_of_ms"] <= state["playhead_ms"]
    for envelope in state["events"]:
        assert envelope["available_at_ms"] <= state["playhead_ms"]
        if envelope["payload"]:
            assert envelope["payload"]["event_time_ms"] <= state["playhead_ms"]
    for insight in state["insights"]:
        assert insight["observed_window"]["end_ms"] <= state["playhead_ms"]
    overlay = state["overlay"]
    if overlay:
        assert overlay["generation"] == state["generation"]
        assert overlay["data_epoch"] == state["data_epoch"]
        assert overlay["valid_from_ms"] <= state["playhead_ms"] < overlay["valid_until_ms"]


def run(base_url: str) -> dict:
    checks = []
    durations = []
    with httpx.Client(base_url=base_url, timeout=10) as client:
        def request(method, path, **kwargs):
            started = time.perf_counter()
            response = client.request(method, path, **kwargs)
            durations.append((time.perf_counter() - started) * 1000)
            return response

        health = request("GET", "/api/health")
        assert health.status_code == 200
        metadata = request("GET", "/api/matches").json()
        assert "seed" not in json.dumps(metadata)
        assert "phase_plan" not in json.dumps(metadata)
        assert len(metadata["matches"]) == 1
        match = metadata["matches"][0]
        assert match["provenance"] == "synthetic"
        checks.append("health and safe fictional fixture metadata")

        capability_a, capability_b = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        headers_a = {"Authorization": f"Bearer {capability_a}", "Idempotency-Key": secrets.token_urlsafe(20)}
        headers_b = {"Authorization": f"Bearer {capability_b}", "Idempotency-Key": secrets.token_urlsafe(20)}
        body = {"match_id": match["match_id"], "preferences": {"mode": "casual"}, "speed": 60}
        created = request("POST", "/api/sessions", headers=headers_a, json=body)
        assert created.status_code in (200, 201), created.text
        state_a = created.json()
        created_b = request("POST", "/api/sessions", headers=headers_b, json=body)
        assert created_b.status_code in (200, 201), created_b.text
        state_b = created_b.json()
        assert state_a["session_id"] != state_b["session_id"]
        for state in (state_a, state_b):
            assert_cutoff(state)
            assert state["recaps"]["full_time"]["status"] == "locked"
        retry = request("POST", "/api/sessions", headers=headers_a, json=body)
        assert retry.status_code in (200, 201) and retry.json()["session_id"] == state_a["session_id"]
        assert request("POST", "/api/sessions", headers=headers_a, json={**body, "speed": 1}).status_code == 409
        checks.append("independent sessions, create idempotency, no initial spoilers")

        path_a = f'/api/sessions/{state_a["session_id"]}'
        path_b = f'/api/sessions/{state_b["session_id"]}'
        wrong = request("GET", path_a + "/state", headers=headers_b)
        absent = request("GET", "/api/sessions/not-a-session/state", headers=headers_b)
        assert wrong.status_code == absent.status_code == 404
        assert request("GET", path_a + "/state").status_code == 404
        control = {"action": "play", "expected_generation": state_a["generation"]}
        assert request("POST", path_a + "/controls", headers=headers_b, json=control).status_code == 404
        for response in (wrong, absent):
            assert {"code", "message", "retryable", "correlation_id"}.issubset(response.json())
        checks.append("capability isolation for data and control; uniform errors")

        async_headers = {**headers_a, "Idempotency-Key": secrets.token_urlsafe(20)}
        assert request("POST", path_a + "/controls", headers=async_headers, json=control).status_code == 200
        time.sleep(0.12)
        playing = request("GET", path_a + "/state", headers=headers_a).json()
        still_b = request("GET", path_b + "/state", headers=headers_b).json()
        assert playing["playhead_ms"] > state_a["playhead_ms"]
        assert still_b["playhead_ms"] == state_b["playhead_ms"]
        assert_cutoff(playing)
        paused = request("POST", path_a + "/controls", headers={**headers_a, "Idempotency-Key": secrets.token_urlsafe(20)}, json={"action": "pause", "expected_generation": state_a["generation"]}).json()
        time.sleep(0.06)
        after_pause = request("GET", path_a + "/state", headers=headers_a).json()
        assert after_pause["playhead_ms"] == paused["playhead_ms"]
        assert_cutoff(after_pause)
        checks.append("server clock advances independently; pause freezes cutoff")

        bad_cursor = request("GET", path_b + "/updates", params={"cursor": state_a["next_cursor"]}, headers=headers_b)
        assert bad_cursor.status_code in (200, 409)
        if bad_cursor.status_code == 200:
            assert bad_cursor.json()["resync_required"] is True
            assert bad_cursor.json()["session_id"] == state_b["session_id"]
        favorite = next(player for player in match["roster"] if player["team_id"] == match["home"]["team_id"])
        personalized = request("PATCH", path_a + "/preferences", headers=headers_a, json={"expected_preferences_version": paused["preferences_version"], "mode": "analyst", "favorite_team_id": match["home"]["team_id"], "favorite_player_id": favorite["player_id"]})
        assert personalized.status_code == 200, personalized.text
        personalized = personalized.json()
        assert personalized["score"] == paused["score"]
        assert personalized["snapshot"]["team_metrics"] == paused["snapshot"]["team_metrics"]
        assert request("GET", path_b + "/state", headers=headers_b).json()["preferences"]["mode"] == "casual"
        assert request("PATCH", path_a + "/preferences", headers=headers_a, json={"expected_preferences_version": paused["preferences_version"], "mode": "casual"}).status_code == 409
        checks.append("cursor binding, preference conflict, favorite facts and other-session isolation")

        old_cursor = personalized["next_cursor"]
        restart = request("POST", path_a + "/controls", headers={**headers_a, "Idempotency-Key": secrets.token_urlsafe(20)}, json={"action": "restart", "expected_generation": personalized["generation"]})
        assert restart.status_code == 200
        restarted = restart.json()
        assert restarted["generation"] == personalized["generation"] + 1
        assert restarted["playhead_ms"] == 0 and restarted["overlay"] is None
        assert not restarted["insights"] and restarted["recaps"]["full_time"]["status"] == "locked"
        expired = request("GET", path_a + "/updates", params={"cursor": old_cursor}, headers=headers_a)
        assert expired.status_code in (200, 409)
        if expired.status_code == 200:
            assert expired.json()["resync_required"] is True
        assert_cutoff(restarted)
        checks.append("restart clears derived state; old generation cursor cannot preserve stale output")

        assert request("POST", path_a + "/controls", headers={**headers_a, "Idempotency-Key": secrets.token_urlsafe(20)}, json={"action": "set_speed", "speed": 999, "expected_generation": restarted["generation"]}).status_code == 422
        assert request("PATCH", path_a + "/preferences", headers=headers_a, json={"expected_preferences_version": restarted["preferences_version"], "language": "xx"}).status_code == 422
        assert request("GET", path_a + "/recaps/full_time", headers=headers_a).json()["recap"]["status"] == "locked"
        checks.append("invalid speeds/language rejected; future recap locked")
    return {"status": "passed", "checks": checks, "http_requests": len(durations), "max_http_ms": round(max(durations), 2), "mean_http_ms": round(sum(durations) / len(durations), 2), "scope": "local HTTP smoke; no model calls; no full match or clean-machine assertion"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default=".runtime/api-smoke.json")
    args = parser.parse_args()
    result = run(args.base_url)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
