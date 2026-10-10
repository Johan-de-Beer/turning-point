import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { Crosshair, LoaderCircle } from 'lucide-react';
import type { Match, Session } from '../../lib/contracts';
import { matchClock } from '../../lib/format';
import {
  angleLabel, categoryLabel, metres, momentLayout, observationsFor, seconds, share, speed, zoneLabel,
  type KeyMoment, type TacticalObservation, type Tactics, type TacticsView, type TeamTactics,
} from '../../lib/tactics';

const REFRESH_MS = 5000;
const views: { id: TacticsView; label: string }[] = [
  { id: 'defending', label: 'Defending' }, { id: 'attacking', label: 'Attacking' }, { id: 'set_pieces', label: 'Set pieces' },
];

type Props = { state: Session; match: Match; getTactics: (signal?: AbortSignal) => Promise<Tactics> };

export function TacticsPanel({ state, match, getTactics }: Props) {
  const [report, setReport] = useState<Tactics | null>(null);
  const [failed, setFailed] = useState(false);
  const [teamId, setTeamId] = useState(state.preferences.favorite_team_id ?? match.home.team_id);
  const [view, setView] = useState<TacticsView>('defending');
  const [momentId, setMomentId] = useState<string | null>(null);
  const fetched = useRef({ key: '', at: 0 });
  const latest = useRef(state); latest.current = state;
  const load = useRef(getTactics); load.current = getTactics;

  // Refresh on a real-time cadence while the observed match moves on; at once on restart or correction.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const refresh = async (force = false) => {
      const current = latest.current;
      const key = `${current.session_id}:${current.generation}:${current.data_epoch}:${Math.floor(current.playhead_ms / 1000)}`;
      if (!force && (key === fetched.current.key || Date.now() - fetched.current.at < REFRESH_MS)) return;
      fetched.current = { key, at: Date.now() };
      try {
        const next = await load.current(controller.signal);
        if (!cancelled) { setReport(next); setFailed(false); }
      } catch { if (!cancelled) setFailed(true); }
    };
    void refresh(true);
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => { cancelled = true; controller.abort(); window.clearInterval(timer); };
  }, [state.session_id, state.generation, state.data_epoch, state.status]);

  useEffect(() => { if (state.preferences.favorite_team_id) setTeamId(state.preferences.favorite_team_id); }, [state.preferences.favorite_team_id]);

  const team = report?.teams[teamId];
  const findings = useMemo(() => report ? observationsFor(report, teamId, view) : [], [report, teamId, view]);
  const moments = report?.key_moments ?? [];
  const available = findings.map((item) => item.moment_id).filter((id): id is string => !!id);
  const shown = moments.find((item) => item.moment_id === momentId && available.includes(item.moment_id)) ?? moments.find((item) => item.moment_id === available[0]) ?? null;
  const analyst = state.preferences.mode === 'analyst';
  const teams = [match.home, match.away];
  const name = (id: string) => match.roster.find((player) => player.player_id === id)?.display_name ?? id;
  const shirt = (id: string) => match.roster.find((player) => player.player_id === id)?.shirt_number ?? '';
  const colour = (id: string) => teams.find((item) => item.team_id === id)?.color ?? '#94a3b8';

  return <section className="panel tactics-panel" id="tactics" aria-labelledby="tactics-title" style={{ '--home': match.home.color, '--away': match.away.color } as CSSProperties}>
    <div className="section-heading">
      <h2 id="tactics-title">Tactical analysis</h2>
      <span className="section-count">{report ? `${report.episodes_observed} tracked phases · synthetic tracking` : 'Synthetic tracking'}</span>
    </div>
    <div className="tactics-controls">
      <div className="segmented-control" role="group" aria-label="Team">
        {teams.map((item) => <button key={item.team_id} type="button" aria-pressed={teamId === item.team_id} className={teamId === item.team_id ? 'active' : ''} onClick={() => setTeamId(item.team_id)}><i className="team-dot" style={{ '--insight-color': item.color } as CSSProperties} aria-hidden="true" />{item.short_name}</button>)}
      </div>
      <div className="segmented-control" role="group" aria-label="Phase of play">
        {views.map((item) => <button key={item.id} type="button" aria-pressed={view === item.id} className={view === item.id ? 'active' : ''} onClick={() => setView(item.id)}>{item.label}</button>)}
      </div>
    </div>
    {!report || !team ? <p className="tactics-empty">{failed ? 'The tactical analysis is unavailable right now. It retries automatically.' : <><LoaderCircle className="spin" size={16} aria-hidden="true" /> Loading the tactical analysis…</>}</p> : <>
      <div className="tactics-lead">
        <div className="tactics-findings">
          <h3>What stands out</h3>
          {findings.length ? <ol>{findings.map((item) => <Finding key={item.observation_id} item={item} view={view} active={shown?.moment_id === item.moment_id} onMoment={item.moment_id ? () => setMomentId(item.moment_id) : undefined} />)}</ol>
            : <p className="tactics-empty">{report.episodes_observed ? 'Not enough observed phases for a pattern here yet.' : 'Patterns appear once attacks, presses and corners have been observed.'}</p>}
        </div>
        <div className="tactics-moment">
          {shown ? <MomentPitch moment={shown} name={name} shirt={shirt} colour={colour} teamName={(id) => teams.find((item) => item.team_id === id)?.display_name ?? id} />
            : findings.length ? <div className="moment-placeholder"><Crosshair size={22} aria-hidden="true" /><p>Key moments appear here when a finding has one.</p></div> : null}
        </div>
      </div>
      <details className="tactics-numbers" open={analyst || undefined}>
        <summary>The numbers behind it</summary>
        {view === 'defending' && <Defending team={team} name={name} />}
        {view === 'attacking' && <Attacking team={team} name={name} />}
        {view === 'set_pieces' && <SetPieces team={team} name={name} />}
      </details>
      <details className="tactics-limits">
        <summary>How this is measured</summary>
        <ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        {analyst && <dl className="tactics-definitions">{Object.entries(report.definitions).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{value}</dd></div>)}</dl>}
      </details>
    </>}
  </section>;
}

