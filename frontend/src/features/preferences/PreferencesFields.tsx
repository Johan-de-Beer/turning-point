import { useId, useState } from 'react';
import { Check, Heart, Info, Layers3, Search, UserRound, UsersRound } from 'lucide-react';
import type { Match, Preferences } from '../../lib/contracts';
import { teamFor } from '../../lib/events';

export function PreferencesFields({ match, value, onChange, compact = false }: { match: Match; value: Preferences; onChange: (preferences: Preferences) => void; compact?: boolean }) {
  const [query, setQuery] = useState('');
  const id = useId();
  const players = match.roster.filter((player) => player.display_name.toLowerCase().includes(query.toLowerCase()) || player.shirt_number.toString() === query || player.player_id === value.favorite_player_id);
  return <div className={`preferences-fields ${compact ? 'preferences-compact' : ''}`}>
    <fieldset className="form-group">
      <legend className="field-label">Choose your view</legend>
      <div className="mode-options">
        <button type="button" className={value.mode === 'casual' ? 'selected' : ''} aria-pressed={value.mode === 'casual'} onClick={() => onChange({ ...value, mode: 'casual' })}>
          <span className="mode-icon"><UsersRound size={18} /></span><span>Casual<small>The match story in plain words</small></span>{value.mode === 'casual' && <Check size={16} className="mode-check" />}
        </button>
        <button type="button" className={value.mode === 'analyst' ? 'selected' : ''} aria-pressed={value.mode === 'analyst'} onClick={() => onChange({ ...value, mode: 'analyst' })}>
          <span className="mode-icon"><Layers3 size={18} /></span><span>Analyst<small>Windows, metrics and rule checks</small></span>{value.mode === 'analyst' && <Check size={16} className="mode-check" />}
        </button>
      </div>
    </fieldset>
    <div className="form-grid">
      <label className="form-group"><span className="field-label"><Heart size={14} /> Favorite club <span className="optional">optional</span></span>
        <select aria-label="Favorite club" value={value.favorite_team_id ?? ''} onChange={(event) => onChange({ ...value, favorite_team_id: event.target.value || null })}>
          <option value="">Follow the whole match</option>
          {[match.home, match.away].map((team) => <option key={team.team_id} value={team.team_id}>{team.display_name}</option>)}
        </select>
      </label>
      <label className="form-group"><span className="field-label"><UserRound size={14} /> Favorite player <span className="optional">optional</span></span>
        <select aria-label="Favorite player" value={value.favorite_player_id ?? ''} onChange={(event) => onChange({ ...value, favorite_player_id: event.target.value || null })}>
          <option value="">No player focus</option>
          {players.map((player) => <option key={player.player_id} value={player.player_id}>#{player.shirt_number} {player.display_name} · {teamFor(match, player.team_id)?.short_name}</option>)}
        </select>
      </label>
    </div>
    {!compact && <label className="form-group"><span className="field-label">Search the fictional roster</span>
      <div className="search-input"><Search size={16} aria-hidden="true" /><input aria-label="Search players" aria-describedby={`${id}-count`} placeholder="Player name or shirt number" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
      <small className="field-hint" id={`${id}-count`}>{query ? `${players.length} matching ${players.length === 1 ? 'player' : 'players'}` : `${match.roster.length} fictional adult players`}</small>
    </label>}
    <label className="check-row"><input type="checkbox" checked={value.pause_on_insight} onChange={(event) => onChange({ ...value, pause_on_insight: event.target.checked })} /><span>Pause when a new insight arrives<small>Useful at accelerated replay speeds.</small></span></label>
    {!compact && <p className="language-note"><Info size={16} aria-hidden="true" /><span>English only. Favorites change your view, never the match statistics.</span></p>}
  </div>;
}
