import { describe, expect, it } from 'vitest';
import sample from './fixtures/analytics-20min.json';
import { analyticsSchema, pvText, teamWorkload, tiltSummary } from './analytics';

// The sample is the backend's own report after 20 observed minutes (kept in sync by a backend test).
const report = analyticsSchema.parse(sample);

describe('live analytics contract', () => {
  it('accepts the backend report and rejects drift or future observations', () => {
    expect(report.engine_version).toBe('analytics_v1');
    expect(analyticsSchema.safeParse({ ...structuredClone(sample), hidden_profile: {} }).success).toBe(false);
    const future = structuredClone(sample);
    future.shots[0].time_ms = future.playhead_ms + 1;
    expect(analyticsSchema.safeParse(future).success).toBe(false);
  });

  it('keeps field tilt and possession as shares of both teams', () => {
    const { field_tilt: tilt, possession_share: possession } = report.territory.match;
    expect((tilt.harbor ?? 0) + (tilt.vale ?? 0)).toBeCloseTo(100);
    expect((possession.harbor ?? 0) + (possession.vale ?? 0)).toBeCloseTo(100);
    expect(tiltSummary(report, 'harbor', 'Harbor Athletic')).toMatch(/^Harbor Athletic have \d+% of the ball and \d+% of the final-third passes/);
  });

  it('labels every shot with xG and a major or minor chance', () => {
    expect(report.shots.length).toBeGreaterThan(0);
    for (const shot of report.shots) expect(shot.chance === 'major').toBe(shot.xg >= .3);
  });

  it('orders each team’s workload by distance and keeps speed bands nested', () => {
    const rows = teamWorkload(report, 'vale');
    expect(rows).toHaveLength(11);
    expect(rows.map((row) => row.distance_m)).toEqual([...rows.map((row) => row.distance_m)].sort((a, b) => b - a));
    expect(rows.every((row) => row.sprint_m <= row.hsr_m && row.hsr_m <= row.distance_m)).toBe(true);
  });

  it('shows possession value as signed percentage points', () => {
    expect(pvText(.0234)).toBe('+2.3');
    expect(pvText(-.012)).toBe('−1.2');
    expect(pvText(null)).toBe('—');
  });
});
