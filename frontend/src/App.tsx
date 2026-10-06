import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { ArrowRight, Braces, Check, Clock3, Download, Flag, Info, LoaderCircle, RotateCcw, ShieldCheck, Target, WifiOff, X } from 'lucide-react';
import { Brand, EmptyState } from './components/Brand';
import { Dialog } from './components/Dialog';
import { LazyPitch } from './components/LazyPitch';
import { Diagnostics } from './features/diagnostics/Diagnostics';
import { EvidenceInspector } from './features/evidence/EvidenceInspector';
import { EventFeed, InsightTimeline, RecapLinks } from './features/match/ActivityRail';
import { InsightCard } from './features/match/InsightCard';
import { MatchHeader } from './features/match/MatchHeader';
import { MetricsPanel } from './features/match/MetricsPanel';
import { PlayerFocus } from './features/match/PlayerFocus';
import { PreferencesFields } from './features/preferences/PreferencesFields';
import { RecapView } from './features/recap/RecapView';
import { StartScreen } from './features/start/StartScreen';
import { eligibleOverlay, type Envelope, type Evidence, type Preferences } from './lib/contracts';
import { downloadJson, matchClock, windowLabel } from './lib/format';
import { projectPitchState } from './lib/pitchProjection';
import { useMatch } from './lib/useMatch';

