import { z } from 'zod';

// Runtime mirror of the backend's phases_v1 report. Strict so a contract drift fails loudly.
const id = z.string().min(1).max(160);
const count = z.number().int().nonnegative();
const num = z.number().finite();
const maybe = num.nullable();
const percent = num.min(0).max(100).nullable();
const point = z.strictObject({ x: num.min(0).max(100), y: num.min(0).max(100) });
const thirds = z.record(z.string(), count);

const moment = z.strictObject({ time_ms: count, event_ref: id.nullable(), label: z.string().min(1) });
const phaseName = z.enum(['attacking', 'attacking_transition', 'attacking_set_piece', 'defending', 'defensive_transition', 'defending_set_piece']);
const phaseRow = z.strictObject({ phase: phaseName, seconds: num.min(0), share: percent, passes: count, final_third_entries: count, xt: num, shots_for: count, xg_for: num.min(0), goals_for: count, shots_against: count, xg_against: num.min(0), goals_against: count });
const teamPhases = z.strictObject({ team_id: id, live_seconds: num.min(0), rows: z.array(phaseRow), restarts: z.record(z.string(), count) });
const attacking = z.strictObject({ regains: count, counters: count, counter_shots: count, counter_xg: num.min(0), recycled: count, lost_quickly: count, median_to_final_third_s: maybe, by_third: thirds, counters_by_third: thirds, moments: z.array(moment) });
const counterPress = z.strictObject({ losses: count, tracked: count, pressed: count, press_rate: percent, median_pressure_s: maybe, pack_2s: maybe, regained_5s: count, regained_10s: count, bypassed: count, shots_conceded: count, xg_conceded: num.min(0), rest_defence: maybe, rest_defenders: maybe, by_third: thirds, moments: z.array(moment) });
const transitions = z.strictObject({ team_id: id, attacking, defensive: counterPress });
const blockKind = z.enum(['high', 'mid', 'low']);
const blockRow = z.strictObject({ block: blockKind, seconds: num.min(0), share: percent, back_four_m: maybe, length_m: maybe, width_m: maybe, line_gap_m: maybe, box_defenders: maybe, opponent_entries: count, wide_entry_share: percent, opponent_shots: count, long_shot_share: percent, xg_against: num.min(0), goals_against: count, crosses_faced: count, ppda: maybe, regains: count, counters: count });
const snapshot = z.strictObject({ situation: z.enum(['settled', 'opponent_build_up', 'high_press']), seconds: num.min(0), back_four_m: maybe, front_line_m: maybe, length_m: maybe });
const recovery = z.strictObject({ balls_in_behind: count, tracked: count, retreat_m: maybe, top_speed_mps: maybe, keeper_start_m: maybe, keeper_max_m: maybe, sweeps: count, shots_conceded: count, moments: z.array(moment) });
const blocks = z.strictObject({ team_id: id, settled_seconds: num.min(0), rows: z.array(blockRow), snapshots: z.array(snapshot), recovery });
const playerProgression = z.strictObject({ player_id: id, team_id: id, progressive_passes: count, progressive_carries: count, progressive_carry_m: num.min(0), carries: count, carries_final_third: count, carries_box: count, take_ons: count, xt_passes: num, xt_carries: num, xt: num });
const threatAction = z.strictObject({ event_ref: id, time_ms: count, team_id: id, player_id: id, action: z.enum(['pass', 'carry']), xt: num, start: point, end: point });
const progression = z.strictObject({ team_id: id, progressive_passes: count, progressive_carries: count, carry_share: percent, progressive_carry_m: num.min(0), carries_final_third: count, carries_box: count, take_ons: count, xt: num, xt_passes: num, xt_carries: num, xt_by_channel: z.record(z.string(), num), xt_intervals: z.array(num) });
const xtGrid = z.strictObject({ grid_x: count.min(1), grid_y: count.min(1), values: z.array(num.min(0).max(1)), training: z.record(z.string(), z.union([count, z.array(count)])) });
const fullbackStyle = z.enum(['overlapping', 'underlapping', 'inverted', 'holding', 'balanced', 'insufficient_evidence']);
const fullback = z.strictObject({ player_id: id, team_id: id, side: z.enum(['right', 'left']), style: fullbackStyle, seconds: num.min(0), depth_m: maybe, attack_depth_m: maybe, touchline_m: maybe, inside_share: percent, overlaps: count, underlaps: count, depth_at_loss_m: maybe, crosses: count, progressive_actions: count, xt: num, moments: z.array(moment) });
const rotationKind = z.enum(['holding_midfielder_drops', 'striker_drops', 'wide_overlap', 'wide_underlap', 'fullback_inverts']);
const rotation = z.strictObject({ kind: rotationKind, players: z.array(id), episodes: count, seconds: num.min(0), possessions: count, final_third_rate: percent, baseline_rate: percent, moments: z.array(moment) });
const controlRead = z.enum(['control_with_territory', 'possession_without_penetration', 'territory_without_the_ball', 'pinned_back', 'balanced', 'insufficient_evidence']);
const control = z.strictObject({ team_id: id, possession_share: percent, field_tilt: percent, final_third_entries: count, box_entries: count, progressive_actions: count, xg: num.min(0), ppda: maybe, possessions: count, purposeful: count, sterile: count, sterile_passes: count, read: controlRead });
const pressInterval = z.strictObject({ start_ms: count, end_ms: count, ppda: maybe, opponent_passes: count, defensive_actions: count, high_regains: count });
const pressing = z.strictObject({ team_id: id, halves: z.array(pressInterval), intervals: z.array(pressInterval), high_regains: count, high_regain_shots: count, high_regain_xg: num.min(0), regains_by_third: thirds });
const finishing = z.strictObject({ player_id: id, team_id: id, shots: count, goals: count, xg: num.min(0), goals_minus_xg: num, xg_per_shot: maybe });
const teamXg = z.strictObject({ team_id: id, intervals: z.array(num.min(0)), intervals_against: z.array(num.min(0)), against_by_setup: z.record(z.string(), num.min(0)), goals_minus_xg: num });
const note = z.strictObject({ note_id: id, team_id: id, topic: z.string().min(1), quantitative: z.string().min(1), look_for: z.string().min(1), moments: z.array(moment), caveat: z.string().nullable() });

