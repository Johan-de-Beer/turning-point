import { ArrowUpRight, LoaderCircle, LockKeyhole, RotateCcw, ShieldCheck, UserRound } from 'lucide-react';
import { EmptyState, TeamMark } from '../../components/Brand';
import type { Match, Recap, Session } from '../../lib/contracts';
import { teamFor } from '../../lib/events';
import { humanize, matchClock, windowLabel } from '../../lib/format';
import { FactValue } from '../evidence/EvidenceInspector';

export function RecapView({ recap, state, match, onEvidence }: { recap: Recap | undefined; state: Session; match: Match; onEvidence: (id: string) => void }) {
  if (!recap || recap.status === 'locked') return <EmptyState icon={<LockKeyhole size={28} />} title="The match is still in progress" text="The recap unlocks only after its period-end marker is delivered. Future events and scores are never loaded into this view." />;
  if (recap.status === 'pending') return <EmptyState icon={<LoaderCircle size={28} className="spin" />} title="Preparing the recap" text="The recap is being prepared from the period-end evidence cutoff." />;
  const variant = recap.variants[state.preferences.mode];
  const beats = variant?.story_beats ?? recap.story_beats;
  const analyst = state.preferences.mode === 'analyst';
  return <div className={`recap-view ${analyst ? 'is-analyst' : ''}`}>
    {recap.correction_notice && <div className="correction-notice"><RotateCcw size={17} />{recap.correction_notice}</div>}
    <div className="recap-score" aria-label={`${match.home.display_name} ${recap.score[match.home.team_id] ?? 0}, ${match.away.display_name} ${recap.score[match.away.team_id] ?? 0}`}>
      <span className="recap-team"><TeamMark team={match.home} /><span>{match.home.display_name}</span></span>
      <strong aria-hidden="true">{recap.score[match.home.team_id] ?? 0}<i>–</i>{recap.score[match.away.team_id] ?? 0}</strong>
      <span className="recap-team away"><span>{match.away.display_name}</span><TeamMark team={match.away} /></span>
    </div>
    <span className="eyebrow">{recap.phase === 'half_time' ? 'Half-time' : 'Full-time'}</span>
    <h2>{variant?.headline ?? humanize(recap.phase)}</h2>
    <p className="recap-intro">{variant?.explanation ?? 'An auditable synthesis of observed play.'}</p>
    {analyst && <div className="recap-facts"><h3>Measured at the cutoff</h3>{recap.facts.map((fact) => <div key={fact.fact_id}><span>{teamFor(match, fact.subject_id)?.short_name ?? match.roster.find((player) => player.player_id === fact.subject_id)?.display_name ?? humanize(fact.subject_id)} · {humanize(fact.metric)}</span><strong><FactValue value={fact.numeric_value} unit={fact.unit} /></strong><code>{fact.fact_id}</code></div>)}</div>}
    {beats.length ? <ol className="story-beats">{beats.map((beat, index) => <li key={beat.insight_id}>
      <span className="story-number" aria-hidden="true">{index + 1}</span>
      <div><span className="window-tag">{windowLabel(beat.observed_window)}</span><h3>{beat.headline}</h3><p>{beat.explanation}</p>
        <button className="text-button" onClick={() => onEvidence(beat.insight_id)}>Inspect the evidence <ArrowUpRight size={14} /></button></div>
    </li>)}</ol> : <p className="section-description">No distinct confirmed patterns were eligible at this cutoff. The score and period context remain observed facts.</p>}
    {variant?.player_summary && <div className="recap-player"><UserRound size={20} /><p>{variant.player_summary}</p></div>}
    <p className="recap-cutoff"><ShieldCheck size={15} /><span>Observed through {matchClock(recap.cutoff_ms ?? 0)} · generation {recap.generation} · data epoch {recap.data_epoch}</span></p>
  </div>;
}
