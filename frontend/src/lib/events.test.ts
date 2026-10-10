import { describe, expect, it } from 'vitest';
import { envelopeSchema, insightSchema, matchSchema, type Envelope, type Session } from './contracts';
import { casualFactCues, feedItems, involvesPlayer, percentOfMatch, playerLabel, timelineMarkers } from './events';

const match = matchSchema.parse({ match_id: 'test_match', schema_version: '1.0', provenance: 'synthetic', home: { team_id: 'harbor', display_name: 'Harbor Athletic', short_name: 'HBR', color: '#38bdf8' }, away: { team_id: 'vale', display_name: 'Vale United', short_name: 'VAL', color: '#fbbf24' }, roster: [{ player_id: 'harbor_08', team_id: 'harbor', display_name: 'Test Harbor Eight', shirt_number: 8, position: 'MID' }, { player_id: 'harbor_09', team_id: 'harbor', display_name: 'Test Harbor Nine', shirt_number: 9, position: 'FWD', role: 'ST' }, { player_id: 'vale_04', team_id: 'vale', display_name: 'Test Vale Four', shirt_number: 4, position: 'DEF' }], period_lengths_ms: [2700000, 2700000] });

let seq = 0;
function envelope(kind: string, time: number, extra: Record<string, unknown> = {}): Envelope {
  seq += 1;
  const base = { match_id: match.match_id, event_time_ms: time, period: time > 2700000 ? 2 : 1, kind, team_id: 'harbor', player_id: 'harbor_08', possession_id: 'pos_1', detail: {} };
  const payload = kind === 'PERIOD_START' || kind === 'PERIOD_END' ? { ...base, team_id: null, player_id: null, possession_id: null, ...extra } : { ...base, ...extra };
  return envelopeSchema.parse({ delivery_seq: seq, available_at_ms: time, event_id: `e${seq}`, revision: 1, operation: 'upsert', payload });
}

const kickoff = envelope('PERIOD_START', 0);
const possession = envelope('POSSESSION', 1000, { detail: { start: { x: 50, y: 50 } } });
const passTo9 = envelope('PASS', 2000, { detail: { recipient_id: 'harbor_09', completed: true, start: { x: 40, y: 50 }, end: { x: 60, y: 50 } } });
const failedTo9 = envelope('PASS', 3000, { detail: { recipient_id: 'harbor_09', completed: false, start: { x: 40, y: 50 }, end: { x: 60, y: 50 } } });
const valeTackle = envelope('TACKLE', 4000, { team_id: 'vale', player_id: 'vale_04', detail: { position: { x: 50, y: 50 }, successful: true } });
const valeGoal = envelope('SHOT', 5000, { team_id: 'vale', player_id: 'vale_04', detail: { position: { x: 90, y: 50 }, outcome: 'goal' } });
const events = [kickoff, possession, passTo9, failedTo9, valeTackle, valeGoal];

describe('player-focused event feed', () => {
  it('uses actor and completed-pass recipient semantics for involvement', () => {
    expect(involvesPlayer(passTo9, 'harbor_09')).toBe(true);
    expect(involvesPlayer(failedTo9, 'harbor_09')).toBe(false);
    expect(involvesPlayer(failedTo9, 'harbor_08')).toBe(true);
  });
  it('hides possession bookkeeping and lists newest first without a filter', () => {
    const items = feedItems(events, null);
    expect(items.map((item) => item.envelope.event_id)).toEqual([valeGoal, valeTackle, failedTo9, passTo9, kickoff].map((item) => item.event_id));
    expect(items.every((item) => !item.context)).toBe(true);
  });
  it('keeps goals and period markers visible as labelled context when filtering to a player', () => {
    const items = feedItems(events, 'harbor_09');
    expect(items.map((item) => [item.envelope.event_id, item.context])).toEqual([[valeGoal.event_id, true], [passTo9.event_id, false], [kickoff.event_id, true]]);
  });
  it('returns only context when the player has no supported events yet', () => {
    expect(feedItems([kickoff, valeTackle], 'harbor_09').map((item) => item.context)).toEqual([true]);
  });
});

const fact = (metric: string, value: number, unit: 'count' | 'percent', subject = 'harbor') => ({ fact_id: `f_${metric}_${subject}`, metric, subject_id: subject, numeric_value: value, unit, window: { start_ms: 0, end_ms: 180000 }, source_event_refs: [], derivation_version: 'metrics_v1' });
const insight = insightSchema.parse({ insight_id: 'ins_1', pattern: 'sustained_pressure', subject_ids: ['harbor'], anchor_snapshot_id: 'snap', facts: [fact('possession_share', 66.67, 'percent'), fact('shots', 1, 'count'), fact('final_third_entries', 6, 'count'), fact('shots', 0, 'count', 'vale')], evidence_quality: 'complete', observed_window: { start_ms: 120000, end_ms: 300000 }, interpretation: 'x', limitations: [], status: 'ready', supersedes_id: null, variants: {}, conditions: [], supported_player_ids: [], generation: 1, data_epoch: 1, episode_id: 'ep' });

describe('casual fact cues', () => {
  it('render only computed facts, rounding presentation values and keeping team attribution', () => {
    const cues = casualFactCues(insight, match);
    expect(cues).toEqual([
      { factId: 'f_possession_share_harbor', value: '67%', label: 'of the ball · HBR', teamId: 'harbor' },
      { factId: 'f_shots_harbor', value: '1', label: 'shot · HBR', teamId: 'harbor' },
      { factId: 'f_final_third_entries_harbor', value: '6', label: 'entries into the attacking third · HBR', teamId: 'harbor' },
    ]);
  });
});

describe('match timeline markers', () => {
  it('places observed insights and goals at their match times and omits pending insights', () => {
    const pending = { ...insight, insight_id: 'ins_2', status: 'pending' as const };
    const markers = timelineMarkers({ playhead_ms: 300000, insights: [insight, pending], events } as unknown as Session);
    expect(markers.insights).toEqual([{ kind: 'insight', id: 'ins_1', start: 120000, end: 300000, teamId: 'harbor', pattern: 'sustained_pressure', status: 'ready' }]);
    expect(markers.goals).toEqual([{ kind: 'goal', id: valeGoal.event_id, at: 5000, teamId: 'vale', playerId: 'vale_04' }]);
    expect(percentOfMatch(2700000)).toBe(50);
    expect(percentOfMatch(9e9)).toBe(100);
  });
});

describe('player positions', () => {
  it('labels players with their specific position, falling back to the broad group', () => {
    expect(playerLabel(match, 'harbor_09')).toBe('Test Harbor Nine (ST)');
    expect(playerLabel(match, 'harbor_08')).toBe('Test Harbor Eight (MID)');
    expect(playerLabel(match, 'nobody')).toBeNull();
  });
});