export const phasesSchema = z.strictObject({
  session_id: id, generation: count.min(1), data_epoch: count.min(1), playhead_ms: count, next_cursor: z.string(),
  engine_version: z.literal('phases_v1'), provenance: z.literal('synthetic_events_and_tracking'),
  phases: z.record(z.string(), teamPhases), transitions: z.record(z.string(), transitions), blocks: z.record(z.string(), blocks),
  progression: z.record(z.string(), progression), player_progression: z.array(playerProgression), top_threat: z.array(threatAction), xt_grid: xtGrid,
  fullbacks: z.array(fullback), rotations: z.record(z.string(), z.strictObject({ team_id: id, rows: z.array(rotation) })),
  control: z.record(z.string(), control), pressing: z.record(z.string(), pressing), finishing: z.array(finishing), xg: z.record(z.string(), teamXg),
  notes: z.array(note), definitions: z.record(z.string(), z.string()), limitations: z.array(z.string()),
}).superRefine((report, ctx) => {
  const moments = [
    ...Object.values(report.transitions).flatMap((row) => [...row.attacking.moments, ...row.defensive.moments]),
    ...Object.values(report.blocks).flatMap((row) => row.recovery.moments),
    ...report.fullbacks.flatMap((row) => row.moments), ...Object.values(report.rotations).flatMap((row) => row.rows.flatMap((item) => item.moments)),
    ...report.notes.flatMap((row) => row.moments),
  ];
  const future = moments.some((item) => item.time_ms > report.playhead_ms) || report.top_threat.some((item) => item.time_ms > report.playhead_ms)
    || Object.values(report.pressing).some((row) => row.intervals.some((item) => item.end_ms > report.playhead_ms));
  if (future) ctx.addIssue({ code: 'custom', message: 'Phase analysis cannot come from the future' });
  if (report.xt_grid.values.length !== report.xt_grid.grid_x * report.xt_grid.grid_y) ctx.addIssue({ code: 'custom', message: 'xT grid size mismatch' });
});

