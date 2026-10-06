import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { ChevronLeft, ChevronRight, Maximize2, Play, Waves } from 'lucide-react';
import { displayEvents, type PitchPoint } from './pitchEvents';
import { eventDuration, isObserved, PitchPlayback, sampleEvent, type PlaybackFrame } from './pitchPlayback';
import { action, AWAY_COLOR, clock, eventTitle, HOME_COLOR, player, playerName, selected, steppableRecords, type PitchSceneProps } from './pitchShared';
import './pitch.css';

// A flat top-down pitch in metres. Recorded endpoints only: one ball, the active
// actor and a completed-pass recipient, plus a faint trail of recent actions.
const LENGTH = 105, WIDTH = 68, PAD = 3;
const VIEW_W = LENGTH + PAD * 2, VIEW_H = WIDTH + PAD * 2;
const metres = (point: PitchPoint) => ({ x: point.x / 100 * LENGTH, y: point.y / 100 * WIDTH });
const placement = (point: PitchPoint): CSSProperties => {
  const m = metres(point);
  return { left: `${(m.x + PAD) / VIEW_W * 100}%`, top: `${(m.y + PAD) / VIEW_H * 100}%` };
};

function Markings({ unit }: { unit: number }) {
  const box = (x: number, depth: number, width: number) => <rect x={x} y={(WIDTH - width) / 2} width={depth} height={width} />;
  return <g className="flat-lines" fill="none" strokeWidth={1.5 * unit}>
    <rect x="0" y="0" width={LENGTH} height={WIDTH} />
    <path d={`M${LENGTH / 2} 0V${WIDTH}`} />
    <circle cx={LENGTH / 2} cy={WIDTH / 2} r="9.15" />
    {box(0, 16.5, 40.32)}{box(LENGTH - 16.5, 16.5, 40.32)}
    {box(0, 5.5, 18.32)}{box(LENGTH - 5.5, 5.5, 18.32)}
    {box(-1.5, 1.5, 7.32)}{box(LENGTH, 1.5, 7.32)}
    <path d="M16.5 26.69A9.15 9.15 0 0 1 16.5 41.31M88.5 26.69A9.15 9.15 0 0 0 88.5 41.31" />
    <g className="flat-spots">{[[LENGTH / 2, WIDTH / 2], [11, WIDTH / 2], [LENGTH - 11, WIDTH / 2]].map(([x, y]) => <circle key={x} cx={x} cy={y} r=".35" />)}</g>
  </g>;
}

