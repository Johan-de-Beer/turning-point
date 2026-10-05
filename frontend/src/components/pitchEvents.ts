export interface PitchEvent {
  event_id: string;
  event_time_ms: number;
  period: number;
  kind: string;
  team_id?: string | null;
  player_id?: string | null;
  detail: Record<string, unknown>;
}

export interface PitchPoint { x: number; y: number }
export interface DisplayEvent { event: PitchEvent; point: PitchPoint; start: PitchPoint | null; color: string }

export function coordinate(value: unknown): PitchPoint | null {
  if (typeof value !== 'object' || value === null) return null;
  const p = value as Record<string, unknown>;
  if (typeof p.x !== 'number' || typeof p.y !== 'number' || !Number.isFinite(p.x) || !Number.isFinite(p.y)) return null;
  if (p.x < 0 || p.x > 100 || p.y < 0 || p.y > 100) return null;
  return { x: p.x, y: p.y };
}

/** Fixed pitch: Harbor attacks screen-right in half one; both teams swap in half two. */
export function fixedOrientation(point: PitchPoint, home: boolean, period: number): PitchPoint {
  const forward = home === (period === 1);
  return forward ? point : { x: 100 - point.x, y: 100 - point.y };
}

export function displayEvents(events: readonly PitchEvent[], homeId: string, awayId: string, period: number, playhead: number, selected?: string | null): DisplayEvent[] {
  const eligible = events.filter(e => e.event_time_ms <= playhead && (selected ? e.event_id === selected : e.period === period && playhead - e.event_time_ms <= 90_000));
  return eligible.slice(-8).flatMap(event => {
    if (event.team_id !== homeId && event.team_id !== awayId) return [];
    const endpoint = coordinate(event.detail.end) ?? coordinate(event.detail.position) ?? coordinate(event.detail.start);
    if (!endpoint) return []; // No invented positions for events without coordinates.
    const home = event.team_id === homeId;
    const start = coordinate(event.detail.start);
    return [{ event, point: fixedOrientation(endpoint, home, event.period), start: start ? fixedOrientation(start, home, event.period) : null, color: home ? '#38bdf8' : '#fbbf24' }];
  });
}
