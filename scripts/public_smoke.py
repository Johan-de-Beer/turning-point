"""Small HTTPS public-deployment check. Capabilities stay only in memory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from api_smoke import assert_cutoff


class SNITransport(httpx.HTTPTransport):
    def __init__(self, hostname: str):
        super().__init__()
        self.hostname = hostname

    def handle_request(self, request):
        request.extensions["sni_hostname"] = self.hostname
        return super().handle_request(request)


def run(base_url: str, connect_ip: str | None, routing_only: bool = False) -> dict:
    target = urlsplit(base_url)
    assert target.scheme == "https", "Public smoke requires HTTPS"
    endpoint = urlunsplit((target.scheme, connect_ip, target.path, "", "")) if connect_ip else base_url
    checks, durations = [], []
    headers = {"Host": target.netloc, "Origin": base_url.rstrip("/")}
    transport = SNITransport(target.hostname) if connect_ip else httpx.HTTPTransport()
    with httpx.Client(base_url=endpoint, transport=transport, headers=headers, timeout=15) as client:
        def call(method, path, **kwargs):
            started = time.perf_counter()
            response = client.request(method, path, **kwargs)
            durations.append((time.perf_counter() - started) * 1000)
            return response

        home = call("GET", "/")
        assert home.status_code == 200
        assert "Turning Point" in home.text
        assert "object-src 'none'" in home.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in home.headers["content-security-policy"]
        assert home.headers["x-content-type-options"] == "nosniff"
        assert "max-age=" in home.headers["strict-transport-security"]
        health = call("GET", "/api/health")
        assert health.status_code == 200 and health.headers["cache-control"] == "no-store"
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert call("GET", path).status_code == 404
        checks.append("valid HTTPS/SNI, same-origin frontend/API, security headers, no API documentation")

        metadata = call("GET", "/api/matches").json()
        match = metadata["matches"][0]
        assert len(metadata["matches"]) == 1 and match["provenance"] == "synthetic"
        assert not {"phase_plan", "seed", "final_score", "assertion_manifest"}.intersection(match)
        foreign = call("POST", "/api/sessions", headers={"Origin": "https://unrelated.invalid"}, json={})
        assert foreign.status_code == 403 and foreign.json()["code"] == "origin_not_allowed"
        oversize = call("POST", "/api/sessions", content=b"x" * 17000)
        assert oversize.status_code == 413
        checks.append("safe fixture metadata, foreign-origin rejection, bounded request body")

        if routing_only:
            return {"status": "passed", "base_url": base_url, "connection_override": connect_ip,
                "checks": checks, "http_requests": len(durations),
                "mean_http_ms": round(sum(durations) / len(durations), 2), "max_http_ms": round(max(durations), 2),
                "scope": "HTTPS/SNI routing, headers and public request bounds; business replay checked separately"}

        capability_a, capability_b = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        owner_a, owner_b = {"Authorization": f"Bearer {capability_a}"}, {"Authorization": f"Bearer {capability_b}"}
        payload = {"match_id": match["match_id"], "preferences": {"mode": "casual"}, "speed": 60}
        created_a = call("POST", "/api/sessions", headers={**owner_a, "Idempotency-Key": secrets.token_urlsafe(20)}, json=payload)
        created_b = call("POST", "/api/sessions", headers={**owner_b, "Idempotency-Key": secrets.token_urlsafe(20)}, json=payload)
        assert created_a.status_code in (200, 201) and created_b.status_code in (200, 201)
        a, b = created_a.json(), created_b.json()
        assert a["session_id"] != b["session_id"]
        for state in (a, b):
            assert_cutoff(state)
            assert state["recaps"]["full_time"]["status"] == "locked"
        path_a, path_b = f'/api/sessions/{a["session_id"]}', f'/api/sessions/{b["session_id"]}'
        assert call("GET", path_a + "/state", headers=owner_b).status_code == 404
        assert call("GET", path_a + "/state").status_code == 404
        played = call("POST", path_a + "/controls", headers={**owner_a, "Idempotency-Key": secrets.token_urlsafe(20)}, json={"action": "play", "expected_generation": a["generation"]})
        assert played.status_code == 200
        time.sleep(.3)
        advanced = call("GET", path_a + "/state", headers=owner_a).json()
        assert advanced["playhead_ms"] > 0
        paused = call("POST", path_a + "/controls", headers={**owner_a, "Idempotency-Key": secrets.token_urlsafe(20)}, json={"action": "pause", "expected_generation": a["generation"]})
        assert paused.status_code == 200
        still_b = call("GET", path_b + "/state", headers=owner_b).json()
        assert still_b["playhead_ms"] == 0
        assert_cutoff(advanced)
        checks.append("capability-isolated sessions, independent replay clocks, no future events/recap, working pause")

    return {"status": "passed", "base_url": base_url, "connection_override": connect_ip, "checks": checks,
        "http_requests": len(durations), "mean_http_ms": round(sum(durations) / len(durations), 2),
        "max_http_ms": round(max(durations), 2), "scope": "HTTPS public mock smoke; modest request count; no model calls, flood/load/security-certification claim"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://football.thedebeer.co.za")
    parser.add_argument("--connect-ip")
    parser.add_argument("--output", default=".runtime/public-smoke.json")
    parser.add_argument("--routing-only", action="store_true")
    args = parser.parse_args()
    result = run(args.base_url, args.connect_ip, args.routing_only)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
