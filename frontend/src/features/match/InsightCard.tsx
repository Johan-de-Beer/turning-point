import type { CSSProperties } from 'react';
import { ArrowUpRight, Info, UserRound } from 'lucide-react';
import { patternGlossary, patternLabel } from '../../components/EventDescription';
import type { Insight, Match, Session } from '../../lib/contracts';
import { casualFactCues, teamFor } from '../../lib/events';
import { formatPercent, humanize, windowLabel } from '../../lib/format';

function providerLabel(provenance: string | undefined): string {
  if (provenance === 'microsoft_foundry') return 'Microsoft Foundry narrative';
  if (provenance === 'deterministic_fallback') return 'Template fallback';
  return 'Mock narrative';
}

export function InsightCard({ insight, state, match, onEvidence }: { insight: Insight | null; state: Session; match: Match; onEvidence: (id: string) => void }) {
  const analyst = state.preferences.mode === 'analyst';
  if (!insight) {
    const warming = state.snapshot.coverage.status === 'warming_up';
    const pending = state.diagnostics.pending_jobs > 0;
    const label = pending ? 'Under review' : warming ? 'Gathering context' : 'Open play';
    return <section className="insight-card is-empty" id="current-insight" aria-labelledby="insight-title">
      <div className="insight-meta"><span className="eyebrow">Match insight</span><span className="insight-window">{windowLabel(state.snapshot.window)}</span></div>
      <span className="waiting-line"><span className="pulse-dot" aria-hidden="true" />{label}</span>
      <h2 id="insight-title">{pending ? 'Checking the pattern.' : warming ? 'Give the game a moment.' : 'No clear pattern yet.'}</h2>
      <p className="insight-explanation">{pending ? 'An explanation is being checked against the observed events before it is shown.' : warming ? 'Insights begin after a complete three-minute window of play.' : 'The current window does not meet the conditions for a confirmed pattern. That is a normal result, not a missing one.'}</p>
      <p className="insight-hint">{analyst ? 'Coverage and rule checks for the current window are in Match numbers.' : 'Follow the latest events in the activity column.'}</p>
    </section>;
  }
  const variant = insight.variants[state.preferences.mode];
  const team = insight.pattern === 'end_to_end' ? undefined : teamFor(match, insight.subject_ids[0]);
  const player = match.roster.find((item) => item.player_id === state.preferences.favorite_player_id);
  const playerSupported = player ? insight.supported_player_ids.includes(player.player_id) : false;
  const cues = casualFactCues(insight, match);
  return <section className={`insight-card pattern-${insight.pattern}`} id="current-insight" aria-labelledby="insight-title" style={{ '--insight-color': team?.color ?? 'var(--teal)' } as CSSProperties}>
    <div className="insight-meta">
      <span className="pattern-chip"><span className="team-dot" aria-hidden="true" />{patternLabel[insight.pattern]}{team ? ` · ${team.short_name}` : ' · Both teams'}</span>
      {insight.status !== 'ready' && <span className={`status-tag status-${insight.status}`}>{humanize(insight.status)}</span>}
      <span className="insight-window">Observed {windowLabel(insight.observed_window)}</span>
    </div>
    <h2 id="insight-title">{variant?.headline ?? insight.interpretation}</h2>
    <p className="insight-explanation">{variant?.explanation ?? 'A checked explanation is being prepared for this view.'}</p>
    {analyst
      ? <div className="analyst-facts">{insight.facts.map((fact) => <div key={fact.fact_id}><span>{humanize(fact.metric)}</span><strong>{fact.unit === 'percent' ? formatPercent(fact.numeric_value) : fact.numeric_value}</strong><small>{teamFor(match, fact.subject_id)?.short_name ?? humanize(fact.subject_id)}</small></div>)}</div>
      : <>
        <ul className="fact-cues" aria-label="Key observations">{cues.map((cue) => <li key={cue.factId} style={{ '--cue-color': teamFor(match, cue.teamId)?.color ?? 'var(--teal)' } as CSSProperties}><strong>{cue.value}</strong><span>{cue.label}</span></li>)}</ul>
        <details className="glossary"><summary><Info size={14} aria-hidden="true" />What does “{patternLabel[insight.pattern].toLowerCase()}” mean?</summary><p>{patternGlossary[insight.pattern]} It describes the observed window and does not predict what happens next.</p></details>
      </>}
    {player && <p className={`player-context ${playerSupported ? 'is-supported' : ''}`}><UserRound size={15} aria-hidden="true" />{playerSupported ? `${player.display_name} appears in the events behind this insight.` : `${player.display_name} has no recorded role in this pattern. It is shown as match context.`}</p>}
    <div className="insight-footer">
      <button className="button button-secondary evidence-link" onClick={() => onEvidence(insight.insight_id)}>Why this insight?<ArrowUpRight size={16} aria-hidden="true" /></button>
      <span className="provider-label">{providerLabel(variant?.provenance)}</span>
    </div>
  </section>;
}
