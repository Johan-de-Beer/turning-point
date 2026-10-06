import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { ChevronLeft, ChevronRight, Maximize2, MoveUpRight, Play, RotateCcw, Waves } from 'lucide-react';
import { displayEvents, type PitchEvent } from './pitchEvents';
import { eventDuration, isObserved, PitchPlayback, sampleEvent, type PlaybackFrame } from './pitchPlayback';
import { buildStadium, disposeObject, fieldPosition, PITCH_BACKGROUND } from './stadiumScene';
import { action, clock, eventTitle, playerName, selected, steppableRecords, type PitchSceneProps } from './pitchShared';
import './pitch.css';
export type { PitchEvent } from './pitchEvents';
export type { PitchSceneProps } from './pitchShared';
type Runtime = { scene: THREE.Scene; camera: THREE.PerspectiveCamera; playback: PitchPlayback; resetCamera: (top: boolean) => void };
type View = { event: PitchEvent | null; inspection: boolean; complete: boolean };
function football(): THREE.Mesh {
  const canvas = document.createElement('canvas'); canvas.width = 512; canvas.height = 256;
  const c = canvas.getContext('2d')!; c.fillStyle = '#fffdf5'; c.fillRect(0, 0, 512, 256);
  for (let row = 0; row < 4; row++) for (let col = 0; col < 8; col++) {
    const x = col * 64 + (row % 2 ? 32 : 0), y = row * 70; c.beginPath();
    for (let corner = 0; corner < 5; corner++) {
      const angle = corner * Math.PI * 2 / 5 - Math.PI / 2, px = x + Math.cos(angle) * 15, py = y + Math.sin(angle) * 15;
      if (!corner) c.moveTo(px, py); else c.lineTo(px, py);
    }
    c.closePath(); c.fillStyle = '#15232a'; c.fill(); c.strokeStyle = '#8b9696'; c.stroke();
  }
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
  return new THREE.Mesh(new THREE.SphereGeometry(.9, 24, 16), new THREE.MeshStandardMaterial({ map: texture, roughness: .65, emissive: '#fffdf5', emissiveIntensity: .15 }));
}
function actorMarker(): THREE.Group {
  const group = new THREE.Group();
  const disc = new THREE.Mesh(new THREE.RingGeometry(1.4, 1.9, 32), new THREE.MeshBasicMaterial({ color: '#38bdf8', side: THREE.DoubleSide }));
  disc.name = 'disc'; disc.rotation.x = -Math.PI / 2; disc.position.y = .18; group.add(disc);
  const body = new THREE.Mesh(new THREE.CylinderGeometry(.7, .95, 1.5, 12), new THREE.MeshStandardMaterial({ color: '#38bdf8', roughness: .8 }));
  body.name = 'shirt'; body.position.y = 1.35; group.add(body);
  const head = new THREE.Mesh(new THREE.SphereGeometry(.46, 12, 8), new THREE.MeshStandardMaterial({ color: '#e9c7a4', roughness: 1 }));
  head.position.y = 2.55; group.add(head);
  const legs = new THREE.Mesh(new THREE.CylinderGeometry(.48, .48, .8, 8), new THREE.MeshStandardMaterial({ color: '#132630' }));
  legs.position.y = .5; group.add(legs); return group;
}
export function PitchScene(props: PitchSceneProps) {
  const host = useRef<HTMLDivElement>(null), viewport = useRef<HTMLDivElement>(null), runtime = useRef<Runtime | null>(null);
  const actorLabel = useRef<HTMLSpanElement>(null), recipientLabel = useRef<HTMLSpanElement>(null), progressBar = useRef<HTMLSpanElement>(null);
  const current = useRef(props); current.current = props;
  const [webgl, setWebgl] = useState(false), [topDown, setTopDown] = useState(false), [assetReady, setAssetReady] = useState(false), [expanded, setExpanded] = useState(false);
  const [motion, setMotion] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [view, setView] = useState<View>({ event: null, inspection: false, complete: false }), [preview, setPreview] = useState(false);
  const settings = useRef({ motion, topDown }); settings.current = { motion, topDown };
  const previewToken = useRef(0), previewRunning = useRef(false);
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)'), change = () => setMotion(!query.matches);
    query.addEventListener('change', change); return () => query.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    const container = host.current; if (!container) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' }); } catch { return; }
    let disposed = false, visible = true, previousView = '', visualEvent = '', inspectionKey = '', inspectionElapsed = 0, token = 0;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5)); renderer.setClearColor(PITCH_BACKGROUND, 1);
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.15;
    renderer.domElement.setAttribute('aria-hidden', 'true'); container.appendChild(renderer.domElement);
    const scene = new THREE.Scene(); scene.fog = new THREE.Fog(PITCH_BACKGROUND, 260, 520);
    const camera = new THREE.PerspectiveCamera(38, 2, .3, 700), controls = new OrbitControls(camera, renderer.domElement);
    renderer.domElement.style.touchAction = 'pan-y'; controls.target.set(0, 1, 0); controls.dampingFactor = .12;
    controls.enablePan = false; controls.enableZoom = false; controls.minPolarAngle = .06; controls.maxPolarAngle = 1.05; controls.rotateSpeed = .4;
    controls.touches.ONE = THREE.TOUCH.PAN; controls.touches.TWO = THREE.TOUCH.DOLLY_ROTATE;
    const resetCamera = (top: boolean) => {
      const tangent = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
      const distance = Math.max(168 / (2 * tangent * camera.aspect), (top ? 126 : 116) / (2 * tangent)) * 1.04;
      camera.position.set(top ? 0 : distance * .16, top ? distance : distance * .78, top ? .1 : distance * .61);
      controls.target.set(0, 1, 0); controls.update();
    };
    const playback = new PitchPlayback(current.current.homeTeamId, current.current.awayTeamId);
    playback.ingest(current.current.events, current.current.playheadMs, current.current.period, current.current.replayKey ?? 'stadium');
    const ball = football(), actor = actorMarker(), recipient = actorMarker(); ball.castShadow = true;
    const shadow = new THREE.Mesh(new THREE.CircleGeometry(1.15, 24), new THREE.MeshBasicMaterial({ color: '#071b13', opacity: .4, transparent: true, depthWrite: false }));
    shadow.rotation.x = -Math.PI / 2;
    const route = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: '#38bdf8', transparent: true, opacity: .45 }));
    const target = new THREE.Mesh(new THREE.RingGeometry(1.3, 1.65, 32), new THREE.MeshBasicMaterial({ color: '#38bdf8', side: THREE.DoubleSide, transparent: true, opacity: .75 }));
    target.rotation.x = -Math.PI / 2;
    const interactive = [ball, actor, recipient, target, route]; scene.add(...interactive, shadow);
    for (const object of [...interactive, shadow]) object.visible = false;
    runtime.current = { scene, camera, playback, resetCamera };
    buildStadium(scene, () => !disposed, loaded => setAssetReady(loaded));
    const resize = () => {
      const w = container.clientWidth, h = container.clientHeight; if (!w || !h) return;
      camera.aspect = w / h; camera.updateProjectionMatrix(); resetCamera(settings.current.topDown); renderer.setSize(w, h);
    };
    const observer = new ResizeObserver(resize); observer.observe(container); resize();
    const intersection = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? true; }); intersection.observe(container);
    const ray = new THREE.Raycaster(); let pointerStart = { x: 0, y: 0 };
    const down = (event: PointerEvent) => { pointerStart = { x: event.clientX, y: event.clientY }; };
    const selectEvent = (event: PointerEvent) => {
      if (!current.current.onSelectEvent || Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 5) return;
      const bounds = container.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2((event.clientX - bounds.left) / bounds.width * 2 - 1, -(event.clientY - bounds.top) / bounds.height * 2 + 1), camera);
      const hit = ray.intersectObjects(interactive.filter(object => object.visible), true).find(item => item.object.userData.eventId);
      if (hit) current.current.onSelectEvent(hit.object.userData.eventId as string);
    };
    container.addEventListener('pointerdown', down); container.addEventListener('pointerup', selectEvent);
    const placeLabel = (element: HTMLSpanElement | null, marker: THREE.Group, label: string, offset: number) => {
      if (!element) return; element.hidden = !marker.visible || !label; element.textContent = label;
      if (!element.hidden) {
        const point = marker.position.clone(); point.y = 3.5; point.project(camera);
        element.style.left = ((point.x + 1) * container.clientWidth / 2) + 'px';
        element.style.top = ((1 - point.y) * container.clientHeight / 2 + offset) + 'px';
      }
    };
    let animation = 0, lastFrame = 0;
    const render = (now: number) => {
      if (disposed) return; animation = requestAnimationFrame(render); if (now - lastFrame < 32) return;
      const dt = Math.min((now - lastFrame) / 1000, .075); lastFrame = now; if (!visible || document.hidden) return;
      const p = current.current, inspected = selected(p), ctx = runtime.current; if (!ctx) return;
      let frame: PlaybackFrame | null;
      if (inspected) {
        const key = JSON.stringify([p.replayKey, inspected.event_id, inspected.revision, inspected.detail]);
        if (key !== inspectionKey) { inspectionKey = key; inspectionElapsed = eventDuration(inspected); previewRunning.current = false; setPreview(false); token = previewToken.current; }
        if (token !== previewToken.current) { token = previewToken.current; inspectionElapsed = 0; }
        if (previewRunning.current && settings.current.motion) inspectionElapsed += dt;
        if (!settings.current.motion) inspectionElapsed = eventDuration(inspected);
        frame = sampleEvent(inspected, inspectionElapsed / eventDuration(inspected), p.homeTeamId, p.awayTeamId);
        if (frame.progress >= 1 && previewRunning.current) { previewRunning.current = false; setPreview(false); }
      } else {
        frame = ctx.playback.advance(dt, p.isPlaying || !!p.finishObservedEvents, settings.current.motion, p.speed ?? 12);
      }
      const eventKey = frame ? JSON.stringify([frame.event.event_id, frame.event.revision, frame.event.detail, !!inspected]) : '';
      const color = frame?.event.team_id === p.awayTeamId ? '#fbbf24' : '#38bdf8', eventChanged = eventKey !== visualEvent;
      if (eventChanged) {
        visualEvent = eventKey;
        if (frame?.from && frame.to) {
          route.geometry.dispose(); route.geometry = new THREE.BufferGeometry().setFromPoints([fieldPosition(frame.from, .2), fieldPosition(frame.to, .2)]);
          (route.material as THREE.LineBasicMaterial).color.set(color); (target.material as THREE.MeshBasicMaterial).color.set(color);
          target.position.copy(fieldPosition(frame.to, .2));
          for (const marker of [actor, recipient]) for (const name of ['disc', 'shirt']) ((marker.getObjectByName(name) as THREE.Mesh).material as THREE.MeshBasicMaterial).color.set(color);
        }
        for (const object of interactive) object.traverse(child => { child.userData.eventId = frame?.event.event_id ?? ''; });
      }
      const old = ball.position.clone();
      ball.visible = !!frame?.position; shadow.visible = ball.visible;
      actor.visible = !!frame?.from && !!frame.event.player_id;
      recipient.visible = !!frame?.to && frame.event.kind === 'PASS' && frame.event.detail.completed === true && !!frame.event.detail.recipient_id;
      route.visible = !!frame?.moving; target.visible = !!frame?.moving;
      if (frame?.position) {
        const height = frame.moving && frame.event.kind !== 'CARRY' ? Math.sin(Math.PI * frame.progress) * (frame.event.kind === 'SHOT' ? 2.8 : 1.8) : 0;
        ball.position.copy(fieldPosition(frame.position, .95 + height));
        if (!eventChanged && frame.progress > 0 && frame.progress < 1) { ball.rotation.z -= (ball.position.x - old.x) / .9; ball.rotation.x += (ball.position.z - old.z) / .9; }
        shadow.position.copy(fieldPosition(frame.position, .13));
      }
      if (frame?.from && frame.to) { actor.position.copy(fieldPosition(frame.event.kind === 'CARRY' ? frame.position! : frame.from, 0)); recipient.position.copy(fieldPosition(frame.to, 0)); }
      controls.autoRotate = settings.current.motion && !settings.current.topDown && p.events.length === 0; controls.autoRotateSpeed = .18;
      controls.enableDamping = settings.current.motion && (p.isPlaying || p.events.length === 0);
      if (controls.autoRotate || controls.enableDamping) controls.update(dt);
      placeLabel(actorLabel.current, actor, frame ? playerName(frame.event.player_id, p) : '', -10);
      placeLabel(recipientLabel.current, recipient, frame ? playerName(frame.event.detail.recipient_id, p) : '', 12);
      if (viewport.current) {
        const from = frame?.from ? fieldPosition(frame.from) : null, to = frame?.to ? fieldPosition(frame.to) : null;
        const values: Record<string, string | number> = {
          'active-event-id': frame?.event.event_id ?? '', 'active-event-kind': frame?.event.kind ?? '', 'active-event-team': frame?.event.team_id ?? '',
          'active-event-time': frame?.event.event_time_ms ?? '', 'active-event-period': frame?.event.period ?? '', 'active-event-revision': frame?.event.revision ?? 1, 'replay-key': p.replayKey ?? 'stadium',
          'observed-cutoff-ms': p.playheadMs, 'observed-period': p.period, 'ball-x': ball.position.x.toFixed(6), 'ball-z': ball.position.z.toFixed(6),
          'ball-visible': String(ball.visible), 'animation-progress': frame?.progress.toFixed(6) ?? '',
          'route-start-x': from?.x.toFixed(6) ?? '', 'route-start-z': from?.z.toFixed(6) ?? '', 'route-end-x': to?.x.toFixed(6) ?? '', 'route-end-z': to?.z.toFixed(6) ?? '',
          'queued-events': ctx.playback.queuedCount, 'played-count': ctx.playback.completedCount, 'last-completed-event-id': ctx.playback.lastCompletedId, 'playback-mode': inspected ? 'inspection' : 'live',
        };
        for (const [key, value] of Object.entries(values)) viewport.current.setAttribute('data-' + key, String(value));
      }
      if (progressBar.current) progressBar.current.style.width = ((frame?.progress ?? 0) * 100) + '%';
      const nextView = eventKey + ':' + (frame?.progress === 1);
      if (nextView !== previousView) { previousView = nextView; setView({ event: frame?.event ?? null, inspection: !!inspected, complete: frame?.progress === 1 }); }
      renderer.render(scene, camera);
    };
    animation = requestAnimationFrame(render); setWebgl(true);
    const lost = (event: Event) => { event.preventDefault(); setWebgl(false); };
    renderer.domElement.addEventListener('webglcontextlost', lost);
    return () => {
      disposed = true; cancelAnimationFrame(animation); observer.disconnect(); intersection.disconnect(); controls.dispose();
      container.removeEventListener('pointerdown', down); container.removeEventListener('pointerup', selectEvent); renderer.domElement.removeEventListener('webglcontextlost', lost);
      disposeObject(scene); renderer.dispose(); renderer.domElement.remove(); runtime.current = null;
    };
  }, []);
  useEffect(() => { runtime.current?.playback.ingest(props.events, props.playheadMs, props.period, props.replayKey ?? 'stadium'); }, [props.events, props.playheadMs, props.period, props.replayKey, webgl]);
  useEffect(() => { runtime.current?.resetCamera(topDown); }, [topDown]);
  useEffect(() => {
    const changed = () => setExpanded(document.fullscreenElement === viewport.current);
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape' && document.fullscreenElement === viewport.current) { event.preventDefault(); void document.exitFullscreen().catch(() => {}); } };
    document.addEventListener('fullscreenchange', changed); document.addEventListener('keydown', close);
    return () => { document.removeEventListener('fullscreenchange', changed); document.removeEventListener('keydown', close); };
  }, []);
  const toggleFullscreen = () => { if (document.fullscreenElement === viewport.current) void document.exitFullscreen(); else if (viewport.current?.requestFullscreen) void viewport.current.requestFullscreen().catch(() => {}); };
  const records = steppableRecords(props);
  const index = records.findIndex(event => event.event_id === (props.selectedEventId ?? view.event?.event_id));
  const inspectedRecord = selected(props);
  const fallback = displayEvents(inspectedRecord ? [inspectedRecord] : props.events.filter(event => isObserved(event, props.playheadMs)), props.homeTeamId, props.awayTeamId, props.period, props.playheadMs, props.selectedEventId);
  const shown = webgl ? view.event : selected(props) ?? fallback.at(-1)?.event ?? null;
  return <div className={'pitch-viewport ' + (expanded ? 'pitch-expanded' : '')} ref={viewport} data-testid="pitch-scene" data-stadium-loaded={assetReady}>
    {!webgl && <svg className="pitch-fallback" viewBox="0 0 120 80" role="img" aria-label="Football pitch with recorded event endpoints"><rect x="5" y="5" width="110" height="70" fill="#26713f" /><g stroke="#d7e7cf" strokeWidth=".35" fill="none"><rect x="8" y="8" width="104" height="64" /><path d="M60 8v64" /><circle cx="60" cy="40" r="9" /></g>{fallback.map(({ event, point, start, color }) => <g key={event.event_id} fill={color} stroke={color}>{start && <line x1={8 + start.x * 1.04} y1={8 + start.y * .64} x2={8 + point.x * 1.04} y2={8 + point.y * .64} strokeWidth=".6" />}<circle cx={8 + point.x * 1.04} cy={8 + point.y * .64} r="1.2" /></g>)}</svg>}
    <div className={'pitch-canvas ' + (webgl ? 'is-ready' : '')} ref={host} /><div className="pitch-vignette" aria-hidden="true" />
    <span className="pitch-player-label" ref={actorLabel} hidden /><span className="pitch-player-label recipient" ref={recipientLabel} hidden />
    <div className="pitch-top-label"><span className="pitch-status-dot" />{view.inspection ? 'Recorded event' : 'Event replay'}</div>
    <div className="pitch-view-controls">
      <button type="button" onClick={() => setTopDown(!topDown)} aria-pressed={topDown} title="Change pitch camera"><MoveUpRight size={14} /><span>{topDown ? 'Broadcast' : 'Top view'}</span></button>
      <button type="button" onClick={() => setMotion(!motion)} aria-pressed={motion} title="Toggle event animation"><Waves size={14} /><span>Motion {motion ? 'on' : 'off'}</span></button>
      <button type="button" onClick={() => runtime.current?.resetCamera(topDown)} aria-label="Reset pitch camera" title="Reset pitch camera"><RotateCcw size={14} /></button>
      <button type="button" onClick={toggleFullscreen} aria-label={expanded ? 'Close expanded pitch' : 'Expand pitch'} aria-pressed={expanded}><Maximize2 size={14} /></button>
    </div>
    <div className="pitch-bottom-label"><span><i className="pitch-team-dot home" />{props.homeTeamName ?? props.homeTeamId}<i className="pitch-team-dot away" />{props.awayTeamName ?? props.awayTeamId}</span><span>{(shown?.period ?? props.period) === 2 ? 'Second half · ends switched' : 'First half'}<b>Drag to explore</b></span></div>
    <div className="pitch-action" data-testid="pitch-action"><div className="pitch-action-copy"><span>{shown ? clock(shown.event_time_ms) + ' · ' + action(shown) : 'Waiting for kick-off'}</span><strong>{shown ? eventTitle(shown, props) : 'Recorded movements appear as play begins'}</strong></div><div className="pitch-event-controls">
      {props.onSelectEvent && <><button type="button" aria-label="Previous observed event" disabled={index <= 0} onClick={() => props.onSelectEvent!(records[index - 1].event_id)}><ChevronLeft size={15} /></button><button type="button" aria-label="Next observed event" disabled={index < 0 || index >= records.length - 1} onClick={() => props.onSelectEvent!(records[index + 1].event_id)}><ChevronRight size={15} /></button></>}
      {view.inspection && <button type="button" className="pitch-replay-event" disabled={!motion} onClick={() => { if (previewRunning.current) { previewRunning.current = false; setPreview(false); } else { previewToken.current++; previewRunning.current = true; setPreview(true); } }}><Play size={12} />{preview ? 'Pause event' : 'Replay this event'}</button>}
    </div><div className="pitch-action-progress" aria-hidden="true"><span ref={progressBar} /></div></div>
  </div>;
}
