import type { Envelope, Insight, Match, Player, Session, Team } from './contracts';
import { formatPercent } from './format';

export const MATCH_MS = 5_400_000;
export const HALF_MS = 2_700_000;

export function teamFor(match: Match, teamId: string | null | undefined): Team | undefined {
  return [match.home, match.away].find((team) => team.team_id === teamId);
}

/** Specific position when the roster has one (ST, CAM, CDM…), else the broad group. */
export function positionLabel(player: Pick<Player, 'position' | 'role'>): string {
  return player.role ?? player.position;
}

/** "Name (ST)": a player's name with their position, for event descriptions. */
export function playerLabel(match: Match, playerId: string | null | undefined): string | null {
  const player = match.roster.find((item) => item.player_id === playerId);
  return player ? `${player.display_name} (${positionLabel(player)})` : null;
}

/** Goals, period boundaries and withdrawn records stay visible whatever the player focus. */
export function isEssentialContext(envelope: Envelope): boolean {
  const event = envelope.payload;
  if (!event) return true;
  return event.kind === 'PERIOD_START' || event.kind === 'PERIOD_END' || (event.kind === 'SHOT' && event.detail.outcome === 'goal');
}

/** Actor or completed-pass recipient: the same semantics as the server's involvement count. */
export function involvesPlayer(envelope: Envelope, playerId: string): boolean {
  const event = envelope.payload;
  if (!event) return false;
  return event.player_id === playerId || (event.kind === 'PASS' && event.detail.completed && event.detail.recipient_id === playerId);
}

export type FeedItem = { envelope: Envelope; context: boolean };

/**
 * Newest-first observed feed. A player filter narrows the list to that player's actions but
 * keeps essential match context, flagged so it is never presented as the player's own action.
 */
export function feedItems(events: readonly Envelope[], playerId: string | null, limit = 12): FeedItem[] {
  const visible = events.filter((envelope) => !envelope.payload || envelope.payload.kind !== 'POSSESSION');
  const items = visible.flatMap((envelope): FeedItem[] => {
    if (!playerId) return [{ envelope, context: false }];
    if (involvesPlayer(envelope, playerId)) return [{ envelope, context: false }];
    return isEssentialContext(envelope) ? [{ envelope, context: true }] : [];
  });
  return items.slice(-limit).reverse();
}

export type TimelineInsightMarker = { kind: 'insight'; id: string; start: number; end: number; teamId: string | null; pattern: Insight['pattern']; status: Insight['status'] };
export type TimelineGoalMarker = { kind: 'goal'; id: string; at: number; teamId: string; playerId: string | null };

export function percentOfMatch(ms: number): number {
  return Math.min(100, Math.max(0, ms / MATCH_MS * 100));
}

/** Observed-only markers: confirmed insight windows and goals, placed at their match times. */
export function timelineMarkers(state: Session): { insights: TimelineInsightMarker[]; goals: TimelineGoalMarker[] } {
  const insights = state.insights
    .filter((insight) => ['ready', 'corrected', 'expired', 'retracted'].includes(insight.status))
    .map((insight): TimelineInsightMarker => ({
      kind: 'insight', id: insight.insight_id, start: insight.observed_window.start_ms, end: insight.observed_window.end_ms,
      teamId: insight.pattern === 'end_to_end' ? null : insight.subject_ids[0] ?? null, pattern: insight.pattern, status: insight.status,
    }))
    .sort((a, b) => a.end - b.end);
  const goals = state.events.flatMap((envelope): TimelineGoalMarker[] => {
    const event = envelope.payload;
    if (!event || event.kind !== 'SHOT' || event.detail.outcome !== 'goal' || !event.team_id || event.event_time_ms > state.playhead_ms) return [];
    return [{ kind: 'goal', id: envelope.event_id, at: event.event_time_ms, teamId: event.team_id, playerId: event.player_id }];
  });
  return { insights, goals };
}

const casualLabels: Record<string, (value: number) => string> = {
  shots: (value) => `${value === 1 ? 'shot' : 'shots'}`,
  final_third_entries: (value) => `${value === 1 ? 'entry' : 'entries'} into the attacking third`,
  box_entries: (value) => `${value === 1 ? 'entry' : 'entries'} into the box`,
  completed_passes: (value) => `completed ${value === 1 ? 'pass' : 'passes'}`,
  possession_share: () => 'of the ball',
  live_turnovers: (value) => `${value === 1 ? 'change' : 'changes'} of possession`,
  on_target: () => 'on target',
};

export type FactCue = { factId: string; value: string; label: string; teamId: string | null };

/** Plain-language fact chips for Casual mode, built only from the insight's computed facts. */
export function casualFactCues(insight: Insight, match: Match, limit = 3): FactCue[] {
  return insight.facts.slice(0, limit).map((fact) => {
    const team = teamFor(match, fact.subject_id);
    const label = casualLabels[fact.metric]?.(fact.numeric_value) ?? fact.metric.replaceAll('_', ' ');
    const value = fact.unit === 'percent' ? formatPercent(fact.numeric_value) : fact.unit === 'milliseconds' ? `${Math.round(fact.numeric_value / 1000)}s` : String(fact.numeric_value);
    return { factId: fact.fact_id, value, label: team ? `${label} · ${team.short_name}` : label, teamId: team?.team_id ?? null };
  });
}
