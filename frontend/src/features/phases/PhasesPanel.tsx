import { useEffect, useState, type CSSProperties } from 'react';
import { LoaderCircle, Target } from 'lucide-react';
import type { Match, Session } from '../../lib/contracts';
import { matchClock } from '../../lib/format';
import { positionLabel } from '../../lib/events';
import { num1, pct, xgText } from '../../lib/analytics';
import { metres } from '../../lib/tactics';
import {
  blockName, busiestPhases, controlLabel, fullbackLabel, lineContrast, momentEventId, phaseLabel, rotationLabel, snapshotLabel, teamNotes, xtText, zoneText,
  type Moment, type Phases, type PhasesView,
} from '../../lib/phases';
import { useLiveReport } from '../../lib/useLiveReport';
import { Stats, Table } from '../tactics/TacticsPanel';

const views: { id: PhasesView; label: string }[] = [
  { id: 'notes', label: 'Analyst notes' }, { id: 'phases', label: 'Phases of play' }, { id: 'transitions', label: 'Transitions & counter-press' },
  { id: 'blocks', label: 'Block & line' }, { id: 'threat', label: 'Carries & xT' }, { id: 'roles', label: 'Full-backs & rotations' },
  { id: 'control', label: 'Possession vs control' },
];

type Props = { state: Session; match: Match; getPhases: (signal?: AbortSignal) => Promise<Phases>; onShowEvent: (eventId: string) => void };

export function PhasesPanel({ state, match, getPhases, onShowEvent }: Props) {
  const { report, failed } = useLiveReport(state, getPhases);
  const [teamId, setTeamId] = useState(state.preferences.favorite_team_id ?? match.home.team_id);
  const [view, setView] = useState<PhasesView>('notes');
  useEffect(() => { if (state.preferences.favorite_team_id) setTeamId(state.preferences.favorite_team_id); }, [state.preferences.favorite_team_id]);
  const teams = [match.home, match.away];
  const team = teams.find((item) => item.team_id === teamId) ?? match.home;
  const opponent = team.team_id === match.home.team_id ? match.away : match.home;
  const name = (id: string) => { const item = match.roster.find((row) => row.player_id === id); return item ? `${item.display_name} (${positionLabel(item)})` : id; };
  const analyst = state.preferences.mode === 'analyst';
  const section = { report: report!, match, team, opponent, name, onShowEvent };

  return <section className="panel tactics-panel analytics-panel phases-panel" id="phases" aria-labelledby="phases-title" style={{ '--home': match.home.color, '--away': match.away.color } as CSSProperties}>
    <div className="section-heading">
      <h2 id="phases-title">Phases of play</h2>
      <span className="section-count">{report ? `To ${matchClock(report.playhead_ms)} · synthetic events and tracking` : 'Synthetic events and tracking'}</span>
    </div>
    <div className="tactics-controls">
      <div className="segmented-control" role="group" aria-label="Team">
        {teams.map((item) => <button key={item.team_id} type="button" aria-pressed={teamId === item.team_id} className={teamId === item.team_id ? 'active' : ''} onClick={() => setTeamId(item.team_id)}><i className="team-dot" style={{ '--insight-color': item.color } as CSSProperties} aria-hidden="true" />{item.short_name}</button>)}
      </div>
      <div className="segmented-control analytics-views" role="group" aria-label="View">
        {views.map((item) => <button key={item.id} type="button" aria-pressed={view === item.id} className={view === item.id ? 'active' : ''} onClick={() => setView(item.id)}>{item.label}</button>)}
      </div>
    </div>
    {!report ? <p className="tactics-empty">{failed ? 'The phase analysis is unavailable right now. It retries automatically.' : <><LoaderCircle className="spin" size={16} aria-hidden="true" /> Loading the phase analysis…</>}</p> : <>
      <div className="tactics-sections">
        {view === 'notes' && <Notes {...section} />}
        {view === 'phases' && <PhasesView {...section} />}
        {view === 'transitions' && <Transitions {...section} />}
        {view === 'blocks' && <Blocks {...section} />}
        {view === 'threat' && <Threat {...section} />}
        {view === 'roles' && <Roles {...section} />}
        {view === 'control' && <Control {...section} />}
      </div>
      <details className="tactics-limits">
        <summary>How this is measured</summary>
        <ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        {analyst && <dl className="tactics-definitions">{Object.entries(report.definitions).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{value}</dd></div>)}</dl>}
      </details>
    </>}
  </section>;
}

