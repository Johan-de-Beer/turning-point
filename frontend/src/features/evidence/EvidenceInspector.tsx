import type { CSSProperties } from 'react';
import { ArrowUpRight, Check, RotateCcw, ShieldCheck, X } from 'lucide-react';
import { describeEvent, patternLabel } from '../../components/EventDescription';
import type { Envelope, Evidence, Match } from '../../lib/contracts';
import { teamFor } from '../../lib/events';
import { formatPercent, humanize, matchClock, windowLabel } from '../../lib/format';

export function FactValue({ value, unit }: { value: number; unit: string }) {
  return <>{unit === 'percent' ? formatPercent(value) : unit === 'milliseconds' ? `${Math.round(value / 1000)}s` : value}</>;
}

function subjectName(match: Match, subjectId: string, short = false): string {
  const team = teamFor(match, subjectId);
  return team ? (short ? team.short_name : team.display_name) : humanize(subjectId);
}

export function EvidenceInspector({ evidence, match, selectedId, onSelect }: { evidence: Evidence; match: Match; selectedId: string | null; onSelect: (record: Envelope) => void }) {
  const { insight, snapshot } = evidence;
  const passed = evidence.conditions.filter((condition) => condition.passed).length;
  const team = insight.pattern === 'end_to_end' ? undefined : teamFor(match, insight.subject_ids[0]);
  return <div className="evidence-inspector">
    {insight.status === 'retracted' && <div className="correction-notice"><RotateCcw size={17} /><span>This historic insight was retracted after a correction. These original event versions explain its prior decision; they do not describe the current corrected match.</span></div>}
    <section className="evidence-overview" aria-label="Summary">
      <div className="evidence-overview-meta">
        <span className="evidence-kicker" style={{ '--insight-color': team?.color ?? 'var(--text-2)' } as CSSProperties}>{patternLabel[insight.pattern]} · {team?.display_name ?? 'Both teams'}</span>
        <span>{windowLabel(insight.observed_window)} · {snapshot.rules_version}</span>
      </div>
      <p className="evidence-intro">{insight.interpretation}</p>
      <ul className="evidence-stats">
        <li><strong>{passed}/{evidence.conditions.length}</strong><span>rule checks passed</span></li>
        <li><strong>{evidence.facts.length}</strong><span>measured facts</span></li>
        <li><strong>{evidence.events.length}</strong><span>source event records</span></li>
        <li><strong className={snapshot.coverage.eligible ? 'is-ok' : ''}>{snapshot.coverage.eligible ? 'Passed' : humanize(snapshot.coverage.status)}</strong><span>coverage gate</span></li>
      </ul>
    </section>

    <section aria-labelledby="facts-title">
      <h3 id="facts-title">Measured facts</h3>
      <p className="section-description"><span className="kind-tag kind-measured">Measured</span> Exact counts from observed events in this window. <span className="status-tag status-ready"><ShieldCheck size={12} /> {humanize(insight.evidence_quality)} evidence</span></p>
      <div className="facts-grid">{evidence.facts.map((fact) => <div className="fact-card" key={fact.fact_id}>
        <span className="fact-metric">{humanize(fact.metric)}</span>
        <strong><FactValue value={fact.numeric_value} unit={fact.unit} /></strong>
        <span className="fact-subject">{subjectName(match, fact.subject_id)}</span>
        <p>{fact.source_event_refs.length} source {fact.source_event_refs.length === 1 ? 'reference' : 'references'}</p>
        <code title={fact.fact_id}>{fact.fact_id}</code>
      </div>)}</div>
    </section>

    <section aria-labelledby="rules-title">
      <h3 id="rules-title">Heuristic rule checks</h3>
      <p className="section-description"><span className="kind-tag kind-heuristic">Heuristic</span> Each condition is checked against the same three-minute window. These descriptive demo thresholds have not been scientifically validated.</p>
      <div className="rule-table table-scroll" tabIndex={0} aria-label="Rule checks table"><table>
        <thead><tr><th scope="col">Observation</th><th scope="col">Subject</th><th scope="col">Rule</th><th scope="col">Observed</th><th scope="col">Check</th></tr></thead>
        <tbody>{evidence.conditions.map((condition, index) => <tr key={`${condition.metric}-${index}`}>
          <td>{humanize(condition.metric)}</td><td>{subjectName(match, condition.subject_id, true)}</td><td>{condition.operator} {condition.threshold}</td>
          <td>{condition.actual == null ? 'Unavailable' : Math.round(condition.actual * 100) / 100}</td>
          <td>{condition.passed ? <span className="check-pass"><Check size={14} /> Pass</span> : <span className="check-fail"><X size={14} /> Fail</span>}</td>
        </tr>)}</tbody>
      </table></div>
    </section>

    <section aria-labelledby="coverage-title">
      <h3 id="coverage-title">Coverage and comparison</h3>
      <div className="coverage-grid">
        <div><span>Known owned in-play</span><strong>{Math.round(snapshot.coverage.known_in_play_ms / 1000)}s</strong></div>
        <div><span>Stoppage</span><strong>{Math.round(snapshot.coverage.stoppage_ms / 1000)}s</strong></div>
        <div><span>Unknown state</span><strong>{Math.round(snapshot.coverage.unknown_state_ms / 1000)}s</strong></div>
        <div><span>Coverage gate</span><strong>{snapshot.coverage.eligible ? 'Passed' : humanize(snapshot.coverage.status)}</strong></div>
      </div>
      {snapshot.baseline
        ? <div className="baseline-comparison"><p>Prior observed window: <strong>{windowLabel(snapshot.baseline.window)}</strong></p>{[match.home, match.away].map((side) => <p key={side.team_id}>{side.short_name}: {snapshot.team_metrics[side.team_id]?.shots} shots now · {snapshot.baseline?.team_metrics[side.team_id]?.shots} before</p>)}</div>
        : <p className="baseline-unavailable">A full preceding window is unavailable. No increase or change is claimed from a missing baseline.</p>}
    </section>

    <section aria-labelledby="events-title">
      <h3 id="events-title">Supporting event versions</h3>
      <p className="section-description">Select a record to show its location on the schematic pitch.</p>
      <div className="evidence-event-table table-scroll" tabIndex={0} aria-label="Supporting events table"><table>
        <thead><tr><th scope="col">Match time</th><th scope="col">Event</th><th scope="col">Observed record</th><th scope="col">Reference</th><th scope="col">Pitch</th></tr></thead>
        <tbody>{evidence.events.map((envelope) => {
          const description = describeEvent(envelope, match);
          return <tr key={`${envelope.event_id}@${envelope.revision}`} className={selectedId === envelope.event_id ? 'selected-record' : ''}>
            <td className="numeric">{matchClock(envelope.payload?.event_time_ms ?? envelope.available_at_ms)}</td><td>{envelope.payload?.kind ?? 'DELETED'}</td>
            <td>{description.title}<small>{description.detail}</small></td><td><code>{envelope.event_id}@{envelope.revision}</code></td>
            <td><button className="text-button" data-event-id={envelope.event_id} data-event-revision={envelope.revision} onClick={() => onSelect(envelope)} aria-label={`Show ${envelope.event_id} on the pitch`}>Show <ArrowUpRight size={13} /></button></td>
          </tr>;
        })}</tbody>
      </table></div>
      <p className="reference-count">{evidence.events.length} observed source records. Original revisions are linked to their fact IDs.</p>
    </section>

    <section className="limitations-section" aria-labelledby="limits-title">
      <h3 id="limits-title">Interpretation and limitations</h3>
      <p className="section-description"><span className="kind-tag kind-limitation">Limitation</span> What this insight does not tell you.</p>
      <ul>{insight.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
      <details><summary>Metric definitions</summary>{Object.entries(evidence.metric_definitions).map(([metric, definition]) => <p key={metric}><strong>{humanize(metric)}:</strong> {definition}</p>)}</details>
    </section>
  </div>;
}
