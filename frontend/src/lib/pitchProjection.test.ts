import { describe, expect, it } from 'vitest';
import { defaultPreferences, mergeObservedEvents, type Envelope, type Session } from './contracts';
import { projectPitchState } from './pitchProjection';

const metrics = { shots: 0, on_target: 0, completed_passes: 0, attempted_passes: 0, pass_accuracy: null, final_third_entries: 0, box_entries: 0, possession_share: null, goals: 0, duels: 0, duels_won: 0, final_third_passes: 0, field_tilt: null, xg: 0 };
function session(events: Envelope[] = []): Session {
  return {
    schema_version: '1.0', session_id: 'session_a', match_id: 'test_match', generation: 1, data_epoch: 1, preferences_version: 1,
    status: 'playing', playhead_ms: 180000, observed_high_water_ms: 180000, period: 1, speed: 12, last_delivery_seq: 20,
    next_cursor: 'opaque_cursor', resync_required: false, preferences: defaultPreferences, score: { harbor: 0, vale: 0 }, events,
    snapshot: { snapshot_id: 'snapshot_a', session_id: 'session_a', generation: 1, data_epoch: 1, as_of_ms: 180000,
      delivery_cursor: 20, period: 1, window: { start_ms: 0, end_ms: 180000 },
      coverage: { status: 'insufficient_evidence', eligible: false, known_in_play_ms: 0, owned_in_play_ms: { harbor: 0, vale: 0 }, stoppage_ms: 0, unknown_state_ms: 180000, state_valid: true },
      team_metrics: { harbor: metrics, vale: metrics }, live_turnovers: 0, baseline: null, evidence_refs: [], rules_version: 'rules_v1' },
    insights: [], overlay: null, recaps: {}, player_stats: {},
    diagnostics: { provider: 'mock', provider_status: 'No external calls', pipeline: {}, agent_runs: [], ingestion_errors: [], suppressed_candidates: [], correction_notice: null, pending_jobs: 0, rules_version: 'rules_v1', definitions: {} },
  };
}
function pass(sequence: number): Envelope {
  return { delivery_seq: sequence, available_at_ms: sequence * 1000, event_id: `evt_${sequence}`, revision: 1, operation: 'upsert',
    payload: { match_id: 'test_match', event_time_ms: sequence * 1000, period: 1, kind: 'PASS', team_id: 'harbor', player_id: 'harbor_08', possession_id: 'pos_a',
      detail: { recipient_id: 'harbor_09', completed: true, start: { x: 17 + sequence, y: 32 }, end: { x: 31 + sequence, y: 46 } } } };
}

