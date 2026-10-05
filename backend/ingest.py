"""Idempotent canonical revision ingestion with retained tombstone identity."""
from __future__ import annotations

from .models import EventEnvelope, Match


class IngestionError(ValueError):
    pass


def validate_references(match: Match, envelope: EventEnvelope):
    event = envelope.payload
    if event is None:
        return
    roster = {p.player_id: p.team_id for p in match.roster}
    teams = {match.home.team_id, match.away.team_id}
    if event.match_id != match.match_id:
        raise IngestionError("Event match does not match fixture")
    if event.team_id and event.team_id not in teams:
        raise IngestionError("Unknown team reference")
    if event.player_id and roster.get(event.player_id) != event.team_id:
        raise IngestionError("Actor does not belong to the event team")
    if event.kind == "PASS" and (roster.get(event.detail.recipient_id) != event.team_id or event.detail.recipient_id == event.player_id):
        raise IngestionError("Recipient must be a different player on the same team")


def canonical_order(records: dict[str, EventEnvelope]) -> list[EventEnvelope]:
    return sorted((e for e in records.values() if e.operation == "upsert"),
                  key=lambda e: (e.payload.event_time_ms, e.payload.period, e.delivery_seq))


def validate_state_sequence(records: dict[str, EventEnvelope], target_event_id: str | None = None):
    live = False
    owner = None
    possession_id = None
    current_period = None
    closed = False
    for envelope in canonical_order(records):
        e = envelope.payload
        def reject(message):
            if target_event_id is None or envelope.event_id == target_event_id:
                raise IngestionError(message)
        if e.kind == "PERIOD_START":
            if current_period == e.period or (current_period is not None and not closed):
                reject("Duplicate or overlapping period start")
            current_period, live, owner, possession_id = e.period, True, None, None
            closed = False
        elif e.period != current_period:
            reject("Event is missing its period start")
        elif closed:
            reject("Event occurs after its period ended")
        elif e.kind in ("PERIOD_END", "STOPPAGE"):
            live, owner, possession_id = False, None, None
            if e.kind == "PERIOD_END":
                closed = True
        elif e.kind == "POSSESSION":
            live, owner, possession_id = True, e.team_id, e.possession_id
        else:
            if not live or owner is None:
                reject("In-play event during stoppage or unknown possession")
            if e.possession_id != possession_id:
                reject("In-play event has a broken possession reference")
            if e.kind != "TACKLE" and e.team_id != owner:
                reject("Actor team does not own the current possession")


class Ingestor:
    def __init__(self, match: Match, records: dict[str, EventEnvelope] | None = None,
                 revisions: dict[str, EventEnvelope] | None = None):
        self.match = match
        self.records = records or {}
        self.revisions = revisions or {}
        self.identities = {event_id: next((e.payload for e in self.revisions.values() if e.event_id == event_id and e.payload), record.payload)
                           for event_id, record in self.records.items()}
        self.deliveries: dict[int, EventEnvelope] = {}

    def apply(self, envelope: EventEnvelope) -> tuple[bool, bool]:
        validate_references(self.match, envelope)
        old = self.records.get(envelope.event_id)
        identity = self.identities.get(envelope.event_id)
        # Identity/time checks also apply to duplicates and out-of-order revisions.
        if envelope.operation == "delete":
            if old is None or identity is None:
                raise IngestionError("Tombstone requires a retained original record")
            if envelope.available_at_ms < identity.event_time_ms:
                raise IngestionError("Tombstone delivered before original event time")
        elif identity and (identity.match_id, identity.period, identity.event_time_ms) != (envelope.payload.match_id, envelope.payload.period, envelope.payload.event_time_ms):
            raise IngestionError("A revision cannot change an event identity, period or time")
        same_delivery = self.deliveries.get(envelope.delivery_seq)
        if same_delivery:
            if same_delivery != envelope:
                raise IngestionError("Conflicting delivery sequence")
            return False, False
        previous_revision = self.revisions.get(envelope.ref)
        if previous_revision:
            if (previous_revision.operation, previous_revision.payload) != (envelope.operation, envelope.payload):
                raise IngestionError("Conflicting payload for the same event/revision")
            self.deliveries[envelope.delivery_seq] = envelope
            return False, False
        if old and envelope.revision <= old.revision:
            # Out-of-order earlier versions are retained but cannot replace canonical.
            self.revisions[envelope.ref] = envelope
            self.deliveries[envelope.delivery_seq] = envelope
            return False, False
        proposed = dict(self.records)
        proposed[envelope.event_id] = envelope
        if envelope.operation != "delete":
            # Previously accepted tombstones can leave an invalid historical
            # context. Validate this upsert's own context, allowing a later legal
            # possession transition to restore known state without inventing it.
            validate_state_sequence(proposed, target_event_id=envelope.event_id)
        # A valid tombstone may remove a state transition. Retain the deletion,
        # then let coverage fail closed on missing context; never invent a state.
        self.records = proposed
        self.revisions[envelope.ref] = envelope
        self.deliveries[envelope.delivery_seq] = envelope
        if identity is None and envelope.payload:
            self.identities[envelope.event_id] = envelope.payload
        return True, old is not None


def validate_fixture(match: Match, events: list[EventEnvelope]):
    if len({e.delivery_seq for e in events}) != len(events):
        raise IngestionError("Fixture delivery sequences must be unique")
    ingestor = Ingestor(match)
    for e in sorted(events, key=lambda e: (e.available_at_ms, e.delivery_seq)):
        ingestor.apply(e)
    validate_state_sequence(ingestor.records)
    markers = [e.payload for e in canonical_order(ingestor.records) if e.payload.kind in ("PERIOD_START", "PERIOD_END")]
    if [(m.period, m.kind) for m in markers] != [(1, "PERIOD_START"), (1, "PERIOD_END"), (2, "PERIOD_START"), (2, "PERIOD_END")]:
        raise IngestionError("A complete fixture needs both period start/end markers")
