import pytest

from backend.generator import load_fixture
from backend.models import EventEnvelope
from backend.replay import FakeClock, ReplayService
from backend.storage import Storage


@pytest.fixture(scope="session")
def fixture():
    return load_fixture()


@pytest.fixture
def service(fixture):
    match, events = fixture
    clock = FakeClock()
    storage = Storage(":memory:")
    replay = ReplayService(match, events, storage, clock=clock)
    return replay, clock


def event(seq, t, kind, team=None, detail=None, period=1, player=None, possession="pos_1", event_id=None):
    marker = kind in ("PERIOD_START", "PERIOD_END", "STOPPAGE")
    return EventEnvelope.model_validate({"delivery_seq": seq, "available_at_ms": t, "event_id": event_id or f"test_{seq}",
        "revision": 1, "operation": "upsert", "payload": {"match_id": "tp_demo_01", "event_time_ms": t,
        "period": period, "kind": kind, "team_id": team, "player_id": None if marker else player or f"{team}_08",
        "possession_id": None if marker else possession, "detail": detail or {}}})


def point(x, y=50):
    return {"x": x, "y": y}
