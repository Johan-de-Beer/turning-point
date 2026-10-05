import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Info, Layers3, LoaderCircle, Pause, Play, RotateCcw, Settings2, ShieldCheck, UsersRound, Workflow } from 'lucide-react';
import { Brand, TeamMark } from '../../components/Brand';
import { patternLabel } from '../../components/EventDescription';
import type { Match, Session } from '../../lib/contracts';
import { HALF_MS, MATCH_MS, percentOfMatch, teamFor, timelineMarkers } from '../../lib/events';
import { humanize, matchClock, windowLabel } from '../../lib/format';
import type { ControlAction, useMatch } from '../../lib/useMatch';

type Controller = ReturnType<typeof useMatch>;

function statusLabel(state: Session): string {
  if (state.status === 'playing') return `${state.period === 1 ? 'First' : 'Second'} half`;
  if (state.status === 'half_time') return 'Half-time';
  if (state.status === 'ended') return 'Full-time';
  return humanize(state.status);
}

export function Scoreboard({ match, state }: { match: Match; state: Session }) {
  const home = state.score[match.home.team_id] ?? 0;
  const away = state.score[match.away.team_id] ?? 0;
  const status = statusLabel(state);
  const favorite = state.preferences.favorite_team_id;
  return <section className="scoreboard" aria-label={`${match.home.display_name} ${home}, ${match.away.display_name} ${away}. ${status}. ${matchClock(state.playhead_ms)}`}>
    <div className="score-team home"><TeamMark team={match.home} /><div><span className="team-name"><span className="name-full">{match.home.display_name}</span><span className="name-short" aria-hidden="true">{match.home.short_name}</span></span><span className="team-sub">{favorite === match.home.team_id ? 'Your club' : 'Home'}</span></div></div>
    <div className="score-center">
      <span className="score-figures" aria-hidden="true">{home}<em>–</em>{away}</span>
      <span className="clock" aria-hidden="true"><span className={`clock-dot ${state.status === 'playing' ? '' : 'paused'}`} />{matchClock(state.playhead_ms)}<span className="clock-status">{status}</span></span>
    </div>
    <div className="score-team away"><div><span className="team-name"><span className="name-full">{match.away.display_name}</span><span className="name-short" aria-hidden="true">{match.away.short_name}</span></span><span className="team-sub">{favorite === match.away.team_id ? 'Your club' : 'Away'}</span></div><TeamMark team={match.away} /></div>
  </section>;
}

export function ReplayToolbar({ controller, onRestart }: { controller: Controller; onRestart: () => void }) {
  const { state, busy, control, updatePreferences } = controller;
  if (!state) return null;
  const action: ControlAction = state.status === 'half_time' ? 'continue_half' : state.status === 'playing' ? 'pause' : 'play';
  const actionName = state.status === 'half_time' ? 'Continue second half' : state.status === 'playing' ? 'Pause replay' : 'Play replay';
  return <section className="replay-toolbar" aria-label="Replay controls">
    <div className="playback-controls">
      <button className={`button playback-button ${state.status === 'half_time' ? 'is-continue' : ''}`} aria-label={actionName} disabled={busy || state.status === 'ended'} onClick={() => void control(action)}>
        {busy ? <LoaderCircle size={16} className="spin" /> : state.status === 'playing' ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}
        <span>{state.status === 'half_time' ? 'Second half' : state.status === 'playing' ? 'Pause' : state.status === 'ended' ? 'Ended' : 'Play'}</span>
      </button>
      <button className="icon-button" aria-label="Restart replay" title="Restart replay" disabled={busy} onClick={onRestart}><RotateCcw size={17} /></button>
      <label className="speed-control"><span>Speed</span>
        <select aria-label="Replay speed" value={state.speed} disabled={busy} onChange={(event) => void control('set_speed', Number(event.target.value) as 1 | 12 | 60)}>
          <option value={1}>1×</option><option value={12}>12×</option><option value={60}>60×</option>
        </select>
      </label>
      <span className={`speed-chip ${state.speed > 1 ? 'is-accelerated' : ''}`}>Synthetic replay{state.speed > 1 ? ` · ${state.speed}× accelerated` : ' · real time'}</span>
    </div>
    <div className="lens-controls">
      <div className="segmented-control" role="group" aria-label="Audience mode">
        <button aria-pressed={state.preferences.mode === 'casual'} disabled={busy} className={state.preferences.mode === 'casual' ? 'active' : ''} onClick={() => void updatePreferences({ ...state.preferences, mode: 'casual' })}><UsersRound size={14} />Casual</button>
        <button aria-pressed={state.preferences.mode === 'analyst'} disabled={busy} className={state.preferences.mode === 'analyst' ? 'active' : ''} onClick={() => void updatePreferences({ ...state.preferences, mode: 'analyst' })}><Layers3 size={14} />Analyst</button>
      </div>
    </div>
  </section>;
}

