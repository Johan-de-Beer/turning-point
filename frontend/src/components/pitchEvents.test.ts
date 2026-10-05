import { describe, expect, it } from 'vitest';
import { coordinate, displayEvents, fixedOrientation, type PitchEvent } from './pitchEvents';

describe('schematic event rendering', () => {
  it('rotates team-relative locations and switches ends after halftime', () => {
    expect(fixedOrientation({ x: 80, y: 20 }, true, 1)).toEqual({ x: 80, y: 20 });
    expect(fixedOrientation({ x: 80, y: 20 }, false, 1)).toEqual({ x: 20, y: 80 });
    expect(fixedOrientation({ x: 80, y: 20 }, true, 2)).toEqual({ x: 20, y: 80 });
    expect(fixedOrientation({ x: 80, y: 20 }, false, 2)).toEqual({ x: 80, y: 20 });
  });
  it('rejects invalid and missing coordinates instead of inventing positions', () => {
    expect(coordinate({ x: Infinity, y: 10 })).toBeNull();
    expect(coordinate({ x: 101, y: 10 })).toBeNull();
    expect(coordinate({ x: 50 })).toBeNull();
  });
  it('never renders future or unrelated selected markers', () => {
    const event: PitchEvent = { event_id: 'e1', event_time_ms: 1000, period: 1, kind: 'SHOT', team_id: 'harbor', detail: { position: { x: 90, y: 50 } } };
    expect(displayEvents([event], 'harbor', 'vale', 1, 999)).toEqual([]);
    expect(displayEvents([event], 'harbor', 'vale', 1, 2000, 'missing')).toEqual([]);
    expect(displayEvents([event], 'harbor', 'vale', 1, 2000, 'e1')).toHaveLength(1);
    expect(displayEvents([{ ...event, detail: {} }], 'harbor', 'vale', 1, 2000)).toEqual([]);
  });
});
