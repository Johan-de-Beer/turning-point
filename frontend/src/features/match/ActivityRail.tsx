import type { CSSProperties } from 'react';
import { ArrowUpRight, FileText, LockKeyhole } from 'lucide-react';
import { describeEvent, patternLabel } from '../../components/EventDescription';
import type { Match, Session } from '../../lib/contracts';
import { feedItems, teamFor } from '../../lib/events';
import { humanize, matchClock, windowLabel } from '../../lib/format';

export function InsightTimeline({ match, state, onEvidence }: { match: Match; state: Session; onEvidence: (id: string) => void }) {
  const insights = [...state.insights].sort((a, b) => b.observed_window.end_ms - a.observed_window.end_ms);
  return <section className="rail-section timeline-section" id="timeline" aria-labelledby="timeline-title">
    <div className="section-heading"><h2 id="timeline-title">Insight timeline</h2><span className="count-chip">{insights.length} {insights.length === 1 ? 'insight' : 'insights'}</span></div>
    {insights.length ? <ol className="timeline-list">{insights.map((insight) => {
      const variant = insight.variants[state.preferences.mode];
      const team = insight.pattern === 'end_to_end' ? undefined : teamFor(match, insight.subject_ids[0]);
      return <li key={insight.insight_id} style={{ '--marker-color': team?.color ?? 'var(--teal)' } as CSSProperties}>
        <button className={`timeline-card ${insight.status === 'retracted' ? 'retracted' : ''}`} onClick={() => onEvidence(insight.insight_id)}>
          <span className="timeline-meta"><span className="timeline-clock">{matchClock(insight.observed_window.end_ms)}</span><span>{patternLabel[insight.pattern]}{team ? ` · ${team.short_name}` : ''}</span>{insight.status !== 'ready' && <span className={`status-tag status-${insight.status}`}>{humanize(insight.status)}</span>}</span>
          <strong>{variant?.headline ?? (insight.status === 'pending' ? 'Pattern under review' : patternLabel[insight.pattern])}</strong>
          <span className="timeline-window">Window {windowLabel(insight.observed_window)}<ArrowUpRight size={14} aria-hidden="true" /></span>
        </button>
      </li>;
    })}</ol> : <p className="rail-empty">Confirmed insights will appear here with their original match times.</p>}
  </section>;
}

export function EventFeed({ state, match, selectedId, playerOnly, onPlayerOnly, onSelect }: {
  state: Session; match: Match; selectedId: string | null; playerOnly: boolean;
  onPlayerOnly: (value: boolean) => void; onSelect: (id: string) => void;
}) {
  const player = match.roster.find((item) => item.player_id === state.preferences.favorite_player_id);
  const filtering = Boolean(player && playerOnly);
  const items = feedItems(state.events, filtering ? player!.player_id : null);
  return <section className="rail-section event-feed" aria-labelledby="feed-title">
    <div className="section-heading"><h2 id="feed-title">Latest events</h2><span className="feed-live">Observed to {matchClock(state.observed_high_water_ms)}</span></div>
    {player && <label className="feed-filter"><input type="checkbox" checked={playerOnly} onChange={(event) => onPlayerOnly(event.target.checked)} /><span>Only #{player.shirt_number} {player.display_name}<small>Goals and period markers stay visible.</small></span></label>}
    {items.length ? <ol className="event-list">{items.map(({ envelope, context }) => {
      const description = describeEvent(envelope, match);
      const event = envelope.payload;
      const team = teamFor(match, event?.team_id);
      const time = event?.event_time_ms ?? envelope.available_at_ms;
      return <li key={`${envelope.event_id}@${envelope.revision}`}>
        <button className={`event-row ${selectedId === envelope.event_id ? 'event-selected' : ''} ${event?.kind === 'SHOT' && event.detail.outcome === 'goal' ? 'is-goal' : ''}`} disabled={!event} data-event-id={envelope.event_id} data-event-revision={envelope.revision} data-event-time-ms={time} data-event-kind={event?.kind} data-team-id={event?.team_id ?? undefined} data-player-id={event?.player_id ?? undefined} onClick={() => onSelect(envelope.event_id)} aria-label={`Highlight ${description.title} at ${matchClock(time)} in the event replay${context ? ' (match context)' : ''}`}>
          <span className="event-time">{matchClock(time)}</span>
          <span className="event-glyph" style={{ color: team?.color }} aria-hidden="true">{description.icon}</span>
          <span className="event-description"><strong>{description.title}</strong><small>{description.detail}{team ? ` · ${team.short_name}` : ''}{envelope.revision > 1 && ' · corrected'}{context && ' · match context'}</small></span>
        </button>
      </li>;
    })}</ol> : <p className="rail-empty">{filtering ? `No relevant events for ${player!.display_name} yet.` : 'Waiting for kick-off.'}</p>}
  </section>;
}

export function RecapLinks({ state, onRecap }: { state: Session; onRecap: (phase: 'half_time' | 'full_time') => void }) {
  return <section className="rail-section recap-links" aria-label="Recaps">{(['half_time', 'full_time'] as const).map((phase) => {
    const recap = state.recaps[phase];
    const locked = !recap || recap.status === 'locked';
    const name = phase === 'half_time' ? 'Half-time' : 'Full-time';
    return <button key={phase} className="recap-link" disabled={locked} onClick={() => onRecap(phase)}>
      <span className="recap-icon" aria-hidden="true">{locked ? <LockKeyhole size={17} /> : <FileText size={17} />}</span>
      <span>{name} recap<small>{locked ? `Unlocks at ${phase === 'half_time' ? '45:00' : '90:00'}` : recap.status === 'pending' ? 'Preparing the recap' : recap.status === 'corrected' ? 'Corrected · read the recap' : 'Read the recap'}</small></span>
      {!locked && <ArrowUpRight size={16} aria-hidden="true" />}
    </button>;
  })}</section>;
}
