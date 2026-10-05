import { coordinate, fixedOrientation, type PitchEvent, type PitchPoint } from './pitchEvents';

export interface EventGeometry { from: PitchPoint | null; to: PitchPoint | null; moving: boolean }
export interface PlaybackFrame extends EventGeometry {
  event: PitchEvent;
  position: PitchPoint | null;
  progress: number;
}

export function isObserved(event: PitchEvent, cutoff: number): boolean {
  return event.event_time_ms <= cutoff && (event.available_at_ms ?? event.event_time_ms) <= cutoff;
}

/** All endpoints come from delivered records. No guessed shot or off-ball position. */
export function eventGeometry(event: PitchEvent, homeId: string, awayId: string): EventGeometry {
  if (event.team_id !== homeId && event.team_id !== awayId) return { from: null, to: null, moving: false };
  const source = coordinate(event.detail.start) ?? coordinate(event.detail.position);
  const destination = event.kind === 'SHOT' ? coordinate(event.detail.target) : coordinate(event.detail.end);
  const orient = (point: PitchPoint | null) => point ? fixedOrientation(point, event.team_id === homeId, event.period) : null;
  const from = orient(source), to = orient(destination) ?? from;
  return { from, to, moving: !!from && !!destination && ['PASS', 'CARRY', 'SHOT'].includes(event.kind) };
}

export function sampleEvent(event: PitchEvent, progress: number, homeId: string, awayId: string): PlaybackFrame {
  const geometry = eventGeometry(event, homeId, awayId);
  const amount = Math.max(0, Math.min(1, progress));
  const position = geometry.from && geometry.to ? {
    x: geometry.from.x + (geometry.to.x - geometry.from.x) * amount,
    y: geometry.from.y + (geometry.to.y - geometry.from.y) * amount,
  } : null;
  return { ...geometry, event, position, progress: geometry.moving ? amount : 1 };
}

/** Visual replay duration, not a claim about measured ball-tracking time. */
export function eventDuration(event: PitchEvent): number {
  return event.kind === 'PASS' ? .85 : event.kind === 'CARRY' ? 1.1 : event.kind === 'SHOT' ? .75 : event.kind === 'POSSESSION' ? .18 : .3;
}

const version = (event: PitchEvent) => JSON.stringify([event.revision ?? 1, event.event_time_ms, event.period, event.kind, event.team_id, event.player_id, event.detail]);
const order = (a: PitchEvent, b: PitchEvent) => (a.delivery_seq ?? a.event_time_ms) - (b.delivery_seq ?? b.event_time_ms) || a.event_id.localeCompare(b.event_id);
const temporalOrder = (a: PitchEvent, b: PitchEvent) => a.event_time_ms - b.event_time_ms || order(a, b);

/** One ball, one delivered action at a time. Polling/revisions never replay old actions. */
export class PitchPlayback {
  private key = '';
  private initialized = false;
  private seen = new Map<string, string>();
  private pending: PitchEvent[] = [];
  private active: PitchEvent | null = null;
  private elapsed = 0;
  private cutoff = 0;
  completedCount = 0;
  lastCompletedId = '';

  private readonly homeId: string;
  private readonly awayId: string;
  constructor(homeId: string, awayId: string) { this.homeId = homeId; this.awayId = awayId; }

  ingest(events: readonly PitchEvent[], cutoff: number, period: number, key: string): void {
    if (key !== this.key || cutoff < this.cutoff) {
      this.key = key; this.initialized = false;
      this.seen.clear(); this.pending = []; this.active = null; this.elapsed = 0;
      this.completedCount = 0; this.lastCompletedId = '';
    }
    // Continue may arrive before the last half-one action has rendered. Keep
    // those observed actions ahead of half two; geometry uses each record's period.
    this.cutoff = cutoff;
    const observed = events.filter(event => isObserved(event, cutoff));
    const ids = new Set(observed.map(event => event.event_id));
    this.pending = this.pending.filter(event => ids.has(event.event_id));
    if (this.active && !ids.has(this.active.event_id)) { this.active = null; this.elapsed = 0; }
    const playable = (event: PitchEvent) => !!eventGeometry(event, this.homeId, this.awayId).from || ['STOPPAGE', 'PERIOD_START', 'PERIOD_END'].includes(event.kind);
    const eligible = observed.filter(event => event.period === period && playable(event)).sort(temporalOrder);
    if (!this.initialized) {
      this.initialized = true;
      if (cutoff > 5000) {
        for (const event of observed) this.seen.set(event.event_id, version(event));
        this.active = eligible.at(-1) ?? null;
        this.elapsed = this.active ? eventDuration(this.active) + .3 : 0;
        return; // Reconnect shows the last known location, not a replay of the entire history.
      }
    }
    for (const event of observed) {
      const previous = this.seen.get(event.event_id), signature = version(event);
      if (previous === signature) continue;
      if (previous !== undefined && (event.revision ?? 1) < JSON.parse(previous)[0]) continue;
      this.seen.set(event.event_id, signature);
      if (previous !== undefined) {
        if (this.active?.event_id === event.event_id) this.active = event;
        this.pending = this.pending.map(queued => queued.event_id === event.event_id ? event : queued);
      } else if (event.period <= period && playable(event)) this.pending.push(event);
    }
    this.pending.sort(temporalOrder);
    if (!this.active && this.pending.length) { this.active = this.pending.shift()!; this.elapsed = 0; }
  }

  get queuedCount(): number { return this.pending.length; }
  get frame(): PlaybackFrame | null {
    return this.active ? sampleEvent(this.active, this.elapsed / eventDuration(this.active), this.homeId, this.awayId) : null;
  }

  seekLatest(): void {
    if (this.pending.length) this.active = [this.active, ...this.pending].filter((event): event is PitchEvent => !!event).sort(temporalOrder).at(-1)!;
    this.pending = [];
    this.elapsed = this.active ? eventDuration(this.active) + .3 : 0;
  }

  advance(seconds: number, playing: boolean, motion: boolean, speed: number): PlaybackFrame | null {
    if (!playing) return this.frame;
    if (!motion) { this.seekLatest(); return this.frame; }
    // Catch up without consuming an entire unseen action between render calls.
    // Each moving event returns an intermediate position and its endpoint.
    const remaining = Math.max(0, seconds) * speed / 12 * Math.min(4, 1 + Math.max(0, this.pending.length - 3) / 6);
    if (!this.active && this.pending.length) { this.active = this.pending.shift()!; this.elapsed = 0; }
    if (this.active && remaining > 0) {
      const duration = eventDuration(this.active), hold = this.active.kind === 'SHOT' && this.active.detail.outcome === 'goal' ? .3 : .045;
      if (this.elapsed >= duration) {
        this.elapsed += remaining;
        if (this.elapsed >= duration + hold && this.pending.length) { this.active = this.pending.shift()!; this.elapsed = 0; }
      } else {
        this.elapsed += Math.min(remaining, duration / 2, duration - this.elapsed);
        if (this.elapsed >= duration) { this.completedCount++; this.lastCompletedId = this.active.event_id; }
      }
    }
    return this.frame;
  }
}