type Surface = 'preferences' | 'evidence' | 'overlay' | 'diagnostics' | 'recap' | 'provenance' | null;

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
  const [playerOnly, setPlayerOnly] = useState(false);
  const overlay = state ? eligibleOverlay(state) : null;
  const pitchProjection = useMemo(() => projectPitchState(state, selectedRecord), [state?.events, state?.playhead_ms, state?.session_id, state?.generation, selectedRecord]);
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
  useEffect(() => { if (!state?.preferences.favorite_player_id) setPlayerOnly(false); }, [state?.preferences.favorite_player_id]);
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
  function selectEvent(id: string) { setSelectedRecord(null); setSelectedEventId(id); }
  function showOnPitch(id: string) {
    selectEvent(id);
    document.getElementById('pitch-panel')?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest' });
  }

  const periodEnd = state && (state.status === 'half_time' || state.status === 'ended') ? (state.status === 'half_time' ? 'half_time' : 'full_time') : null;

  return <>
    <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{announcement}</div>
    <a className="skip-link" href="#main-content">Skip to match content</a>
    {!state || !match ? <StartScreen controller={controller} onProvenance={() => setSurface('provenance')} /> : <div className="app-shell">
      <MatchHeader controller={controller} match={match} state={state} onRestart={() => setRestartOpen(true)} onPreferences={openPreferences}
        onProvenance={() => setSurface('provenance')} onDiagnostics={() => setSurface('diagnostics')} onInsight={(id) => void openEvidence(id)} onGoal={showOnPitch} />
      <main className="match-room" id="main-content" tabIndex={-1}>
        {error && <div className="error-banner" role="alert">{connection === 'offline' ? <WifiOff size={18} /> : <Info size={18} />}<p>{error.message}<small>Showing the last valid observation, cut off at {matchClock(state.observed_high_water_ms)}.</small></p><button className="text-button" onClick={() => void controller.retry()}>Reconnect <RotateCcw size={14} /></button></div>}
        {state.diagnostics.correction_notice && <div className="correction-notice"><RotateCcw size={17} /><span>{state.diagnostics.correction_notice}</span></div>}
        {periodEnd && <div className="period-banner" role="status"><Flag size={19} aria-hidden="true" /><div><strong>{periodEnd === 'half_time' ? 'Half-time' : 'Full-time'}</strong><p>{periodEnd === 'half_time' ? 'The first-half recap is ready. Continue the second half when you’re ready.' : 'The final recap is ready to read.'}</p></div>
          <button className="button button-small" onClick={() => openRecap(periodEnd)}>Open {periodEnd === 'half_time' ? 'half-time' : 'full-time'} recap <ArrowRight size={16} /></button></div>}
        <div className="match-layout">
          <div className="match-main">
            <InsightCard insight={currentInsight} state={state} match={match} onEvidence={(id) => void openEvidence(id)} />
            <section className="pitch-panel" id="pitch-panel" aria-label="Observed event replay">
              <div className="pitch-heading"><h2 className="pitch-title">Event view</h2><span className={`live-chip ${state.status !== 'playing' ? 'is-paused' : ''}`}><span aria-hidden="true" />{state.status === 'playing' ? 'Replaying' : state.status === 'half_time' ? 'Half-time' : state.status === 'ended' ? 'Full-time' : 'Paused'}</span><button className="text-button" disabled={!overlay} onClick={() => setSurface('overlay')}><Braces size={15} /> Overlay JSON</button></div>
              <LazyPitch events={pitchProjection.events} replayKey={pitchProjection.replayKey} speed={state.speed} players={match.roster} homeTeamId={match.home.team_id} awayTeamId={match.away.team_id} homeTeamName={match.home.display_name} awayTeamName={match.away.display_name} period={state.period} playheadMs={state.playhead_ms} isPlaying={state.status === 'playing'} finishObservedEvents={state.status === 'half_time' || state.status === 'ended'} selectedEventId={selectedEventId} selectedEvent={pitchProjection.selectedEvent} onSelectEvent={selectEvent} />
              {overlay && <div className="overlay-preview" aria-label="Eligible lower-third overlay" style={{ '--overlay-progress': `${Math.max(0, Math.min(1, (overlay.valid_until_ms - state.playhead_ms) / (overlay.valid_until_ms - overlay.valid_from_ms))) * 100}%` } as CSSProperties}>
                <div className="overlay-brand"><Brand compact /></div>
                <div className="overlay-copy"><span>Turning Point</span><strong>{overlay.display.headline}</strong><p>{overlay.display.subline}</p></div>
                <span className="overlay-time" aria-label={`Visible for ${Math.ceil((overlay.valid_until_ms - state.playhead_ms) / 1000)} more match seconds`}>{Math.ceil((overlay.valid_until_ms - state.playhead_ms) / 1000)}s</span>
                <span className="overlay-countdown" aria-hidden="true" />
              </div>}
              {selectedEventId && <div className="selected-event-banner"><Target size={15} aria-hidden="true" /><span>Highlighting <code>{selectedEventId}{selectedRecord ? `@${selectedRecord.revision}` : ''}</code></span><button className="icon-button" aria-label="Clear highlighted event" onClick={() => { setSelectedRecord(null); setSelectedEventId(null); }}><X size={15} /></button></div>}
            </section>
          </div>
          <aside className="activity-rail" aria-label="Match activity">
            <InsightTimeline match={match} state={state} onEvidence={(id) => void openEvidence(id)} />
            <EventFeed state={state} match={match} selectedId={selectedEventId} playerOnly={playerOnly} onPlayerOnly={setPlayerOnly} onSelect={showOnPitch} />
            <RecapLinks state={state} onRecap={openRecap} />
          </aside>
        </div>
        <div className="secondary-grid">
          <MetricsPanel state={state} match={match} />
          <PlayerFocus state={state} match={match} busy={busy} onChange={(id) => void controller.updatePreferences({ ...preferences, favorite_player_id: id })} onEvidence={(id) => void openEvidence(id)} />
        </div>
        <footer className="match-footer"><span>Synthetic fixture with fictional clubs and players. The event view draws only the active players from recorded endpoints, not tracking data. Observed through {matchClock(state.observed_high_water_ms)}.</span><button className="text-button" onClick={() => setSurface('diagnostics')}>Provider & pipeline diagnostics</button></footer>
      </main>
    </div>}
    {surface === 'preferences' && match && <Dialog title="Make the match yours." eyebrow="Your preferences" onClose={() => setSurface(null)}><PreferencesFields match={match} value={draft} onChange={setDraft} /><div className="dialog-actions"><button className="button button-ghost" onClick={() => setSurface(null)}>Cancel</button><button className="button button-primary" disabled={busy} onClick={async () => { await controller.updatePreferences(draft); setSurface(null); }}>Save preferences <Check size={16} /></button></div></Dialog>}
    {surface === 'evidence' && <Dialog title="The evidence behind the insight." eyebrow="Why this insight?" wide onClose={() => setSurface(null)}>{evidenceLoading ? <EmptyState icon={<LoaderCircle className="spin" size={28} />} title="Opening the observed record" text="Loading the original snapshot, facts and event revisions." /> : evidenceError ? <EmptyState icon={<Info size={28} />} title="Evidence is unavailable" text={evidenceError} /> : evidence && match ? <EvidenceInspector evidence={evidence} match={match} selectedId={selectedEventId} onSelect={(record) => { setSelectedRecord(record); setSelectedEventId(record.event_id); setSurface(null); }} /> : null}</Dialog>}
    {surface === 'diagnostics' && state && <Dialog title="From event to explanation." eyebrow="Pipeline diagnostics" wide onClose={() => setSurface(null)}><Diagnostics state={state} /></Dialog>}
    {surface === 'recap' && state && match && <Dialog title={recapPhase === 'half_time' ? 'The half-time story.' : 'The full-time story.'} eyebrow="Evidence-linked recap" wide onClose={() => setSurface(null)}><RecapView recap={state.recaps[recapPhase]} state={state} match={match} onEvidence={(id) => void openEvidence(id)} /></Dialog>}
    {surface === 'overlay' && <Dialog title="A story ready to render." eyebrow="Structured overlay preview" wide onClose={() => { setSurface(null); setCopied(false); }}>{overlay && state ? <>
      <p className="section-description">This machine-readable lower third is eligible at the current match clock. A paused replay freezes its validity interval. It is a local renderer preview, not a broadcast integration.</p>
      <div className="overlay-json-meta"><span>Valid {windowLabel({ start_ms: overlay.valid_from_ms, end_ms: overlay.valid_until_ms })}</span><span>{overlay.mode} · {overlay.fact_ids.length} fact references</span></div>
      <pre className="json-view" tabIndex={0}>{JSON.stringify(overlay, null, 2)}</pre>
      <div className="dialog-actions"><button className="button button-ghost" onClick={async () => { await navigator.clipboard.writeText(JSON.stringify(overlay, null, 2)); setCopied(true); }}>{copied ? <Check size={16} /> : <Braces size={16} />}{copied ? 'Copied' : 'Copy JSON'}</button><button className="button button-primary" onClick={() => downloadJson(`${overlay.overlay_id}.json`, overlay)}><Download size={16} /> Export overlay</button></div>
    </> : <EmptyState icon={<Clock3 size={28} />} title="The overlay has expired" text="Its match-clock validity has ended. Historic insights remain in the timeline with their original observation window." />}</Dialog>}
    {surface === 'provenance' && <Dialog title="A synthetic match. A transparent story." eyebrow="Data & asset provenance" onClose={() => setSurface(null)}><div className="provenance-content">
      <div className="provider-banner"><ShieldCheck size={24} /><div><strong>Entirely fictional. Clearly labeled.</strong><p>Clubs, adult players and match events are original synthetic demonstration data.</p></div></div>
      <p>The server releases only the events observed by your replay clock. Football statistics come from deterministic calculations, and every insight links back to the event revisions that support it.</p>
      <p>The stadium is an original Blender asset. A single ball replays delivered synthetic passes, carries and shots using their recorded endpoints. Only the active actor and completed-pass recipient are positioned. Animation timing and intermediate motion illustrate discrete events; they do not represent real continuous ball tracking or off-ball player movement.</p>
      <p>The local default runs two specialized mock agent roles: Football Analyst and Evidence Editor. Their outputs are labeled. There is no real match feed, broadcast integration, prediction or claim of causality.</p>
      <p className="language-note">No league, club or Microsoft endorsement is implied.</p>
    </div></Dialog>}
    {restartOpen && <Dialog title="Restart the replay?" eyebrow="Restart replay" onClose={() => setRestartOpen(false)}><p>Restart resets the observed clock, score, insights and recaps. Your preferences carry into a new replay generation.</p><div className="dialog-actions"><button className="button button-ghost" onClick={() => setRestartOpen(false)}>Keep watching</button><button className="button button-primary" disabled={busy} onClick={async () => { await controller.control('restart'); setRestartOpen(false); }}><RotateCcw size={16} />Restart replay</button></div></Dialog>}
  </>;
}
