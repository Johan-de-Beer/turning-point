import type { PitchEvent } from './pitchEvents';
import { isObserved } from './pitchPlayback';

// Shared by the 2D pitch and the WebGL stadium. Keep this module free of three.js
// so the default flat view never pulls the stadium chunk into the main bundle.
export type PitchPlayer = { player_id: string; display_name: string; shirt_number: number; team_id: string };
export interface PitchSceneProps {
  events: readonly PitchEvent[]; homeTeamId: string; awayTeamId: string;
  homeTeamName?: string; awayTeamName?: string; players?: readonly PitchPlayer[];
  period: number; playheadMs: number; isPlaying: boolean; finishObservedEvents?: boolean; speed?: 1 | 12 | 60; replayKey?: string;
  selectedEventId?: string | null; selectedEvent?: PitchEvent | null; onSelectEvent?: (id: string) => void;
}

export const HOME_COLOR = '#38bdf8';
export const AWAY_COLOR = '#fbbf24';

export const clock = (ms: number) => Math.floor(ms / 60000).toString().padStart(2, '0') + ':' + Math.floor(ms / 1000 % 60).toString().padStart(2, '0');

export function action(event: PitchEvent): string {
  if (event.kind === 'PASS') return event.detail.completed ? 'Completed pass' : 'Incomplete pass';
  if (event.kind === 'CARRY') return 'Ball carry';
  if (event.kind === 'SHOT') return event.detail.outcome === 'goal' ? 'Goal' : 'Shot · ' + String(event.detail.outcome).replace('_', ' ');
  if (event.kind === 'POSSESSION') return 'Possession';
  if (event.kind === 'TACKLE') return event.detail.successful ? 'Successful tackle' : 'Tackle attempt';
  if (event.kind === 'STOPPAGE') return 'Play stopped · ' + String(event.detail.reason).replace('_', ' ');
  if (event.kind === 'PERIOD_END') return event.period === 1 ? 'Half-time' : 'Full-time';
  return event.period === 1 ? 'Kick-off' : 'Second-half kick-off';
}

export const player = (id: unknown, props: PitchSceneProps) => props.players?.find(item => item.player_id === id);
export const playerName = (id: unknown, props: PitchSceneProps) => player(id, props)?.display_name ?? '';

export function eventTitle(event: PitchEvent, props: PitchSceneProps): string {
  const actor = playerName(event.player_id, props) || (event.team_id === props.homeTeamId ? props.homeTeamName : props.awayTeamName) || event.team_id || 'Match';
  const recipient = playerName(event.detail.recipient_id, props);
  return event.kind === 'PASS' && recipient ? actor + ' → ' + recipient : actor;
}

/** The highlighted historic record, only once it is inside the observed cutoff. */
export function selected(props: PitchSceneProps): PitchEvent | null {
  const event = props.selectedEventId ? props.selectedEvent ?? props.events.find(record => record.event_id === props.selectedEventId) : null;
  return event && event.event_id === props.selectedEventId && isObserved(event, props.playheadMs) ? event : null;
}

/** Observed on-ball records that the previous/next controls step through. */
export const steppableRecords = (props: PitchSceneProps) => props.events.filter(event => isObserved(event, props.playheadMs) && ['PASS', 'CARRY', 'SHOT', 'TACKLE', 'POSSESSION'].includes(event.kind));
