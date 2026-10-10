import { useEffect, useState, type CSSProperties } from 'react';
import { LoaderCircle, TriangleAlert } from 'lucide-react';
import type { Match, Session } from '../../lib/contracts';
import { matchClock } from '../../lib/format';
import { positionLabel } from '../../lib/events';
import {
  actionLabel, assistLabel, blockLabel, bodyPartLabel, chanceText, km, kmh, pct, pvText, teamWorkload, tiltSummary, xgText,
  type Analytics, type AnalyticsView, type DefensiveLine,
} from '../../lib/analytics';
import { metres } from '../../lib/tactics';
import { useLiveReport } from '../../lib/useLiveReport';
import { Stats, Table } from '../tactics/TacticsPanel';

const views: { id: AnalyticsView; label: string }[] = [
  { id: 'territory', label: 'Field tilt' }, { id: 'chances', label: 'Chances (xG)' }, { id: 'line', label: 'Defensive line' },
  { id: 'workload', label: 'Workload' }, { id: 'value', label: 'Possession value' },
];

type Props = { state: Session; match: Match; getAnalytics: (signal?: AbortSignal) => Promise<Analytics> };

export function AnalyticsPanel({ state, match, getAnalytics }: Props) {
  const { report, failed } = useLiveReport(state, getAnalytics);
  const [teamId, setTeamId] = useState(state.preferences.favorite_team_id ?? match.home.team_id);
  const [view, setView] = useState<AnalyticsView>('territory');
  useEffect(() => { if (state.preferences.favorite_team_id) setTeamId(state.preferences.favorite_team_id); }, [state.preferences.favorite_team_id]);
  const teams = [match.home, match.away];
  const team = teams.find((item) => item.team_id === teamId) ?? match.home;
  const opponent = team.team_id === match.home.team_id ? match.away : match.home;
  const player = (id: string) => match.roster.find((item) => item.player_id === id);
  const name = (id: string) => { const item = player(id); return item ? `${item.display_name} (${positionLabel(item)})` : id; };
  const analyst = state.preferences.mode === 'analyst';
  const section = { report: report!, match, team, opponent, name };

  return <section className="panel tactics-panel analytics-panel" id="analytics" aria-labelledby="analytics-title" style={{ '--home': match.home.color, '--away': match.away.color } as CSSProperties}>
    <div className="section-heading">
      <h2 id="analytics-title">Live analytics</h2>
      <span className="section-count">{report ? `To ${matchClock(report.playhead_ms)} · synthetic events and tracking` : 'Synthetic events and tracking'}</span>
    </div>
    <div className="tactics-controls">
      <div className="segmented-control" role="group" aria-label="Team">
        {teams.map((item) => <button key={item.team_id} type="button" aria-pressed={teamId === item.team_id} className={teamId === item.team_id ? 'active' : ''} onClick={() => setTeamId(item.team_id)}><i className="team-dot" style={{ '--insight-color': item.color } as CSSProperties} aria-hidden="true" />{item.short_name}</button>)}
      </div>
      <div className="segmented-control analytics-views" role="group" aria-label="Metric">
        {views.map((item) => <button key={item.id} type="button" aria-pressed={view === item.id} className={view === item.id ? 'active' : ''} onClick={() => setView(item.id)}>{item.label}</button>)}
      </div>
    </div>
    {!report ? <p className="tactics-empty">{failed ? 'The live analytics are unavailable right now. They retry automatically.' : <><LoaderCircle className="spin" size={16} aria-hidden="true" /> Loading the live analytics…</>}</p> : <>
      <div className="tactics-sections">
        {view === 'territory' && <Territory {...section} />}
        {view === 'chances' && <Chances {...section} />}
        {view === 'line' && <Line {...section} />}
        {view === 'workload' && <WorkloadView {...section} />}
        {view === 'value' && <Value {...section} />}
      </div>
      <details className="tactics-limits">
        <summary>How this is measured</summary>
        <ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        {analyst && <dl className="tactics-definitions">{Object.entries(report.definitions).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{value}</dd></div>)}</dl>}
      </details>
    </>}
  </section>;
}

type Section = { report: Analytics; match: Match; team: Match['home']; opponent: Match['home']; name: (id: string) => string };