function Finding({ item, view, active, onMoment }: { item: TacticalObservation; view: TacticsView; active: boolean; onMoment?: () => void }) {
  const weakness = item.kind === 'opportunity' && view === 'defending';
  const tag = item.kind === 'tendency' ? 'Tendency' : weakness ? 'Weakness' : 'Opportunity';
  return <li className={`finding finding-${weakness ? 'weakness' : item.kind}`}>
    <div className="finding-meta"><span className="finding-tag">{tag}</span><span>{categoryLabel[item.category]}</span><span>n = {item.sample_size}</span></div>
    <strong>{item.headline}</strong>
    <p>{item.detail}</p>
    {onMoment && <button type="button" className="text-button" aria-pressed={active} onClick={onMoment}><Crosshair size={14} aria-hidden="true" />{active ? 'Showing on the pitch' : 'Show the moment'}</button>}
  </li>;
}

function Markings() {
  return <g className="moment-lines" fill="none" strokeWidth=".35">
    <rect x="0" y="0" width="105" height="68" />
    <path d="M52.5 0V68" />
    <circle cx="52.5" cy="34" r="9.15" />
    <rect x="0" y="13.84" width="16.5" height="40.32" /><rect x="88.5" y="13.84" width="16.5" height="40.32" />
    <rect x="0" y="24.84" width="5.5" height="18.32" /><rect x="99.5" y="24.84" width="5.5" height="18.32" />
    <rect x="-1.5" y="30.34" width="1.5" height="7.32" /><rect x="105" y="30.34" width="1.5" height="7.32" />
  </g>;
}

function MomentPitch({ moment, name, shirt, colour, teamName }: { moment: KeyMoment; name: (id: string) => string; shirt: (id: string) => number | string; colour: (id: string) => string; teamName: (id: string) => string }) {
  const layout = momentLayout(moment);
  const highlighted = layout.players.filter((player) => player.highlighted);
  return <figure className="moment-figure">
    <svg viewBox="-3 -3 111 74" role="img" aria-label={`${moment.title}. ${teamName(moment.team_id)} attack to the right. ${highlighted.map((player) => name(player.player_id)).join(' and ')} highlighted.`}>
      <rect x="-3" y="-3" width="111" height="74" className="moment-grass" />
      <Markings />
      {layout.line != null && <g className="moment-offside"><line x1={layout.line} y1="0" x2={layout.line} y2="68" /><text x={layout.line + .8} y="3.2">Offside line</text></g>}
      {layout.path.length > 1 && <polyline className="moment-path" points={layout.path.map((p) => `${p.x},${p.y}`).join(' ')} />}
      {layout.players.map((player) => <g key={player.player_id} transform={`translate(${player.x} ${player.y})`} className={player.highlighted ? 'moment-player is-highlighted' : 'moment-player'}>
        <circle r={player.highlighted ? 1.9 : 1.5} fill={colour(player.team_id)} />
        <text y=".55">{shirt(player.player_id)}</text>
      </g>)}
      <circle className="moment-ball" cx={layout.ball.x} cy={layout.ball.y} r=".8" strokeWidth=".3" />
      {highlighted.map((player) => {
        // Attackers' names sit above their marker, defenders' below, kept inside the pitch.
        const above = player.attacking ? player.y > 6 : player.y > 62;
        return <text key={player.player_id} className="moment-label" x={Math.min(98, Math.max(7, player.x))} y={above ? Math.max(2, player.y - 2.6) : player.y + 4.2}>{name(player.player_id)}</text>;
      })}
    </svg>
    <figcaption><strong>{moment.title}</strong><span>{matchClock(moment.time_ms)} · {teamName(moment.team_id)} attacking → · synthetic positions</span></figcaption>
  </figure>;
}