export function FlatPitch(props: PitchSceneProps) {
  const current = useRef(props); current.current = props;
  const viewport = useRef<HTMLDivElement>(null), field = useRef<HTMLDivElement>(null);
  const playback = useRef<PitchPlayback | null>(null);
  playback.current ??= new PitchPlayback(props.homeTeamId, props.awayTeamId);
  const [frame, setFrame] = useState<PlaybackFrame | null>(null);
  const [motion, setMotion] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [expanded, setExpanded] = useState(false), [preview, setPreview] = useState(false);
  // SVG units per CSS pixel, so markers and labels keep a readable on-screen size at every width.
  const [unit, setUnit] = useState(VIEW_W / 900);
  const motionRef = useRef(motion); motionRef.current = motion;
  const previewToken = useRef(0), previewRunning = useRef(false);

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)'), change = () => setMotion(!query.matches);
    query.addEventListener('change', change); return () => query.removeEventListener('change', change);
  }, []);
  useEffect(() => { playback.current!.ingest(props.events, props.playheadMs, props.period, props.replayKey ?? 'stadium'); }, [props.events, props.playheadMs, props.period, props.replayKey]);
  useEffect(() => {
    const element = field.current; if (!element) return;
    const observer = new ResizeObserver(() => { if (element.clientWidth) setUnit(VIEW_W / element.clientWidth); });
    observer.observe(element); return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let animation = 0, last = 0, signature = '', inspectionKey = '', elapsed = 0, token = previewToken.current;
    const tick = (now: number) => {
      animation = requestAnimationFrame(tick); if (now - last < 32) return;
      const dt = Math.min((now - last) / 1000, .075); last = now; if (document.hidden) return;
      const p = current.current, inspected = selected(p);
      let next: PlaybackFrame | null;
      if (inspected) {
        const key = JSON.stringify([p.replayKey, inspected.event_id, inspected.revision, inspected.detail]);
        if (key !== inspectionKey) { inspectionKey = key; elapsed = eventDuration(inspected); previewRunning.current = false; setPreview(false); token = previewToken.current; }
        if (token !== previewToken.current) { token = previewToken.current; elapsed = 0; }
        if (previewRunning.current && motionRef.current) elapsed += dt;
        if (!motionRef.current) elapsed = eventDuration(inspected);
        next = sampleEvent(inspected, elapsed / eventDuration(inspected), p.homeTeamId, p.awayTeamId);
        if (next.progress >= 1 && previewRunning.current) { previewRunning.current = false; setPreview(false); }
      } else {
        inspectionKey = '';
        next = playback.current!.advance(dt, p.isPlaying || !!p.finishObservedEvents, motionRef.current, p.speed ?? 12);
      }
      const nextSignature = next ? [next.event.event_id, next.event.revision, next.progress.toFixed(3), !!inspected].join(':') : '';
      if (nextSignature !== signature) { signature = nextSignature; setFrame(next); }
    };
    animation = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animation);
  }, []);
  useEffect(() => {
    const changed = () => setExpanded(document.fullscreenElement === viewport.current);
    document.addEventListener('fullscreenchange', changed); return () => document.removeEventListener('fullscreenchange', changed);
  }, []);
  const toggleFullscreen = () => { if (document.fullscreenElement === viewport.current) void document.exitFullscreen(); else if (viewport.current?.requestFullscreen) void viewport.current.requestFullscreen().catch(() => {}); };

  const inspected = selected(props);
  const shown = frame?.event ?? null;
  const records = steppableRecords(props);
  const index = records.findIndex(event => event.event_id === (props.selectedEventId ?? shown?.event_id));
  const color = shown?.team_id === props.awayTeamId ? AWAY_COLOR : HOME_COLOR;
  const actorPoint = frame?.from && shown?.player_id ? (shown.kind === 'CARRY' ? frame.position : frame.from) : null;
  const recipientPoint = frame?.to && shown?.kind === 'PASS' && shown.detail.completed === true && shown.detail.recipient_id ? frame.to : null;
  const actor = shown ? player(shown.player_id, props) : undefined, recipient = shown ? player(shown.detail.recipient_id, props) : undefined;
  const trail = inspected ? [] : displayEvents(props.events.filter(event => isObserved(event, props.playheadMs)), props.homeTeamId, props.awayTeamId, props.period, props.playheadMs)
    .filter(item => item.event.event_id !== shown?.event_id).slice(-6);
  const period = shown?.period ?? props.period;
  const homeAttacksRight = period === 1;
  const left = homeAttacksRight ? props.homeTeamName ?? props.homeTeamId : props.awayTeamName ?? props.awayTeamId;
  const right = homeAttacksRight ? props.awayTeamName ?? props.awayTeamId : props.homeTeamName ?? props.homeTeamId;
  const marker = 11 * unit, ball = 5 * unit;
  const point = (p: PitchPoint) => metres(p);
  const select = () => { if (shown && props.onSelectEvent) props.onSelectEvent(shown.event_id); };

  return <div className={'pitch-viewport pitch-flat ' + (expanded ? 'pitch-expanded' : '')} ref={viewport} data-testid="pitch-2d" data-active-event-id={shown?.event_id ?? ''} data-playback-mode={inspected ? 'inspection' : 'live'}>
    <div className="flat-field" ref={field}>
      <svg viewBox={`${-PAD} ${-PAD} ${VIEW_W} ${VIEW_H}`} role="img" aria-label={`Top-down pitch. ${left} attack to the right, ${right} attack to the left.${shown ? ` ${clock(shown.event_time_ms)} ${action(shown)}, ${eventTitle(shown, props)}.` : ''}`}>
        <rect x={-PAD} y={-PAD} width={VIEW_W} height={VIEW_H} className="flat-grass" />
        {Array.from({ length: 10 }, (_, stripe) => <rect key={stripe} x={stripe * 10.5} y="0" width="10.5" height={WIDTH} className={stripe % 2 ? 'flat-stripe' : 'flat-stripe-alt'} />)}
        <Markings unit={unit} />
        <g className="flat-trail" aria-hidden="true">{trail.map(({ event, point: end, start, color: trailColor }) => {
          const e = metres(end), s = start ? metres(start) : null;
          return <g key={event.event_id} stroke={trailColor} fill={trailColor}>{s && <line x1={s.x} y1={s.y} x2={e.x} y2={e.y} strokeWidth={1.5 * unit} />}<circle cx={e.x} cy={e.y} r={3 * unit} /></g>;
        })}</g>
        {frame?.from && frame.to && frame.moving && <g aria-hidden="true">
          <line className="flat-route" x1={point(frame.from).x} y1={point(frame.from).y} x2={point(frame.to).x} y2={point(frame.to).y} stroke={color} strokeWidth={2 * unit} strokeDasharray={`${5 * unit} ${4 * unit}`} />
          <circle cx={point(frame.to).x} cy={point(frame.to).y} r={marker * .9} fill="none" stroke={color} strokeWidth={2 * unit} opacity=".8" />
        </g>}
        <g className="flat-players" onClick={select} aria-hidden="true">
          {recipientPoint && <g transform={`translate(${point(recipientPoint).x} ${point(recipientPoint).y})`}><circle r={marker} fill={color} stroke="#0b1220" strokeWidth={2 * unit} /><text y={4 * unit} fontSize={11 * unit}>{recipient?.shirt_number ?? ''}</text></g>}
          {actorPoint && <g transform={`translate(${point(actorPoint).x} ${point(actorPoint).y})`}><circle r={marker} fill={color} stroke="#f8fafc" strokeWidth={2 * unit} /><text y={4 * unit} fontSize={11 * unit}>{actor?.shirt_number ?? ''}</text></g>}
          {frame?.position && <circle className="flat-ball" cx={point(frame.position).x} cy={point(frame.position).y} r={ball} strokeWidth={1.5 * unit} />}
        </g>
      </svg>
      {actorPoint && actor && <span className="pitch-player-label flat-label" style={placement(actorPoint)}>{playerName(shown?.player_id, props)}</span>}
      {recipientPoint && recipient && <span className="pitch-player-label flat-label recipient" style={placement(recipientPoint)}>{recipient.display_name}</span>}
      <div className="pitch-top-label"><span className="pitch-status-dot" />{inspected ? 'Recorded event' : 'Event replay'}</div>
      <div className="pitch-view-controls">
        <button type="button" onClick={() => setMotion(!motion)} aria-pressed={motion} title="Toggle event animation"><Waves size={14} /><span>Motion {motion ? 'on' : 'off'}</span></button>
        <button type="button" onClick={toggleFullscreen} aria-label={expanded ? 'Close expanded pitch' : 'Expand pitch'} aria-pressed={expanded}><Maximize2 size={14} /></button>
      </div>
    </div>
    <div className="flat-key" aria-hidden="true"><span>{left} →</span><span>{period === 2 ? 'Second half · ends switched' : 'First half'}</span><span>← {right}</span></div>
    <div className="pitch-action flat-action" data-testid="pitch-action"><div className="pitch-action-copy"><span>{shown ? clock(shown.event_time_ms) + ' · ' + action(shown) : 'Waiting for kick-off'}</span><strong>{shown ? eventTitle(shown, props) : 'Recorded movements appear as play begins'}</strong></div><div className="pitch-event-controls">
      {props.onSelectEvent && <><button type="button" aria-label="Previous observed event" disabled={index <= 0} onClick={() => props.onSelectEvent!(records[index - 1].event_id)}><ChevronLeft size={15} /></button><button type="button" aria-label="Next observed event" disabled={index < 0 || index >= records.length - 1} onClick={() => props.onSelectEvent!(records[index + 1].event_id)}><ChevronRight size={15} /></button></>}
      {inspected && <button type="button" className="pitch-replay-event" disabled={!motion} onClick={() => { if (previewRunning.current) { previewRunning.current = false; setPreview(false); } else { previewToken.current++; previewRunning.current = true; setPreview(true); } }}><Play size={12} />{preview ? 'Pause event' : 'Replay this event'}</button>}
    </div><div className="pitch-action-progress" aria-hidden="true"><span style={{ width: `${(frame?.progress ?? 0) * 100}%` }} /></div></div>
  </div>;
}