type Section = { report: Phases; match: Match; team: Match['home']; opponent: Match['home']; name: (id: string) => string; onShowEvent: (eventId: string) => void };

const minutes = (start: number, end: number) => `${Math.round(start / 60000)}′–${Math.round(end / 60000)}′`;

/** Moments to watch: the numbers point to them, the replay explains them. */
function Moments({ items, onShowEvent, caption = 'Moments to watch' }: { items: Moment[]; onShowEvent: (eventId: string) => void; caption?: string }) {
  if (!items.length) return null;
  return <div className="phase-moments"><span>{caption}</span><ul>
    {items.map((item, index) => {
      const eventId = momentEventId(item);
      return <li key={`${item.time_ms}-${index}`}><span className="moment-time">{matchClock(item.time_ms)}</span><span>{item.label}</span>
        {eventId && <button type="button" className="text-button" onClick={() => onShowEvent(eventId)} aria-label={`Show ${item.label} at ${matchClock(item.time_ms)} on the pitch`}><Target size={14} aria-hidden="true" /> Show</button>}</li>;
    })}
  </ul></div>;
}

function Notes({ report, team, onShowEvent }: Section) {
  const notes = teamNotes(report, team.team_id);
  return <section><h3>Analyst notes</h3>
    <p className="tactics-compare">Each note pairs the numbers with what to look for on the replay. The numbers say how often and where; the moments show why. They are prompts for what to watch, not conclusions.</p>
    {notes.length ? <ol className="phase-notes">{notes.map((item) => <li key={item.note_id}>
      <h4>{item.topic}</h4>
      <p>{item.quantitative}</p>
      <p className="phase-look"><strong>Watch for:</strong> {item.look_for}</p>
      {item.caveat && <p className="phase-caveat">{item.caveat}</p>}
      <Moments items={item.moments} onShowEvent={onShowEvent} />
    </li>)}</ol> : <p className="tactics-empty">Not enough play observed yet for notes.</p>}
  </section>;
}

function PhasesView({ report, team }: Section) {
  const row = report.phases[team.team_id];
  const rows = busiestPhases(report, team.team_id);
  if (!row) return null;
  return <section><h3>Time in each phase</h3>
    <p className="tactics-compare">Every live-ball second belongs to one of six phases. Transitions are the first 10 s after the ball changes hands (15 s while a counter is on); set pieces the first 10 s after a corner, free kick or throw-in.</p>
    <div className="phase-bar" role="img" aria-label={rows.map((item) => `${phaseLabel[item.phase]} ${pct(item.share)}`).join(', ')}>
      {rows.map((item) => <span key={item.phase} className={`phase-${item.phase}`} style={{ width: `${item.share ?? 0}%` }} title={`${phaseLabel[item.phase]} ${pct(item.share)}`} />)}
    </div>
    <Table caption={`${team.display_name} by phase, ${Math.round(row.live_seconds / 60)} live minutes`} head={['Phase', 'Time', 'Share', 'Passes', 'Final-third entries', 'xT added', 'Shots / xG for', 'Shots / xG against', 'Goals']}
      rows={rows.map((item) => [phaseLabel[item.phase], `${Math.round(item.seconds)} s`, pct(item.share), item.passes, item.final_third_entries, xtText(item.xt),
        `${item.shots_for} / ${xgText(item.xg_for)}`, `${item.shots_against} / ${xgText(item.xg_against)}`, `${item.goals_for}–${item.goals_against}`])} />
    {Object.keys(row.restarts).length > 0 && <Stats items={Object.entries(row.restarts).map(([key, value]) => [key.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase()), value])} />}
  </section>;
}