export type Phases = z.infer<typeof phasesSchema>;
export type PhaseName = z.infer<typeof phaseName>;
export type Moment = z.infer<typeof moment>;
export type FullbackStyle = z.infer<typeof fullbackStyle>;
export type RotationKind = z.infer<typeof rotationKind>;
export type ControlRead = z.infer<typeof controlRead>;
export type Snapshot = z.infer<typeof snapshot>;
export type PhasesView = 'phases' | 'transitions' | 'blocks' | 'threat' | 'roles' | 'control' | 'notes';

export const phaseLabel: Record<PhaseName, string> = {
  attacking: 'In possession', attacking_transition: 'Attacking transition', attacking_set_piece: 'Attacking set piece',
  defending: 'Out of possession', defensive_transition: 'Defensive transition', defending_set_piece: 'Defending set piece',
};
export const blockName: Record<z.infer<typeof blockKind>, string> = { high: 'High block', mid: 'Mid-block', low: 'Low block' };
export const snapshotLabel: Record<Snapshot['situation'], string> = { settled: 'Settled defending', opponent_build_up: 'Opponent building from the back', high_press: 'Pressing high' };
export const fullbackLabel: Record<FullbackStyle, string> = {
  overlapping: 'Overlapping', underlapping: 'Underlapping', inverted: 'Inverted', holding: 'Holding', balanced: 'Balanced', insufficient_evidence: 'Not yet clear',
};
export const rotationLabel: Record<RotationKind, string> = {
  holding_midfielder_drops: 'Holding midfielder drops in', striker_drops: 'Striker drops deep', wide_overlap: 'Full-back overlaps',
  wide_underlap: 'Full-back underlaps', fullback_inverts: 'Full-back steps inside',
};
export const controlLabel: Record<ControlRead, string> = {
  control_with_territory: 'Ball and territory', possession_without_penetration: 'Ball without penetration', territory_without_the_ball: 'Territory without the ball',
  pinned_back: 'Pinned back', balanced: 'Balanced', insufficient_evidence: 'Not yet clear',
};

/** xT as a signed number with three decimals (it is a change in scoring probability, 0–1). */
export const xtText = (value: number | null | undefined) => value == null ? '—' : `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(3)}`;
/** A zone's threat as a percentage chance of scoring from possession there. */
export const zoneText = (value: number) => `${(value * 100).toFixed(1)}%`;

/** The event id behind a moment's reference ("evt_00104@1"), for highlighting on the pitch. */
export function momentEventId(item: Moment): string | null {
  return item.event_ref ? item.event_ref.split('@')[0] : null;
}

/** A team's notes, in the order the backend wrote them. */
export function teamNotes(report: Phases, teamId: string) {
  return report.notes.filter((item) => item.team_id === teamId);
}

/** The phase rows that have any time in them, longest first. */
export function busiestPhases(report: Phases, teamId: string) {
  return (report.phases[teamId]?.rows ?? []).filter((row) => row.seconds > 0).sort((a, b) => b.seconds - a.seconds);
}

/**
 * The line-height contrast the snapshots exist to show: how far the back four moves up
 * from settled defending when the opponent builds from the back or the team presses high.
 */
export function lineContrast(report: Phases, teamId: string, teamName: string): string {
  const rows = Object.fromEntries((report.blocks[teamId]?.snapshots ?? []).map((row) => [row.situation, row]));
  const settled = rows.settled?.back_four_m;
  const press = rows.high_press?.back_four_m ?? rows.opponent_build_up?.back_four_m;
  if (settled == null || press == null) return `Not enough settled defending yet to compare ${teamName}'s line heights.`;
  const gap = press - settled;
  return `${teamName}'s back four sits ${settled.toFixed(1)} m from goal when settled and ${press.toFixed(1)} m when pressing high: ${Math.abs(gap) < 3 ? 'about the same height' : gap > 0 ? `${gap.toFixed(1)} m higher` : `${Math.abs(gap).toFixed(1)} m deeper`}.`;
}
