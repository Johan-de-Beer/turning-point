import { z } from 'zod';

// Runtime mirror of the backend's analytics_v2 report. Strict so a contract drift fails loudly.
const id = z.string().min(1).max(160);
const count = z.number().int().nonnegative();
const num = z.number().finite();
const maybe = num.nullable();
const percent = num.min(0).max(100).nullable();
const point = z.strictObject({ x: num.min(0).max(100), y: num.min(0).max(100) });

const territoryWindow = z.strictObject({ start_ms: count, end_ms: count, final_third_passes: z.record(z.string(), count), field_tilt: z.record(z.string(), percent), possession_share: z.record(z.string(), percent) });
const gameStateName = z.enum(['winning', 'drawing', 'losing']);
const placement = z.strictObject({ y_m: num.min(-3.66).max(3.66), z_m: num.min(0).max(2.44), speed_mps: num.min(0) });
const shot = z.strictObject({ event_ref: id, time_ms: count, team_id: id, player_id: id, outcome: z.enum(['goal', 'saved', 'blocked', 'off_target']), xg: num.min(0).max(1), distance_m: num, angle_deg: num, assist: z.enum(['through_ball', 'cutback', 'pass', 'individual', 'cross', 'set_piece']), body_part: z.enum(['right_foot', 'left_foot', 'head']), chance: z.enum(['major', 'minor']), xgot: num.min(0).max(1).nullable(), placement: placement.nullable(), key_passer_id: id.nullable(), game_state: gameStateName });
const teamChances = z.strictObject({ team_id: id, shots: count, on_target: count, goals: count, xg: num.min(0), xg_against: num.min(0), major_chances: count, xg_per_shot: maybe });
const lineFigures = z.strictObject({ seconds: num.min(0), deepest_m: maybe, back_four_m: maybe, centroid_m: maybe, gap_m: maybe, width_m: maybe });
const lineInterval = z.strictObject({ start_ms: count, end_ms: count, seconds: num.min(0), back_four_m: maybe, deepest_m: maybe });
const defensiveLine = z.strictObject({ team_id: id, block: z.enum(['high', 'mid', 'low', 'insufficient_evidence']), match: lineFigures, recent: lineFigures, settled: lineFigures, after_loss: lineFigures, before_shots: lineFigures, shots_faced: count, intervals: z.array(lineInterval) });
const workload = z.strictObject({ player_id: id, team_id: id, minutes: num.min(0), distance_m: num.min(0), hsr_m: num.min(0), sprint_m: num.min(0), sprints: count, accelerations: count, decelerations: count, load: num.min(0), top_speed_mps: num.min(0), metres_per_min: maybe, recent_metres_per_min: maybe, trend_pct: maybe, flag: z.literal('intensity_drop').nullable() });
const action = z.strictObject({ event_ref: id, time_ms: count, team_id: id, player_id: id, action: z.enum(['pass', 'carry', 'shot', 'lost_pass', 'dispossessed', 'tackle_won', 'interception']), start: point, end: point.nullable(), value_before: num, value_after: num, pv: num, scoring_delta: num, conceding_delta: num, vaep: num });
const playerValue = z.strictObject({ player_id: id, team_id: id, actions: count, pv: num, positive_actions: count, best_ref: id.nullable(), vaep: num, defensive_vaep: num });
const teamValue = z.strictObject({ team_id: id, actions: count, possessions: count, pv: num, pv_per_action: maybe, by_action: z.record(z.string(), num), vaep: num, vaep_by_action: z.record(z.string(), num) });
const stateRow = z.strictObject({ state: gameStateName, minutes: num.min(0), possession_share: percent, field_tilt: percent, passes: count, shots: count, xg: num.min(0), xg_per_shot: maybe, goals: count, box_touches: count, xova: num, vaep: num, vaep_per_action: maybe, ppda: maybe, vertical_mps: maybe, directness: maybe, back_four_m: maybe });
const gameState = z.strictObject({ score: z.record(z.string(), count), segments: z.array(z.strictObject({ start_ms: count, end_ms: count, score: z.record(z.string(), count) })), teams: z.record(z.string(), z.strictObject({ team_id: id, current: gameStateName, rows: z.array(stateRow) })) });
const heatmap = z.strictObject({ subject_id: id, team_id: id, kind: z.enum(['touches', 'tracking', 'received', 'defensive']), total: count, cells: z.array(count) });
const heatmaps = z.strictObject({ grid_x: count.min(1), grid_y: count.min(1), maps: z.array(heatmap) });
const keeper = z.strictObject({ player_id: id, team_id: id, shots_on_target: count, saves: count, goals_conceded: count, xg_faced: num.min(0), xgot_faced: num.min(0), xg_prevented: num, save_pct: percent });
const shooting = z.strictObject({ team_id: id, shots_on_target: count, xg_on_target: num.min(0), xgot: num.min(0), placement_added: num });
const tempoFigures = z.strictObject({ possessions: count, vertical_mps: maybe, final_third_entries: count, passes_per_entry: maybe, forward_passes: count, lateral_passes: count, backward_passes: count, directness: maybe, possession_s: z.record(z.string(), maybe), progressive_passes: count, regain_to_progressive_s: maybe });
const tempo = z.strictObject({ team_id: id, match: tempoFigures, intervals: z.array(z.strictObject({ start_ms: count, end_ms: count, vertical_mps: maybe, directness: maybe, passes_per_entry: maybe })) });
const pressing = z.strictObject({ team_id: id, ppda: maybe, opponent_passes: count, defensive_actions: count });
const playerCreation = z.strictObject({ player_id: id, team_id: id, box_touches: count, zone14_touches: count, key_passes: count, assists: count, xa: num.min(0), shots: count, xg: num.min(0) });
const creation = z.strictObject({ team_id: id, box_touches: count, box_entries: count, zone14_touches: count, zone14_entries: count, key_passes: count, first_time_key_passes: count, assists: count, xa: num.min(0), key_pass_types: z.record(z.string(), count), key_pass_origins: z.record(z.string(), count), xg_per_box_touch: maybe });
const packingAction = z.strictObject({ event_ref: id, time_ms: count, team_id: id, player_id: id, action: z.enum(['pass', 'carry']), packed: count, defenders_packed: count, start: point, end: point });
const playerPacking = z.strictObject({ player_id: id, team_id: id, passes: count, packed_by_passes: count, carries: count, packed_by_carries: count, passing_rate: maybe, dribbling_rate: maybe, defenders_packed: count });
const teamPacking = z.strictObject({ team_id: id, passes: count, packed_by_passes: count, carries: count, packed_by_carries: count, passing_rate: maybe, dribbling_rate: maybe, defenders_packed: count, line_breaking: count });

