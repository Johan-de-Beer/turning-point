import type { CSSProperties, ReactNode } from 'react';
import type { Team } from '../lib/contracts';

export function Brand({ compact = false }: { compact?: boolean }) {
  return <div className={`brand ${compact ? 'brand-compact' : ''}`}>
    <div className="brand-symbol" aria-hidden="true"><span /><span /></div>
    {!compact && <div className="brand-wordmark">Turning Point</div>}
  </div>;
}

/** Flat team block in the club colour, labelled with the short name so colour is never the only cue. */
export function TeamMark({ team, size = 'medium' }: { team: Team; size?: 'small' | 'medium' | 'large' }) {
  return <span className={`team-mark mark-${size}`} style={{ '--team-color': team.color } as CSSProperties} aria-hidden="true">{team.short_name}</span>;
}

export function TeamDot({ team }: { team: Team | undefined }) {
  return <span className="team-dot" style={{ background: team?.color ?? 'var(--text-3)' }} aria-hidden="true" />;
}

export function EmptyState({ icon, title, text, compact = false }: { icon?: ReactNode; title: string; text: string; compact?: boolean }) {
  return <div className={`empty-state ${compact ? 'empty-compact' : ''}`}>
    {icon && <div className="empty-icon">{icon}</div>}
    <h3>{title}</h3>
    <p>{text}</p>
  </div>;
}
