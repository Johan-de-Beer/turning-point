import { useState } from 'react';
import { ArrowUpRight, Search, X } from 'lucide-react';
import { TeamMark } from '../../components/Brand';
import { patternLabel } from '../../components/EventDescription';
import type { Match, Session } from '../../lib/contracts';
import { teamFor } from '../../lib/events';
import { matchClock } from '../../lib/format';

export function PlayerFocus({ state, match, busy, onChange, onEvidence }: { state: Session; match: Match; busy: boolean; onChange: (id: string | null) => void; onEvidence: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const player = match.roster.find((item) => item.player_id === state.preferences.favorite_player_id);
  const players = match.roster.filter((item) => item.display_name.toLowerCase().includes(query.toLowerCase()) || item.shirt_number.toString() === query || item.player_id === player?.player_id);
  const stats = player ? state.player_stats[player.player_id] : null;
  const relevant = player ? state.insights.filter((insight) => insight.supported_player_ids.includes(player.player_id) && ['ready', 'corrected', 'expired'].includes(insight.status)) : [];
  const team = player ? teamFor(match, player.team_id) : undefined;
  return <section className="panel player-focus" id="player-focus" aria-labelledby="player-title">
    <div className="section-heading">
      <h2 id="player-title">Player focus</h2>
      {player && team && <TeamMark team={team} size="small" />}
    </div>
    <div className="player-controls">
      <div className="search-input"><Search size={16} aria-hidden="true" /><input aria-label="Search players" placeholder="Name or number" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
      <select aria-label="Focus player" value={player?.player_id ?? ''} disabled={busy} onChange={(event) => onChange(event.target.value || null)}>
        <option value="">Choose a player</option>
        {players.map((item) => <option key={item.player_id} value={item.player_id}>#{item.shirt_number} {item.display_name} · {teamFor(match, item.team_id)?.short_name}</option>)}
      </select>
      {player && <button className="icon-button" aria-label="Clear player focus" title="Clear player focus" disabled={busy} onClick={() => onChange(null)}><X size={16} /></button>}
    </div>
    {player && stats ? <>
      <p className="player-identity"><span className="player-number" style={{ color: team?.color }}>{player.shirt_number}</span><span><strong>{player.display_name}</strong>{team?.display_name} · {player.position}</span></p>
      <dl className="player-stat-grid">
        <div><dt>Involvements</dt><dd>{stats.involvement}</dd></div>
        <div><dt>Modeled touches</dt><dd>{stats.touches}</dd></div>
        <div><dt>Passes completed</dt><dd>{stats.passes_completed}/{stats.passes_attempted}</dd></div>
        <div><dt>Passes received</dt><dd>{stats.passes_received}</dd></div>
        <div><dt>Shots (on target)</dt><dd>{stats.shots} <small>({stats.on_target})</small></dd></div>
        <div><dt>{stats.goals ? 'Goals' : 'Tackles'}</dt><dd>{stats.goals || stats.tackles}</dd></div>
      </dl>
      {relevant.length ? <div className="player-insights"><h3>In the evidence for</h3><ul>{relevant.slice(-3).reverse().map((insight) => <li key={insight.insight_id}><button className="player-insight-link" onClick={() => onEvidence(insight.insight_id)}><span>{patternLabel[insight.pattern]}</span><small>{matchClock(insight.observed_window.end_ms)}</small><ArrowUpRight size={15} aria-hidden="true" /></button></li>)}</ul></div>
        : <p className="player-no-events">{stats.involvement ? 'No confirmed insight involves this player yet.' : 'No relevant events yet.'}</p>}
      <details className="player-definition"><summary>How are these counted?</summary>{['involvement', 'touches'].map((key) => state.diagnostics.definitions[key] && <p key={key}><strong>{key === 'touches' ? 'Modeled touches' : 'Involvements'}:</strong> {state.diagnostics.definitions[key]}</p>)}<p>Team statistics always include both clubs.</p></details>
    </> : <p className="player-no-events">Pick a fictional player to see their observed involvement, passes and shots. Team numbers stay the same whoever you follow.</p>}
  </section>;
}
