import type { Envelope, Event, Session } from './contracts';

/** A discrete observed action, retaining the transport identity used to replay it once. */
export type ObservedPitchEvent = Event & {
  event_id: string;
  revision: number;
  delivery_seq: number;
  available_at_ms: number;
};

function observedEvent(record: Envelope, playheadMs: number): ObservedPitchEvent | null {
  if (!record.payload || record.operation !== 'upsert' || record.available_at_ms > playheadMs || record.payload.event_time_ms > playheadMs) return null;
  return {
    ...record.payload,
    event_id: record.event_id,
    revision: record.revision,
    delivery_seq: record.delivery_seq,
    available_at_ms: record.available_at_ms,
  };
}

/** Project the whole canonical observation set, never a recent-event display window.
 * Evidence is a separate immutable version; highlighting it cannot replace live data.
 */
export function projectPitchState(state: Session | null, selectedRecord: Envelope | null = null) {
  if (!state) return { events: [] as ObservedPitchEvent[], selectedEvent: null, replayKey: undefined };
  const events = state.events.flatMap((record) => {
    const event = observedEvent(record, state.playhead_ms);
    return event ? [event] : [];
  }).sort((a, b) => a.delivery_seq - b.delivery_seq);
  return {
    events,
    selectedEvent: selectedRecord ? observedEvent(selectedRecord, state.playhead_ms) : null,
    replayKey: `${state.session_id}:${state.generation}`,
  };
}