/** A home/away comparison bar in the same idiom as the match numbers. */
function Split({ label, home, away, match }: { label: string; home: number | null | undefined; away: number | null | undefined; match: Match }) {
  const total = (home ?? 0) + (away ?? 0);
  const homeShare = total ? (home ?? 0) / total * 100 : 0;
  return <div className="metric-row">
    <dt className="metric-label">{label}</dt>
    <dd className="metric-values" aria-label={`${match.home.short_name} ${pct(home)}, ${match.away.short_name} ${pct(away)}`}>
      <strong className="home-value">{pct(home)}</strong>
      <span className="comparison-bar" aria-hidden="true"><span className="bar-home" style={{ width: `${homeShare}%` }} /><span className="bar-away" style={{ width: `${total ? 100 - homeShare : 0}%` }} /></span>
      <strong className="away-value">{pct(away)}</strong>
    </dd>
  </div>;
}

function Territory({ report, match, team }: Section) {
  const { match: whole, recent, intervals } = report.territory;
  const [home, away] = [match.home.team_id, match.away.team_id];
  return <>
    <section><h3>Field tilt</h3>
      <p className="tactics-compare">{tiltSummary(report, team.team_id, team.display_name)}</p>
      <div className="metric-legend"><span><i className="legend-home" aria-hidden="true" />{match.home.short_name}</span><span>{match.away.short_name}<i className="legend-away" aria-hidden="true" /></span></div>
      <dl className="metric-rows">
        <Split label="Field tilt · match" home={whole.field_tilt[home]} away={whole.field_tilt[away]} match={match} />
        <Split label="Possession · match" home={whole.possession_share[home]} away={whole.possession_share[away]} match={match} />
        <Split label="Field tilt · last 10 minutes" home={recent.field_tilt[home]} away={recent.field_tilt[away]} match={match} />
      </dl>
      <Stats items={[['Final-third passes', `${whole.final_third_passes[home]} – ${whole.final_third_passes[away]}`], ['Last 10 minutes', `${recent.final_third_passes[home]} – ${recent.final_third_passes[away]}`]]} />
    </section>
    <section><h3>By 15 minutes</h3>
      <dl className="metric-rows">{intervals.map((item) => <Split key={item.start_ms} label={`${Math.round(item.start_ms / 60000)}′–${Math.round(item.end_ms / 60000)}′ · ${item.final_third_passes[home] + item.final_third_passes[away]} passes`} home={item.field_tilt[home]} away={item.field_tilt[away]} match={match} />)}</dl>
      <Table caption="Possession against field tilt" head={['Minutes', `${match.home.short_name} possession`, `${match.home.short_name} field tilt`, `${match.away.short_name} possession`, `${match.away.short_name} field tilt`]}
        rows={intervals.map((item) => [`${Math.round(item.start_ms / 60000)}′–${Math.round(item.end_ms / 60000)}′`, pct(item.possession_share[home]), pct(item.field_tilt[home]), pct(item.possession_share[away]), pct(item.field_tilt[away])])} />
    </section>
  </>;
}

function Chances({ report, team, name }: Section) {
  const row = report.chances[team.team_id];
  const shots = report.shots.filter((item) => item.team_id === team.team_id).slice().reverse();
  if (!row) return null;
  return <section><h3>Chance quality</h3>
    <Stats items={[['xG for', xgText(row.xg)], ['xG against', xgText(row.xg_against)], ['Goals', row.goals], ['Shots / on target', `${row.shots} / ${row.on_target}`], ['Major chances', row.major_chances], ['xG per shot', xgText(row.xg_per_shot)]]} />
    {shots.length ? <Table caption="Each shot, newest first" head={['Time', 'Shooter', 'Outcome', 'xG', 'Chance', 'Set-up', 'Body part', 'Distance']}
      rows={shots.map((item) => [matchClock(item.time_ms), name(item.player_id), item.outcome.replace('_', ' '), xgText(item.xg), item.chance === 'major' ? 'Major' : 'Minor', assistLabel[item.assist], bodyPartLabel[item.body_part], metres(item.distance_m)])} />
      : <p className="tactics-empty">No shots yet.</p>}
  </section>;
}

function lineRow(label: string, item: DefensiveLine['match']) {
  return [label, metres(item.back_four_m), metres(item.deepest_m), metres(item.centroid_m), metres(item.gap_m), metres(item.width_m)];
}