export const analyticsSchema = z.strictObject({
  session_id: id, generation: count.min(1), data_epoch: count.min(1), playhead_ms: count, next_cursor: z.string(),
  engine_version: z.literal('analytics_v2'), provenance: z.literal('synthetic_events_and_tracking'),
  territory: z.strictObject({ match: territoryWindow, recent: territoryWindow, intervals: z.array(territoryWindow) }),
  chances: z.record(z.string(), teamChances), shots: z.array(shot), defensive_line: z.record(z.string(), defensiveLine),
  workload: z.array(workload), team_value: z.record(z.string(), teamValue), player_value: z.array(playerValue), top_actions: z.array(action),
  top_vaep: z.array(action), game_state: gameState, heatmaps, goalkeeping: z.strictObject({ keepers: z.array(keeper), shooting: z.record(z.string(), shooting) }),
  tempo: z.record(z.string(), tempo), pressing: z.record(z.string(), pressing), creation: z.record(z.string(), creation), player_creation: z.array(playerCreation),
  packing: z.record(z.string(), teamPacking), player_packing: z.array(playerPacking), top_packing: z.array(packingAction),
  definitions: z.record(z.string(), z.string()), limitations: z.array(z.string()),
}).superRefine((report, ctx) => {
  const future = report.shots.some((item) => item.time_ms > report.playhead_ms) || report.top_actions.some((item) => item.time_ms > report.playhead_ms)
    || report.territory.intervals.some((item) => item.end_ms > report.playhead_ms) || report.top_vaep.some((item) => item.time_ms > report.playhead_ms)
    || report.top_packing.some((item) => item.time_ms > report.playhead_ms) || report.game_state.segments.some((item) => item.end_ms > report.playhead_ms);
  const cells = report.heatmaps.grid_x * report.heatmaps.grid_y;
  if (report.heatmaps.maps.some((item) => item.cells.length !== cells)) ctx.addIssue({ code: 'custom', message: 'Heatmap grid size mismatch' });
  if (future) ctx.addIssue({ code: 'custom', message: 'Analytics cannot come from the future' });
});

