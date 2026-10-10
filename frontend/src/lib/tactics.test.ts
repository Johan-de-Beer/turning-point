import { describe, expect, it } from 'vitest';
import sample from './fixtures/tactics-15min.json';
import { angleLabel, momentLayout, observationsFor, tacticsSchema } from './tactics';

// The sample is the backend's own report after 15 observed minutes (kept in sync by a backend test).
const report = tacticsSchema.parse(sample);

describe('tactical analysis contract', () => {
  it('accepts the backend report and rejects moments beyond the playhead', () => {
    expect(report.engine_version).toBe('tactics_v1');
    expect(report.provenance).toBe('synthetic_tracking');
    const future = structuredClone(sample);
    future.key_moments[0].time_ms = future.playhead_ms + 1;
    expect(tacticsSchema.safeParse(future).success).toBe(false);
    const extra = { ...structuredClone(sample), hidden_plan: {} };
    expect(tacticsSchema.safeParse(extra).success).toBe(false);
  });

  it('shows a defensive weakness to the defending team and to the opponent who can test it', () => {
    const weakness = report.observations.find((item) => item.category === 'offside_trap' && item.kind === 'opportunity')!;
    expect(observationsFor(report, weakness.subject_team_id, 'defending')).toContain(weakness);
    expect(observationsFor(report, weakness.for_team_id, 'attacking')).toContain(weakness);
    expect(observationsFor(report, weakness.for_team_id, 'defending')).not.toContain(weakness);
  });

  it('keeps each team’s corners in its own set-piece view', () => {
    for (const team of Object.keys(report.teams)) {
      const corners = observationsFor(report, team, 'set_pieces');
      expect(corners.every((item) => item.category === 'corners' && item.subject_team_id === team)).toBe(true);
    }
    expect(observationsFor(report, 'harbor', 'set_pieces').length).toBeGreaterThan(0);
  });

  it('lays a key moment out in pitch metres with the highlighted players marked', () => {
    const moment = report.key_moments[0];
    const layout = momentLayout(moment);
    expect(layout.players).toHaveLength(22);
    expect(layout.players.filter((player) => player.highlighted).map((player) => player.player_id).sort()).toEqual([...moment.highlight_ids].sort());
    expect(layout.ball.x).toBeCloseTo(moment.ball.x * 1.05);
    expect(layout.ball.y).toBeCloseTo(moment.ball.y * .68);
  });

  it('describes pass angles relative to straight at goal', () => {
    expect(angleLabel(3)).toBe('straight');
    expect(angleLabel(31.6)).toBe('32° right');
    expect(angleLabel(-18)).toBe('18° left');
  });
});
