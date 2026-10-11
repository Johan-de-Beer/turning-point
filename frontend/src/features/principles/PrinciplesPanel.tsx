import { useEffect, useState, type CSSProperties } from 'react';
import { LoaderCircle } from 'lucide-react';
import type { Match, Session } from '../../lib/contracts';
import { matchClock } from '../../lib/format';
import { positionLabel } from '../../lib/events';
import { num1, pct, xgText } from '../../lib/analytics';
import { metres } from '../../lib/tactics';
import { xtText } from '../../lib/phases';
import {
  bandLabel, markingLabel, movementLabel, movementsOf, reportSections, shapeText, signed, systemLabel, triggerLabel, unitLabel, wingerLabel, zoneLabel,
  type MovementKind, type Principles, type PrinciplesView,
} from '../../lib/principles';
import { useLiveReport } from '../../lib/useLiveReport';
import { Stats, Table } from '../tactics/TacticsPanel';
import { Moments } from '../phases/PhasesPanel';

const views: { id: PrinciplesView; label: string }[] = [
  { id: 'report', label: 'Match report' }, { id: 'structure', label: 'Build-up & rest defence' }, { id: 'wingers', label: 'Wingers & width' },
  { id: 'pressing', label: 'Pressing & marking' }, { id: 'movement', label: 'Counter-movements' }, { id: 'third_man', label: 'Third man' },
];

type Props = { state: Session; match: Match; getPrinciples: (signal?: AbortSignal) => Promise<Principles>; onShowEvent: (eventId: string) => void };

export function PrinciplesPanel({ state, match, getPrinciples, onShowEvent }: Props) {
  const { report, failed } = useLiveReport(state, getPrinciples);
  const [teamId, setTeamId] = useState(state.preferences.favorite_team_id ?? match.home.team_id);
  const [view, setView] = useState<PrinciplesView>('report');
  useEffect(() => { if (state.preferences.favorite_team_id) setTeamId(state.preferences.favorite_team_id); }, [state.preferences.favorite_team_id]);
  const teams = [match.home, match.away];
  const team = teams.find((item) => item.team_id === teamId) ?? match.home;
  const opponent = team.team_id === match.home.team_id ? match.away : match.home;
  const name = (id: string) => { const item = match.roster.find((row) => row.player_id === id); return item ? `${item.display_name} (${positionLabel(item)})` : id; };
  const analyst = state.preferences.mode === 'analyst';
  const section = { report: report!, match, team, opponent, name, onShowEvent };

  return <section className="panel tactics-panel analytics-panel phases-panel" id="principles" aria-labelledby="principles-title" style={{ '--home': match.home.color, '--away': match.away.color } as CSSProperties}>
    <div className="section-heading">
      <h2 id="principles-title">Principles of play</h2>
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
    {!report ? <p className="tactics-empty">{failed ? 'The principles of play are unavailable right now. It retries automatically.' : <><LoaderCircle className="spin" size={16} aria-hidden="true" /> Loading the principles of play…</>}</p> : <>
      <div className="tactics-sections">
        {view === 'report' && <Report {...section} />}
        {view === 'structure' && <Structure {...section} />}
        {view === 'wingers' && <Wingers {...section} />}
        {view === 'pressing' && <Pressing {...section} />}
        {view === 'movement' && <Movement {...section} />}
        {view === 'third_man' && <ThirdMan {...section} />}
      </div>
      <details className="tactics-limits">
        <summary>How this is measured</summary>
        <ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        {analyst && <dl className="tactics-definitions">{Object.entries(report.definitions).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{value}</dd></div>)}</dl>}
      </details>
    </>}
  </section>;
}

type Section = { report: Principles; match: Match; team: Match['home']; opponent: Match['home']; name: (id: string) => string; onShowEvent: (eventId: string) => void };

function Report({ report, team, name, onShowEvent }: Section) {
  const row = report.match_report[team.team_id];
  if (!row) return null;
  return <section><h3>Match report</h3>
    <p className="tactics-compare">{row.summary} The report follows a professional analyst's order: each phase, then strengths to keep and weaknesses an opponent could target. Each line is built from the numbers, with moments to check on the replay; it says what happened, not why.</p>
    {row.key_player && <p className="phase-look"><strong>Key player: {name(row.key_player)}.</strong> {row.key_player_reason}</p>}
    {reportSections(report, team.team_id).map((item) => <div key={item.title}><h4 className="report-heading">{item.title}</h4>
      <ol className="phase-notes">{item.lines.map((line) => <li key={line.topic}>
        <h4>{line.topic}</h4><p>{line.text}</p>
        <Moments items={line.moments} onShowEvent={onShowEvent} />
      </li>)}</ol>
    </div>)}
  </section>;
}

