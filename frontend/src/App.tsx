import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Braces, Check, CheckCircle2, ChevronRight, Clock3, Download, FileText, Flag, Heart, Info, Layers3, LayoutDashboard, LoaderCircle, LockKeyhole, Pause, Play, Radio, RotateCcw, Search, Settings2, ShieldCheck, Target, UserRound, UsersRound, WifiOff, X } from 'lucide-react';
import { Dialog } from './components/Dialog';
import { PitchScene } from './components/PitchScene';
import { eligibleOverlay, type Envelope, type Evidence, type Insight, type Match, type Preferences, type Recap, type Session, type Team } from './lib/contracts';
import { downloadJson, formatPercent, humanize, matchClock, relativeDelta, windowLabel } from './lib/format';
import { useMatch, type ControlAction } from './lib/useMatch';

type Controller = ReturnType<typeof useMatch>;
type Surface = 'preferences' | 'evidence' | 'overlay' | 'diagnostics' | 'recap' | 'provenance' | null;

function Brand({ compact = false }: { compact?: boolean }) {
  return <div className={`brand ${compact ? 'brand-compact' : ''}`}><div className="brand-symbol" aria-hidden="true"><span /><span /><span /></div>{!compact && <div className="brand-wordmark">turning<span>point</span></div>}</div>;
}

function TeamMark({ team, size = 'medium' }: { team: Team; size?: 'small' | 'medium' | 'large' }) {
  return <span className={`team-mark team-${team.team_id} mark-${size}`} style={{ '--team-color': team.color } as CSSProperties} aria-hidden="true"><span>{team.team_id === 'harbor' ? 'H' : 'V'}</span><i /><i /></span>;
}

function EmptyState({ icon, title, text, compact = false }: { icon?: ReactNode; title: string; text: string; compact?: boolean }) {
  return <div className={`empty-state ${compact ? 'empty-compact' : ''}`}>{icon && <div className="empty-icon">{icon}</div>}<h3>{title}</h3><p>{text}</p></div>;
}

function teamFor(match: Match, teamId: string | null | undefined): Team | undefined {
  return [match.home, match.away].find((team) => team.team_id === teamId);
}

function describeEvent(envelope: Envelope, match: Match): { title: string; detail: string; icon: ReactNode } {
  const event = envelope.payload;
  if (!event) return { title: 'Event withdrawn', detail: `${envelope.event_id} · revision ${envelope.revision}`, icon: <RotateCcw size={16} /> };
  const actor = match.roster.find((player) => player.player_id === event.player_id);
  const name = actor?.display_name ?? teamFor(match, event.team_id)?.display_name ?? 'Match';
  switch (event.kind) {
    case 'SHOT': return { title: event.detail.outcome === 'goal' ? `Goal · ${name}` : `Shot · ${name}`, detail: humanize(event.detail.outcome), icon: event.detail.outcome === 'goal' ? <Flag size={16} /> : <Target size={16} /> };
    case 'PASS': return { title: `${name} → ${match.roster.find((player) => player.player_id === event.detail.recipient_id)?.display_name ?? 'teammate'}`, detail: event.detail.completed ? 'Completed pass' : 'Incomplete pass', icon: <ArrowUpRight size={16} /> };
    case 'CARRY': return { title: name, detail: 'Ball carry', icon: <ArrowRight size={16} /> };
    case 'TACKLE': return { title: name, detail: event.detail.successful ? 'Successful tackle' : 'Attempted tackle', icon: <ShieldCheck size={16} /> };
    case 'POSSESSION': return { title: `${teamFor(match, event.team_id)?.display_name ?? 'Team'} in possession`, detail: 'Possession begins', icon: <Activity size={16} /> };
    case 'STOPPAGE': return { title: 'Play stopped', detail: humanize(event.detail.reason), icon: <Pause size={16} /> };
    case 'PERIOD_START': return { title: event.period === 1 ? 'Kick-off' : 'Second half begins', detail: 'Period boundary', icon: <Play size={16} /> };
    case 'PERIOD_END': return { title: event.period === 1 ? 'Half-time' : 'Full-time', detail: 'Period boundary', icon: <Flag size={16} /> };
  }
}