export type Analytics = z.infer<typeof analyticsSchema>;
export type Shot = z.infer<typeof shot>;
export type Workload = z.infer<typeof workload>;
export type DefensiveLine = z.infer<typeof defensiveLine>;
export type ValuedAction = z.infer<typeof action>;
export type Heatmap = z.infer<typeof heatmap>;
export type GameStateName = z.infer<typeof gameStateName>;
export type AnalyticsView = 'territory' | 'state' | 'heatmap' | 'chances' | 'keepers' | 'tempo' | 'creation' | 'packing' | 'line' | 'workload' | 'value';

export const blockLabel: Record<DefensiveLine['block'], string> = { high: 'High line', mid: 'Mid-block', low: 'Low block', insufficient_evidence: 'Not yet clear' };
export const assistLabel: Record<Shot['assist'], string> = { through_ball: 'Through ball', cutback: 'Cutback', pass: 'Pass', individual: 'Individual', cross: 'Cross', set_piece: 'Corner' };
export const bodyPartLabel: Record<Shot['body_part'], string> = { right_foot: 'Right foot', left_foot: 'Left foot', head: 'Header' };
export const actionLabel: Record<ValuedAction['action'], string> = { pass: 'Pass', carry: 'Carry', shot: 'Shot', lost_pass: 'Pass lost', dispossessed: 'Dispossessed', tackle_won: 'Tackle won', interception: 'Interception' };
export const stateLabel: Record<GameStateName, string> = { winning: 'Winning', drawing: 'Drawing', losing: 'Losing' };
export const heatmapLabel: Record<Heatmap['kind'], string> = { touches: 'Touches', tracking: 'Positions (tracking)', received: 'Passes received', defensive: 'Defensive actions' };
export const keyPassLabel: Record<string, string> = { through_ball: 'Through ball', cutback: 'Cutback', pass: 'Pass', cross: 'Cross', set_piece: 'Corner' };
export const num1 = (value: number | null | undefined) => value == null ? '—' : value.toFixed(1);
export const num2 = (value: number | null | undefined) => value == null ? '—' : value.toFixed(2);
export const signed2 = (value: number | null | undefined) => value == null ? '—' : `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(2)}`;

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

/** The score as "2–1" with the home team first. */
export function scoreline(report: Analytics, home: string, away: string): string {
  return `${report.game_state.score[home] ?? 0}–${report.game_state.score[away] ?? 0}`;
}

/** Shares (0–100) of a heatmap's weight by third (along the pitch) and channel (across it). */
export function heatmapZones(map: Heatmap, gridX: number, gridY: number): { thirds: number[]; channels: number[] } {
  const thirds = [0, 0, 0], channels = [0, 0, 0];
  map.cells.forEach((value, index) => {
    const cx = Math.floor(index / gridY), cy = index % gridY;
    thirds[Math.min(2, Math.floor(cx * 3 / gridX))] += value;
    channels[Math.min(2, Math.floor(cy * 3 / gridY))] += value;
  });
  const total = map.total || 1;
  return { thirds: thirds.map((value) => 100 * value / total), channels: channels.map((value) => 100 * value / total) };
}

/**
 * One plain sentence on how a team's numbers moved with the scoreline, the context the
 * game-state split exists to give. Descriptive only; it never claims a cause.
 */
export function stateSummary(report: Analytics, teamId: string, teamName: string): string {
  const rows = report.game_state.teams[teamId]?.rows ?? [];
  if (rows.length < 2) return `${teamName} have only been ${rows[0] ? stateLabel[rows[0].state].toLowerCase() : 'level'} so far, so there is no game-state contrast yet.`;
  const [a, b] = [...rows].sort((x, y) => y.minutes - x.minutes);
  const parts = [`${pct(a.possession_share)} of the ball while ${a.state} against ${pct(b.possession_share)} while ${b.state}`];
  if (a.xg_per_shot != null && b.xg_per_shot != null) parts.push(`${a.xg_per_shot.toFixed(2)} xG per shot against ${b.xg_per_shot.toFixed(2)}`);
  return `${teamName} had ${parts.join(', and ')}.`;
}
