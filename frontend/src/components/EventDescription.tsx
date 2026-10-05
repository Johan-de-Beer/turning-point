import type { ReactNode } from 'react';
import { Activity, ArrowRight, ArrowUpRight, Flag, Pause, Play, RotateCcw, ShieldCheck, Target } from 'lucide-react';
import type { Envelope, Match } from '../lib/contracts';
import { teamFor } from '../lib/events';
import { humanize } from '../lib/format';

export function describeEvent(envelope: Envelope, match: Match): { title: string; detail: string; icon: ReactNode } {
  const event = envelope.payload;
  if (!event) return { title: 'Event withdrawn', detail: `${envelope.event_id} · revision ${envelope.revision}`, icon: <RotateCcw size={16} /> };
  const actor = match.roster.find((player) => player.player_id === event.player_id);
  const name = actor?.display_name ?? teamFor(match, event.team_id)?.display_name ?? 'Match';
  switch (event.kind) {
    case 'SHOT': return { title: event.detail.outcome === 'goal' ? `Goal · ${name}` : `Shot · ${name}`, detail: humanize(event.detail.outcome), icon: event.detail.outcome === 'goal' ? <Flag size={16} /> : <Target size={16} /> };
    case 'PASS': return { title: `${name} → ${match.roster.find((player) => player.player_id === event.detail.recipient_id)?.display_name ?? 'teammate'}`, detail: event.detail.completed ? 'Completed pass' : 'Incomplete pass', icon: <ArrowUpRight size={16} /> };
    case 'CARRY': return { title: name, detail: 'Ball carry', icon: <ArrowRight size={16} /> };
    case 'TACKLE': return { title: name, detail: event.detail.successful ? 'Successful tackle' : 'Attempted tackle', icon: <ShieldCheck size={16} /> };
    case 'POSSESSION': return { title: `${teamFor(match, event.team_id)?.display_name ?? 'Team'} in possession`, detail: 'Possession begins', icon: <Activity size={16} /> };
    case 'STOPPAGE': return { title: 'Play stopped', detail: humanize(event.detail.reason), icon: <Pause size={16} /> };
    case 'PERIOD_START': return { title: event.period === 1 ? 'Kick-off' : 'Second half begins', detail: 'Period boundary', icon: <Play size={16} /> };
    case 'PERIOD_END': return { title: event.period === 1 ? 'Half-time' : 'Full-time', detail: 'Period boundary', icon: <Flag size={16} /> };
  }
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