function Line({ report, team }: Section) {
  const line = report.defensive_line[team.team_id];
  if (!line) return null;
  return <section><h3>Defensive line height</h3>
    <Stats items={[['Block', blockLabel[line.block]], ['Back four · match', metres(line.match.back_four_m)], ['Back four · last 5 minutes', metres(line.recent.back_four_m)], ['Deepest defender', metres(line.match.deepest_m)], ['Gap to midfield', metres(line.match.gap_m)], ['Time out of possession', `${Math.round(line.match.seconds / 60)} min`]]} />
    <Table caption="Distance from own goal by phase, in metres" head={['Phase', 'Back four', 'Deepest', 'Team centroid', 'Gap to midfield', 'Back-four width']}
      rows={[lineRow('Settled', line.settled), lineRow('After losing the ball (5 s)', line.after_loss), lineRow(`1 s before ${line.shots_faced} opponent shots`, line.before_shots)]} />
    <Table caption="Back-four height by 15 minutes" head={['Minutes', 'Back four', 'Deepest', 'Out of possession']}
      rows={line.intervals.map((item) => [`${Math.round(item.start_ms / 60000)}′–${Math.round(item.end_ms / 60000)}′`, metres(item.back_four_m), metres(item.deepest_m), `${Math.round(item.seconds)} s`])} />
  </section>;
}

function WorkloadView({ report, team, name }: Section) {
  const rows = teamWorkload(report, team.team_id);
  const flagged = rows.filter((row) => row.flag);
  return <section><h3>Player workload · external load</h3>
    {flagged.length > 0 && <p className="workload-alert"><TriangleAlert size={16} aria-hidden="true" />{flagged.map((row) => name(row.player_id)).join(', ')}: running intensity well below the team's trend in the last 10 minutes.</p>}
    <Table caption="Live workload, highest distance first" head={['Player', 'Distance', 'm/min', 'Last 10 min', 'High-speed running', 'Sprints', 'Acc / Dec', 'Load', 'Top speed']}
      rows={rows.map((row) => [name(row.player_id), km(row.distance_m), row.metres_per_min ?? '—',
        <span key="trend" className={row.flag ? 'trend-drop' : undefined}>{row.recent_metres_per_min ?? '—'}{row.trend_pct != null && <small> ({Math.round(row.trend_pct)}%)</small>}</span>,
        `${Math.round(row.hsr_m)} m`, `${row.sprints} · ${Math.round(row.sprint_m)} m`, `${row.accelerations} / ${row.decelerations}`, Math.round(row.load), kmh(row.top_speed_mps)])} />
  </section>;
}

function Value({ report, team, name }: Section) {
  const value = report.team_value[team.team_id];
  const players = report.player_value.filter((row) => row.team_id === team.team_id).slice(0, 8);
  const actions = report.top_actions.filter((row) => row.team_id === team.team_id);
  if (!value) return null;
  return <>
    <section><h3>Possession value</h3>
      <p className="tactics-compare">Value is the change in the chance of scoring an action causes, in percentage points (+2.3 means the team's scoring chance rose by 2.3 points).</p>
      <Stats items={[['Total', pvText(value.pv)], ['Per action', pvText(value.pv_per_action)], ['Valued actions', value.actions], ['Possessions', value.possessions],
        ...Object.entries(value.by_action).map(([key, amount]): [string, string] => [actionLabel[key as keyof typeof actionLabel] ?? key, pvText(amount)])]} />
      <Table caption="Who adds the most value" head={['Player', 'Value added', 'Actions', 'Positive']} rows={players.map((row) => [name(row.player_id), pvText(row.pv), row.actions, row.positive_actions])} />
    </section>
    <section><h3>Most valuable actions</h3>
      {actions.length ? <Table caption="Passes and carries that raised the scoring chance most" head={['Time', 'Player', 'Action', 'Before', 'After', 'Value']}
        rows={actions.map((row) => [matchClock(row.time_ms), name(row.player_id), actionLabel[row.action], chanceText(row.value_before), chanceText(row.value_after), pvText(row.pv)])} />
        : <p className="tactics-empty">No valued actions yet.</p>}
    </section>
  </>;
}