function Structure({ report, team, onShowEvent }: Section) {
  const row = report.structures[team.team_id];
  if (!row) return null;
  const shapeRows = (items: typeof row.build_up) => items.map((item) => [item.shape, pct(item.share), `${Math.round(item.seconds)} s`, shapeText(item)]);
  return <>
    <section><h3>Build-up structure</h3>
      <p className="tactics-compare">The deepest five outfield players in settled possession with the ball in the team's own half, split into a base line and the screen in front of it. 3+2 is a back three with two midfielders ahead; 2+3 is two centre-backs with three ahead (often a full-back stepping inside).</p>
      <Table caption={`${team.display_name} building from the back, ${Math.round(row.build_up_seconds)} s`} head={['Shape', 'Share', 'Time', 'Base | screen']} rows={shapeRows(row.build_up)} />
    </section>
    <section><h3>Rest defence</h3>
      <p className="tactics-compare">The same five with the ball in the final third: the insurance against a counter if the ball is lost.</p>
      <Stats items={[['Behind the ball (10 m or more)', num1(row.behind_ball)], ['Over-committed (3 or fewer behind)', pct(row.overcommitted_share)], ['Final-third time', `${Math.round(row.rest_seconds)} s`]]} />
      <Table caption={`${team.display_name} with the ball in the final third`} head={['Shape', 'Share', 'Time', 'Base | screen']} rows={shapeRows(row.rest_defence)} />
      <Table caption="Losses in the final third by rest-defence shape" head={['Shape', 'Losses', 'Counters conceded', 'Shots / xG conceded']}
        rows={row.losses.map((item) => [item.shape, item.losses, item.counters_conceded, `${item.shots_conceded} / ${xgText(item.xg_conceded)}`])} />
      <Moments items={row.moments} onShowEvent={onShowEvent} />
    </section>
  </>;
}

function Wingers({ report, team, name, onShowEvent }: Section) {
  const rows = report.wingers.filter((item) => item.team_id === team.team_id);
  const width = report.width[team.team_id];
  return <>
    <section><h3>Winger roles</h3>
      <p className="tactics-compare">An inverted winger drifts inside into the half-space to combine, shoot or thread passes; a touchline winger holds the width. With the winger inside, the full-back usually has to give the width.</p>
      <Table caption="Measured from synthetic positions with the ball in the opponent's half" head={['Player', 'Side / foot', 'Role', 'From touchline', 'Time inside', 'Cut-ins', 'Shots (central)', 'Full-back wider', 'xT']}
        rows={rows.map((item) => [name(item.player_id), `${item.side === 'right' ? 'Right' : 'Left'} · ${item.foot}-footed${item.opposite_foot ? ' (opposite foot)' : ''}`, wingerLabel[item.style], metres(item.touchline_m), pct(item.inside_share), item.cut_ins,
          `${item.shots} (${item.central_shots})`, pct(item.fullback_width_share), xtText(item.xt)])} />
      {rows.map((item) => <Moments key={item.player_id} caption={name(item.player_id)} items={item.moments} onShowEvent={onShowEvent} />)}
    </section>
    {width && <section><h3>Attacking width</h3>
      <Stats items={[['Width in the final third', metres(width.width_m)], ['Final-third entries', width.entries], ['Through the centre', pct(width.central_entry_share)], ['Crosses', width.crosses]]} />
    </section>}
  </>;
}

