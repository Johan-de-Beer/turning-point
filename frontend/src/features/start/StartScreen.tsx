import type { CSSProperties } from 'react';
import { ArrowRight, Info, LoaderCircle, Play, RotateCcw, ShieldCheck, WifiOff } from 'lucide-react';
import { Brand } from '../../components/Brand';
import { LazyPitch } from '../../components/LazyPitch';
import type { Team } from '../../lib/contracts';
import type { useMatch } from '../../lib/useMatch';
import { PreferencesFields } from '../preferences/PreferencesFields';

type Controller = ReturnType<typeof useMatch>;

function FixtureSide({ team, side }: { team: Team; side: 'Home' | 'Away' }) {
  return <span className="fixture-side" style={{ '--team-color': team.color } as CSSProperties}>
    <span className="fixture-code" aria-hidden="true">{team.short_name}</span>
    <span className="fixture-name">{team.display_name}<small>{side}</small></span>
  </span>;
}

export function StartScreen({ controller, onProvenance }: { controller: Controller; onProvenance: () => void }) {
  const { match, preferences, loading, busy, start, updatePreferences, retry, error } = controller;
  if (!match) return <main className="loading-screen">
    <Brand />
    <div className="loading-panel" role={loading ? 'status' : 'alert'}>
      {loading ? <><LoaderCircle className="spin" size={28} /><h1>Loading the fixture</h1><p>Connecting to your local replay.</p></>
        : <><WifiOff size={28} /><h1>Replay server unavailable</h1><p>{error?.message ?? 'Start the FastAPI server, then try again.'}</p><button className="button button-primary" onClick={() => void retry()}>Try again <RotateCcw size={17} /></button></>}
    </div>
  </main>;
  return <main className="start-screen">
    <header className="start-header">
      <Brand />
      <button className="synthetic-badge" onClick={onProvenance}><ShieldCheck size={14} aria-hidden="true" />Synthetic match</button>
    </header>
    <section className="start-hero" aria-labelledby="start-title">
      <div className="start-copy">
        <h1 id="start-title">Read the game.</h1>
        <p className="start-lede">Follow a replayed match and get short explanations of what changed, each one linked to the counts and events behind it. Written for fans and analysts alike.</p>
      </div>
      <section className="start-card fixture-card" aria-labelledby="fixture-title">
        <h2 id="fixture-title" className="fixture-teams">
          <FixtureSide team={match.home} side="Home" />
          <span className="fixture-v"><span aria-hidden="true">v</span><span className="sr-only">versus</span></span>
          <FixtureSide team={match.away} side="Away" />
        </h2>
        <dl className="fixture-details">
          <div><dt>Format</dt><dd>Replay of a simulated 90 minutes</dd></div>
          <div><dt>Pace</dt><dd>12×, about 7½ minutes. Pause any time.</dd></div>
          <div><dt>Clubs</dt><dd>Fictional, with fictional players</dd></div>
        </dl>
        <PreferencesFields match={match} value={preferences} onChange={(next) => void updatePreferences(next)} compact />
        <button className="button button-primary start-button" disabled={busy} onClick={() => void start()}>
          {busy ? <LoaderCircle size={18} className="spin" /> : <Play size={17} fill="currentColor" />}<span>{busy ? 'Opening replay…' : 'Start replay'}</span><ArrowRight size={20} />
        </button>
      </section>
    </section>
    {error && <div className="error-banner" role="alert"><Info size={18} /><p>{error.message}</p><button className="text-button" onClick={() => void retry()}>Retry</button></div>}
    <section className="start-stadium" aria-label="Stadium preview">
      <LazyPitch events={[]} homeTeamId={match.home.team_id} awayTeamId={match.away.team_id} homeTeamName={match.home.display_name} awayTeamName={match.away.display_name} players={match.roster} period={1} playheadMs={0} isPlaying={false} />
    </section>
    <footer className="start-footer"><span>Synthetic data and fictional clubs. The stadium view replays recorded event endpoints, not tracking data. No account needed.</span><button className="text-button" onClick={onProvenance}>About the data</button></footer>
  </main>;
}
