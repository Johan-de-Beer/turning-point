import { describe, expect, it } from 'vitest';
import sample from './fixtures/principles-20min.json';
import { movementsOf, principlesSchema, reportSections, shapeText, signed } from './principles';

// The sample is the backend's own report after 20 observed minutes (kept in sync by a backend test).
const report = principlesSchema.parse(sample);

describe('principles of play contract', () => {
  it('accepts the backend report and rejects drift or future observations', () => {
    expect(report.engine_version).toBe('principles_v1');
    expect(principlesSchema.safeParse({ ...structuredClone(sample), hidden_profile: {} }).success).toBe(false);
    const future = structuredClone(sample);
    (future.match_report.harbor.phases[0] as { moments: unknown[] }).moments = [{ time_ms: future.playhead_ms + 1, event_ref: null, label: 'Later' }];
    expect(principlesSchema.safeParse(future).success).toBe(false);
  });

  it('orders the match report like an analyst: phases, strengths, then weaknesses', () => {
    const sections = reportSections(report, 'harbor');
    expect(sections[0].title).toBe('Phase by phase');
    expect(sections[0].lines.map((line) => line.topic)).toEqual(['In possession', 'Out of possession', 'Attack to defence', 'Defence to attack', 'Set pieces']);
    for (const section of sections) for (const line of section.lines) expect(line.text).toMatch(/\d|yet\.$/);
  });

  it('formats structures, spare defenders and movement rows', () => {
    expect(shapeText({ shape: '2+3', base: ['RCB', 'LCB'], screen: ['LB', 'DM', 'RCM'] })).toBe('RCB, LCB | LB, DM, RCM');
    expect(signed(.84)).toBe('+0.8');
    expect(signed(-.84)).toBe('−0.8');
    const rows = movementsOf(report, 'harbor', 'drop_and_sprint');
    expect(rows.map((row) => row.episodes)).toEqual([...rows.map((row) => row.episodes)].sort((a, b) => b - a));
  });
});
