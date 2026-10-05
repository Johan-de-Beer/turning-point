"""Fail if private fixture material is shipped in the production client."""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    distribution = ROOT / "frontend/dist"
    if not (distribution / "index.html").exists():
        raise SystemExit("Build frontend first: npm run build")
    fixture = ROOT / "server_data/fixtures/tp_demo_01.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    event_ids = {event["event_id"] for event in data["events"]}
    failures = []
    checked = 0
    for path in distribution.rglob("*"):
        if not path.is_file() or path.suffix not in (".js", ".html", ".css", ".json", ".map"):
            continue
        checked += 1
        text = path.read_text(encoding="utf-8")
        # Literal schema fields, not generic JS words such as a graphics random seed.
        private_fields = re.findall(r'["\'](?:seed|fixture_version|phase_plan|assertion_manifest|final_score|planned_pattern)["\']\s*:', text)
        if private_fields:
            failures.append(f"{path.relative_to(ROOT)} contains private fixture fields")
        if "server_data/fixtures" in text or "server_data\\fixtures" in text:
            failures.append(f"{path.relative_to(ROOT)} references private fixture storage")
        if any(event_id in text for event_id in event_ids):
            failures.append(f"{path.relative_to(ROOT)} embeds server fixture event IDs")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Client artifact audit passed: {checked} text artifacts, no private fixture fields, paths, or event IDs.")
    print("Scope: shipped static assets only; API cutoff checks are separate in api_smoke.py/browser-qa.mjs.")


if __name__ == "__main__":
    main()
