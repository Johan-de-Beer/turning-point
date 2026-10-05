import math

import pytest
from pydantic import ValidationError

from backend.generator import generate_fixture
from backend.ingest import IngestionError, Ingestor, validate_fixture
from backend.models import Control, EventEnvelope, Point, Preferences, SessionCreate
from backend.metrics import score
from .conftest import event, point


def test_generator_reproducible_legal_and_complete():
    a, events = generate_fixture()
    b, again = generate_fixture()
    assert a == b and events == again
    validate_fixture(a, events)
    assert len(events) > 600
    assert all(e.available_at_ms >= e.payload.event_time_ms for e in events)
    assert {e.payload.kind for e in events} >= {"PERIOD_START", "PERIOD_END", "POSSESSION", "PASS", "CARRY", "SHOT", "STOPPAGE"}
    assert "seed" not in a.public().model_dump()


@pytest.mark.parametrize("value", [math.inf, math.nan, -1, 101, "42"])
def test_coordinates_strict_finite_and_bounded(value):
    with pytest.raises(ValidationError):
        Point(x=value, y=50)


@pytest.mark.parametrize("value", [True, "60", 2, 60.0])
def test_speed_enum_is_strict(value):
    with pytest.raises(ValidationError):
        SessionCreate(match_id="tp_demo_01", speed=value)


def test_unknown_fields_enums_period_times_and_capability_input_fail():
    with pytest.raises(ValidationError):
        Preferences(language="fr")
    with pytest.raises(ValidationError):
        Control(action="seek", expected_generation=1)
    with pytest.raises(ValidationError):
        Control(action="play", expected_generation=True)
    with pytest.raises(ValidationError):
        event(1, 100, "PERIOD_START")
    e = event(1, 0, "PERIOD_START").model_dump()
    e["payload"]["kind"] = "GOAL"
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(e)
    with pytest.raises(ValidationError):
        Point(x=50, y=50, shot_speed=99)


def test_duplicate_identical_revision_and_delivery_idempotent(fixture):
    match, events = fixture
    ingestion = Ingestor(match)
    assert ingestion.apply(events[0]) == (True, False)
    assert ingestion.apply(events[0]) == (False, False)
    repeated = events[0].model_copy(update={"delivery_seq": 10000})
    assert ingestion.apply(repeated) == (False, False)
    assert len(ingestion.records) == 1


def test_conflicting_same_revision_rejected_and_state_retained(fixture):
    match, events = fixture
    ingestion = Ingestor(match)
    for e in events[:3]:
        ingestion.apply(e)
    target = events[2]
    changed = target.model_dump()
    changed["delivery_seq"] = 10000
    changed["payload"]["detail"]["end"]["x"] += 1
    with pytest.raises(IngestionError, match="Conflicting"):
        ingestion.apply(EventEnvelope.model_validate(changed))
    assert ingestion.records[target.event_id] == target


def test_wrong_recipient_actor_and_live_state_rejected(fixture):
    match, events = fixture
    ingestion = Ingestor(match)
    for e in events[:2]:
        ingestion.apply(e)
    invalid = events[2].model_dump()
    invalid["payload"]["detail"]["recipient_id"] = "vale_07"
    with pytest.raises(IngestionError, match="Recipient"):
        ingestion.apply(EventEnvelope.model_validate(invalid))
    stop = event(5000, 1000, "STOPPAGE", detail={"reason": "ball_out"})
    ingestion.apply(stop)
    with pytest.raises(IngestionError, match="stoppage"):
        ingestion.apply(events[2])


def test_period_end_cannot_be_followed_by_play(fixture):
    match, _ = fixture
    ingestion = Ingestor(match)
    ingestion.apply(event(1, 0, "PERIOD_START"))
    ingestion.apply(event(2, 2_700_000, "PERIOD_END"))
    with pytest.raises(IngestionError, match="ended"):
        ingestion.apply(event(3, 2_700_000, "POSSESSION", "harbor", {"start": point(40)}))


