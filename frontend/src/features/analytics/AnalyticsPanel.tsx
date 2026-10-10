import { useEffect, useState, type CSSProperties } from 'react';
import { LoaderCircle, TriangleAlert } from 'lucide-react';
import type { Match, Session } from '../../lib/contracts';
import { matchClock } from '../../lib/format';
import { positionLabel } from '../../lib/events';
import {
  actionLabel, assistLabel, blockLabel, bodyPartLabel, chanceText, heatmapLabel, heatmapZones, keyPassLabel, km, kmh, num1, num2, pct, pvText,
  scoreline, signed2, stateLabel, stateSummary, teamWorkload, tiltSummary, xgText,
  type Analytics, type AnalyticsView, type DefensiveLine, type Heatmap,
} from '../../lib/analytics';
import { metres } from '../../lib/tactics';
import { useLiveReport } from '../../lib/useLiveReport';
import { Stats, Table } from '../tactics/TacticsPanel';

const views: { id: AnalyticsView; label: string }[] = [
  { id: 'territory', label: 'Field tilt' }, { id: 'state', label: 'Game state' }, { id: 'heatmap', label: 'Heatmaps' },
  { id: 'chances', label: 'Chances (xG)' }, { id: 'keepers', label: 'Goalkeeping (xGoT)' }, { id: 'creation', label: 'Chance creation' },
  { id: 'tempo', label: 'Tempo & press' }, { id: 'packing', label: 'Packing' }, { id: 'line', label: 'Defensive line' },
  { id: 'workload', label: 'Workload' }, { id: 'value', label: 'Value (xOVA, VAEP)' },
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
        {view === 'state' && <GameStateView {...section} />}
        {view === 'heatmap' && <HeatmapView {...section} />}
        {view === 'chances' && <Chances {...section} />}
        {view === 'keepers' && <Goalkeeping {...section} />}
        {view === 'creation' && <Creation {...section} />}
        {view === 'tempo' && <Tempo {...section} />}
        {view === 'packing' && <Packing {...section} />}
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
    {shots.length ? <Table caption="Each shot, newest first" head={['Time', 'Shooter', 'Outcome', 'xG', 'xGoT', 'Chance', 'Set-up', 'Body part', 'Distance', 'Score state']}
      rows={shots.map((item) => [matchClock(item.time_ms), name(item.player_id), item.outcome.replace('_', ' '), xgText(item.xg), xgText(item.xgot), item.chance === 'major' ? 'Major' : 'Minor', assistLabel[item.assist], bodyPartLabel[item.body_part], metres(item.distance_m), stateLabel[item.game_state]])} />
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
  const players = report.player_value.filter((row) => row.team_id === team.team_id).slice().sort((a, b) => b.vaep - a.vaep).slice(0, 10);
  const actions = report.top_actions.filter((row) => row.team_id === team.team_id);
  const vaep = report.top_vaep.filter((row) => row.team_id === team.team_id);
  if (!value) return null;
  return <>
    <section><h3>Possession value (xOVA) and VAEP</h3>
      <p className="tactics-compare">Values are changes in percentage points of scoring chance (+2.3 means the chance rose by 2.3 points). xOVA counts only the scoring side of on-ball actions. VAEP also subtracts the change in the chance of conceding, so it charges a lost ball for the counter-attack it gives away and credits tackles and interceptions.</p>
      <Stats items={[['xOVA total', pvText(value.pv)], ['xOVA per action', pvText(value.pv_per_action)], ['VAEP total', pvText(value.vaep)], ['Valued actions', value.actions], ['Possessions', value.possessions]]} />
      <Table caption="Value by action type" head={['Action', 'xOVA', 'VAEP']}
        rows={Object.keys(value.vaep_by_action).map((key) => [actionLabel[key as keyof typeof actionLabel] ?? key, key in value.by_action ? pvText(value.by_action[key]) : '—', pvText(value.vaep_by_action[key])])} />
      <Table caption="Who adds the most value (by VAEP)" head={['Player', 'VAEP', 'of which defensive', 'xOVA', 'On-ball actions', 'Positive']} rows={players.map((row) => [name(row.player_id), pvText(row.vaep), pvText(row.defensive_vaep), pvText(row.pv), row.actions, row.positive_actions])} />
    </section>
    <section><h3>Most valuable actions</h3>
      {actions.length ? <Table caption="Passes and carries that raised the scoring chance most (xOVA)" head={['Time', 'Player', 'Action', 'Before', 'After', 'Value']}
        rows={actions.map((row) => [matchClock(row.time_ms), name(row.player_id), actionLabel[row.action], chanceText(row.value_before), chanceText(row.value_after), pvText(row.pv)])} />
        : <p className="tactics-empty">No valued actions yet.</p>}
      {vaep.length > 0 && <Table caption="Highest VAEP actions, defensive ones included" head={['Time', 'Player', 'Action', 'Scoring change', 'Conceding change', 'VAEP']}
        rows={vaep.map((row) => [matchClock(row.time_ms), name(row.player_id), actionLabel[row.action], pvText(row.scoring_delta), pvText(row.conceding_delta), pvText(row.vaep)])} />}
    </section>
  </>;
}

function GameStateView({ report, match, team }: Section) {
  const state = report.game_state;
  const own = state.teams[team.team_id];
  const opponentId = team.team_id === match.home.team_id ? match.away.team_id : match.home.team_id;
  if (!own) return null;
  const clockRange = (start: number, end: number) => `${Math.round(start / 60000)}′–${Math.round(end / 60000)}′`;
  return <>
    <section><h3>Game state</h3>
      <p className="tactics-compare">{match.home.short_name} {scoreline(report, match.home.team_id, match.away.team_id)} {match.away.short_name}. {team.display_name} are {stateLabel[own.current].toLowerCase()}. {stateSummary(report, team.team_id, team.display_name)} Teams change how they play with the score, so read every number below against the state it was produced in.</p>
      <Table caption="Score by period of the match" head={['Minutes', 'Score', `${team.short_name} state`]}
        rows={state.segments.map((item) => {
          const mine = item.score[team.team_id] ?? 0, theirs = item.score[opponentId] ?? 0;
          return [clockRange(item.start_ms, item.end_ms), `${item.score[match.home.team_id] ?? 0}–${item.score[match.away.team_id] ?? 0}`, stateLabel[mine > theirs ? 'winning' : mine < theirs ? 'losing' : 'drawing']];
        })} />
    </section>
    <section><h3>{team.display_name} by game state</h3>
      <Table caption="Each row covers only the minutes spent in that state" head={['State', 'Minutes', 'Possession', 'Field tilt', 'Passes', 'Shots', 'xG', 'xG per shot', 'Box touches', 'VAEP', 'PPDA', 'Vertical m/s', 'Directness', 'Back four']}
        rows={own.rows.map((row) => [stateLabel[row.state], Math.round(row.minutes), pct(row.possession_share), pct(row.field_tilt), row.passes, row.shots, xgText(row.xg), xgText(row.xg_per_shot), row.box_touches, pvText(row.vaep), num1(row.ppda), num2(row.vertical_mps), num2(row.directness), metres(row.back_four_m)])} />
    </section>
  </>;
}

/** A sequential single-hue heatmap on a flat pitch, in the team's attacking direction (left to right). */
function PitchHeat({ map, gridX, gridY, color, label }: { map: Heatmap; gridX: number; gridY: number; color: string; label: string }) {
  const max = Math.max(1, ...map.cells);
  const w = 105 / gridX, h = 68 / gridY;
  return <svg className="heatmap-pitch" viewBox="-2 -2 109 72" role="img" aria-label={label}>
    <rect x="0" y="0" width="105" height="68" className="heatmap-surface" />
    {map.cells.map((value, index) => {
      const cx = Math.floor(index / gridY), cy = index % gridY;
      return <rect key={index} x={cx * w + .25} y={cy * h + .25} width={w - .5} height={h - .5} rx=".6" fill={color} fillOpacity={value ? .12 + .83 * value / max : 0}>
        <title>{`${value} ${map.kind === 'tracking' ? 'seconds' : 'events'}`}</title>
      </rect>;
    })}
    <g className="heatmap-lines" fill="none">
      <rect x="0" y="0" width="105" height="68" /><path d="M52.5 0V68" /><circle cx="52.5" cy="34" r="9.15" />
      <rect x="0" y="13.84" width="16.5" height="40.32" /><rect x="88.5" y="13.84" width="16.5" height="40.32" />
      <path d="M70 0V68M35 0V68" strokeDasharray="1 1.5" />
    </g>
  </svg>;
}

function HeatmapView({ report, match, team, name }: Section) {
  const [subject, setSubject] = useState<string>(team.team_id);
  const [kind, setKind] = useState<Heatmap['kind']>('touches');
  useEffect(() => setSubject(team.team_id), [team.team_id]);
  const { grid_x: gridX, grid_y: gridY, maps } = report.heatmaps;
  const map = maps.find((item) => item.subject_id === subject && item.kind === kind);
  const kinds = (['touches', 'tracking', 'received', 'defensive'] as const).filter((item) => maps.some((m) => m.kind === item));
  const players = match.roster.filter((item) => item.team_id === team.team_id);
  const zones = map && map.total ? heatmapZones(map, gridX, gridY) : null;
  const subjectName = subject === team.team_id ? team.display_name : name(subject);
  return <section><h3>Heatmaps</h3>
    <div className="tactics-controls">
      <label className="heatmap-select">Show <select value={subject} onChange={(event) => setSubject(event.target.value)}>
        <option value={team.team_id}>{team.display_name} (whole team)</option>
        {players.map((item) => <option key={item.player_id} value={item.player_id}>{name(item.player_id)}</option>)}
      </select></label>
      <div className="segmented-control analytics-views" role="group" aria-label="Heatmap type">
        {kinds.map((item) => <button key={item} type="button" aria-pressed={kind === item} className={kind === item ? 'active' : ''} onClick={() => setKind(item)}>{heatmapLabel[item]}</button>)}
      </div>
    </div>
    {map && map.total ? <>
      <PitchHeat map={map} gridX={gridX} gridY={gridY} color={team.color} label={`${heatmapLabel[kind]} heatmap for ${subjectName}, attacking left to right`} />
      <p className="tactics-compare">{subjectName}: {map.total} {kind === 'tracking' ? 'seconds tracked' : 'events'}. Attacking left to right; brighter means more often. A hot zone shows where play happens, not how well it went.</p>
      {zones && <Table caption="Share by zone" head={['Zone', 'Own third', 'Middle third', 'Final third', 'Left channel', 'Centre', 'Right channel']}
        rows={[[heatmapLabel[kind], ...zones.thirds.map(pct), ...zones.channels.map(pct)]]} />}
    </> : <p className="tactics-empty">Nothing recorded for {subjectName} yet.</p>}
  </section>;
}

function Goalkeeping({ report, team, opponent, name }: Section) {
  const keeper = report.goalkeeping.keepers.find((row) => row.team_id === team.team_id);
  const shooting = report.goalkeeping.shooting[team.team_id];
  const faced = report.shots.filter((item) => item.team_id === opponent.team_id && item.xgot != null).slice().reverse();
  if (!keeper || !shooting) return null;
  const verdict = keeper.shots_on_target === 0 ? 'has not faced a shot on target yet' : keeper.xg_prevented > 0.05 ? `has prevented ${keeper.xg_prevented.toFixed(2)} goals more than an average keeper would from these placements` : keeper.xg_prevented < -0.05 ? `has conceded ${Math.abs(keeper.xg_prevented).toFixed(2)} goals more than an average keeper would from these placements` : 'has conceded about what an average keeper would';
  return <>
    <section><h3>Goalkeeping: xGoT and goals prevented</h3>
      <p className="tactics-compare">{name(keeper.player_id)} {verdict}. xGoT rates each on-target shot after it is struck, from where it crossed the line and how hard it was hit. One match is a small sample.</p>
      <Stats items={[['Goals prevented (xGP)', signed2(keeper.xg_prevented)], ['xGoT faced', num2(keeper.xgot_faced)], ['Goals conceded', keeper.goals_conceded], ['Shots on target faced', keeper.shots_on_target], ['Saves', keeper.saves], ['Save %', pct(keeper.save_pct)], ['Pre-shot xG faced (on target)', num2(keeper.xg_faced)]]} />
      {faced.length > 0 && <Table caption="On-target shots faced, newest first" head={['Time', 'Shooter', 'Outcome', 'xG', 'xGoT', 'Placement', 'Height', 'Pace']}
        rows={faced.map((item) => [matchClock(item.time_ms), name(item.player_id), item.outcome, xgText(item.xg), xgText(item.xgot),
          item.placement ? `${Math.abs(item.placement.y_m).toFixed(1)} m ${item.placement.y_m >= 0 ? 'right' : 'left'} of centre` : '—', item.placement ? metres(item.placement.z_m) : '—', item.placement ? kmh(item.placement.speed_mps) : '—'])} />}
    </section>
    <section><h3>{team.display_name} shooting</h3>
      <Stats items={[['Shots on target', shooting.shots_on_target], ['xG of those shots', num2(shooting.xg_on_target)], ['xGoT', num2(shooting.xgot)], ['Placement added (xGoT − xG)', signed2(shooting.placement_added)]]} />
    </section>
  </>;
}

function Creation({ report, team, name }: Section) {
  const row = report.creation[team.team_id];
  const players = report.player_creation.filter((item) => item.team_id === team.team_id).slice(0, 10);
  if (!row) return null;
  const types = Object.entries(row.key_pass_types).map(([key, value]) => `${keyPassLabel[key] ?? key} ${value}`).join(', ') || '—';
  return <section><h3>Chance creation</h3>
    <p className="tactics-compare">Touches in the box show how often {team.display_name} get the ball where most chances come from; key passes and xA credit the players who set the shots up, scored or not.</p>
    <Stats items={[['Touches in the box', row.box_touches], ['Box entries', row.box_entries], ['Zone 14 touches', row.zone14_touches], ['Zone 14 entries', row.zone14_entries],
      ['Key passes', `${row.key_passes} (${row.first_time_key_passes} first time)`], ['Assists', row.assists], ['xA', xgText(row.xa)], ['xG per box touch', num2(row.xg_per_box_touch)],
      ['Key passes from wide / central', `${row.key_pass_origins.wide ?? 0} / ${row.key_pass_origins.central ?? 0}`], ['Key-pass types', types]]} />
    <Table caption="Creators and box presence" head={['Player', 'Key passes', 'xA', 'Assists', 'Box touches', 'Zone 14 touches', 'Shots', 'xG']}
      rows={players.map((item) => [name(item.player_id), item.key_passes, xgText(item.xa), item.assists, item.box_touches, item.zone14_touches, item.shots, xgText(item.xg)])} />
  </section>;
}

function Tempo({ report, match, team }: Section) {
  const row = report.tempo[team.team_id]?.match;
  const intervals = report.tempo[team.team_id]?.intervals ?? [];
  const press = report.pressing[team.team_id];
  const [home, away] = [match.home.team_id, match.away.team_id];
  if (!row || !press) return null;
  return <>
    <section><h3>Build-up tempo</h3>
      <p className="tactics-compare">How fast {team.display_name} move the ball forward. Higher vertical progression and directness mean a quicker, more direct build-up; more passes per final-third entry and longer possessions mean a slower, patient one.</p>
      <Stats items={[['Vertical progression', row.vertical_mps == null ? '—' : `${row.vertical_mps.toFixed(2)} m/s`], ['Passes per final-third entry', num1(row.passes_per_entry)], ['Final-third entries', row.final_third_entries],
        ['Directness (forward ÷ other passes)', num2(row.directness)], ['Forward / lateral / back', `${row.forward_passes} / ${row.lateral_passes} / ${row.backward_passes}`], ['Progressive passes', row.progressive_passes],
        ['Regain to progressive pass', row.regain_to_progressive_s == null ? '—' : `${row.regain_to_progressive_s.toFixed(1)} s`], ['Possessions', row.possessions]]} />
      <Table caption="Average possession length by where it started" head={['Started in', 'Own third', 'Middle third', 'Final third']}
        rows={[['Seconds', num1(row.possession_s.defensive), num1(row.possession_s.middle), num1(row.possession_s.final)]]} />
      <Table caption="Tempo by 15 minutes" head={['Minutes', 'Vertical m/s', 'Directness', 'Passes per entry']}
        rows={intervals.map((item) => [`${Math.round(item.start_ms / 60000)}′–${Math.round(item.end_ms / 60000)}′`, num2(item.vertical_mps), num2(item.directness), num1(item.passes_per_entry)])} />
    </section>
    <section><h3>Pressing intensity (PPDA)</h3>
      <p className="tactics-compare">Passes the opponent is allowed in their own 60% of the pitch for each duel or interception there. Lower means a more aggressive press.</p>
      <Stats items={[[`${match.home.short_name} PPDA`, num1(report.pressing[home]?.ppda)], [`${match.away.short_name} PPDA`, num1(report.pressing[away]?.ppda)],
        [`${team.short_name} defensive actions`, press.defensive_actions], ['Opponent passes allowed', press.opponent_passes]]} />
    </section>
  </>;
}

function Packing({ report, team, name }: Section) {
  const row = report.packing[team.team_id];
  const players = report.player_packing.filter((item) => item.team_id === team.team_id).slice(0, 10);
  const top = report.top_packing.filter((item) => item.team_id === team.team_id);
  if (!row) return null;
  return <section><h3>Packing: opponents bypassed</h3>
    <p className="tactics-compare">Each completed forward pass or carry is credited with the outfield opponents it took out of the game, from the synthetic positions at that moment. The rate divides by every attempt, so it rewards players who break lines efficiently, not just often.</p>
    <Stats items={[['Passing packing rate', num2(row.passing_rate)], ['Dribbling packing rate', num2(row.dribbling_rate)], ['Opponents bypassed by passes', row.packed_by_passes],
      ['by carries', row.packed_by_carries], ['Defenders bypassed', row.defenders_packed], ['Line-breaking actions (3+)', row.line_breaking]]} />
    <Table caption="Players by opponents bypassed" head={['Player', 'Passing rate', 'Passes', 'Bypassed by passes', 'Dribbling rate', 'Carries', 'Bypassed by carries', 'Defenders bypassed']}
      rows={players.map((item) => [name(item.player_id), num2(item.passing_rate), item.passes, item.packed_by_passes, num2(item.dribbling_rate), item.carries, item.packed_by_carries, item.defenders_packed])} />
    {top.length > 0 && <Table caption="Actions that bypassed the most opponents" head={['Time', 'Player', 'Action', 'Opponents', 'Defenders']}
      rows={top.map((item) => [matchClock(item.time_ms), name(item.player_id), item.action === 'pass' ? 'Pass' : 'Carry', item.packed, item.defenders_packed])} />}
  </section>;
}
