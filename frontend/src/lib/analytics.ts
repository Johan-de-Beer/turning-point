import { z } from 'zod';

// Runtime mirror of the backend's analytics_v1 report. Strict so a contract drift fails loudly.
const id = z.string().min(1).max(160);
const count = z.number().int().nonnegative();
const num = z.number().finite();
const maybe = num.nullable();
const percent = num.min(0).max(100).nullable();
const point = z.strictObject({ x: num.min(0).max(100), y: num.min(0).max(100) });

const territoryWindow = z.strictObject({ start_ms: count, end_ms: count, final_third_passes: z.record(z.string(), count), field_tilt: z.record(z.string(), percent), possession_share: z.record(z.string(), percent) });
const shot = z.strictObject({ event_ref: id, time_ms: count, team_id: id, player_id: id, outcome: z.enum(['goal', 'saved', 'blocked', 'off_target']), xg: num.min(0).max(1), distance_m: num, angle_deg: num, assist: z.enum(['through_ball', 'cutback', 'pass', 'individual', 'cross', 'set_piece']), body_part: z.enum(['right_foot', 'left_foot', 'head']), chance: z.enum(['major', 'minor']) });
const teamChances = z.strictObject({ team_id: id, shots: count, on_target: count, goals: count, xg: num.min(0), xg_against: num.min(0), major_chances: count, xg_per_shot: maybe });
const lineFigures = z.strictObject({ seconds: num.min(0), deepest_m: maybe, back_four_m: maybe, centroid_m: maybe, gap_m: maybe, width_m: maybe });
const lineInterval = z.strictObject({ start_ms: count, end_ms: count, seconds: num.min(0), back_four_m: maybe, deepest_m: maybe });
const defensiveLine = z.strictObject({ team_id: id, block: z.enum(['high', 'mid', 'low', 'insufficient_evidence']), match: lineFigures, recent: lineFigures, settled: lineFigures, after_loss: lineFigures, before_shots: lineFigures, shots_faced: count, intervals: z.array(lineInterval) });
const workload = z.strictObject({ player_id: id, team_id: id, minutes: num.min(0), distance_m: num.min(0), hsr_m: num.min(0), sprint_m: num.min(0), sprints: count, accelerations: count, decelerations: count, load: num.min(0), top_speed_mps: num.min(0), metres_per_min: maybe, recent_metres_per_min: maybe, trend_pct: maybe, flag: z.literal('intensity_drop').nullable() });
const action = z.strictObject({ event_ref: id, time_ms: count, team_id: id, player_id: id, action: z.enum(['pass', 'carry', 'shot', 'lost_pass', 'dispossessed']), start: point, end: point.nullable(), value_before: num, value_after: num, pv: num });
const playerValue = z.strictObject({ player_id: id, team_id: id, actions: count, pv: num, positive_actions: count, best_ref: id.nullable() });
const teamValue = z.strictObject({ team_id: id, actions: count, possessions: count, pv: num, pv_per_action: maybe, by_action: z.record(z.string(), num) });

export const analyticsSchema = z.strictObject({
  session_id: id, generation: count.min(1), data_epoch: count.min(1), playhead_ms: count, next_cursor: z.string(),
  engine_version: z.literal('analytics_v1'), provenance: z.literal('synthetic_events_and_tracking'),
  territory: z.strictObject({ match: territoryWindow, recent: territoryWindow, intervals: z.array(territoryWindow) }),
  chances: z.record(z.string(), teamChances), shots: z.array(shot), defensive_line: z.record(z.string(), defensiveLine),
  workload: z.array(workload), team_value: z.record(z.string(), teamValue), player_value: z.array(playerValue), top_actions: z.array(action),
  definitions: z.record(z.string(), z.string()), limitations: z.array(z.string()),
}).superRefine((report, ctx) => {
  const future = report.shots.some((item) => item.time_ms > report.playhead_ms) || report.top_actions.some((item) => item.time_ms > report.playhead_ms)
    || report.territory.intervals.some((item) => item.end_ms > report.playhead_ms);
  if (future) ctx.addIssue({ code: 'custom', message: 'Analytics cannot come from the future' });
});

export type Analytics = z.infer<typeof analyticsSchema>;
export type Shot = z.infer<typeof shot>;
export type Workload = z.infer<typeof workload>;
export type DefensiveLine = z.infer<typeof defensiveLine>;
export type ValuedAction = z.infer<typeof action>;
export type AnalyticsView = 'territory' | 'chances' | 'line' | 'workload' | 'value';

export const blockLabel: Record<DefensiveLine['block'], string> = { high: 'High line', mid: 'Mid-block', low: 'Low block', insufficient_evidence: 'Not yet clear' };
export const assistLabel: Record<Shot['assist'], string> = { through_ball: 'Through ball', cutback: 'Cutback', pass: 'Pass', individual: 'Individual', cross: 'Cross', set_piece: 'Corner' };
export const bodyPartLabel: Record<Shot['body_part'], string> = { right_foot: 'Right foot', left_foot: 'Left foot', head: 'Header' };
export const actionLabel: Record<ValuedAction['action'], string> = { pass: 'Pass', carry: 'Carry', shot: 'Shot', lost_pass: 'Pass lost', dispossessed: 'Dispossessed' };

export const pct = (value: number | null | undefined) => value == null ? '—' : `${Math.round(value)}%`;
export const xgText = (value: number | null | undefined) => value == null ? '—' : value.toFixed(2);
export const km = (metres: number) => `${(metres / 1000).toFixed(2)} km`;
export const kmh = (mps: number) => `${(mps * 3.6).toFixed(1)} km/h`;
/** A location's scoring chance as a percentage. */
export const chanceText = (value: number) => `${(value * 100).toFixed(1)}%`;
/** Possession value in percentage points of scoring probability, signed. */
export const pvText = (value: number | null | undefined) => value == null ? '—' : `${value >= 0 ? '+' : '−'}${Math.abs(value * 100).toFixed(1)}`;

/**
 * One plain sentence comparing possession with field tilt for a team, the contrast the
 * metric exists to show. Descriptive only.
 */
export function tiltSummary(report: Analytics, teamId: string, teamName: string): string {
  const { possession_share: possession, field_tilt: tilt, final_third_passes: passes } = report.territory.match;
  const total = Object.values(passes).reduce((sum, value) => sum + value, 0);
  if (!total || tilt[teamId] == null || possession[teamId] == null) return `No final-third passes yet, so ${teamName}'s field tilt is not available.`;
  const gap = tilt[teamId]! - possession[teamId]!;
  const relation = Math.abs(gap) < 5 ? 'about as much territory as' : gap > 0 ? 'more territory than' : 'less territory than';
  return `${teamName} have ${pct(possession[teamId])} of the ball and ${pct(tilt[teamId])} of the final-third passes: ${relation} their possession suggests.`;
}

/** The workload rows for one team, highest distance first. */
export function teamWorkload(report: Analytics, teamId: string): Workload[] {
  return report.workload.filter((row) => row.team_id === teamId).sort((a, b) => b.distance_m - a.distance_m);
}
