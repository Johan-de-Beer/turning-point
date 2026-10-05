"""Measure deterministic replay work separately from network and provider latency."""
from __future__ import annotations

import asyncio
import json
import platform
import secrets
import statistics
import time
from pathlib import Path

from backend.agents import MockProvider
from backend.generator import load_fixture
from backend.models import Control, SessionCreate
from backend.replay import FakeClock, ReplayService
from backend.storage import Storage


async def main() -> None:
    match, fixture = load_fixture()
    clock = FakeClock()
    storage = Storage(":memory:")
    service = ReplayService(match, fixture, storage, clock=clock, provider=MockProvider(delay=0))
    session = service.create(SessionCreate(match_id=match.match_id, speed=60), secrets.token_urlsafe(32))
    service.controls(session, Control(action="play", expected_generation=1))
    timings = []
    try:
        for half in (1, 2):
            if half == 2:
                service.controls(session, Control(action="continue_half", expected_generation=1))
            for _ in range(540):
                # One exact 5-second simulated evaluation per measured call.
                clock.advance(5 / 60)
                started = time.perf_counter()
                service.reconcile(session)
                timings.append((time.perf_counter() - started) * 1000)
                await service.drain()
            # Floating clock increments may leave a final millisecond remainder.
            clock.advance(.001)
            service.reconcile(session)
            await service.drain()
        state = service.state(session)
        assert state.status == "ended"
        patterns = sorted({insight.pattern for insight in state.insights if insight.status in ("ready", "corrected")})
        assert patterns == ["end_to_end", "sterile_possession", "sustained_pressure"]
        ordered = sorted(timings)
        result = {"status": "passed", "python": platform.python_version(), "platform": platform.platform(), "fixture_envelopes": len(fixture), "observed_records": len(session.ingestor.records), "evaluations_measured": len(timings), "mean_reconcile_ms": round(statistics.mean(timings), 3), "p95_reconcile_ms": round(ordered[int(len(ordered) * .95) - 1], 3), "max_reconcile_ms": round(max(timings), 3), "confirmed_patterns": patterns, "scope": "single in-memory SQLite session; exact5simulated-second calls; provider stages drained separately with mock delay0; excludes HTTP/browser and external model latency"}
        output = Path(".runtime/replay-measurement.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        await service.shutdown()
        storage.close()


if __name__ == "__main__":
    asyncio.run(main())
