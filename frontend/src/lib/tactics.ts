import { z } from 'zod';

// Runtime mirror of the backend's tactics_v1 report. Strict so a contract drift fails loudly.
const id = z.string().min(1).max(160);
const count = z.number().int().nonnegative();
const num = z.number().finite();
const maybe = num.nullable();
const point = z.strictObject({ x: num.min(0).max(100), y: num.min(0).max(100) });

const defenderStep = z.strictObject({ player_id: id, traps: count, steps: count, late_steps: count, mean_lag_ms: maybe, mean_depth_at_pass_m: maybe, runners_played_onside: count });
const offsideTrap = z.strictObject({ attacks_faced: count, traps: count, caught_offside: count, broken: count, mean_step_speed_mps: maybe, mean_line_height_m: maybe, mean_line_spread_m: maybe, defenders: z.array(defenderStep) });
const shiftLag = z.strictObject({ player_id: id, shifts: count, mean_lag_ms: num });
const marking = z.strictObject({ player_id: id, assignments: count, early_releases: count, runs_faced: count, tracked: count, late_reactions: count, mean_reaction_ms: maybe });
const shape = z.strictObject({ attacks_faced: count, mean_width_before_m: maybe, mean_width_at_pass_m: maybe, mean_length_before_m: maybe, mean_length_at_pass_m: maybe, mean_shift_to_ball_m: maybe, shift_lags: z.array(shiftLag), marking_system: z.enum(['man_oriented', 'zonal', 'mixed', 'insufficient_evidence']), follow_rate: maybe, marking: z.array(marking) });
const pressTrigger = z.strictObject({ player_id: id, presses: count, mean_time_to_pressure_ms: maybe, mean_closing_speed_mps: maybe });
const pressTarget = z.strictObject({ player_id: id, possessions: count, presses: count, press_rate: num });
const pressOutcomes = z.strictObject({ possessions: count, regained: count, forced_to_keeper: count, played_through: count, stoppage: count, retained: count, mean_time_to_keeper_ms: maybe, mean_time_to_regain_ms: maybe });
const press = z.strictObject({ opportunities: count, presses: count, triggers: z.array(pressTrigger), targets: z.array(pressTarget), when_pressing: pressOutcomes, when_not_pressing: pressOutcomes, mean_time_to_pressure_ms: maybe, mean_closing_speed_mps: maybe });
const runner = z.strictObject({ player_id: id, runs: count, in_behind: count, targeted: count, offside: count, drew_defender: count, drag_rate: maybe });
const creator = z.strictObject({ player_id: id, attacks_started: count, chances: count, mean_time_to_chance_ms: maybe });
const decisivePass = z.strictObject({ event_ref: id, time_ms: count, passer_id: id, recipient_id: id, completed: z.boolean(), length_m: num, speed_mps: maybe, through_ball: z.boolean().nullable(), recipient_ran: z.boolean().nullable(), led_to_chance: z.boolean(), chance: z.enum(['major', 'minor']).nullable(), xg: num.min(0).max(1).nullable(), shot_ref: id.nullable() });
const buildUp = z.strictObject({ sequences: count, short_starts: count, long_starts: count, reached_middle_third: count, reached_final_third: count, mean_time_to_middle_ms: maybe, mean_time_to_final_ms: maybe, passes_attempted: count, passes_completed: count, pass_accuracy: maybe, lines_broken: count, mean_lines_broken: maybe, lost_in_own_half: count });
const side = z.enum(['left', 'right']);
const swing = z.enum(['inswinger', 'outswinger']);
const delivery = z.strictObject({ event_ref: id, time_ms: count, taker_id: id, foot: side, side, swing, expected_swing: swing, curve_m: num, flight_ms: count, speed_mps: num, zone: z.enum(['near_post', 'far_post', 'penalty_spot', 'six_yard', 'other']), target_id: id, accuracy_m: num, time_to_spot_ms: z.number().int().nullable(), arrival_vs_ball_ms: z.number().int().nullable(), first_contact: z.enum(['attack', 'defence']), attackers_in_box: count });
const targetMan = z.strictObject({ player_id: id, deliveries: count, reached_spot: count, mean_time_to_spot_ms: maybe, mean_arrival_vs_ball_ms: maybe, first_contacts: count });
const corners = z.strictObject({ corners: count, deliveries: z.array(delivery), target_men: z.array(targetMan) });
const teamTactics = z.strictObject({ team_id: id, offside_trap: offsideTrap, shape, press, runs: z.array(runner), creators: z.array(creator), decisive_passes: z.array(decisivePass), build_up: buildUp, corners });
export const observationCategories = ['offside_trap', 'shape', 'marking', 'press', 'runs', 'chance_creation', 'build_up', 'corners'] as const;
const observation = z.strictObject({ observation_id: id, category: z.enum(observationCategories), kind: z.enum(['tendency', 'opportunity']), subject_team_id: id, for_team_id: id, headline: z.string().max(140), detail: z.string().max(600), player_ids: z.array(id), sample_size: count, evidence: z.strictObject({ episode_ids: z.array(id), event_refs: z.array(id) }), moment_id: id.nullable() });
const moment = z.strictObject({ moment_id: id, category: z.string(), time_ms: count, period: z.union([z.literal(1), z.literal(2)]), team_id: id, title: z.string().max(140), ball: point, players: z.array(z.strictObject({ player_id: id, team_id: id, x: num, y: num })), offside_line_x: maybe, highlight_ids: z.array(id), path: z.array(point), event_ref: id });