function Transitions({ report, team, onShowEvent }: Section) {
  const row = report.transitions[team.team_id];
  if (!row) return null;
  const { attacking: a, defensive: d } = row;
  return <>
    <section><h3>After winning the ball</h3>
      <Stats items={[['Open-play regains', a.regains], ['Counters', a.counters], ['Median to final third', a.median_to_final_third_s == null ? '—' : `${a.median_to_final_third_s} s`], ['Recycled', a.recycled], ['Lost again within 5 s', a.lost_quickly], ['Counter shots / xG', `${a.counter_shots} / ${xgText(a.counter_xg)}`]]} />
      <Table caption="Where the ball was won" head={['Third', 'Regains', 'Counters']} rows={['defensive', 'middle', 'final'].map((key) => [key[0].toUpperCase() + key.slice(1), a.by_third[key] ?? 0, a.counters_by_third[key] ?? 0])} />
      <Moments items={a.moments} onShowEvent={onShowEvent} />
    </section>
    <section><h3>After losing the ball · counter-press</h3>
      <p className="tactics-compare">Pressed means a player other than the one who lost it got within 3 m of the ball inside 3 s. Rest defence is how many outfield players were goal-side of the ball at the moment of the loss.</p>
      <Stats items={[['Pressed', `${d.pressed} of ${d.tracked} (${pct(d.press_rate)})`], ['Time to pressure', d.median_pressure_s == null ? '—' : `${d.median_pressure_s} s`], ['Players near the ball at 2 s', num1(d.pack_2s)],
        ['Won back within 5 s / 10 s', `${d.regained_5s} / ${d.regained_10s}`], ['Bypassed (20 m upfield in 10 s)', d.bypassed], ['Rest defence', `${num1(d.rest_defence)} (${num1(d.rest_defenders)} defenders)`], ['Shots / xG conceded in 15 s', `${d.shots_conceded} / ${xgText(d.xg_conceded)}`]]} />
      <Moments items={d.moments} onShowEvent={onShowEvent} />
    </section>
  </>;
}

function Blocks({ report, team, opponent, onShowEvent }: Section) {
  const row = report.blocks[team.team_id];
  if (!row) return null;
  return <>
    <section><h3>Defensive block</h3>
      <p className="tactics-compare">Settled defending only (no transition or set piece): {Math.round(row.settled_seconds / 60) === 1 ? '1 minute' : `${Math.round(row.settled_seconds / 60)} minutes`}. The block is read from the back four's depth: high from 42 m, low under 30 m.</p>
      <Table caption={`${team.display_name} by block, against ${opponent.display_name}`} head={['Block', 'Share', 'Back four', 'Length', 'Width', 'Line gap', 'Box defenders', 'Entries / wide', 'Crosses faced', 'Shots / long', 'xG against', 'PPDA', 'Regains / counters']}
        rows={row.rows.filter((item) => item.seconds).map((item) => [blockName[item.block], pct(item.share), metres(item.back_four_m), metres(item.length_m), metres(item.width_m), metres(item.line_gap_m), num1(item.box_defenders),
          `${item.opponent_entries} / ${pct(item.wide_entry_share)}`, item.crosses_faced, `${item.opponent_shots} / ${pct(item.long_shot_share)}`, xgText(item.xg_against), num1(item.ppda), `${item.regains} / ${item.counters}`])} />
    </section>
    <section><h3>Line height by situation</h3>
      <p className="tactics-compare">{lineContrast(report, team.team_id, team.display_name)}</p>
      <Table caption="Back four and front line, metres from own goal" head={['Situation', 'Time', 'Back four', 'Front line', 'Length']}
        rows={row.snapshots.map((item) => [snapshotLabel[item.situation], `${Math.round(item.seconds)} s`, metres(item.back_four_m), metres(item.front_line_m), metres(item.length_m)])} />
    </section>
    <section><h3>Balls in behind · recovery</h3>
      <Stats items={[['Balls in behind', row.recovery.balls_in_behind], ['Back-four retreat (5 s)', metres(row.recovery.retreat_m)], ['Fastest recovery', row.recovery.top_speed_mps == null ? '—' : `${row.recovery.top_speed_mps} m/s`],
        ['Keeper starting position', metres(row.recovery.keeper_start_m)], ['Keeper furthest (5 s)', metres(row.recovery.keeper_max_m)], ['Keeper sweeps', row.recovery.sweeps], ['Shots conceded in 10 s', row.recovery.shots_conceded]]} />
      <Moments items={row.recovery.moments} onShowEvent={onShowEvent} />
    </section>
  </>;
}

