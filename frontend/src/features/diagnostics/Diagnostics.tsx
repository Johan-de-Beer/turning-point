import { Activity, RotateCcw, ShieldCheck } from 'lucide-react';
import { EmptyState } from '../../components/Brand';
import type { Session } from '../../lib/contracts';
import { humanize } from '../../lib/format';

export function Diagnostics({ state }: { state: Session }) {
  const diagnostics = state.diagnostics;
  return <div className="diagnostics-view">
    <div className="provider-banner"><ShieldCheck size={22} /><div><strong>{diagnostics.provider === 'mock' ? 'Deterministic mock provider' : humanize(diagnostics.provider)}</strong><p>{diagnostics.provider_status}. No credentials or raw prompts are shown here.</p></div></div>
    <ol className="pipeline-steps" aria-label="Pipeline stages">{Object.entries(diagnostics.pipeline).map(([stage, status], index) => <li key={stage} className={`pipeline-step status-${status.replace(/\W+/g, '-')}`}>
      <span className="step-index">{index + 1}</span><strong>{humanize(stage)}</strong><small>{humanize(status)}</small>
    </li>)}</ol>
    <dl className="diagnostic-keys">
      <div><dt>Generation</dt><dd>{state.generation}</dd></div>
      <div><dt>Data epoch</dt><dd>{state.data_epoch}</dd></div>
      <div><dt>Preferences</dt><dd>{state.preferences_version}</dd></div>
      <div><dt>Pending jobs</dt><dd>{diagnostics.pending_jobs}</dd></div>
      <div><dt>Rules</dt><dd>{diagnostics.rules_version}</dd></div>
    </dl>
    {diagnostics.correction_notice && <div className="correction-notice"><RotateCcw size={17} />{diagnostics.correction_notice}</div>}
    <h3>Two-role review trail</h3>
    {diagnostics.agent_runs.length ? <div className="agent-run-list">{[...diagnostics.agent_runs].reverse().map((run) => <div className="agent-run" key={run.run_id}>
      <div className="agent-run-heading"><span aria-hidden="true">{run.role === 'football_analyst' ? <Activity size={17} /> : <ShieldCheck size={17} />}</span><strong>{humanize(run.role)}</strong><span className={`status-tag status-${run.status}`}>{humanize(run.status)}</span></div>
      <p>{run.provider} · {run.duration_ms}ms · {run.fact_ids.length} selected facts</p><code>{run.snapshot_id}</code>
      {run.validation_errors.length > 0 && <ul>{run.validation_errors.map((error) => <li key={error}>{error}</li>)}</ul>}
      {run.fallback_reason && <p className="fallback-reason">Fallback: {run.fallback_reason}</p>}
    </div>)}</div> : <EmptyState compact title="The review trail starts with the first candidate" text="The Analyst proposes an interpretation; the Editor checks it against the same immutable facts." />}
    <details><summary>Ingestion and suppressed candidates</summary>
      <p>Rejected records: {diagnostics.ingestion_errors.length}</p>{diagnostics.ingestion_errors.map((error) => <p key={error}>{error}</p>)}
      <p>Suppressed candidates: {diagnostics.suppressed_candidates.length}</p>{diagnostics.suppressed_candidates.map((candidate) => <p key={candidate}>{candidate}</p>)}
    </details>
  </div>;
}