export const tacticsSchema = z.strictObject({
  session_id: id, generation: count.min(1), data_epoch: count.min(1), playhead_ms: count, next_cursor: z.string(),
  engine_version: z.literal('tactics_v1'), provenance: z.literal('synthetic_tracking'), episodes_observed: count,
  teams: z.record(z.string(), teamTactics), observations: z.array(observation), key_moments: z.array(moment),
  definitions: z.record(z.string(), z.string()), limitations: z.array(z.string()),
}).superRefine((report, ctx) => {
  if (report.key_moments.some((item) => item.time_ms > report.playhead_ms)) ctx.addIssue({ code: 'custom', message: 'Tactical moments cannot come from the future' });
});

export type Tactics = z.infer<typeof tacticsSchema>;
export type TeamTactics = z.infer<typeof teamTactics>;
export type TacticalObservation = z.infer<typeof observation>;
export type KeyMoment = z.infer<typeof moment>;
export type TacticsView = 'defending' | 'attacking' | 'set_pieces';

export const categoryLabel: Record<TacticalObservation['category'], string> = {
  offside_trap: 'Offside trap', shape: 'Defensive shape', marking: 'Marking', press: 'Press',
  runs: 'Runs in behind', chance_creation: 'Chance creation', build_up: 'Build-up', corners: 'Corners',
};

const defending: readonly TacticalObservation['category'][] = ['offside_trap', 'shape', 'marking', 'press'];
const attacking: readonly TacticalObservation['category'][] = ['runs', 'chance_creation', 'build_up'];

/**
 * Findings for one team and view. Defending shows how the team defends, including its
 * weaknesses. Attacking shows its own attacking patterns plus every opponent weakness
 * it could test. Set pieces shows its own corners.
 */
export function observationsFor(report: Tactics, teamId: string, view: TacticsView): TacticalObservation[] {
  return report.observations.filter((item) => {
    if (view === 'defending') return item.subject_team_id === teamId && defending.includes(item.category);
    if (view === 'set_pieces') return item.subject_team_id === teamId && item.category === 'corners';
    return item.for_team_id === teamId && (attacking.includes(item.category) || item.kind === 'opportunity');
  });
}

export const seconds = (ms: number | null | undefined, digits = 1) => ms == null ? '—' : `${(ms / 1000).toFixed(digits)} s`;
export const metres = (value: number | null | undefined) => value == null ? '—' : `${value.toFixed(1)} m`;
export const speed = (value: number | null | undefined) => value == null ? '—' : `${value.toFixed(1)} m/s`;
export const share = (part: number, whole: number) => whole ? `${Math.round(part / whole * 100)}%` : '—';

/** Chance type for a decisive pass, with the xG of the shot that followed beneath it. */
export function chanceLabel(pass: Pick<TeamTactics['decisive_passes'][number], 'chance' | 'xg'>): { type: string; xg: string } {
  if (!pass.chance) return { type: 'None', xg: '' };
  return { type: pass.chance === 'major' ? 'Major' : 'Minor', xg: pass.xg == null ? 'no shot' : `xG ${pass.xg.toFixed(2)}` };
}

export const zoneLabel: Record<z.infer<typeof delivery>['zone'], string> = {
  near_post: 'Near post', far_post: 'Far post', penalty_spot: 'Penalty spot', six_yard: 'Six-yard box', other: 'Elsewhere',
};

/** The moment's players in pitch metres, the team in possession attacking left to right. */
export function momentLayout(item: KeyMoment) {
  const scale = (p: { x: number; y: number }) => ({ x: p.x / 100 * 105, y: p.y / 100 * 68 });
  return {
    ball: scale(item.ball),
    players: item.players.map((player) => ({ ...player, ...scale(player), attacking: player.team_id === item.team_id, highlighted: item.highlight_ids.includes(player.player_id) })),
    line: item.offside_line_x == null ? null : item.offside_line_x / 100 * 105,
    path: item.path.map(scale),
  };
}
