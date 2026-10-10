import type { ReactNode } from 'react';
import { Activity, ArrowRight, ArrowUpRight, Flag, Pause, Play, RotateCcw, ShieldCheck, Target } from 'lucide-react';
import type { Envelope, Match } from '../lib/contracts';
import { playerLabel, teamFor } from '../lib/events';
import { humanize } from '../lib/format';

export function describeEvent(envelope: Envelope, match: Match): { title: string; detail: string; icon: ReactNode } {
  const event = envelope.payload;
  if (!event) return { title: 'Event withdrawn', detail: `${envelope.event_id} · revision ${envelope.revision}`, icon: <RotateCcw size={16} /> };
  const name = playerLabel(match, event.player_id) ?? teamFor(match, event.team_id)?.display_name ?? 'Match';
  switch (event.kind) {
    case 'SHOT': return { title: event.detail.outcome === 'goal' ? `Goal · ${name}` : `Shot · ${name}`, detail: `${humanize(event.detail.outcome)}${event.detail.body_part ? ` · ${bodyPart[event.detail.body_part]}` : ''}`, icon: event.detail.outcome === 'goal' ? <Flag size={16} /> : <Target size={16} /> };
    case 'PASS': return { title: `${name} → ${playerLabel(match, event.detail.recipient_id) ?? 'teammate'}`, detail: event.detail.completed ? 'Completed pass' : 'Incomplete pass', icon: <ArrowUpRight size={16} /> };
    case 'CARRY': return { title: name, detail: 'Ball carry', icon: <ArrowRight size={16} /> };
    case 'TACKLE': return { title: name, detail: duelLabel(event.detail.successful, event.detail.contest), icon: <ShieldCheck size={16} /> };
    case 'POSSESSION': return { title: `${teamFor(match, event.team_id)?.display_name ?? 'Team'} in possession`, detail: 'Possession begins', icon: <Activity size={16} /> };
    case 'STOPPAGE': return { title: 'Play stopped', detail: humanize(event.detail.reason), icon: <Pause size={16} /> };
    case 'PERIOD_START': return { title: event.period === 1 ? 'Kick-off' : 'Second half begins', detail: 'Period boundary', icon: <Play size={16} /> };
    case 'PERIOD_END': return { title: event.period === 1 ? 'Half-time' : 'Full-time', detail: 'Period boundary', icon: <Flag size={16} /> };
  }
}

const bodyPart = { right_foot: 'right foot', left_foot: 'left foot', head: 'header' } as const;

/** The actor of a duel is always the defending player; ``successful`` means they won it. */
export function duelLabel(won: boolean, contest: 'ground' | 'aerial' | undefined): string {
  if (contest === 'aerial') return won ? 'Aerial duel won' : 'Aerial duel lost';
  return won ? 'Tackle won' : 'Tackle lost · carrier kept the ball';
}

export const patternLabel: Record<string, string> = {
  sustained_pressure: 'Sustained pressure',
  sterile_possession: 'Sterile possession',
  end_to_end: 'End-to-end play',
};

/** One-line football glossary for Casual mode; descriptions, not causal claims. */
export const patternGlossary: Record<string, string> = {
  sustained_pressure: 'One team keeps the ball high up the pitch and keeps shooting while the other barely gets a shot away.',
  sterile_possession: 'One team has plenty of the ball and passes well, but it is not turning into shots or box entries.',
  end_to_end: 'Both teams are shooting and the ball keeps changing hands, with neither side controlling possession.',
};
