import { z } from 'zod';

const integer = z.number().int().nonnegative();
const count = integer;
const id = z.string().min(1).max(160);
const finite = z.number().finite();
const percent = finite.min(0).max(100).nullable();
export const playerRoles = ['GK', 'RB', 'CB', 'LB', 'RWB', 'LWB', 'CDM', 'CM', 'CAM', 'RM', 'LM', 'RW', 'LW', 'CF', 'ST'] as const;
export const teamSchema = z.strictObject({ team_id: id, display_name: z.string().min(1).max(80), short_name: z.string().min(1).max(12), color: z.string().regex(/^#[0-9a-fA-F]{6}$/) });
export const playerSchema = z.strictObject({ player_id: id, team_id: id, display_name: z.string().min(1).max(80), shirt_number: integer.min(1).max(99), position: z.enum(['GK', 'DEF', 'MID', 'FWD']), role: z.enum(playerRoles).nullable().optional() });
export const matchSchema = z.strictObject({ match_id: id, schema_version: z.literal('1.0'), provenance: z.literal('synthetic'), home: teamSchema, away: teamSchema, roster: z.array(playerSchema), period_lengths_ms: z.tuple([z.literal(2700000), z.literal(2700000)]) }).superRefine((match, ctx) => {
  if (match.home.team_id === match.away.team_id) ctx.addIssue({ code: 'custom', message: 'The fixture must have two distinct teams' });
  const players = new Set<string>();
  const shirts = new Set<string>();
  for (const player of match.roster) {
    if (![match.home.team_id, match.away.team_id].includes(player.team_id) || players.has(player.player_id) || shirts.has(`${player.team_id}:${player.shirt_number}`)) ctx.addIssue({ code: 'custom', message: 'Invalid roster reference or duplicate player' });
    players.add(player.player_id);
    shirts.add(`${player.team_id}:${player.shirt_number}`);
  }
});
export const matchesSchema = z.strictObject({ matches: z.array(matchSchema) });
const point = z.strictObject({ x: finite.min(0).max(100), y: finite.min(0).max(100) });
const eventBase = { match_id: id, event_time_ms: integer.max(5400000), period: z.union([z.literal(1), z.literal(2)]), team_id: id.nullable(), player_id: id.nullable(), possession_id: id.nullable() };
export const eventSchema = z.discriminatedUnion('kind', [
  z.strictObject({ ...eventBase, kind: z.literal('PERIOD_START'), detail: z.strictObject({}) }),
  z.strictObject({ ...eventBase, kind: z.literal('PERIOD_END'), detail: z.strictObject({}) }),
  z.strictObject({ ...eventBase, kind: z.literal('POSSESSION'), detail: z.strictObject({ start: point }) }),
  z.strictObject({ ...eventBase, kind: z.literal('PASS'), detail: z.strictObject({ recipient_id: id, completed: z.boolean(), start: point, end: point }) }),
  z.strictObject({ ...eventBase, kind: z.literal('CARRY'), detail: z.strictObject({ start: point, end: point }) }),
  z.strictObject({ ...eventBase, kind: z.literal('SHOT'), detail: z.strictObject({ position: point, target: point.nullable().optional(), outcome: z.enum(['goal', 'saved', 'blocked', 'off_target']), body_part: z.enum(['right_foot', 'left_foot', 'head']).nullable().optional() }) }),
  z.strictObject({ ...eventBase, kind: z.literal('TACKLE'), detail: z.strictObject({ position: point, successful: z.boolean(), contest: z.enum(['ground', 'aerial']).optional() }) }),
  z.strictObject({ ...eventBase, kind: z.literal('STOPPAGE'), detail: z.strictObject({ reason: z.enum(['ball_out', 'corner', 'foul', 'goal', 'interval']) }) }),
]).superRefine((event, ctx) => {
  const start = (event.period - 1) * 2700000;
  if (event.event_time_ms < start || event.event_time_ms > start + 2700000) ctx.addIssue({ code: 'custom', message: 'Event lies outside its period' });
  if (event.kind === 'PERIOD_START' || event.kind === 'PERIOD_END') {
    if (event.event_time_ms !== start + (event.kind === 'PERIOD_END' ? 2700000 : 0) || event.team_id || event.player_id || event.possession_id) ctx.addIssue({ code: 'custom', message: 'Invalid period marker' });
  } else if (event.kind === 'STOPPAGE') {
    if (event.player_id) ctx.addIssue({ code: 'custom', message: 'Stoppage has no player actor' });
  } else if (!event.team_id || !event.player_id || !event.possession_id) ctx.addIssue({ code: 'custom', message: 'In-play events require team, player and possession' });
});
export const envelopeSchema = z.strictObject({ delivery_seq: integer.min(1), available_at_ms: integer.max(5400000), event_id: id, revision: integer.min(1), operation: z.enum(['upsert', 'delete']), payload: eventSchema.nullable() }).superRefine((envelope, ctx) => {
  if ((envelope.operation === 'upsert' && !envelope.payload) || (envelope.operation === 'delete' && envelope.payload)) ctx.addIssue({ code: 'custom', message: 'Envelope operation and payload disagree' });
  if (envelope.payload && envelope.available_at_ms < envelope.payload.event_time_ms) ctx.addIssue({ code: 'custom', message: 'Event was delivered before it occurred' });
});
export const preferencesSchema = z.strictObject({ mode: z.enum(['casual', 'analyst']), favorite_team_id: id.nullable(), favorite_player_id: id.nullable(), language: z.literal('en'), pause_on_insight: z.boolean() });
export const defaultPreferences: Preferences = { mode: 'casual', favorite_team_id: null, favorite_player_id: null, language: 'en', pause_on_insight: false };
const windowSchema = z.strictObject({ start_ms: integer, end_ms: integer }).refine((value) => value.end_ms >= value.start_ms, { message: 'Invalid observation window' });
const coverageSchema = z.strictObject({ status: z.enum(['warming_up', 'eligible', 'insufficient_evidence']), eligible: z.boolean(), known_in_play_ms: integer, owned_in_play_ms: z.record(z.string(), integer), stoppage_ms: integer, unknown_state_ms: integer, state_valid: z.boolean() });
const teamMetricsSchema = z.strictObject({ shots: count, on_target: count, completed_passes: count, attempted_passes: count, pass_accuracy: percent, final_third_entries: count, box_entries: count, possession_share: percent, goals: count, duels: count, duels_won: count, final_third_passes: count, field_tilt: percent, xg: finite.min(0) });
const baselineSchema = z.strictObject({ window: windowSchema, coverage: coverageSchema, team_metrics: z.record(z.string(), teamMetricsSchema), live_turnovers: count });
export const snapshotSchema = z.strictObject({ snapshot_id: id, session_id: id, generation: integer.min(1), data_epoch: integer.min(1), as_of_ms: integer, delivery_cursor: integer, period: z.union([z.literal(1), z.literal(2)]), window: windowSchema, coverage: coverageSchema, team_metrics: z.record(z.string(), teamMetricsSchema), live_turnovers: count, baseline: baselineSchema.nullable(), evidence_refs: z.array(id), rules_version: z.literal('rules_v1') });
export const factSchema = z.strictObject({ fact_id: id, metric: z.string(), subject_id: id, numeric_value: finite, unit: z.enum(['count', 'percent', 'milliseconds']), window: windowSchema, source_event_refs: z.array(id), derivation_version: z.literal('metrics_v1') });
const variantSchema = z.strictObject({ insight_id: id, mode: z.enum(['casual', 'analyst']), language: z.literal('en'), preferences_version: integer.min(1), headline: z.string().max(100), explanation: z.string().max(1000), fact_ids: z.array(id), player_focus_ids: z.array(id), provenance: z.enum(['mock_template', 'deterministic_fallback', 'microsoft_foundry']) });
const conditionSchema = z.strictObject({ metric: z.string(), subject_id: id, operator: z.string(), threshold: finite, actual: finite.nullable(), passed: z.boolean() });
export const insightSchema = z.strictObject({ insight_id: id, pattern: z.enum(['sustained_pressure', 'sterile_possession', 'end_to_end']), subject_ids: z.array(id), anchor_snapshot_id: id, facts: z.array(factSchema), evidence_quality: z.enum(['complete', 'insufficient']), observed_window: windowSchema, interpretation: z.string(), limitations: z.array(z.string()), status: z.enum(['pending', 'ready', 'corrected', 'retracted', 'expired', 'rejected']), supersedes_id: id.nullable(), variants: z.record(z.string(), variantSchema), conditions: z.array(conditionSchema), supported_player_ids: z.array(id), generation: integer.min(1), data_epoch: integer.min(1), episode_id: id });
export const overlaySchema = z.strictObject({ overlay_id: id, insight_id: id.nullable(), session_id: id, generation: integer.min(1), data_epoch: integer.min(1), mode: z.enum(['casual', 'analyst']), language: z.literal('en'), valid_from_ms: integer, valid_until_ms: integer, priority: integer, display: z.strictObject({ headline: z.string().max(100), subline: z.string().max(160) }), fact_ids: z.array(id), status: z.literal('active') });
const storyBeatSchema = z.strictObject({ insight_id: id, headline: z.string(), explanation: z.string(), fact_ids: z.array(id), observed_window: windowSchema });
const recapVariantSchema = z.strictObject({ headline: z.string(), explanation: z.string(), story_beats: z.array(storyBeatSchema), fact_ids: z.array(id), player_summary: z.string().nullable() });
export const recapSchema = z.strictObject({ recap_id: id, phase: z.enum(['half_time', 'full_time']), cutoff_snapshot_id: id.nullable(), generation: integer.min(1), data_epoch: integer.min(1), score: z.record(z.string(), count), story_beats: z.array(storyBeatSchema), facts: z.array(factSchema), fact_ids: z.array(id), variants: z.record(z.string(), recapVariantSchema), status: z.enum(['locked', 'pending', 'ready', 'corrected']), correction_notice: z.string().nullable(), cutoff_ms: integer.nullable() });
const playerStatsSchema = z.strictObject({ player_id: id, team_id: id, involvement: count, touches: count, passes_attempted: count, passes_completed: count, passes_received: count, carries: count, shots: count, on_target: count, goals: count, tackles: count, duels: count, duels_won: count, event_refs: z.array(id) });
const agentRunSchema = z.strictObject({ run_id: id, role: z.enum(['football_analyst', 'evidence_editor']), provider: z.string(), input_fingerprint: z.string(), session_id: id, generation: integer.min(1), data_epoch: integer.min(1), snapshot_id: id, rules_version: z.string(), preferences_version: integer.min(1), mode: z.string(), language: z.string(), status: z.enum(['queued', 'running', 'approved', 'rejected', 'timeout', 'fallback', 'discarded', 'recoverable']), fact_ids: z.array(id), validation_errors: z.array(z.string()), duration_ms: integer, fallback_reason: z.string().nullable() });
const diagnosticsSchema = z.strictObject({ provider: z.string(), provider_status: z.string(), pipeline: z.record(z.string(), z.string()), agent_runs: z.array(agentRunSchema), ingestion_errors: z.array(z.string()), suppressed_candidates: z.array(z.string()), correction_notice: z.string().nullable(), pending_jobs: integer, rules_version: z.string(), definitions: z.record(z.string(), z.string()) });
export const sessionSchema = z.strictObject({ schema_version: z.literal('1.0'), session_id: id, match_id: id, generation: integer.min(1), data_epoch: integer.min(1), preferences_version: integer.min(1), status: z.enum(['ready', 'playing', 'paused', 'half_time', 'ended']), playhead_ms: integer.max(5400000), observed_high_water_ms: integer.max(5400000), period: z.union([z.literal(1), z.literal(2)]), speed: z.union([z.literal(1), z.literal(12), z.literal(60)]), last_delivery_seq: integer, next_cursor: z.string(), resync_required: z.boolean(), preferences: preferencesSchema, score: z.record(z.string(), count), events: z.array(envelopeSchema), snapshot: snapshotSchema, insights: z.array(insightSchema), overlay: overlaySchema.nullable(), recaps: z.record(z.string(), recapSchema), player_stats: z.record(z.string(), playerStatsSchema), diagnostics: diagnosticsSchema }).superRefine((state, ctx) => {
  if (state.snapshot.as_of_ms > state.playhead_ms || state.snapshot.window.end_ms > state.playhead_ms || state.events.some((event) => event.available_at_ms > state.playhead_ms || (event.payload && event.payload.event_time_ms > state.playhead_ms))) ctx.addIssue({ code: 'custom', message: 'Future observations are not permitted' });
  if (state.snapshot.session_id !== state.session_id || state.snapshot.generation !== state.generation || state.snapshot.data_epoch !== state.data_epoch) ctx.addIssue({ code: 'custom', message: 'Snapshot version does not match session' });
  if (state.insights.some((insight) => insight.observed_window.end_ms > state.playhead_ms)) ctx.addIssue({ code: 'custom', message: 'Insight references future observations' });
});
const identityShape = { session_id: id, generation: integer.min(1), data_epoch: integer.min(1), playhead_ms: integer, next_cursor: z.string() };
export const evidenceSchema = z.strictObject({ ...identityShape, insight: insightSchema, snapshot: snapshotSchema, facts: z.array(factSchema), conditions: z.array(conditionSchema), events: z.array(envelopeSchema), metric_definitions: z.record(z.string(), z.string()) });
export const recapResponseSchema = z.strictObject({ ...identityShape, recap: recapSchema });

export type Match = z.infer<typeof matchSchema>;
export type Team = z.infer<typeof teamSchema>;
export type Player = z.infer<typeof playerSchema>;
export type Preferences = z.infer<typeof preferencesSchema>;
export type Session = z.infer<typeof sessionSchema>;
export type Insight = z.infer<typeof insightSchema>;
export type Envelope = z.infer<typeof envelopeSchema>;
export type Event = z.infer<typeof eventSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export type Recap = z.infer<typeof recapSchema>;
export type Overlay = z.infer<typeof overlaySchema>;

export function validateSessionReferences(state: Session, match: Match): void {
  if (state.match_id !== match.match_id) throw new Error('Session fixture does not match');
  const players = new Map(match.roster.map((player) => [player.player_id, player]));
  const teams = [match.home.team_id, match.away.team_id];
  for (const { payload: event } of state.events) {
    if (!event) continue;
    if (event.match_id !== match.match_id || (event.team_id && !teams.includes(event.team_id))) throw new Error('Invalid observed fixture reference');
    if (event.player_id && players.get(event.player_id)?.team_id !== event.team_id) throw new Error('Invalid observed actor reference');
    if (event.kind === 'PASS' && players.get(event.detail.recipient_id)?.team_id !== event.team_id) throw new Error('Invalid pass recipient reference');
  }
}

export function eligibleOverlay(state: Session): Overlay | null {
  const overlay = state.overlay;
  return overlay && overlay.session_id === state.session_id && overlay.generation === state.generation && overlay.data_epoch === state.data_epoch && overlay.mode === state.preferences.mode && overlay.language === state.preferences.language && overlay.valid_from_ms <= state.playhead_ms && state.playhead_ms < overlay.valid_until_ms ? overlay : null;
}

export function canAcceptState(current: Session | null, incoming: Session): boolean {
  return !current || (incoming.session_id === current.session_id && (incoming.generation > current.generation || (incoming.generation === current.generation && incoming.data_epoch >= current.data_epoch && incoming.preferences_version >= current.preferences_version && incoming.playhead_ms >= current.playhead_ms && incoming.last_delivery_seq >= current.last_delivery_seq && incoming.observed_high_water_ms >= current.observed_high_water_ms)));
}

export function mergeObservedEvents(current: Session | null, incoming: Session): Session {
  if (!current || incoming.session_id !== current.session_id || incoming.generation !== current.generation || incoming.resync_required) return incoming;
  const canonical = new Map(current.events.map((envelope) => [envelope.event_id, envelope]));
  for (const envelope of incoming.events) {
    const previous = canonical.get(envelope.event_id);
    if (!previous || envelope.revision > previous.revision) canonical.set(envelope.event_id, envelope);
  }
  return { ...incoming, events: [...canonical.values()].sort((a, b) => (a.payload?.event_time_ms ?? a.available_at_ms) - (b.payload?.event_time_ms ?? b.available_at_ms) || a.delivery_seq - b.delivery_seq) };
}
