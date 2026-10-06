import type { CSSProperties } from 'react';
import type { Match, Session } from '../../lib/contracts';
import { formatPercent, humanize, relativeDelta, windowLabel } from '../../lib/format';

export function MetricsPanel({ state, match }: { state: Session; match: Match }) {
  const metrics = state.snapshot.team_metrics;
  const home = metrics[match.home.team_id];
  const away = metrics[match.away.team_id];
  if (!home || !away) return null;
  const rows = [
    { label: 'Possession', home: home.possession_share, away: away.possession_share, percentage: true, definition: 'Share of known owned in-play time.' },
    { label: 'Shots', home: home.shots, away: away.shots, definition: 'Observed shot events; each goal counts once.' },
    { label: 'Final-third entries', home: home.final_third_entries, away: away.final_third_entries, definition: 'Completed pass or carry crossing into x ≥ 66.67.' },
    { label: 'Pass accuracy', home: home.pass_accuracy, away: away.pass_accuracy, percentage: true, definition: 'Completed / attempted passes. No attempts is unavailable.' },
  ];
  const analyst = state.preferences.mode === 'analyst';
  const coverage = state.snapshot.coverage;
  return <section className="panel metrics-panel" id="metrics" aria-labelledby="metrics-title" style={{ '--home': match.home.color, '--away': match.away.color } as CSSProperties}>
    <div className="section-heading">
      <h2 id="metrics-title">Match numbers</h2>
      <span className="section-count">Last three minutes · {windowLabel(state.snapshot.window)}</span>
    </div>
    <div className="metric-legend"><span><i className="legend-home" aria-hidden="true" />{match.home.short_name}</span><span>{match.away.short_name}<i className="legend-away" aria-hidden="true" /></span></div>
    <dl className="metric-rows">{rows.map((row) => {
      const total = (row.home ?? 0) + (row.away ?? 0);
      const homeShare = total ? (row.home ?? 0) / total * 100 : 0;
      const awayShare = total ? 100 - homeShare : 0;
      const value = (side: number | null) => row.percentage ? formatPercent(side) : side ?? '—';
      return <div className="metric-row" key={row.label}>
        <dt className="metric-label">{row.label}</dt>
        <dd className="metric-values" aria-label={`${match.home.short_name} ${row.home == null ? 'unavailable' : value(row.home)}, ${match.away.short_name} ${row.away == null ? 'unavailable' : value(row.away)}`}>
          <strong className="home-value">{value(row.home)}</strong>
          <span className="comparison-bar" aria-hidden="true"><span className="bar-home" style={{ width: `${homeShare}%` }} /><span className="bar-away" style={{ width: `${awayShare}%` }} /></span>
          <strong className="away-value">{value(row.away)}</strong>
        </dd>
        {analyst && <dd className="metric-definition">{row.definition}</dd>}
      </div>;
    })}</dl>
    {analyst && <div className="analyst-extra">
      <div><span>Box entries</span><strong>{home.box_entries} <i>–</i> {away.box_entries}</strong></div>
      <div><span>Live turnovers</span><strong>{state.snapshot.live_turnovers}</strong></div>
      <div><span>Known in-play</span><strong>{Math.round(coverage.known_in_play_ms / 1000)}s</strong></div>
      <div><span>Unknown state</span><strong>{Math.round(coverage.unknown_state_ms / 1000)}s</strong></div>
    </div>}
    <div className="metric-footnote">
      <span className={`coverage-note ${coverage.eligible ? 'is-ok' : ''}`}>{coverage.eligible ? 'Complete observed window' : humanize(coverage.status)}</span>
      {analyst && <span>{state.snapshot.baseline ? `${match.home.short_name} shots ${relativeDelta(home.shots, state.snapshot.baseline.team_metrics[match.home.team_id]?.shots)}` : 'Prior window unavailable'}</span>}
    </div>
  </section>;
}