/** The fitted xT grid as a flat pitch in the attacking direction (left to right). */
function ThreatGrid({ report, color }: { report: Phases; color: string }) {
  const { grid_x: gx, grid_y: gy, values } = report.xt_grid;
  const max = Math.max(...values, .0001);
  const w = 105 / gx, h = 68 / gy;
  return <svg className="heatmap-pitch" viewBox="-2 -2 109 72" role="img" aria-label="Expected threat by zone, attacking left to right; darker zones are more likely to lead to a goal">
    <rect x="0" y="0" width="105" height="68" className="heatmap-surface" />
    {values.map((value, index) => {
      const cx = Math.floor(index / gy), cy = index % gy;
      return <rect key={index} x={cx * w + .25} y={cy * h + .25} width={w - .5} height={h - .5} rx=".6" fill={color} fillOpacity={.06 + .89 * value / max}><title>{zoneText(value)}</title></rect>;
    })}
    <g className="heatmap-lines" fill="none">
      <rect x="0" y="0" width="105" height="68" /><path d="M52.5 0V68" /><circle cx="52.5" cy="34" r="9.15" />
      <rect x="0" y="13.84" width="16.5" height="40.32" /><rect x="88.5" y="13.84" width="16.5" height="40.32" />
    </g>
  </svg>;
}

function Threat({ report, team, name, onShowEvent }: Section) {
  const row = report.progression[team.team_id];
  const players = report.player_progression.filter((item) => item.team_id === team.team_id).sort((a, b) => b.xt - a.xt).slice(0, 10);
  const top = report.top_threat.filter((item) => item.team_id === team.team_id);
  if (!row) return null;
  const training = report.xt_grid.training;
  return <>
    <section><h3>Progressive carries and expected threat</h3>
      <p className="tactics-compare">Expected threat (xT) values each zone by how likely possession there leads to a goal, learned from {String(training.matches ?? '—')} other synthetic matches (the demo match is left out). A pass or carry adds the end zone's value minus the start zone's. Unlike the possession value in Live analytics, which is a hand-set formula, xT is fitted from how play moves.</p>
      <Stats items={[['xT added', xtText(row.xt)], ['From passes / carries', `${xtText(row.xt_passes)} / ${xtText(row.xt_carries)}`], ['Progressive passes', row.progressive_passes], ['Progressive carries', `${row.progressive_carries} · ${Math.round(row.progressive_carry_m)} m`],
        ['Carries into final third / box', `${row.carries_final_third} / ${row.carries_box}`], ['Take-ons', row.take_ons]]} />
      <Table caption="xT by channel and by 15 minutes" head={['', ...Object.keys(row.xt_by_channel).map((key) => key[0].toUpperCase() + key.slice(1)), ...row.xt_intervals.map((_, index) => minutes(index * 900000, Math.min(report.playhead_ms, (index + 1) * 900000)))]}
        rows={[['xT', ...Object.values(row.xt_by_channel).map(xtText), ...row.xt_intervals.map(xtText)]]} />
      <ThreatGrid report={report} color={team.color} />
    </section>
    <section><h3>Who moves the ball into danger</h3>
      <Table caption="Players by xT added" head={['Player', 'xT', 'Passes', 'Carries', 'Progressive passes', 'Progressive carries', 'Carry metres', 'Take-ons']}
        rows={players.map((item) => [name(item.player_id), xtText(item.xt), xtText(item.xt_passes), xtText(item.xt_carries), item.progressive_passes, item.progressive_carries, Math.round(item.progressive_carry_m), item.take_ons])} />
      <Moments caption="Biggest threat added" onShowEvent={onShowEvent}
        items={top.map((item) => ({ time_ms: item.time_ms, event_ref: item.event_ref, label: `${name(item.player_id)} ${item.action}: ${xtText(item.xt)} xT` }))} />
    </section>
  </>;
}

