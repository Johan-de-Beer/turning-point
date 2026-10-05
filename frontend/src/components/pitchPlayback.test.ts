import { describe, expect, it } from 'vitest';
import { eventGeometry, PitchPlayback, sampleEvent } from './pitchPlayback';
import type { PitchEvent } from './pitchEvents';

const pass = (id = 'pass-1', overrides: Partial<PitchEvent> = {}): PitchEvent => ({
  event_id: id, revision: 1, delivery_seq: 1, available_at_ms: 1000, event_time_ms: 1000,
  period: 1, kind: 'PASS', team_id: 'harbor', player_id: 'h1',
  detail: { start: { x: 12, y: 24 }, end: { x: 80, y: 64 }, completed: true, recipient_id: 'h2' }, ...overrides,
});
const engine = () => new PitchPlayback('harbor', 'vale');

describe('functional recorded ball replay', () => {
  it('starts, travels along, and finishes the actual recorded pass, rather than a centre-forward template', () => {
    expect(sampleEvent(pass(), 0, 'harbor', 'vale').position).toEqual({ x: 12, y: 24 });
    expect(sampleEvent(pass(), .5, 'harbor', 'vale').position).toEqual({ x: 46, y: 44 });
    expect(sampleEvent(pass(), 1, 'harbor', 'vale').position).toEqual({ x: 80, y: 64 });
    const backwards = pass('back', { detail: { start: { x: 90, y: 15 }, end: { x: 20, y: 83 }, completed: false } });
    expect(sampleEvent(backwards, 1, 'harbor', 'vale').position).toEqual({ x: 20, y: 83 });
  });
  it('orients both teams and both halves using the record period', () => {
    expect(sampleEvent(pass('away', { team_id: 'vale' }), 1, 'harbor', 'vale').position).toEqual({ x: 20, y: 36 });
    expect(sampleEvent(pass('half2', { period: 2 }), 0, 'harbor', 'vale').position).toEqual({ x: 88, y: 76 });
    expect(sampleEvent(pass('away-half2', { team_id: 'vale', period: 2 }), 1, 'harbor', 'vale').position).toEqual({ x: 80, y: 64 });
  });
  it('uses the supplied shot endpoint, and does not invent one for legacy shots', () => {
    const shot = pass('shot', { kind: 'SHOT', detail: { position: { x: 82, y: 47 }, target: { x: 100, y: 51 }, outcome: 'goal' } });
    expect(sampleEvent(shot, 1, 'harbor', 'vale').position).toEqual({ x: 100, y: 51 });
    expect(eventGeometry({ ...shot, detail: { position: { x: 82, y: 47 }, outcome: 'goal' } }, 'harbor', 'vale')).toEqual({ from: { x: 82, y: 47 }, to: { x: 82, y: 47 }, moving: false });
  });
  it('plays every action in a multi-event delivery, including batches larger than eight', () => {
    const playback = engine();
    const records = Array.from({ length: 17 }, (_, i) => pass('p' + i, { delivery_seq: i + 1, event_time_ms: i * 100, available_at_ms: i * 100 }));
    playback.ingest(records, 2000, 1, 'session:1');
    const completed: string[] = [];
    for (let i = 0; i < 1000 && playback.completedCount < 17; i++) {
      playback.advance(.02, true, true, 60);
      if (playback.lastCompletedId && completed.at(-1) !== playback.lastCompletedId) completed.push(playback.lastCompletedId);
    }
    expect(completed).toEqual(records.map(record => record.event_id));
    expect(playback.completedCount).toBe(17);
    expect(playback.queuedCount).toBe(0);
  });
  it('does not repeat animations on identical polling/full-state/preference responses', () => {
    const playback = engine(); playback.ingest([pass()], 1000, 1, 's:1'); playback.advance(.5, true, true, 12); playback.advance(.5, true, true, 12);
    for (let i = 0; i < 12; i++) { playback.ingest([{ ...pass() }], 1000 + i, 1, 's:1'); playback.advance(.1, true, true, 12); }
    expect(playback.completedCount).toBe(1); expect(playback.queuedCount).toBe(0); expect(playback.frame?.progress).toBe(1);
  });
  it('freezes an in-flight football on pause and continues from the same point', () => {
    const playback = engine(); playback.ingest([pass()], 1000, 1, 's:1'); playback.advance(.2, true, true, 12);
    const paused = playback.frame;
    for (let i = 0; i < 20; i++) playback.advance(.075, false, true, 60);
    expect(playback.frame).toEqual(paused);
    expect(playback.advance(.2, true, true, 12)?.progress).toBeGreaterThan(paused!.progress);
  });
  it('reduced motion shows the latest known endpoint without a moving or looping effect', () => {
    const playback = engine(); const second = pass('p2', { delivery_seq: 2, detail: { start: { x: 80, y: 64 }, end: { x: 25, y: 12 } } });
    playback.ingest([pass(), second], 1000, 1, 's:1'); playback.advance(.1, true, false, 12);
    expect(playback.frame?.event.event_id).toBe('p2'); expect(playback.frame?.position).toEqual({ x: 25, y: 12 }); expect(playback.frame?.progress).toBe(1);
  });
  it('corrects active coordinates in place without replaying the old action; ignores older revision', () => {
    const playback = engine(); playback.ingest([pass()], 1000, 1, 's:1'); playback.advance(.2, true, true, 12);
    const progress = playback.frame!.progress;
    const revised = pass('pass-1', { revision: 2, detail: { start: { x: 12, y: 24 }, end: { x: 30, y: 80 } } });
    playback.ingest([revised], 1200, 1, 's:1');
    expect(playback.frame?.progress).toBe(progress); expect(playback.frame?.event.revision).toBe(2); expect(playback.queuedCount).toBe(0);
    playback.ingest([pass()], 1200, 1, 's:1'); expect(playback.frame?.event.revision).toBe(2);
  });
  it('withdraws a queued/active record and does not repeat it when a correction reinstates it', () => {
    const playback = engine(); const second = pass('p2', { delivery_seq: 2 });
    playback.ingest([pass(), second], 1000, 1, 's:1'); playback.ingest([second], 1100, 1, 's:1');
    expect(playback.frame?.event.event_id).toBe('p2');
    playback.ingest([second, pass('pass-1', { revision: 3 })], 1200, 1, 's:1'); expect(playback.queuedCount).toBe(0);
  });
  it('seeds a restored replay at the latest match-time position, not a late old arrival', () => {
    const latest = pass('latest', { event_time_ms: 9000, available_at_ms: 9000, delivery_seq: 2 });
    const late = pass('late', { delivery_seq: 99, available_at_ms: 10000 });
    const playback = engine(); playback.ingest([latest, late], 10000, 1, 's:1');
    expect(playback.frame?.event.event_id).toBe('latest'); expect(playback.frame?.progress).toBe(1); expect(playback.queuedCount).toBe(0);
  });
  it('clears the old queue/ball on generation change', () => {
    const playback = engine(); playback.ingest([pass()], 1000, 1, 's:1'); playback.advance(.3, true, true, 12);
    playback.ingest([], 0, 1, 's:2'); expect(playback.frame).toBeNull(); expect(playback.queuedCount).toBe(0); expect(playback.completedCount).toBe(0);
    playback.ingest([pass()], 1000, 1, 's:2'); expect(playback.frame?.progress).toBe(0);
  });
  it('renders every dense-batch action in motion and at its endpoint even on slow frames at sixty-speed', () => {
    const playback = engine();
    const records = Array.from({ length: 30 }, (_, i) => pass('dense-' + i, { delivery_seq: i + 1, event_time_ms: i * 50, available_at_ms: i * 50 }));
    playback.ingest(records, 2000, 1, 's:1');
    const moving = new Set<string>(), endpoints: string[] = [];
    for (let i = 0; i < 300 && playback.completedCount < records.length; i++) {
      const frame = playback.advance(.075, true, true, 60)!;
      if (frame.progress > 0 && frame.progress < 1) moving.add(frame.event.event_id);
      if (frame.progress === 1 && endpoints.at(-1) !== frame.event.event_id) endpoints.push(frame.event.event_id);
    }
    expect([...moving]).toEqual(records.map(record => record.event_id));
    expect(endpoints).toEqual(records.map(record => record.event_id));
  });
  it('preserves unfinished observed half-one actions when Continue delivers half two', () => {
    const half1 = pass('half1'), end = pass('end1', { kind: 'PERIOD_END', team_id: null, player_id: null, detail: {}, delivery_seq: 2, event_time_ms: 2700000, available_at_ms: 2700000 });
    const fresh = engine(); fresh.ingest([half1], 1000, 1, 's:1'); fresh.advance(.2, true, true, 12);
    const half2 = pass('half2', { period: 2, delivery_seq: 3, event_time_ms: 2700000, available_at_ms: 2700000 });
    fresh.ingest([half1, end, half2], 2700000, 2, 's:1');
    expect(fresh.frame?.event.event_id).toBe('half1');
    const displayed: string[] = [];
    for (let i = 0; i < 100 && fresh.completedCount < 3; i++) {
      const frame = fresh.advance(.075, true, true, 60)!;
      if (displayed.at(-1) !== frame.event.event_id) displayed.push(frame.event.event_id);
    }
    expect(displayed).toEqual(['half1', 'end1', 'half2']);
    expect(fresh.frame?.position).toEqual({ x: 20, y: 36 });
  });
  it('keeps a queued correction in match-time order despite its later delivery sequence', () => {
    const playback = engine();
    const first = pass('first', { event_time_ms: 500, available_at_ms: 500 });
    const middle = pass('middle', { delivery_seq: 2, event_time_ms: 1000, available_at_ms: 1000 });
    const last = pass('last', { delivery_seq: 3, event_time_ms: 1500, available_at_ms: 1500 });
    playback.ingest([first, middle, last], 2000, 1, 's:1');
    const corrected = { ...middle, revision: 2, delivery_seq: 99, available_at_ms: 2000, detail: { ...middle.detail, end: { x: 30, y: 40 } } };
    playback.ingest([first, corrected, last], 2000, 1, 's:1');
    const displayed: string[] = [];
    for (let i = 0; i < 100 && playback.completedCount < 3; i++) {
      const frame = playback.advance(.075, true, true, 60)!;
      if (displayed.at(-1) !== frame.event.event_id) displayed.push(frame.event.event_id);
      if (frame.event.event_id === 'middle') expect(frame.event.revision).toBe(2);
    }
    expect(displayed).toEqual(['first', 'middle', 'last']);
  });
  it('never queues a record ahead of event-time or delivery-availability cutoffs', () => {
    const playback = engine(); const delayed = pass('delayed', { available_at_ms: 4000 });
    playback.ingest([delayed], 3999, 1, 's:1'); expect(playback.frame).toBeNull();
    playback.ingest([delayed], 4000, 1, 's:1'); expect(playback.frame?.event.event_id).toBe('delayed');
    playback.ingest([delayed, pass('future', { event_time_ms: 6000, available_at_ms: 6000 })], 5000, 1, 's:1'); expect(playback.queuedCount).toBe(0);
  });
  it('hides the football on recorded dead-ball context, without a guessed restart trajectory', () => {
    const playback = engine(); const stop = pass('stop', { kind: 'STOPPAGE', player_id: null, team_id: null, delivery_seq: 2, detail: { reason: 'ball_out' } });
    playback.ingest([pass(), stop], 1000, 1, 's:1');
    for (let i = 0; i < 100 && playback.frame?.event.kind !== 'STOPPAGE'; i++) playback.advance(.02, true, true, 12);
    expect(playback.frame?.event.kind).toBe('STOPPAGE'); expect(playback.frame?.position).toBeNull();
  });
});