function PreferencesFields({ match, value, onChange, compact = false }: { match: Match; value: Preferences; onChange: (preferences: Preferences) => void; compact?: boolean }) {
  const [query, setQuery] = useState('');
  const players = match.roster.filter((player) => player.display_name.toLowerCase().includes(query.toLowerCase()) || player.shirt_number.toString() === query || player.player_id === value.favorite_player_id);
  return <div className={`preferences-fields ${compact ? 'preferences-compact' : ''}`}>
    <div className="form-group"><span className="field-label">Choose your view</span><div className="mode-options">
      <button type="button" className={value.mode === 'casual' ? 'selected' : ''} aria-pressed={value.mode === 'casual'} onClick={() => onChange({ ...value, mode: 'casual' })}><UsersRound size={17} /><span>Casual<small>A clear match story</small></span>{value.mode === 'casual' && <Check size={16} />}</button>
      <button type="button" className={value.mode === 'analyst' ? 'selected' : ''} aria-pressed={value.mode === 'analyst'} onClick={() => onChange({ ...value, mode: 'analyst' })}><Layers3 size={17} /><span>Analyst<small>Metrics and rule checks</small></span>{value.mode === 'analyst' && <Check size={16} />}</button>
    </div></div>
    <div className="form-grid">
      <label className="form-group"><span className="field-label"><Heart size={14} /> Favorite club <span>optional</span></span><select aria-label="Favorite club" value={value.favorite_team_id ?? ''} onChange={(event) => onChange({ ...value, favorite_team_id: event.target.value || null })}><option value="">Follow the whole match</option>{[match.home, match.away].map((team) => <option key={team.team_id} value={team.team_id}>{team.display_name}</option>)}</select></label>
      <label className="form-group"><span className="field-label"><UserRound size={14} /> Favorite player <span>optional</span></span><select aria-label="Favorite player" value={value.favorite_player_id ?? ''} onChange={(event) => onChange({ ...value, favorite_player_id: event.target.value || null })}><option value="">No player focus</option>{players.map((player) => <option key={player.player_id} value={player.player_id}>#{player.shirt_number} {player.display_name} · {teamFor(match, player.team_id)?.short_name}</option>)}</select></label>
    </div>
    {!compact && <label className="form-group"><span className="field-label">Search the fictional roster</span><div className="search-input"><Search size={17} /><input aria-label="Search players" placeholder="Player name or shirt number" value={query} onChange={(event) => setQuery(event.target.value)} /></div></label>}
    <label className="check-row"><input type="checkbox" checked={value.pause_on_insight} onChange={(event) => onChange({ ...value, pause_on_insight: event.target.checked })} /><span>Pause when a new insight arrives<small>Useful at accelerated replay speeds.</small></span></label>
    {!compact && <div className="language-note"><Info size={16} /><span>English only. Favorites change your view, never the match statistics.</span></div>}
  </div>;
}

function StartScreen({ controller, onProvenance }: { controller: Controller; onProvenance: () => void }) {
  const { match, preferences, loading, busy, start, updatePreferences, retry, error } = controller;
  if (!match) return <main className="loading-screen"><Brand /><div className="loading-panel">
    {loading ? <><LoaderCircle className="spin" size={28} /><h1>Loading the fixture</h1><p>Connecting to your local replay.</p></>
      : <><WifiOff size={28} /><h1>Replay server unavailable</h1><p>{error?.message ?? 'Start the FastAPI server, then try again.'}</p><button className="button button-primary" onClick={() => void retry()}>Try again <RotateCcw size={17} /></button></>}
  </div></main>;
  return <main className="start-screen">
    <header className="start-header"><Brand /><button className="synthetic-badge" onClick={onProvenance}><ShieldCheck size={14} /> Synthetic match <Info size={13} /></button></header>
    <section className="start-hero">
      <div className="start-copy">
        <span className="eyebrow">A FOOTBALL SECOND SCREEN</span>
        <h1>Read<br />the game<span className="headline-period">.</span></h1>
        <p>See the shifts in play. Understand the numbers. Follow the match with explanations you can check.</p>
        <a className="start-jump" href="#start-setup">Meet the fixture <ArrowDownRight size={19} /></a>
      </div>
      <div className="hero-stadium">
        <div className="hero-stadium-label"><span>{match.home.short_name} <i>vs</i> {match.away.short_name}</span><span>SCHEMATIC MATCH VIEW</span></div>
        <PitchScene events={[]} homeTeamId={match.home.team_id} awayTeamId={match.away.team_id} period={1} playheadMs={0} isPlaying={false} />
        <div className="hero-caption"><span>Two fictional clubs. A full 90-minute replay.</span><span>3D EVENT VIEW</span></div>
      </div>
    </section>
    <section className="start-setup" id="start-setup">
      <div className="fixture-intro">
        <span className="eyebrow">THE FIXTURE</span>
        <div className="start-fixture"><div><TeamMark team={match.home} size="large" /><h2>{match.home.display_name}</h2><small>HOME</small></div><span className="versus">/</span><div><TeamMark team={match.away} size="large" /><h2>{match.away.display_name}</h2><small>AWAY</small></div></div>
        <p className="fixture-notice"><Clock3 size={17} /><span>Starts at 60× speed. Pause at any point.</span></p>
      </div>
      <div className="setup-controls"><PreferencesFields match={match} value={preferences} onChange={(next) => void updatePreferences(next)} compact /><button className="button button-primary start-button" disabled={busy} onClick={() => void start()}>{busy ? <LoaderCircle size={18} className="spin" /> : <Play size={17} fill="currentColor" />} {busy ? 'Opening replay…' : 'Start replay'}<ArrowRight size={20} /></button></div>
    </section>
    {error && <div className="error-banner" role="alert"><Info size={18} /><p>{error.message}</p><button className="text-button" onClick={() => void retry()}>Retry</button></div>}
    <footer className="start-footer"><button className="text-button" onClick={onProvenance}>About the synthetic data <ArrowUpRight size={13} /></button><span>LOCAL REPLAY <i>·</i> MOCK PROVIDER</span></footer>
  </main>;
}

function Scoreboard({ match, state, onRecap }: { match: Match; state: Session; onRecap: (phase: 'half_time' | 'full_time') => void }) {
  const status = state.status === 'playing' ? `${state.period === 1 ? 'First' : 'Second'} half` : humanize(state.status);
  return <section className="scoreboard" aria-label={`${match.home.display_name} ${state.score[match.home.team_id] ?? 0}, ${match.away.display_name} ${state.score[match.away.team_id] ?? 0}. ${status}. ${matchClock(state.playhead_ms)}`}>
    <div className="fixture-team home"><TeamMark team={match.home} /><div><h1>{match.home.display_name}</h1><span>HOME <i /> {state.preferences.favorite_team_id === match.home.team_id ? 'YOUR CLUB' : match.home.short_name}</span></div></div>
    <div className="score-center"><span className="score-figures">{state.score[match.home.team_id] ?? 0}<em>:</em>{state.score[match.away.team_id] ?? 0}</span><div className="clock"><span className={state.status === 'playing' ? 'clock-dot' : 'clock-dot paused'} />{matchClock(state.playhead_ms)} <span>{status}</span></div></div>
    <div className="fixture-team away"><div><h1>{match.away.display_name}</h1><span>{state.preferences.favorite_team_id === match.away.team_id ? 'YOUR CLUB' : match.away.short_name} <i /> AWAY</span></div><TeamMark team={match.away} /></div>
    {(state.status === 'half_time' || state.status === 'ended') && <button className="score-recap text-button" onClick={() => onRecap(state.status === 'half_time' ? 'half_time' : 'full_time')}><FileText size={15} /> Open {state.status === 'half_time' ? 'half-time' : 'full-time'} recap <ChevronRight size={15} /></button>}
  </section>;
}

function ReplayToolbar({ controller, onPreferences, onRestart }: { controller: Controller; onPreferences: () => void; onRestart: () => void }) {
  const { state, busy, control, updatePreferences } = controller;
  if (!state) return null;
  const action: ControlAction = state.status === 'half_time' ? 'continue_half' : state.status === 'playing' ? 'pause' : 'play';
  const actionName = state.status === 'half_time' ? 'Continue second half' : state.status === 'playing' ? 'Pause replay' : 'Play replay';
  return <section className="replay-toolbar" aria-label="Replay controls"><div className="playback-controls"><button className="button playback-button" aria-label={actionName} disabled={busy || state.status === 'ended'} onClick={() => void control(action)}>{busy ? <LoaderCircle size={16} className="spin" /> : state.status === 'playing' ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}<span>{state.status === 'half_time' ? 'Second half' : state.status === 'playing' ? 'Pause' : 'Play'}</span></button><button className="icon-button restart-button" aria-label="Restart replay" title="Restart replay" disabled={busy} onClick={onRestart}><RotateCcw size={17} /></button><div className="toolbar-divider" /><label className="speed-control"><span>Speed</span><select aria-label="Replay speed" value={state.speed} disabled={busy} onChange={(event) => void control('set_speed', Number(event.target.value) as 1 | 12 | 60)}><option value={1}>1×</option><option value={12}>12×</option><option value={60}>60×</option></select></label><span className="replay-description">Synthetic replay</span></div><div className="lens-controls"><span className="lens-label">VIEW</span><div className="segmented-control" aria-label="Audience mode"><button aria-pressed={state.preferences.mode === 'casual'} disabled={busy} className={state.preferences.mode === 'casual' ? 'active' : ''} onClick={() => void updatePreferences({ ...state.preferences, mode: 'casual' })}><UsersRound size={14} />Casual</button><button aria-pressed={state.preferences.mode === 'analyst'} disabled={busy} className={state.preferences.mode === 'analyst' ? 'active' : ''} onClick={() => void updatePreferences({ ...state.preferences, mode: 'analyst' })}><Layers3 size={14} />Analyst</button></div><button className="icon-button" aria-label="Open preferences" title="Preferences" onClick={onPreferences}><Settings2 size={18} /></button></div></section>;
}

function InsightCard({ insight, state, match, onEvidence }: { insight: Insight | null; state: Session; match: Match; onEvidence: (id: string) => void }) {
  if (!insight) {
    const warming = state.snapshot.coverage.status === 'warming_up';
    const pending = state.diagnostics.pending_jobs > 0;
    return <section className="current-insight empty-insight" id="current-insight">
      <div className="section-heading"><span className="eyebrow">MATCH INSIGHT</span><span className="insight-time">{windowLabel(state.snapshot.window)}</span></div>
      <div className="insight-empty-content"><div>
        <span className="waiting-line"><span className="tiny-dot" />{pending ? 'UNDER REVIEW' : warming ? 'GATHERING CONTEXT' : 'OPEN PLAY'}</span>
        <h2>{pending ? 'Checking the pattern.' : warming ? 'Give the game a moment.' : 'No clear pattern yet.'}</h2>
        <p>{pending ? 'An explanation is being checked against the observed events.' : warming ? 'Insights begin after a complete three-minute window of play.' : 'The current window does not meet the conditions for a confirmed pattern.'}</p>
      </div></div>
      <div className="insight-footer"><span>{state.preferences.mode === 'analyst' ? 'Rules and coverage checks are available in the statistics.' : 'Follow the latest events below.'}</span></div>
    </section>;
  }
  const variant = insight.variants[state.preferences.mode];
  const team = teamFor(match, insight.subject_ids[0]);
  return <section className={`current-insight pattern-${insight.pattern}`} id="current-insight">
    <div className="section-heading"><span className="eyebrow">{insight.status === 'corrected' ? 'CORRECTED INSIGHT' : 'MATCH INSIGHT'}</span><span className="insight-time">{windowLabel(insight.observed_window)}</span></div>
    <div className="pattern-label"><span style={{ backgroundColor: team?.color ?? '#5eead4' }} />{humanize(insight.pattern)}</div>
    <h2>{variant?.headline ?? insight.interpretation}</h2>
    <p className="insight-explanation">{variant?.explanation ?? 'A checked explanation is being prepared for this view.'}</p>
    {state.preferences.mode === 'analyst' && <div className="analyst-facts">{insight.facts.map((fact) => <div key={fact.fact_id}><span>{humanize(fact.metric)}</span><strong>{fact.unit === 'percent' ? formatPercent(fact.numeric_value) : fact.numeric_value}</strong><small>{teamFor(match, fact.subject_id)?.short_name ?? fact.subject_id}</small></div>)}</div>}
    <div className="insight-footer"><button className="text-button evidence-link" onClick={() => onEvidence(insight.insight_id)}>Why this insight? <ArrowUpRight size={17} /></button><span className="provider-label">{variant?.provenance === 'microsoft_foundry' ? 'Microsoft Foundry' : variant?.provenance === 'deterministic_fallback' ? 'Template fallback' : 'Mock narrative'}</span></div>
  </section>;
}

function MetricsPanel({ state, match }: { state: Session; match: Match }) {
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
  return <section className="metrics-panel" id="metrics">
    <div className="section-heading"><div><span className="eyebrow">MATCH NUMBERS</span><h2>Last three minutes</h2></div><span className="window-tag">{windowLabel(state.snapshot.window)}</span></div>
    <div className="metric-teams"><span><i style={{ background: match.home.color }} />{match.home.short_name}</span><span><i style={{ background: match.away.color }} />{match.away.short_name}</span></div>
    <div className="metric-rows">{rows.map((row) => {
      const denominator = (row.home ?? 0) + (row.away ?? 0);
      const share = denominator ? (row.home ?? 0) / denominator * 100 : 50;
      return <div className="metric-row" key={row.label} title={row.definition}>
        <span className="metric-label">{row.label}</span>
        <div className="metric-values"><strong style={{ color: match.home.color }}>{row.percentage ? formatPercent(row.home) : row.home ?? '—'}</strong><span>–</span><strong style={{ color: match.away.color }}>{row.percentage ? formatPercent(row.away) : row.away ?? '—'}</strong></div>
        <div className="comparison-bar" aria-label={`${match.home.short_name} ${row.home == null ? 'unavailable' : row.home}, ${match.away.short_name} ${row.away == null ? 'unavailable' : row.away}. ${row.label}`}><span style={{ width: `${share}%`, background: match.home.color }} /><span style={{ width: `${100 - share}%`, background: match.away.color }} /></div>
        {analyst && <p className="metric-definition">{row.definition}</p>}
      </div>;
    })}</div>
    {analyst && <div className="analyst-extra"><div><span>Box entries</span><strong>{home.box_entries} <i>:</i> {away.box_entries}</strong></div><div><span>Live turnovers</span><strong>{state.snapshot.live_turnovers}</strong></div><div><span>Known in-play</span><strong>{Math.round(state.snapshot.coverage.known_in_play_ms / 1000)}s</strong></div><div><span>Unknown state</span><strong>{Math.round(state.snapshot.coverage.unknown_state_ms / 1000)}s</strong></div></div>}
    <div className="metric-footnote"><span>{state.snapshot.coverage.eligible ? 'Complete observed window' : humanize(state.snapshot.coverage.status)}</span>{analyst && <span>{state.snapshot.baseline ? relativeDelta(home.shots, state.snapshot.baseline.team_metrics[match.home.team_id]?.shots) : 'Prior window unavailable'}</span>}</div>
  </section>;
}

function EventFeed({ state, match, selectedId, onSelect }: { state: Session; match: Match; selectedId: string | null; onSelect: (id: string) => void }) {
  const events = state.events.filter((event) => event.payload && event.payload.kind !== 'POSSESSION').slice(-4).reverse();
  return <section className="event-feed">
    <div className="section-heading"><h2>Latest events</h2><span className="feed-live">OBSERVED THROUGH {matchClock(state.observed_high_water_ms)}</span></div>
    {events.length ? <ol className="event-list">{events.map((envelope) => {
      const description = describeEvent(envelope, match);
      const event = envelope.payload!;
      return <li key={envelope.event_id}><button className={`event-row ${selectedId === envelope.event_id ? 'event-selected' : ''}`} onClick={() => onSelect(envelope.event_id)} aria-label={`Highlight ${description.title} at ${matchClock(event.event_time_ms)} on the schematic pitch`}>
        <span className="event-time">{matchClock(event.event_time_ms)}</span><span className="event-glyph" style={{ color: teamFor(match, event.team_id)?.color }}>{description.icon}</span><span className="event-description"><strong>{description.title}</strong><small>{description.detail}{envelope.revision > 1 && ' · corrected'}</small></span><ArrowUpRight size={14} />
      </button></li>;
    })}</ol> : <p className="feed-empty">Waiting for kick-off.</p>}
  </section>;
}

function PlayerFocus({ state, match, busy, onChange, onEvidence }: { state: Session; match: Match; busy: boolean; onChange: (id: string | null) => void; onEvidence: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const player = match.roster.find((item) => item.player_id === state.preferences.favorite_player_id);
  const players = match.roster.filter((item) => item.display_name.toLowerCase().includes(query.toLowerCase()) || item.shirt_number.toString() === query || item.player_id === player?.player_id);
  const stats = player ? state.player_stats[player.player_id] : null;
  const relevant = player ? state.insights.filter((insight) => insight.supported_player_ids.includes(player.player_id) && ['ready', 'corrected', 'expired'].includes(insight.status)) : [];
  const team = player ? teamFor(match, player.team_id) : undefined;
  return <section className="player-focus" id="player-focus">
    <div className="section-heading"><div><span className="eyebrow">PLAYER FOCUS</span><h2>{player ? player.display_name : 'Follow a player'}</h2></div>{player && <TeamMark team={team!} size="small" />}</div>
    <div className="player-controls"><div className="search-input"><Search size={16} /><input aria-label="Search players" placeholder="Name or number" value={query} onChange={(event) => setQuery(event.target.value)} /></div><select aria-label="Focus player" value={player?.player_id ?? ''} disabled={busy} onChange={(event) => onChange(event.target.value || null)}><option value="">Choose a player</option>{players.map((item) => <option key={item.player_id} value={item.player_id}>#{item.shirt_number} {item.display_name} · {teamFor(match, item.team_id)?.short_name}</option>)}</select></div>
    {player && stats ? <>
      <div className="player-identity"><span className="player-number" style={{ color: team?.color }}>#{player.shirt_number}</span><span>{team?.display_name} <i>·</i> {player.position}</span></div>
      <div className="player-stat-grid"><div><strong>{stats.involvement}</strong><span>Involvements</span></div><div><strong>{stats.passes_completed}/{stats.passes_attempted}</strong><span>Passes completed</span></div><div><strong>{stats.shots}</strong><span>Shots</span></div></div>
      {relevant.length ? <button className="player-insight-link" onClick={() => onEvidence(relevant[relevant.length - 1].insight_id)}>Included in {humanize(relevant[relevant.length - 1].pattern).toLowerCase()} <ArrowUpRight size={16} /></button> : <p className="player-no-events">{stats.involvement ? 'No confirmed insight involves this player yet.' : 'No relevant events yet.'}</p>}
      <details className="player-definition"><summary>What counts as involvement?</summary><p>One event as actor or pass recipient. Team statistics always include both clubs.</p></details>
    </> : <p className="player-no-events">Select a player to see their observed involvement, passes and shots.</p>}
  </section>;
}

function InsightTimeline({ state, onEvidence, onRecap }: { state: Session; onEvidence: (id: string) => void; onRecap: (phase: 'half_time' | 'full_time') => void }) {
  const insights = [...state.insights].sort((a, b) => b.observed_window.end_ms - a.observed_window.end_ms);
  return <section className="timeline-section" id="timeline">
    <div className="section-heading"><div><span className="eyebrow">THE MATCH SO FAR</span><h2>Insight timeline</h2></div><span className="timeline-count">{insights.length} {insights.length === 1 ? 'insight' : 'insights'}</span></div>
    <div className="timeline-list">{insights.length ? insights.map((insight) => {
      const variant = insight.variants[state.preferences.mode];
      return <button className={`timeline-card ${insight.status === 'retracted' ? 'retracted' : ''}`} key={insight.insight_id} onClick={() => onEvidence(insight.insight_id)}>
        <div className="timeline-meta"><span>{matchClock(insight.observed_window.end_ms)}</span>{insight.status !== 'ready' && <span className={`status-tag status-${insight.status}`}>{humanize(insight.status)}</span>}</div>
        <h3>{variant?.headline ?? (insight.status === 'pending' ? 'Pattern under review' : humanize(insight.pattern))}</h3><p>{windowLabel(insight.observed_window)}</p><div className="timeline-bottom"><span>{humanize(insight.pattern)}</span><ArrowUpRight size={17} /></div>
      </button>;
    }) : <p className="timeline-empty">Confirmed insights will appear here as the match develops.</p>}</div>
    <div className="recap-links">{(['half_time', 'full_time'] as const).map((phase) => {
      const recap = state.recaps[phase];
      const locked = !recap || recap.status === 'locked';
      return <button key={phase} className="recap-link" disabled={locked} onClick={() => onRecap(phase)}>{locked ? <LockKeyhole size={18} /> : <FileText size={18} />}<span>{phase === 'half_time' ? 'Half-time' : 'Full-time'} recap<small>{locked ? `After ${phase === 'half_time' ? 'half-time' : 'full-time'}` : recap.status === 'pending' ? 'Preparing the recap' : 'Read the recap'}</small></span><ArrowUpRight size={17} /></button>;
    })}</div>
  </section>;
}

function FactValue({ value, unit }: { value: number; unit: string }) {
  return <>{unit === 'percent' ? formatPercent(value) : unit === 'milliseconds' ? `${Math.round(value / 1000)}s` : value}</>;
}

function EvidenceInspector({ evidence, match, selectedId, onSelect }: { evidence: Evidence; match: Match; selectedId: string | null; onSelect: (id: string) => void }) {
  const { insight, snapshot } = evidence;
  return <div className="evidence-inspector">{insight.status === 'retracted' && <div className="correction-notice"><RotateCcw size={17} /><span>This historic insight was retracted after a correction. These original event versions explain its prior decision; they do not describe the current corrected match.</span></div>}<div className="evidence-summary"><span className="status-tag status-ready"><ShieldCheck size={12} /> {humanize(insight.evidence_quality)} evidence</span><span>{windowLabel(insight.observed_window)} <i>•</i> {snapshot.rules_version}</span></div><p className="evidence-intro">{insight.interpretation}</p><section><h3><CheckCircle2 size={17} /> Measured facts</h3><div className="facts-grid">{evidence.facts.map((fact) => <div className="fact-card" key={fact.fact_id}><span>{humanize(fact.metric)}</span><strong><FactValue value={fact.numeric_value} unit={fact.unit} /></strong><small>{teamFor(match, fact.subject_id)?.display_name ?? fact.subject_id}</small><code>{fact.fact_id}</code><p>{fact.source_event_refs.length} source references · {windowLabel(fact.window)}</p></div>)}</div></section><section><h3><Layers3 size={17} /> Heuristic rule checks</h3><p className="section-description">Each condition is checked against the same three-minute window. These descriptive thresholds have not been scientifically validated.</p><div className="rule-table table-scroll"><table><thead><tr><th>Observation</th><th>Subject</th><th>Rule</th><th>Observed</th><th>Check</th></tr></thead><tbody>{evidence.conditions.map((condition, index) => <tr key={`${condition.metric}-${index}`}><td>{humanize(condition.metric)}</td><td>{teamFor(match, condition.subject_id)?.short_name ?? condition.subject_id}</td><td>{condition.operator} {condition.threshold}</td><td>{condition.actual == null ? 'Unavailable' : Math.round(condition.actual * 100) / 100}</td><td>{condition.passed ? <span className="check-pass"><Check size={14} /> Pass</span> : <span className="check-fail"><X size={14} /> Fail</span>}</td></tr>)}</tbody></table></div></section><section><h3><Activity size={17} /> Coverage and comparison</h3><div className="coverage-grid"><div><span>Known owned in-play</span><strong>{Math.round(snapshot.coverage.known_in_play_ms / 1000)}s</strong></div><div><span>Stoppage</span><strong>{Math.round(snapshot.coverage.stoppage_ms / 1000)}s</strong></div><div><span>Unknown state</span><strong>{Math.round(snapshot.coverage.unknown_state_ms / 1000)}s</strong></div><div><span>Coverage gate</span><strong>{snapshot.coverage.eligible ? 'Passed' : humanize(snapshot.coverage.status)}</strong></div></div>{snapshot.baseline ? <div className="baseline-comparison"><p>Prior observed window: <strong>{windowLabel(snapshot.baseline.window)}</strong></p>{[match.home, match.away].map((team) => <p key={team.team_id}>{team.short_name}: {snapshot.team_metrics[team.team_id]?.shots} shots now · {snapshot.baseline?.team_metrics[team.team_id]?.shots} before</p>)}</div> : <p className="baseline-unavailable">A full preceding window is unavailable. No increase or change is claimed from a missing baseline.</p>}</section><section><h3><Radio size={17} /> Supporting event versions</h3><p className="section-description">Select a record to show its location on the pitch.</p><div className="evidence-event-table table-scroll"><table><thead><tr><th>Match time</th><th>Event</th><th>Observed record</th><th>Reference</th><th>Pitch</th></tr></thead><tbody>{evidence.events.map((envelope) => {
    const description = describeEvent(envelope, match);
    return <tr key={`${envelope.event_id}@${envelope.revision}`} className={selectedId === envelope.event_id ? 'selected-record' : ''}><td>{matchClock(envelope.payload?.event_time_ms ?? envelope.available_at_ms)}</td><td>{envelope.payload?.kind ?? 'DELETED'}</td><td>{description.title}<small>{description.detail}</small></td><td><code>{envelope.event_id}@{envelope.revision}</code></td><td><button className="text-button" onClick={() => onSelect(envelope.event_id)} aria-label={`Show ${envelope.event_id} on the pitch`}>Show <ArrowUpRight size={13} /></button></td></tr>;
  })}</tbody></table></div><p className="reference-count">{evidence.events.length} observed source records. Original revisions are linked to their fact IDs.</p></section><section className="limitations-section"><h3><Info size={17} /> Interpretation and limitations</h3><ul>{insight.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul><details><summary>Metric definitions</summary>{Object.entries(evidence.metric_definitions).map(([metric, definition]) => <p key={metric}><strong>{humanize(metric)}:</strong> {definition}</p>)}</details></section></div>;
}

function Diagnostics({ state }: { state: Session }) {
  const diagnostics = state.diagnostics;
  return <div className="diagnostics-view"><div className="provider-banner"><ShieldCheck size={22} /><div><strong>{diagnostics.provider === 'mock' ? 'Deterministic mock provider' : humanize(diagnostics.provider)}</strong><p>{diagnostics.provider_status}. No credentials or raw prompts are shown here.</p></div></div><div className="pipeline-grid">{Object.entries(diagnostics.pipeline).map(([stage, status], index) => <div key={stage}><span>0{index + 1}</span><strong>{humanize(stage)}</strong><small>{humanize(status)}</small></div>)}</div><div className="diagnostic-keys"><span>Generation <strong>{state.generation}</strong></span><span>Data epoch <strong>{state.data_epoch}</strong></span><span>Preferences <strong>{state.preferences_version}</strong></span><span>Pending jobs <strong>{diagnostics.pending_jobs}</strong></span><span>Rules <strong>{diagnostics.rules_version}</strong></span></div>{diagnostics.correction_notice && <div className="correction-notice"><RotateCcw size={17} />{diagnostics.correction_notice}</div>}<h3>Two-role review trail</h3>{diagnostics.agent_runs.length ? <div className="agent-run-list">{[...diagnostics.agent_runs].reverse().map((run) => <div className="agent-run" key={run.run_id}><div className="agent-run-heading"><span>{run.role === 'football_analyst' ? <Activity size={17} /> : <ShieldCheck size={17} />}</span><strong>{humanize(run.role)}</strong><span className={`status-tag status-${run.status}`}>{humanize(run.status)}</span></div><p>{run.provider} · {run.duration_ms}ms · {run.fact_ids.length} selected facts</p><code>{run.snapshot_id}</code>{run.validation_errors.length > 0 && <ul>{run.validation_errors.map((error) => <li key={error}>{error}</li>)}</ul>}{run.fallback_reason && <p className="fallback-reason">Fallback: {run.fallback_reason}</p>}</div>)}</div> : <EmptyState compact title="The review trail starts with the first candidate" text="The Analyst proposes an interpretation; the Editor checks it against the same immutable facts." />}<details><summary>Ingestion and suppressed candidates</summary><p>Rejected records: {diagnostics.ingestion_errors.length}</p>{diagnostics.ingestion_errors.map((error) => <p key={error}>{error}</p>)}<p>Suppressed candidates: {diagnostics.suppressed_candidates.length}</p>{diagnostics.suppressed_candidates.map((candidate) => <p key={candidate}>{candidate}</p>)}</details></div>;
}

function RecapView({ recap, state, match, onEvidence }: { recap: Recap | undefined; state: Session; match: Match; onEvidence: (id: string) => void }) {
  if (!recap || recap.status === 'locked') return <EmptyState icon={<LockKeyhole size={28} />} title="The match is still in progress" text="The recap unlocks only after its period-end marker is delivered. Future events and scores are never loaded into this view." />;
  if (recap.status === 'pending') return <EmptyState icon={<LoaderCircle size={28} className="spin" />} title="Preparing the recap" text="The recap is being prepared from the period-end evidence cutoff." />;
  const variant = recap.variants[state.preferences.mode];
  const beats = variant?.story_beats ?? recap.story_beats;
  return <div className="recap-view">{recap.correction_notice && <div className="correction-notice"><RotateCcw size={17} />{recap.correction_notice}</div>}<div className="recap-score"><TeamMark team={match.home} /><div><span>{match.home.short_name}</span><strong>{recap.score[match.home.team_id] ?? 0} <i>:</i> {recap.score[match.away.team_id] ?? 0}</strong><span>{match.away.short_name}</span></div><TeamMark team={match.away} /></div><span className="eyebrow">{recap.phase === 'half_time' ? 'HALF-TIME' : 'FULL-TIME'}</span><h2>{variant?.headline ?? humanize(recap.phase)}</h2><p className="recap-intro">{variant?.explanation ?? 'An auditable synthesis of observed play.'}</p><div className="story-beats">{beats.map((beat, index) => <article key={beat.insight_id}><span className="story-number">0{index + 1}</span><div><span className="window-tag">{windowLabel(beat.observed_window)}</span><h3>{beat.headline}</h3><p>{beat.explanation}</p><button className="text-button" onClick={() => onEvidence(beat.insight_id)}>Inspect the evidence <ArrowUpRight size={14} /></button></div></article>)}</div>{!beats.length && <p>No distinct confirmed patterns were eligible at this cutoff. The score and period context remain observed facts.</p>}{variant?.player_summary && <div className="recap-player"><UserRound size={20} /><p>{variant.player_summary}</p></div>}{state.preferences.mode === 'analyst' && <div className="recap-facts"><h3>Recap fact references</h3>{recap.facts.map((fact) => <div key={fact.fact_id}><span>{teamFor(match, fact.subject_id)?.short_name ?? fact.subject_id} · {humanize(fact.metric)}</span><strong><FactValue value={fact.numeric_value} unit={fact.unit} /></strong><code>{fact.fact_id}</code></div>)}</div>}<div className="recap-cutoff"><ShieldCheck size={15} /><span>Observed through {matchClock(recap.cutoff_ms ?? 0)} · generation {recap.generation} · data epoch {recap.data_epoch}</span></div></div>;
}

export default function App() {
  const controller = useMatch();
  const { match, state, preferences, busy, error, connection } = controller;
  const [surface, setSurface] = useState<Surface>(null);
  const [draft, setDraft] = useState<Preferences>(preferences);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [selectedRecord, setSelectedRecord] = useState<Envelope | null>(null);
  const [recapPhase, setRecapPhase] = useState<'half_time' | 'full_time'>('half_time');
  const [restartOpen, setRestartOpen] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const [copied, setCopied] = useState(false);
  const [activeNav, setActiveNav] = useState('overview');
  const overlay = state ? eligibleOverlay(state) : null;
  const pitchEvents = useMemo(() => {
    const records = state?.events.filter((record) => record.event_id !== selectedRecord?.event_id) ?? [];
    if (selectedRecord) records.push(selectedRecord);
    return records.flatMap((record) => record.payload ? [{ ...record.payload, event_id: record.event_id }] : []);
  }, [state?.events, selectedRecord]);
  const currentInsight = useMemo(() => {
    if (!state) return null;
    return state.insights.filter((insight) => ['ready', 'corrected', 'expired'].includes(insight.status) && insight.variants[state.preferences.mode]?.preferences_version === state.preferences_version).sort((a, b) => {
      const aFavorite = state.preferences.favorite_team_id && a.subject_ids.includes(state.preferences.favorite_team_id) ? 1 : 0;
      const bFavorite = state.preferences.favorite_team_id && b.subject_ids.includes(state.preferences.favorite_team_id) ? 1 : 0;
      const aPlayer = state.preferences.favorite_player_id && a.supported_player_ids.includes(state.preferences.favorite_player_id) ? 1 : 0;
      const bPlayer = state.preferences.favorite_player_id && b.supported_player_ids.includes(state.preferences.favorite_player_id) ? 1 : 0;
      return bFavorite - aFavorite || bPlayer - aPlayer || b.observed_window.end_ms - a.observed_window.end_ms;
    })[0] ?? null;
  }, [state]);
  const currentId = currentInsight?.insight_id;
  useEffect(() => {
    if (currentInsight) setAnnouncement(`New match insight: ${currentInsight.variants[state?.preferences.mode ?? 'casual']?.headline ?? currentInsight.interpretation}`);
    // Significant insight announcements only; the replay clock is intentionally excluded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);
  useEffect(() => { setSelectedEventId(null); setSelectedRecord(null); setEvidence(null); setSurface(null); }, [state?.generation]);
  useEffect(() => { setSelectedEventId(null); setSelectedRecord(null); }, [state?.data_epoch]);
  useEffect(() => {
    if (evidence && state && evidence.data_epoch !== state.data_epoch) {
      setEvidence(null);
      setEvidenceError('A delivered correction changed the observed data. Open the insight again to inspect its current status.');
    }
  }, [evidence, state?.data_epoch]);

  function openPreferences() { setDraft(preferences); setSurface('preferences'); }
  async function openEvidence(id: string) {
    setEvidence(null); setEvidenceError(null); setEvidenceLoading(true); setSurface('evidence');
    try { setEvidence(await controller.getEvidence(id)); }
    catch (reason) { setEvidenceError(reason instanceof Error ? reason.message : 'Evidence could not be loaded.'); }
    finally { setEvidenceLoading(false); }
  }
  function openRecap(phase: 'half_time' | 'full_time') { setRecapPhase(phase); setSurface('recap'); }
  function navigate(id: string) {
    setActiveNav(id);
    if (id === 'diagnostics') { setSurface('diagnostics'); return; }
    document.getElementById(id === 'overview' ? 'match-room' : id)?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  }

  return <>
    <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{announcement}</div>
    {!state || !match ? <StartScreen controller={controller} onProvenance={() => setSurface('provenance')} /> : <div className="app-shell">
      <aside className="sidebar">
        <button className="sidebar-brand" aria-label="Match overview" onClick={() => navigate('overview')}><Brand compact /></button>
        <nav aria-label="Match navigation">{[
          { id: 'overview', label: 'Match overview', icon: <LayoutDashboard size={21} /> },
          { id: 'timeline', label: 'Insight timeline', icon: <Clock3 size={21} /> },
          { id: 'player-focus', label: 'Player focus', icon: <UserRound size={21} /> },
          { id: 'diagnostics', label: 'Pipeline diagnostics', icon: <Layers3 size={21} /> },
        ].map((item) => <button key={item.id} className={activeNav === item.id ? 'active' : ''} title={item.label} aria-label={item.label} aria-current={activeNav === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}>{item.icon}</button>)}</nav>
        <button className="sidebar-settings" aria-label="Open preferences" title="Preferences" onClick={openPreferences}><Settings2 size={21} /></button>
      </aside>
      <main className="match-room" id="match-room">
        <header className="masthead"><Brand /><div className="masthead-meta"><button className="synthetic-badge" onClick={() => setSurface('provenance')}><ShieldCheck size={14} /> Synthetic match <Info size={13} /></button><button className="status-pill" onClick={() => setSurface('diagnostics')}><span className={connection === 'online' ? 'tiny-dot' : 'tiny-dot disconnected'} />{connection === 'online' ? (state.diagnostics.provider === 'mock' ? 'Mock provider' : humanize(state.diagnostics.provider)) : humanize(connection)}</button></div></header>
        <Scoreboard match={match} state={state} onRecap={openRecap} />
        <ReplayToolbar controller={controller} onPreferences={openPreferences} onRestart={() => setRestartOpen(true)} />
        <div className="replay-progress" role="progressbar" aria-label="Observed replay progress" aria-valuemin={0} aria-valuemax={90} aria-valuenow={Math.floor(state.playhead_ms / 60000)}><span style={{ width: `${state.playhead_ms / 5400000 * 100}%` }} /><i style={{ left: '50%' }} /></div>
        {error && <div className="error-banner" role="alert">{connection === 'offline' ? <WifiOff size={18} /> : <Info size={18} />}<p>{error.message}<small>Last valid observation: {matchClock(state.observed_high_water_ms)}.</small></p><button className="text-button" onClick={() => void controller.retry()}>Reconnect <RotateCcw size={14} /></button></div>}
        {state.diagnostics.correction_notice && <div className="correction-notice"><RotateCcw size={17} /><span>{state.diagnostics.correction_notice}</span></div>}
        {(state.status === 'half_time' || state.status === 'ended') && <div className="period-banner"><Flag size={19} /><div><strong>{state.status === 'half_time' ? 'Half-time' : 'Full-time'}</strong><p>{state.status === 'half_time' ? 'The first-half recap is ready. Continue when you’re ready.' : 'The final recap is ready to read.'}</p></div><button className="button button-small" onClick={() => openRecap(state.status === 'half_time' ? 'half_time' : 'full_time')}>Read recap <ArrowRight size={16} /></button></div>}
        <div className="match-grid">
          <section className="pitch-panel" aria-label="Schematic event view">
            <div className="pitch-heading"><span className="eyebrow">MATCH VIEW</span><span className={`live-chip ${state.status !== 'playing' ? 'paused-chip' : ''}`}><span />{state.status === 'playing' ? 'REPLAY' : humanize(state.status).toUpperCase()}</span></div>
            <PitchScene events={pitchEvents} homeTeamId={match.home.team_id} awayTeamId={match.away.team_id} period={state.period} playheadMs={state.playhead_ms} isPlaying={state.status === 'playing'} selectedEventId={selectedEventId} onSelectEvent={(id) => { setSelectedRecord(null); setSelectedEventId(id); }} />
            {overlay && <div className="overlay-preview" aria-label="Eligible lower-third overlay"><div className="overlay-brand"><Brand compact /></div><div><span>TURNING POINT</span><strong>{overlay.display.headline}</strong><p>{overlay.display.subline}</p></div><span className="overlay-time">{Math.ceil((overlay.valid_until_ms - state.playhead_ms) / 1000)}s</span></div>}
            <div className="pitch-footer"><span>Event locations, not player tracking</span><button className="text-button" disabled={!overlay} onClick={() => setSurface('overlay')}><Braces size={15} /> Overlay JSON <ArrowUpRight size={14} /></button></div>
            {selectedEventId && <div className="selected-event-banner"><Target size={15} /><span>Selected <code>{selectedEventId}{selectedRecord ? `@${selectedRecord.revision}` : ''}</code></span><button className="icon-button" aria-label="Clear highlighted event" onClick={() => { setSelectedRecord(null); setSelectedEventId(null); }}><X size={15} /></button></div>}
          </section>
          <InsightCard insight={currentInsight} state={state} match={match} onEvidence={(id) => void openEvidence(id)} />
        </div>
        <div className="secondary-grid"><MetricsPanel state={state} match={match} /><PlayerFocus state={state} match={match} busy={busy} onChange={(id) => void controller.updatePreferences({ ...preferences, favorite_player_id: id })} onEvidence={(id) => void openEvidence(id)} /></div>
        <EventFeed state={state} match={match} selectedId={selectedEventId} onSelect={(id) => { setSelectedRecord(null); setSelectedEventId(id); }} />
        <InsightTimeline state={state} onEvidence={(id) => void openEvidence(id)} onRecap={openRecap} />
        <footer className="match-footer"><span>Observed through {matchClock(state.observed_high_water_ms)}</span><button className="text-button" onClick={() => setSurface('diagnostics')}>Provider & diagnostics <ArrowUpRight size={14} /></button></footer>
      </main>
    </div>}
    {surface === 'preferences' && match && <Dialog title="Make the match yours." eyebrow="YOUR PREFERENCES" onClose={() => setSurface(null)}><PreferencesFields match={match} value={draft} onChange={setDraft} /><div className="dialog-actions"><button className="button button-ghost" onClick={() => setSurface(null)}>Cancel</button><button className="button button-primary" disabled={busy} onClick={async () => { await controller.updatePreferences(draft); setSurface(null); }}>Save preferences <Check size={16} /></button></div></Dialog>}
    {surface === 'evidence' && <Dialog title="The evidence behind the insight." eyebrow="WHY THIS INSIGHT?" wide onClose={() => setSurface(null)}>{evidenceLoading ? <EmptyState icon={<LoaderCircle className="spin" size={28} />} title="Opening the observed record" text="Loading the original snapshot, facts and event revisions." /> : evidenceError ? <EmptyState icon={<Info size={28} />} title="Evidence is unavailable" text={evidenceError} /> : evidence && match ? <EvidenceInspector evidence={evidence} match={match} selectedId={selectedEventId} onSelect={(id) => { setSelectedRecord(evidence.events.find((record) => record.event_id === id) ?? null); setSelectedEventId(id); setSurface(null); }} /> : null}</Dialog>}
    {surface === 'diagnostics' && state && <Dialog title="From event to explanation." eyebrow="PIPELINE DIAGNOSTICS" wide onClose={() => setSurface(null)}><Diagnostics state={state} /></Dialog>}
    {surface === 'recap' && state && match && <Dialog title={recapPhase === 'half_time' ? 'The half-time story.' : 'The full-time story.'} eyebrow="EVIDENCE-LINKED RECAP" wide onClose={() => setSurface(null)}><RecapView recap={state.recaps[recapPhase]} state={state} match={match} onEvidence={(id) => void openEvidence(id)} /></Dialog>}
    {surface === 'overlay' && <Dialog title="A story ready to render." eyebrow="STRUCTURED OVERLAY PREVIEW" wide onClose={() => { setSurface(null); setCopied(false); }}>{overlay ? <><p className="section-description">This machine-readable lower third is eligible at the current match clock. A paused replay freezes its validity interval. This is a local renderer preview.</p><div className="overlay-json-meta"><span>{windowLabel({ start_ms: overlay.valid_from_ms, end_ms: overlay.valid_until_ms })}</span><span>{overlay.mode} · {overlay.fact_ids.length} fact references</span></div><pre className="json-view">{JSON.stringify(overlay, null, 2)}</pre><div className="dialog-actions"><button className="button button-ghost" onClick={async () => { await navigator.clipboard.writeText(JSON.stringify(overlay, null, 2)); setCopied(true); }}>{copied ? <Check size={16} /> : <Braces size={16} />}{copied ? 'Copied' : 'Copy JSON'}</button><button className="button button-primary" onClick={() => downloadJson(`${overlay.overlay_id}.json`, overlay)}><Download size={16} /> Export overlay</button></div></> : <EmptyState icon={<Clock3 size={28} />} title="The overlay has expired" text="Its match-clock validity has ended. Historic insights remain in the timeline with their original observation window." />}</Dialog>}
    {surface === 'provenance' && <Dialog title="A synthetic match. A transparent story." eyebrow="DATA & ASSET PROVENANCE" onClose={() => setSurface(null)}><div className="provenance-content"><div className="provider-banner"><ShieldCheck size={24} /><div><strong>Entirely fictional. Clearly labeled.</strong><p>Clubs, adult players and match events are original synthetic demonstration data.</p></div></div><p>The server releases only the events observed by your replay clock. Football statistics come from deterministic calculations, and every insight links back to the event revisions that support it.</p><p>The 3D pitch is an original procedural asset. Animated arcs and markers illustrate discrete event locations. They do not represent continuous ball motion or player tracking.</p><p>The local default runs two specialized mock agent roles: Football Analyst and Evidence Editor. Their outputs are labeled. There is no real match feed, broadcast integration, prediction or claim of causality.</p><p className="language-note">No league, club or Microsoft endorsement is implied.</p></div></Dialog>}
    {restartOpen && <Dialog title="Restart the replay?" eyebrow="RESTART REPLAY" onClose={() => setRestartOpen(false)}><p>Restart resets the observed clock, score, insights and recaps. Your preferences carry into a new replay generation.</p><div className="dialog-actions"><button className="button button-ghost" onClick={() => setRestartOpen(false)}>Keep watching</button><button className="button button-primary" disabled={busy} onClick={async () => { await controller.control('restart'); setRestartOpen(false); }}><RotateCcw size={16} />Restart replay</button></div></Dialog>}
  </>;
}
