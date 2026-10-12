import { z } from 'zod';

// Runtime mirror of the backend's principles_v1 report. Strict so a contract drift fails loudly.
const id = z.string().min(1).max(160);
const count = z.number().int().nonnegative();
const num = z.number().finite();
const maybe = num.nullable();
const percent = num.min(0).max(100).nullable();

const moment = z.strictObject({ time_ms: count, event_ref: id.nullable(), label: z.string().min(1) });
const shape = z.enum(['5', '1+4', '2+3', '3+2', '4+1']);
const role = z.string().min(1).max(8);
const shapeRow = z.strictObject({ shape, seconds: num.min(0), share: percent, base: z.array(role), screen: z.array(role) });
const restLoss = z.strictObject({ shape, losses: count, counters_conceded: count, shots_conceded: count, xg_conceded: num.min(0) });
const formation = z.strictObject({ phase: z.enum(['build_up', 'attack', 'defending']), shape: z.string().regex(/^\d+(-\d+)+$/), seconds: num.min(0), lines: z.array(z.array(role)) });
const support = z.strictObject({ samples: count, options_mean: maybe, two_plus_share: percent, vertical_share: percent, diagonal_share: percent, horizontal_share: percent, back_share: percent, triangle_share: percent });
const structure = z.strictObject({ team_id: id, team_sheet: z.string(), formations: z.array(formation), support, build_up_seconds: num.min(0), build_up: z.array(shapeRow), rest_seconds: num.min(0), rest_defence: z.array(shapeRow), behind_ball: maybe, overcommitted_share: percent, losses: z.array(restLoss), moments: z.array(moment) });
const wingerStyle = z.enum(['inverted', 'touchline', 'balanced', 'insufficient_evidence']);
const side = z.enum(['right', 'left']);
const winger = z.strictObject({ player_id: id, team_id: id, side, foot: side, opposite_foot: z.boolean(), style: wingerStyle, seconds: num.min(0), touchline_m: maybe, inside_share: percent, cut_ins: count, shots: count, central_shots: count, fullback_width_share: percent, xt: num, moments: z.array(moment) });
const width = z.strictObject({ team_id: id, width_m: maybe, entries: count, central_entry_share: percent, crosses: count });
const marking = z.enum(['man', 'zonal', 'mixed', 'insufficient_evidence']);
const unit = z.strictObject({ unit: z.enum(['front', 'midfield', 'back']), samples: count, follow_share: percent, distance_m: maybe, marking, markers: z.array(id) });
const triggerKind = z.enum(['back_pass_keeper', 'to_fullback', 'to_centre_back', 'into_midfield', 'other']);
const trigger = z.strictObject({ trigger: triggerKind, passes: count, tracked: count, pressured: count, rate: percent, median_s: maybe, regained_5s: count });
const pressSystem = z.enum(['man_to_man', 'zonal', 'hybrid', 'insufficient_evidence']);
const pressing = z.strictObject({ team_id: id, seconds: num.min(0), system: pressSystem, units: z.array(unit), spare_at_back: maybe, left_free: id.nullable(), left_free_share: percent, triggers: z.array(trigger), cover_shadow: count, cover_shadow_tracked: count, build_ups: count, forced_wide_share: percent, regains_by_channel: z.record(z.string(), count), depth_seconds: num.min(0), free_share: percent, line_pressed_m: maybe, line_free_m: maybe, drop_when_free_m: maybe, depth_read: z.enum(['drops_when_free', 'holds_line', 'insufficient_evidence']), moments: z.array(moment) });
const band = z.strictObject({ band: z.enum(['near', 'middle', 'far']), samples: count, distance_m: maybe });
const freeReceiver = z.strictObject({ player_id: id, free: count, between_lines: count });
const teamMarking = z.strictObject({ team_id: id, bands: z.array(band), receptions: count, free: count, free_between_lines: count, free_players: z.array(freeReceiver), moments: z.array(moment) });
const movementKind = z.enum(['drop_and_sprint', 'opposite_runs', 'decoy_run', 'crisscross']);
const movementRow = z.strictObject({ kind: movementKind, players: z.array(id), episodes: count, drew: count, found: count, moments: z.array(moment) });
const movements = z.strictObject({ team_id: id, rows: z.array(movementRow), corners: count, crisscross_corners: count });
const pattern = z.strictObject({ first: id, second: id, third: id, count: count.min(1) });
const thirdMan = z.strictObject({ team_id: id, combinations: count, by_zone: z.record(z.string(), count), tracked: count, lane_blocked: count, receiver_free: count, progress_m: maybe, final_third_10s: count, shots_15s: count, patterns: z.array(pattern), moments: z.array(moment) });
const line = z.strictObject({ topic: z.string().min(1), text: z.string().min(1), moments: z.array(moment) });
const reportTeam = z.strictObject({ team_id: id, summary: z.string().min(1), phases: z.array(line), strengths: z.array(line), weaknesses: z.array(line), key_player: id.nullable(), key_player_reason: z.string().nullable() });