function Pressing({ report, team, opponent, name, onShowEvent }: Section) {
  const row = report.pressing[team.team_id];
  const mark = report.marking[team.team_id];
  if (!row) return null;
  return <>
    <section><h3>Pressing system · {systemLabel[row.system]}</h3>
      <p className="tactics-compare">During {opponent.display_name}'s build-up ({Math.round(row.seconds)} s): does each player go with their nearest opponent when that opponent moves? Man-to-man presses follow, zonal ones hold their zone, hybrids mix the two by unit.</p>
      <Table caption="By unit" head={['Unit', 'Marking', 'Followed', 'To nearest opponent', 'Players who follow their man']}
        rows={row.units.map((item) => [unitLabel[item.unit], markingLabel[item.marking], pct(item.follow_share), metres(item.distance_m), item.markers.map(name).join(', ') || '—'])} />
      <Stats items={[['Spare at the back', signed(row.spare_at_back)], ['Most often left free', row.left_free ? `${name(row.left_free)} · ${pct(row.left_free_share)}` : '—'],
        ['Build-ups forced wide', `${pct(row.forced_wide_share)} of ${row.build_ups}`], ['Cover shadow on the six', row.cover_shadow_tracked ? `${row.cover_shadow} of ${row.cover_shadow_tracked}` : 'None tracked']]} />
    </section>
    <section><h3>Pressing triggers</h3>
      <p className="tactics-compare">Pressure on the receiver of {opponent.display_name}'s passes into its own half, by the kind of pass. A trigger shows up as a much higher rate on one kind.</p>
      {!row.triggers.length && <p className="tactics-empty">No passes into {opponent.display_name}'s own half observed yet.</p>}
      <Table caption="Pressured within 3 s of the ball arriving" head={['Pass', 'Passes', 'Pressured', 'Rate', 'Time to pressure', 'Won back in 5 s']}
        rows={row.triggers.map((item) => [triggerLabel[item.trigger], item.passes, `${item.pressured} of ${item.tracked}`, pct(item.rate), item.median_s == null ? '—' : `${item.median_s} s`, item.regained_5s])} />
      <Moments items={row.moments} onShowEvent={onShowEvent} />
    </section>
    {mark && <section><h3>Marking and free men</h3>
      <p className="tactics-compare">The man-marking rule of thumb: the closer an opponent is to the ball, the tighter the marking.</p>
      <Table caption="Distance from each opponent to the nearest defender, settled defending" head={['Opponent', 'Samples', 'Nearest defender']}
        rows={mark.bands.map((item) => [bandLabel[item.band], item.samples, metres(item.distance_m)])} />
      <Stats items={[['Receptions in the middle and final thirds', mark.receptions], ['Received free (5 m)', mark.free], ['Free between the lines', mark.free_between_lines]]} />
      <Table caption={`${opponent.display_name} players who found space`} head={['Player', 'Free receptions', 'Between the lines']}
        rows={mark.free_players.map((item) => [name(item.player_id), item.free, item.between_lines])} />
      <Moments items={mark.moments} onShowEvent={onShowEvent} />
    </section>}
  </>;
}

const kinds: MovementKind[] = ['drop_and_sprint', 'opposite_runs', 'decoy_run', 'crisscross'];

function Movement({ report, team, name, onShowEvent }: Section) {
  const row = report.movements[team.team_id];
  if (!row) return null;
  return <section><h3>Counter-movements</h3>
    <p className="tactics-compare">Off-the-ball movements that look like one thing and do another: dropping to pull a marker out before sprinting in behind, one player dropping while a team-mate runs into the space, runs that drag a defender for someone else, and crossing runs at corners. Drew: a defender went with it. Found: the ball went to the runner or into the space within 3 s.</p>
    <Table caption={`${team.display_name} in settled possession`} head={['Movement', 'Players', 'Times', 'Drew a defender', 'Found']}
      rows={kinds.flatMap((kind) => movementsOf(report, team.team_id, kind, 2).slice(0, 4).map((item) => [movementLabel[kind], item.players.map(name).join(' + '), item.episodes, item.drew, item.found]))} />
    <Stats items={[['Corners', row.corners], ['With crisscross runs', row.crisscross_corners]]} />
    {kinds.map((kind) => movementsOf(report, team.team_id, kind, 2)[0]).filter(Boolean).map((item) => <Moments key={item!.kind} caption={`${movementLabel[item!.kind]}: ${item!.players.map(name).join(' + ')}`} items={item!.moments} onShowEvent={onShowEvent} />)}
  </section>;
}

function ThirdMan({ report, team, name, onShowEvent }: Section) {
  const row = report.third_man[team.team_id];
  if (!row) return null;
  return <section><h3>Third-man combinations</h3>
    <p className="tactics-compare">A plays to B, who sets it first time for C: three players to reach a free team-mate that A could not find directly, for example a keeper finding a free centre-back through the dropping holding midfielder.</p>
    <Stats items={[['Combinations', row.combinations], ['Direct lane blocked', `${row.lane_blocked} of ${row.tracked}`], ['Receiver free on arrival', `${row.receiver_free} of ${row.tracked}`],
      ['Ground gained', metres(row.progress_m)], ['Final third within 10 s', row.final_third_10s], ['Shot within 15 s', row.shots_15s]]} />
    <Table caption="Where" head={['Zone', 'Combinations']} rows={Object.entries(row.by_zone).map(([key, value]) => [zoneLabel[key] ?? key, value])} />
    <Table caption="Most used" head={['A', 'B (sets it)', 'C', 'Times']} rows={row.patterns.map((item) => [name(item.first), name(item.second), name(item.third), item.count])} />
    <Moments items={row.moments} onShowEvent={onShowEvent} />
  </section>;
}
