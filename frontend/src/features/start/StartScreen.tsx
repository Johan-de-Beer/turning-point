import { ArrowRight, Clock3, Info, LoaderCircle, Play, RotateCcw, Search, ShieldCheck, Sparkles, WifiOff } from 'lucide-react';
import { Brand, TeamMark } from '../../components/Brand';
import { LazyPitch } from '../../components/LazyPitch';
import type { useMatch } from '../../lib/useMatch';
import { PreferencesFields } from '../preferences/PreferencesFields';

type Controller = ReturnType<typeof useMatch>;

const steps = [
  { icon: <Play size={16} />, title: 'Follow the replay', text: 'Synthetic events arrive as the server clock advances. Nothing from the future is sent.' },
  { icon: <Sparkles size={16} />, title: 'See what changed', text: 'Deterministic rules spot pressure, sterile possession and end-to-end spells.' },
  { icon: <Search size={16} />, title: 'Check the evidence', text: 'Every explanation links to the exact counts and event records behind it.' },
];

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
      <button className="synthetic-badge" onClick={onProvenance}><ShieldCheck size={14} /> Synthetic match <Info size={13} aria-hidden="true" /></button>
    </header>
    <section className="start-hero" aria-labelledby="start-title">
      <div className="start-copy">
        <span className="eyebrow">A football second screen</span>
        <h1 id="start-title">Read the game<span className="headline-period">.</span></h1>
        <p className="start-lede">Short, checkable explanations of how a match is developing, written for fans and analysts alike.</p>

      </div>
      <section className="start-card" aria-labelledby="fixture-title">
        <div className="start-card-heading"><span className="eyebrow">Tonight's replay</span><span className="chip">Fictional fixture</span></div>
        <h2 id="fixture-title" className="start-fixture">
          <span className="start-team"><TeamMark team={match.home} size="large" /><span>{match.home.display_name}<small>Home</small></span></span>
          <span className="versus" aria-label="versus">vs</span>
          <span className="start-team away"><TeamMark team={match.away} size="large" /><span>{match.away.display_name}<small>Away</small></span></span>
        </h2>
        <PreferencesFields match={match} value={preferences} onChange={(next) => void updatePreferences(next)} compact />
        <button className="button button-primary start-button" disabled={busy} onClick={() => void start()}>
          {busy ? <LoaderCircle size={18} className="spin" /> : <Play size={17} fill="currentColor" />}<span>{busy ? 'Opening replay…' : 'Start replay'}</span><ArrowRight size={20} />
        </button>
        <p className="fixture-notice"><Clock3 size={16} aria-hidden="true" /><span>An accelerated replay of a simulated 90 minutes, not a live fixture. It starts at 12× (about 7½ minutes) and you can pause at any point.</span></p>
      </section>
      <ol className="start-steps">{steps.map((step, index) => <li key={step.title}>
          <span className="step-icon" aria-hidden="true">{step.icon}</span>
          <div><strong><span className="sr-only">Step {index + 1}: </span>{step.title}</strong><p>{step.text}</p></div>
        </li>)}</ol>
    </section>
    {error && <div className="error-banner" role="alert"><Info size={18} /><p>{error.message}</p><button className="text-button" onClick={() => void retry()}>Retry</button></div>}
    <section className="start-stadium" aria-label="Stadium preview">
      <div className="start-stadium-label"><span>{match.home.short_name} <i>vs</i> {match.away.short_name}</span><span>Schematic event view</span></div>
      <LazyPitch events={[]} homeTeamId={match.home.team_id} awayTeamId={match.away.team_id} homeTeamName={match.home.display_name} awayTeamName={match.away.display_name} players={match.roster} period={1} playheadMs={0} isPlaying={false} />
      <p className="start-stadium-caption">An original Blender stadium. The ball replays recorded synthetic event endpoints; it is not real tracking data.</p>
    </section>
    <footer className="start-footer"><button className="text-button" onClick={onProvenance}>About the synthetic data</button><span>Synthetic data · No account needed</span></footer>
  </main>;
}