export const principlesSchema = z.strictObject({
  session_id: id, generation: count.min(1), data_epoch: count.min(1), playhead_ms: count, next_cursor: z.string(),
  engine_version: z.literal('principles_v1'), provenance: z.literal('synthetic_events_and_tracking'),
  structures: z.record(z.string(), structure), wingers: z.array(winger), width: z.record(z.string(), width), pressing: z.record(z.string(), pressing),
  marking: z.record(z.string(), teamMarking), movements: z.record(z.string(), movements), third_man: z.record(z.string(), thirdMan),
  match_report: z.record(z.string(), reportTeam), definitions: z.record(z.string(), z.string()), limitations: z.array(z.string()),
}).superRefine((report, ctx) => {
  const moments = [
    ...Object.values(report.structures).flatMap((row) => row.moments), ...report.wingers.flatMap((row) => row.moments),
    ...Object.values(report.pressing).flatMap((row) => row.moments), ...Object.values(report.marking).flatMap((row) => row.moments),
    ...Object.values(report.movements).flatMap((row) => row.rows.flatMap((item) => item.moments)), ...Object.values(report.third_man).flatMap((row) => row.moments),
    ...Object.values(report.match_report).flatMap((row) => [...row.phases, ...row.strengths, ...row.weaknesses].flatMap((item) => item.moments)),
  ];
  if (moments.some((item) => item.time_ms > report.playhead_ms)) ctx.addIssue({ code: 'custom', message: 'Principles of play cannot come from the future' });
});

export type Principles = z.infer<typeof principlesSchema>;
export type PrinciplesView = 'report' | 'structure' | 'wingers' | 'pressing' | 'movement' | 'third_man';
export type MovementKind = z.infer<typeof movementKind>;

export const wingerLabel: Record<z.infer<typeof wingerStyle>, string> = { inverted: 'Inverted', touchline: 'Touchline', balanced: 'Balanced', insufficient_evidence: 'Not yet clear' };
export const systemLabel: Record<z.infer<typeof pressSystem>, string> = { man_to_man: 'Man-to-man', zonal: 'Zonal', hybrid: 'Hybrid', insufficient_evidence: 'Not yet clear' };
export const markingLabel: Record<z.infer<typeof marking>, string> = { man: 'Man-oriented', zonal: 'Zonal', mixed: 'Mixed', insufficient_evidence: 'Not yet clear' };
export const unitLabel: Record<z.infer<typeof unit>['unit'], string> = { front: 'Front three', midfield: 'Midfield three', back: 'Back four' };
export const triggerLabel: Record<z.infer<typeof triggerKind>, string> = {
  back_pass_keeper: 'Back to the keeper', to_fullback: 'Out to a full-back', to_centre_back: 'To a centre-back', into_midfield: 'Into midfield', other: 'Other',
};
export const movementLabel: Record<MovementKind, string> = { drop_and_sprint: 'Drop and sprint', opposite_runs: 'Opposite runs', decoy_run: 'Decoy run', crisscross: 'Crisscross at a corner' };
export const bandLabel: Record<z.infer<typeof band>['band'], string> = { near: 'Near the ball (under 15 m)', middle: '15 to 30 m from the ball', far: 'Over 30 m from the ball' };
export const zoneLabel: Record<string, string> = { build_up: 'Build-up', middle_third: 'Middle third', final_third: 'Final third' };

/** "+1.2" / "−0.8" for the spare defenders at the back. */
export const signed = (value: number | null | undefined) => value == null ? '—' : `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(1)}`;

/** A shape row as "2+3: RCB, LCB | LB, DM, RCM". */
export function shapeText(row: { shape: string; base: string[]; screen: string[] }): string {
  return row.screen.length ? `${row.base.join(', ')} | ${row.screen.join(', ')}` : row.base.join(', ');
}

/** The movement rows of one kind, most frequent first, keeping only the ones seen at least ``min`` times. */
export function movementsOf(report: Principles, teamId: string, kind: MovementKind, min = 1) {
  return (report.movements[teamId]?.rows ?? []).filter((row) => row.kind === kind && row.episodes >= min).sort((a, b) => b.episodes - a.episodes);
}

/** Lines for a pre-match style brief: what to keep and what an opponent could target, in that order. */
export function reportSections(report: Principles, teamId: string) {
  const row = report.match_report[teamId];
  if (!row) return [];
  return [
    { title: 'Phase by phase', lines: row.phases },
    { title: 'Strengths to keep', lines: row.strengths },
    { title: 'Weaknesses to target', lines: row.weaknesses },
  ].filter((section) => section.lines.length);
}