def test_late_revision_deletion_old_revision_and_score(fixture):
    match, events = fixture
    ingestion = Ingestor(match)
    goal = next(e for e in events if e.payload.kind == "SHOT" and e.payload.detail.outcome == "goal")
    for e in events:
        if e.available_at_ms <= goal.available_at_ms:
            ingestion.apply(e)
    assert score(match, ingestion.records)["harbor"] == 1
    revision = goal.model_dump()
    revision.update(delivery_seq=10000, available_at_ms=goal.available_at_ms + 90_000, revision=2)
    revision["payload"]["detail"]["outcome"] = "saved"
    assert ingestion.apply(EventEnvelope.model_validate(revision)) == (True, True)
    assert score(match, ingestion.records)["harbor"] == 0
    assert ingestion.apply(goal.model_copy(update={"delivery_seq": 10001})) == (False, False)
    tombstone = EventEnvelope(delivery_seq=10002, available_at_ms=goal.available_at_ms + 100_000,
        event_id=goal.event_id, revision=3, operation="delete", payload=None)
    assert ingestion.apply(tombstone) == (True, True)
    assert ingestion.records[goal.event_id].payload is None
    assert ingestion.identities[goal.event_id].event_time_ms == goal.payload.event_time_ms
    bad = tombstone.model_copy(update={"delivery_seq": 10003, "event_id": "never_observed", "revision": 1})
    with pytest.raises(IngestionError, match="retained"):
        ingestion.apply(bad)


def test_late_new_event_uses_event_time_and_does_not_require_seq_order(fixture):
    match, events = fixture
    ingestion = Ingestor(match)
    for e in events[:4]:
        ingestion.apply(e)
    late = event(9000, 9000, "CARRY", "harbor", {"start": point(55), "end": point(72)})
    late = late.model_copy(update={"available_at_ms": 20_000, "payload": late.payload.model_copy(update={"possession_id": "pos_00001"})})
    assert ingestion.apply(late) == (True, False)
    assert ingestion.records[late.event_id].payload.event_time_ms == 9000


def test_out_of_order_revision_and_duplicate_tombstone_still_check_identity(fixture):
    match, events = fixture
    ingestion = Ingestor(match)
    for e in events[:3]:
        ingestion.apply(e)
    original = events[2]
    newer = original.model_copy(update={"delivery_seq": 8000, "revision": 3})
    ingestion.apply(newer)
    wrong_old = original.model_dump()
    wrong_old.update(delivery_seq=8001, revision=2)
    wrong_old["payload"]["event_time_ms"] -= 1
    with pytest.raises(IngestionError, match="identity"):
        ingestion.apply(EventEnvelope.model_validate(wrong_old))
    tombstone = EventEnvelope(delivery_seq=8002, available_at_ms=original.available_at_ms, event_id=original.event_id,
                              revision=4, operation="delete", payload=None)
    ingestion.apply(tombstone)
    early = tombstone.model_copy(update={"delivery_seq": 8003, "available_at_ms": 0})
    with pytest.raises(IngestionError, match="before"):
        ingestion.apply(early)


def test_state_transition_tombstone_retained_and_metrics_fail_closed(fixture):
    from backend.metrics import calculate_window
    match, events = fixture
    ingestion = Ingestor(match)
    for e in events[:4]:
        ingestion.apply(e)
    possession = events[1]
    tombstone = EventEnvelope(delivery_seq=9000, available_at_ms=30_000, event_id=possession.event_id,
                              revision=2, operation="delete", payload=None)
    assert ingestion.apply(tombstone) == (True, True)
    metrics = calculate_window(ingestion.records, ["harbor", "vale"], 1, 0, 180_000)
    assert not metrics.coverage.state_valid and not metrics.coverage.eligible
    # Legal later transitions and actions remain ingestible after the gap.
    for e in events[4:20]:
        ingestion.apply(e)
    clean = calculate_window(ingestion.records, ["harbor", "vale"], 1, 180_000, 360_000)
    assert clean.coverage.unknown_state_ms == 0 and clean.coverage.state_valid
