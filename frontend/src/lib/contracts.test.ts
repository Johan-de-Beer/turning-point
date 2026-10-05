import { describe, expect, it } from 'vitest';
import { canAcceptState, defaultPreferences, eligibleOverlay, envelopeSchema, eventSchema, matchSchema, mergeObservedEvents, sessionSchema, validateSessionReferences, type Envelope, type Overlay, type Session } from './contracts';

const match = matchSchema.parse({ match_id: 'test_match', schema_version: '1.0', provenance: 'synthetic', home: { team_id: 'harbor', display_name: 'Harbor Athletic', short_name: 'HBR', color: '#38bdf8' }, away: { team_id: 'vale', display_name: 'Vale United', short_name: 'VAL', color: '#fbbf24' }, roster: [{ player_id: 'harbor_08', team_id: 'harbor', display_name: 'Test Harbor Player', shirt_number: 8, position: 'MID' }, { player_id: 'vale_08', team_id: 'vale', display_name: 'Test Vale Player', shirt_number: 8, position: 'MID' }], period_lengths_ms: [2700000, 2700000] });
const metrics = { shots: 0, on_target: 0, completed_passes: 0, attempted_passes: 0, pass_accuracy: null, final_third_entries: 0, box_entries: 0, possession_share: null, goals: 0 };
const state: Session = sessionSchema.parse({ schema_version: '1.0', session_id: 'session_a', match_id: match.match_id, generation: 1, data_epoch: 1, preferences_version: 1, status: 'paused', playhead_ms: 180000, observed_high_water_ms: 180000, period: 1, speed: 60, last_delivery_seq: 0, next_cursor: 'opaque_cursor', resync_required: false, preferences: defaultPreferences, score: { harbor: 0, vale: 0 }, events: [], snapshot: { snapshot_id: 'snapshot_a', session_id: 'session_a', generation: 1, data_epoch: 1, as_of_ms: 180000, delivery_cursor: 0, period: 1, window: { start_ms: 0, end_ms: 180000 }, coverage: { status: 'insufficient_evidence', eligible: false, known_in_play_ms: 0, owned_in_play_ms: { harbor: 0, vale: 0 }, stoppage_ms: 0, unknown_state_ms: 180000, state_valid: true }, team_metrics: { harbor: metrics, vale: metrics }, live_turnovers: 0, baseline: null, evidence_refs: [], rules_version: 'rules_v1' }, insights: [], overlay: null, recaps: {}, player_stats: {}, diagnostics: { provider: 'mock', provider_status: 'No external calls', pipeline: { ingest: 'waiting' }, agent_runs: [], ingestion_errors: [], suppressed_candidates: [], correction_notice: null, pending_jobs: 0, rules_version: 'rules_v1', definitions: {} } });
const event: Envelope = envelopeSchema.parse({ delivery_seq: 1, available_at_ms: 1000, event_id: 'evt_a', revision: 1, operation: 'upsert', payload: { match_id: match.match_id, event_time_ms: 1000, period: 1, kind: 'PASS', team_id: 'harbor', player_id: 'harbor_08', possession_id: 'pos_a', detail: { recipient_id: 'harbor_08', completed: true, start: { x: 40, y: 50 }, end: { x: 60, y: 50 } } } });

describe('versioned runtime network boundary', () => {
  it('rejects hidden fixture fields and invalid roster references in metadata', () => {
    expect(matchSchema.safeParse({ ...match, seed: 123 }).success).toBe(false);
    expect(matchSchema.safeParse({ ...match, roster: [{ ...match.roster[0], team_id: 'unknown' }] }).success).toBe(false);
  });
  it('rejects non-finite/out-of-range coordinates, impossible period times and unknown critical fields', () => {
    const payload = event.payload!;
    expect(eventSchema.safeParse({ ...payload, event_time_ms: 2800000 }).success).toBe(false);
    expect(eventSchema.safeParse({ ...payload, unexpected: true }).success).toBe(false);
    expect(eventSchema.safeParse({ ...payload, detail: { recipient_id: 'harbor_08', completed: true, start: { x: Number.POSITIVE_INFINITY, y: 0 }, end: { x: 101, y: 0 } } }).success).toBe(false);
    expect(envelopeSchema.safeParse({ ...event, available_at_ms: 0 }).success).toBe(false);
    expect(envelopeSchema.safeParse({ ...event, operation: 'delete' }).success).toBe(false);
  });
  it('rejects future observations and mismatched snapshot identity', () => {
    expect(sessionSchema.safeParse({ ...state, events: [{ ...event, available_at_ms: 180001 }] }).success).toBe(false);
    expect(sessionSchema.safeParse({ ...state, snapshot: { ...state.snapshot, generation: 2 } }).success).toBe(false);
    expect(() => validateSessionReferences({ ...state, events: [{ ...event, payload: { ...event.payload!, player_id: 'vale_08' } }] }, match)).toThrow('actor');
  });
});

describe('cutoff-safe replay state', () => {
  it('preserves canonical events on empty delta polls while paused', () => {
    const current = { ...state, events: [event] };
    expect(mergeObservedEvents(current, state).events).toEqual([event]);
    expect(mergeObservedEvents(current, { ...state, events: [event] }).events).toHaveLength(1);
  });
  it('uses the highest observed revision and applies tombstones without resurrecting events', () => {
    const revised = { ...event, revision: 2, delivery_seq: 2 };
    const tombstone: Envelope = { ...event, revision: 3, delivery_seq: 3, operation: 'delete', payload: null };
    const merged = mergeObservedEvents({ ...state, events: [event] }, { ...state, events: [revised, tombstone, event] });
    expect(merged.events).toEqual([tombstone]);
  });
  it('resets observed caches across replay generations or a server resync', () => {
    const current = { ...state, events: [event] };
    expect(mergeObservedEvents(current, { ...state, generation: 2 }).events).toEqual([]);
    expect(mergeObservedEvents(current, { ...state, resync_required: true }).events).toEqual([]);
  });
  it('rejects a late response from an older session, epoch, preferences or clock', () => {
    expect(canAcceptState(state, { ...state, session_id: 'other' })).toBe(false);
    expect(canAcceptState({ ...state, data_epoch: 2 }, state)).toBe(false);
    expect(canAcceptState({ ...state, preferences_version: 2 }, state)).toBe(false);
    expect(canAcceptState(state, { ...state, playhead_ms: 179999 })).toBe(false);
    expect(canAcceptState(state, { ...state, generation: 2, playhead_ms: 0 })).toBe(true);
  });
  it('enforces strict overlay expiry and every session/presentation version', () => {
    const overlay: Overlay = { overlay_id: 'overlay_a', insight_id: null, session_id: state.session_id, generation: 1, data_epoch: 1, mode: 'casual', language: 'en', valid_from_ms: 180000, valid_until_ms: 270000, priority: 50, display: { headline: 'Observed window', subline: 'Synthetic test' }, fact_ids: [], status: 'active' };
    expect(eligibleOverlay({ ...state, overlay })).toEqual(overlay);
    expect(eligibleOverlay({ ...state, overlay, playhead_ms: 270000 })).toBeNull();
    expect(eligibleOverlay({ ...state, overlay, playhead_ms: 179999 })).toBeNull();
    expect(eligibleOverlay({ ...state, overlay: { ...overlay, data_epoch: 2 } })).toBeNull();
    expect(eligibleOverlay({ ...state, overlay: { ...overlay, generation: 2 } })).toBeNull();
    expect(eligibleOverlay({ ...state, overlay: { ...overlay, mode: 'analyst' } })).toBeNull();
  });
});
