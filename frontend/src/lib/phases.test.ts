import { describe, expect, it } from 'vitest';
import sample from './fixtures/phases-20min.json';
import { busiestPhases, lineContrast, momentEventId, phasesSchema, teamNotes, xtText } from './phases';

// The sample is the backend's own report after 20 observed minutes (kept in sync by a backend test).
const report = phasesSchema.parse(sample);

describe('phases of play contract', () => {
  it('accepts the backend report and rejects drift or future observations', () => {
    expect(report.engine_version).toBe('phases_v1');
    expect(phasesSchema.safeParse({ ...structuredClone(sample), hidden_profile: {} }).success).toBe(false);
    const future = structuredClone(sample);
    future.notes[0].moments[0].time_ms = future.playhead_ms + 1;
    expect(phasesSchema.safeParse(future).success).toBe(false);
    const grid = structuredClone(sample);
    grid.xt_grid.values.pop();
    expect(phasesSchema.safeParse(grid).success).toBe(false);
  });

  it('splits live time into phases that add up', () => {
    for (const team of ['harbor', 'vale']) {
      const rows = busiestPhases(report, team);
      const seconds = rows.reduce((sum, row) => sum + row.seconds, 0);
      expect(seconds).toBeCloseTo(report.phases[team].live_seconds, 0);
      expect(rows.map((row) => row.seconds)).toEqual([...rows.map((row) => row.seconds)].sort((a, b) => b - a));
    }
  });

  it('gives every note numbers, something to watch for and moments that point at events', () => {
    const notes = teamNotes(report, 'harbor');
    expect(notes.length).toBeGreaterThan(0);
    for (const note of notes) {
      expect(note.quantitative).toMatch(/\d/);
      expect(note.look_for.length).toBeGreaterThan(10);
      for (const moment of note.moments) if (moment.event_ref) expect(momentEventId(moment)).toMatch(/^evt_\d+$/);
    }
  });

  it('describes the line-height contrast and formats xT', () => {
    expect(lineContrast(report, 'harbor', 'Harbor Athletic')).toMatch(/^Harbor Athletic's back four sits [\d.]+ m from goal when settled/);
    expect(xtText(.1412)).toBe('+0.141');
    expect(xtText(-.004)).toBe('−0.004');
    expect(xtText(null)).toBe('—');
  });
});
