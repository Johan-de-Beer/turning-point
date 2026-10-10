"""Regenerate the frontend's backend-contract samples (tactics at 15', analytics at 20')."""
import json
from pathlib import Path

from backend.analytics import AnalyticsEngine
from backend.generator import load_fixture
from backend.ingest import Ingestor
from backend.models import MatchAnalytics, TacticalReport
from backend.tactics import TacticalEngine

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "fixtures"


def records_until(match, events, cutoff):
    ingestor = Ingestor(match)
    for envelope in events:
        if envelope.available_at_ms <= cutoff:
            ingestor.apply(envelope)
    return ingestor.records


def main():
    match, events = load_fixture()
    tactics = TacticalEngine(match, events)
    analytics = AnalyticsEngine(match, events, tactics)
    for name, model, engine, cutoff in (("tactics-15min.json", TacticalReport, tactics, 900_000),
                                        ("analytics-20min.json", MatchAnalytics, analytics, 1_200_000)):
        report = model(session_id="sample", generation=1, data_epoch=1, playhead_ms=cutoff, next_cursor="c",
                       **engine.report(records_until(match, events, cutoff), cutoff))
        (ROOT / name).write_text(json.dumps(report.model_dump(mode="json"), indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