function Roles({ report, team, name, onShowEvent }: Section) {
  const backs = report.fullbacks.filter((item) => item.team_id === team.team_id);
  const rotations = report.rotations[team.team_id]?.rows ?? [];
  return <>
    <section><h3>Full-back roles</h3>
      <Table caption="Measured from synthetic positions while the team has the ball" head={['Player', 'Side', 'Role', 'Inside (build-up)', 'Overlaps / underlaps', 'Depth', 'In final third', 'At a loss', 'Crosses', 'xT']}
        rows={backs.map((item) => [name(item.player_id), item.side === 'right' ? 'Right' : 'Left', fullbackLabel[item.style], pct(item.inside_share), `${item.overlaps} / ${item.underlaps}`, metres(item.depth_m), metres(item.attack_depth_m), metres(item.depth_at_loss_m), item.crosses, xtText(item.xt)])} />
      {backs.map((item) => <Moments key={item.player_id} caption={`${name(item.player_id)}`} items={item.moments} onShowEvent={onShowEvent} />)}
    </section>
    <section><h3>Rotations</h3>
      <p className="tactics-compare">A rotation counts when the swap holds for 2 s or more with the ball. The final-third rate compares possessions with the rotation against those without it; it shows association, not cause.</p>
      {rotations.length ? <Table caption="Positional rotations in possession" head={['Rotation', 'Players', 'Episodes', 'Time', 'Possessions', 'Reached final third', 'Without it']}
        rows={rotations.map((item) => [rotationLabel[item.kind], item.players.map(name).join(', '), item.episodes, `${Math.round(item.seconds)} s`, item.possessions, pct(item.final_third_rate), pct(item.baseline_rate)])} />
        : <p className="tactics-empty">No rotations observed yet.</p>}
      {rotations.slice(0, 2).map((item) => <Moments key={item.kind} caption={rotationLabel[item.kind]} items={item.moments} onShowEvent={onShowEvent} />)}
    </section>
  </>;
}

function Control({ report, match, team, name }: Section) {
  const [home, away] = [report.control[match.home.team_id], report.control[match.away.team_id]];
  const press = report.pressing[team.team_id];
  const xg = report.xg[team.team_id];
  const finishers = report.finishing.filter((item) => item.team_id === team.team_id);
  return <>
    <section><h3>Possession against control</h3>
      <p className="tactics-compare">Possession counts time on the ball; control asks what it was used for. Purposeful possessions reach the final third or a shot; sterile ones string five or more passes without either.</p>
      <Table caption="Both teams" head={['Team', 'Read', 'Possession', 'Field tilt', 'Final-third entries', 'Box entries', 'Progressive actions', 'xG', 'PPDA', 'Purposeful', 'Sterile']}
        rows={[home, away].filter(Boolean).map((item) => [item!.team_id === match.home.team_id ? match.home.short_name : match.away.short_name, controlLabel[item!.read], pct(item!.possession_share), pct(item!.field_tilt),
          item!.final_third_entries, item!.box_entries, item!.progressive_actions, xgText(item!.xg), num1(item!.ppda), `${item!.purposeful} of ${item!.possessions}`, `${item!.sterile} (${item!.sterile_passes} passes)`])} />
    </section>
    {press && <section><h3>{team.display_name} pressing over time</h3>
      <Stats items={[['High regains', press.high_regains], ['Shots / xG from them', `${press.high_regain_shots} / ${xgText(press.high_regain_xg)}`]]} />
      <Table caption="PPDA by 15 minutes (lower means more intense pressing)" head={['Minutes', 'PPDA', 'Opponent passes', 'Defensive actions', 'High regains']}
        rows={press.intervals.map((item) => [minutes(item.start_ms, item.end_ms), num1(item.ppda), item.opponent_passes, item.defensive_actions, item.high_regains])} />
    </section>}
    {xg && <section><h3>Chances and finishing</h3>
      <Table caption="xG for and against by 15 minutes" head={['', ...xg.intervals.map((_, index) => minutes(index * 900000, Math.min(report.playhead_ms, (index + 1) * 900000)))]}
        rows={[['For', ...xg.intervals.map(xgText)], ['Against', ...xg.intervals_against.map(xgText)]]} />
      <Table caption="Finishing: goals against xG" head={['Player', 'Shots', 'Goals', 'xG', 'Goals − xG', 'xG per shot']}
        rows={finishers.map((item) => [name(item.player_id), item.shots, item.goals, xgText(item.xg), `${item.goals_minus_xg >= 0 ? '+' : '−'}${Math.abs(item.goals_minus_xg).toFixed(2)}`, xgText(item.xg_per_shot)])} />
    </section>}
  </>;
}