describe('server observation → canonical cache → functional pitch boundary', () => {
  it('preserves every delivered action in a large batch with exact endpoints and transport identity', () => {
    const batch = Array.from({ length: 12 }, (_, index) => pass(index + 1)).reverse();
    const canonical = mergeObservedEvents(session(), session(batch));
    const projection = projectPitchState(canonical);
    expect(projection.events).toHaveLength(12); // No last-eight/recent-window loss at accelerated speed.
    expect(projection.events.map((event) => event.delivery_seq)).toEqual(Array.from({ length: 12 }, (_, index) => index + 1));
    for (const source of batch) {
      const displayed = projection.events.find((event) => event.event_id === source.event_id)!;
      expect(displayed).toMatchObject({ ...source.payload, event_id: source.event_id, revision: source.revision, delivery_seq: source.delivery_seq, available_at_ms: source.available_at_ms });
      expect(displayed.detail).toEqual(source.payload!.detail);
    }
  });

  it('does not create new animation identities on paused empty updates, preferences, or repeated full state', () => {
    const original = session([pass(1), pass(2)]);
    const paused = mergeObservedEvents(original, { ...session(), status: 'paused' });
    const preferences = mergeObservedEvents(paused, { ...session([pass(2), pass(1)]), preferences_version: 2 });
    const full = mergeObservedEvents(preferences, session([pass(1), pass(2)]));
    for (const accepted of [paused, preferences, full]) {
      expect(projectPitchState(accepted).events).toEqual(projectPitchState(original).events);
      expect(projectPitchState(accepted).replayKey).toBe('session_a:1');
    }
  });

  it('retains corrections as higher revisions with later delivery time and removes withdrawn actions', () => {
    const first = pass(1);
    const correction: Envelope = { ...first, revision: 2, delivery_seq: 10, available_at_ms: 100000,
      payload: { ...first.payload!, kind: 'PASS', detail: { recipient_id: 'harbor_09', completed: false, start: { x: 18, y: 32 }, end: { x: 28, y: 21 } } } };
    const corrected = mergeObservedEvents(session([first, pass(2)]), session([correction]));
    const projected = projectPitchState(corrected).events;
    expect(projected.map((event) => [event.event_id, event.revision, event.delivery_seq])).toEqual([['evt_2', 1, 2], ['evt_1', 2, 10]]);
    expect(projected[1].event_time_ms).toBe(1000);
    expect(projected[1].available_at_ms).toBe(100000);
    expect(projected[1].detail).toEqual(correction.payload!.detail);
    const deleted: Envelope = { ...correction, revision: 3, delivery_seq: 11, operation: 'delete', payload: null };
    const withdrawn = mergeObservedEvents(corrected, session([deleted, first]));
    expect(projectPitchState(withdrawn).events.map((event) => event.event_id)).toEqual(['evt_2']);
  });

  it('highlights the immutable evidence revision without replacing the corrected live action', () => {
    const evidence = pass(1);
    const current: Envelope = { ...evidence, revision: 2, delivery_seq: 10, available_at_ms: 100000,
      payload: { ...evidence.payload!, kind: 'PASS', detail: { recipient_id: 'harbor_09', completed: true, start: { x: 10, y: 12 }, end: { x: 90, y: 87 } } } };
    const projection = projectPitchState(session([current]), evidence);
    expect(projection.events[0].revision).toBe(2);
    expect(projection.events[0].detail).toEqual(current.payload!.detail);
    expect(projection.selectedEvent?.revision).toBe(1);
    expect(projection.selectedEvent?.detail).toEqual(evidence.payload!.detail);
    expect(projection.events).toEqual(projectPitchState(session([current])).events);
  });

  it('never forwards an undelivered location, including a late historic correction or selected evidence', () => {
    const futureDelivery = { ...pass(1), available_at_ms: 180001 };
    const futureEvent = { ...pass(2), payload: { ...pass(2).payload!, event_time_ms: 180001 } };
    const projection = projectPitchState(session([pass(3), futureDelivery, futureEvent]), futureDelivery);
    expect(projection.events.map((event) => event.event_id)).toEqual(['evt_3']);
    expect(projection.selectedEvent).toBeNull();
  });

  it('changes replay identity on restart and empties the old canonical observation set', () => {
    const current = session([pass(1)]);
    const restarted = mergeObservedEvents(current, { ...session(), generation: 2, playhead_ms: 0 });
    expect(projectPitchState(restarted)).toEqual({ events: [], selectedEvent: null, replayKey: 'session_a:2' });
    expect(projectPitchState(null)).toEqual({ events: [], selectedEvent: null, replayKey: undefined });
  });

  it('forwards measured shot targets unchanged and invents no target for older shot records', () => {
    const source = pass(1);
    const shot: Envelope = { ...source, payload: { ...source.payload!, kind: 'SHOT', detail: { position: { x: 82, y: 44 }, target: { x: 99, y: 51 }, outcome: 'saved' } } };
    expect(projectPitchState(session([shot])).events[0].detail).toEqual(shot.payload!.detail);
    const older: Envelope = { ...shot, payload: { ...shot.payload!, kind: 'SHOT', detail: { position: { x: 82, y: 44 }, outcome: 'saved' } } };
    expect(projectPitchState(session([older])).events[0].detail).not.toHaveProperty('target');
  });
});