function Stats({ items }: { items: [string, ReactNode][] }) {
  return <dl className="tactics-stats">{items.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
}

function Table({ caption, head, rows }: { caption: string; head: string[]; rows: ReactNode[][] }) {
  if (!rows.length) return null;
  return <div className="table-scroll" tabIndex={0} role="region" aria-label={caption}><table className="tactics-table">
    <caption>{caption}</caption>
    <thead><tr>{head.map((cell) => <th key={cell} scope="col">{cell}</th>)}</tr></thead>
    <tbody>{rows.map((row, index) => <tr key={index}>{row.map((cell, column) => column === 0 ? <th key={column} scope="row">{cell}</th> : <td key={column}>{cell}</td>)}</tr>)}</tbody>
  </table></div>;
}

type Section = { team: TeamTactics; name: (id: string) => string };

function Defending({ team, name }: Section) {
  const { offside_trap: trap, shape, press } = team;
  const systems = { man_oriented: 'Man-oriented', zonal: 'Zonal', mixed: 'Mixed', insufficient_evidence: 'Not yet clear' };
  const outcome = (o: TeamTactics['press']['when_pressing']) => o.possessions ? `${share(o.forced_to_keeper, o.possessions)} to keeper · ${share(o.regained, o.possessions)} regained · ${share(o.played_through, o.possessions)} played through` : '—';
  return <div className="tactics-sections">
    <section><h3>Offside trap</h3>
      <Stats items={[['Traps', `${trap.traps} of ${trap.attacks_faced}`], ['Runner caught', trap.caught_offside], ['Broken by a late step', trap.broken], ['Step speed', speed(trap.mean_step_speed_mps)], ['Line from goal', metres(trap.mean_line_height_m)], ['Line spread', metres(trap.mean_line_spread_m)]]} />
      <Table caption="Back four when the line steps up" head={['Defender', 'Stepped', 'Late', 'Mean lag', 'Deeper at pass', 'Runners kept onside']}
        rows={trap.defenders.map((d) => [name(d.player_id), `${d.steps}/${d.traps}`, d.late_steps, d.mean_lag_ms == null ? '—' : `${Math.round(d.mean_lag_ms)} ms`, metres(d.mean_depth_at_pass_m), d.runners_played_onside])} />
    </section>
    <section><h3>Shape and marking</h3>
      <Stats items={[['Width', `${metres(shape.mean_width_before_m)} → ${metres(shape.mean_width_at_pass_m)}`], ['Length', `${metres(shape.mean_length_before_m)} → ${metres(shape.mean_length_at_pass_m)}`], ['Shift to ball side', metres(shape.mean_shift_to_ball_m)], ['Marking', systems[shape.marking_system]], ['Dropped with runs', shape.follow_rate == null ? '—' : `${shape.follow_rate}%`]]} />
      <Table caption="Marking assignments" head={['Player', 'Assignments', 'Left to engage ball', 'Runs faced', 'Tracked', 'Late', 'Mean reaction']}
        rows={shape.marking.filter((m) => m.assignments || m.runs_faced).map((m) => [name(m.player_id), m.assignments, m.early_releases, m.runs_faced, m.tracked, m.late_reactions, m.mean_reaction_ms == null ? '—' : `${Math.round(m.mean_reaction_ms)} ms`])} />
      <Table caption="Slowest to finish the lateral shift" head={['Player', 'Shifts', 'Behind the unit']} rows={shape.shift_lags.map((s) => [name(s.player_id), s.shifts, `${Math.round(s.mean_lag_ms)} ms`])} />
    </section>
    <section><h3>Press</h3>
      <Stats items={[['Presses', `${press.presses} of ${press.opportunities}`], ['Time to pressure', seconds(press.mean_time_to_pressure_ms)], ['Closing speed', speed(press.mean_closing_speed_mps)], ['Back to keeper', seconds(press.when_pressing.mean_time_to_keeper_ms)]]} />
      <p className="tactics-compare"><strong>Pressed:</strong> {outcome(press.when_pressing)}<br /><strong>Not pressed:</strong> {outcome(press.when_not_pressing)}</p>
      <Table caption="Who triggers the press" head={['Trigger', 'Presses', 'Time to pressure', 'Closing speed']} rows={press.triggers.map((t) => [name(t.player_id), t.presses, seconds(t.mean_time_to_pressure_ms), speed(t.mean_closing_speed_mps)])} />
      <Table caption="Who is pressed (opponent on the ball)" head={['Player', 'Possessions', 'Pressed', 'Rate']} rows={press.targets.slice(0, 8).map((t) => [name(t.player_id), t.possessions, t.presses, `${Math.round(t.press_rate)}%`])} />
    </section>
  </div>;
}

function Attacking({ team, name }: Section) {
  const build = team.build_up;
  return <div className="tactics-sections">
    <section><h3>Runs in behind</h3>
      <Table caption="Runs at 5.5 m/s or faster from near the line" head={['Runner', 'Runs', 'Got in behind', 'Found by the pass', 'Offside', 'Defender dropped']}
        rows={team.runs.map((r) => [name(r.player_id), r.runs, r.in_behind, r.targeted, r.offside, r.drag_rate == null ? '—' : `${r.drew_defender} (${Math.round(r.drag_rate)}%)`])} />
    </section>
    <section><h3>Chance creation</h3>
      <Table caption="Who starts attacks" head={['Player', 'Attacks started', 'Chances', 'Time to chance']} rows={team.creators.map((c) => [name(c.player_id), c.attacks_started, c.chances, seconds(c.mean_time_to_chance_ms)])} />
      <Table caption="Decisive passes" head={['Time', 'Pass', 'Length', 'Angle', 'Speed', 'Beyond the line', 'Chance']}
        rows={team.decisive_passes.slice().reverse().map((d) => [matchClock(d.time_ms), `${name(d.passer_id)} → ${name(d.recipient_id)}`, metres(d.length_m), angleLabel(d.angle_deg), speed(d.speed_mps), d.through_ball == null ? '—' : d.through_ball ? 'Yes' : 'No', d.led_to_chance ? 'Yes' : 'No'])} />
    </section>
    <section><h3>Build-up from the keeper</h3>
      <Stats items={[['Sequences', build.sequences], ['Short / long start', `${build.short_starts} / ${build.long_starts}`], ['Reached middle third', `${share(build.reached_middle_third, build.sequences)} · ${seconds(build.mean_time_to_middle_ms)}`], ['Reached final third', `${share(build.reached_final_third, build.sequences)} · ${seconds(build.mean_time_to_final_ms)}`], ['Pass accuracy', build.pass_accuracy == null ? '—' : `${build.pass_accuracy}%`], ['Lines broken per sequence', build.mean_lines_broken ?? '—'], ['Lost in own half', build.lost_in_own_half]]} />
    </section>
  </div>;
}

function SetPieces({ team, name }: Section) {
  const { corners } = team;
  if (!corners.corners) return <p className="tactics-empty">No corners observed yet.</p>;
  return <div className="tactics-sections">
    <section><h3>Corner deliveries</h3>
      <Table caption="Each delivery, from the 5 Hz ball path" head={['Time', 'Taker', 'Side', 'Swing', 'Flight', 'Speed', 'Zone', 'Nearest attacker', 'Distance to them', 'First contact']}
        rows={corners.deliveries.slice().reverse().map((d) => [matchClock(d.time_ms), `${name(d.taker_id)} (${d.foot})`, d.side, `${d.swing}${d.swing === d.expected_swing ? '' : ' (unexpected)'}`, seconds(d.flight_ms), speed(d.speed_mps), zoneLabel[d.zone], name(d.target_id), metres(d.accuracy_m), d.first_contact === 'attack' ? 'Won' : 'Lost'])} />
    </section>
    <section><h3>Target men</h3>
      <Table caption="Getting to where the ball lands" head={['Player', 'Deliveries', 'Reached spot', 'Time to spot', 'Against the ball', 'First contacts']}
        rows={corners.target_men.map((t) => [name(t.player_id), t.deliveries, t.reached_spot, seconds(t.mean_time_to_spot_ms, 2), t.mean_arrival_vs_ball_ms == null ? '—' : `${Math.abs(Math.round(t.mean_arrival_vs_ball_ms))} ms ${t.mean_arrival_vs_ball_ms <= 0 ? 'early' : 'late'}`, t.first_contacts])} />
    </section>
  </div>;
}