export function MatchTimeline({ match, state, onInsight, onGoal }: { match: Match; state: Session; onInsight: (id: string) => void; onGoal: (id: string) => void }) {
  const { insights, goals } = timelineMarkers(state);
  const minutes = Math.floor(state.playhead_ms / 60000);
  return <section className="match-timeline" aria-label="Match timeline">
    <div className="timeline-track">
      <div className="timeline-progress" role="progressbar" aria-label="Observed replay progress" aria-valuemin={0} aria-valuemax={90} aria-valuenow={minutes} aria-valuetext={`${matchClock(state.playhead_ms)} of 90:00 observed`}>
        <span className="timeline-fill" style={{ width: `${percentOfMatch(state.playhead_ms)}%` }} />
      </div>
      <span className="timeline-half" style={{ left: `${HALF_MS / MATCH_MS * 100}%` }} aria-hidden="true" />
      <ul className="timeline-markers" aria-label="Observed insights and goals">
        {insights.map((marker) => {
          const team = teamFor(match, marker.teamId);
          return <li key={marker.id} className="timeline-insight" style={{ left: `${percentOfMatch(marker.start)}%`, width: `max(10px, ${percentOfMatch(marker.end) - percentOfMatch(marker.start)}%)`, '--marker-color': team?.color ?? 'var(--teal)' } as CSSProperties}>
            <button className={marker.status === 'retracted' ? 'is-retracted' : ''} onClick={() => onInsight(marker.id)} aria-label={`${patternLabel[marker.pattern]}${team ? `, ${team.display_name}` : ', both teams'}, ${windowLabel({ start_ms: marker.start, end_ms: marker.end })}${marker.status === 'retracted' ? ', retracted' : ''}. Open evidence`} title={`${patternLabel[marker.pattern]} · ${windowLabel({ start_ms: marker.start, end_ms: marker.end })}`} />
          </li>;
        })}
        {goals.map((goal) => {
          const team = teamFor(match, goal.teamId);
          const scorer = match.roster.find((player) => player.player_id === goal.playerId)?.display_name;
          return <li key={goal.id} className="timeline-goal" style={{ left: `${percentOfMatch(goal.at)}%`, '--marker-color': team?.color ?? 'var(--teal)' } as CSSProperties}>
            <button onClick={() => onGoal(goal.id)} aria-label={`Goal, ${team?.display_name ?? 'team'}${scorer ? `, ${scorer}` : ''}, ${matchClock(goal.at)}. Show on pitch`} title={`Goal · ${scorer ?? team?.short_name} · ${matchClock(goal.at)}`}><span>{team?.short_name.charAt(0)}</span></button>
          </li>;
        })}
      </ul>
    </div>
    <div className="timeline-scale" aria-hidden="true"><span>0′</span><span>HT</span><span>90′</span></div>
  </section>;
}

export function MatchHeader({ controller, match, state, onRestart, onPreferences, onProvenance, onDiagnostics, onInsight, onGoal }: {
  controller: Controller; match: Match; state: Session;
  onRestart: () => void; onPreferences: () => void; onProvenance: () => void; onDiagnostics: () => void;
  onInsight: (id: string) => void; onGoal: (id: string) => void;
}) {
  const { connection } = controller;
  const provider = state.diagnostics.provider === 'mock' ? 'Mock provider' : humanize(state.diagnostics.provider);
  const header = useRef<HTMLElement>(null);
  const [stripVisible, setStripVisible] = useState(false);
  useEffect(() => {
    const element = header.current;
    if (!element) return;
    const observer = new IntersectionObserver(([entry]) => setStripVisible(!entry.isIntersecting), { threshold: 0 });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return <>
  {/* Visual-only duplicate of the scoreboard for small screens; the full scoreboard remains the accessible source. */}
  <div className={`score-strip ${stripVisible ? 'is-visible' : ''}`} aria-hidden="true">
    <span>{match.home.short_name}</span>
    <strong>{state.score[match.home.team_id] ?? 0} – {state.score[match.away.team_id] ?? 0}<small>{matchClock(state.playhead_ms)} · {statusLabel(state)}</small></strong>
    <span>{match.away.short_name}</span>
  </div>
  <header className="match-header" ref={header}>
    <div className="match-header-inner">
      <div className="header-top">
        <Brand />
        <Scoreboard match={match} state={state} />
        <div className="header-actions">
          <button className="synthetic-badge" onClick={onProvenance}><ShieldCheck size={14} /> Synthetic match <Info size={13} aria-hidden="true" /></button>
          <button className={`status-pill ${connection === 'online' ? '' : 'is-warning'}`} onClick={onDiagnostics} aria-label={`Pipeline diagnostics: ${connection === 'online' ? provider : humanize(connection)}`}>
            <Workflow size={14} aria-hidden="true" /><span>{connection === 'online' ? provider : humanize(connection)}</span>
          </button>
          <button className="icon-button" aria-label="Open preferences" title="Preferences" onClick={onPreferences}><Settings2 size={18} /></button>
        </div>
      </div>
      <div className="header-controls">
        <ReplayToolbar controller={controller} onRestart={onRestart} />
        <MatchTimeline match={match} state={state} onInsight={onInsight} onGoal={onGoal} />
      </div>
    </div>
  </header>
  </>;
}
