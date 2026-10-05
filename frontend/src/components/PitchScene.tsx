import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Maximize2, MoveUpRight, RotateCcw, Waves } from 'lucide-react';
import { displayEvents, type DisplayEvent, type PitchEvent } from './pitchEvents';
import { buildStadium, disposeObject, fieldPosition, glowTexture, PITCH_BACKGROUND } from './stadiumScene';
import './pitch.css';

export type { PitchEvent } from './pitchEvents';
export interface PitchSceneProps {
  events: readonly PitchEvent[];
  homeTeamId: string;
  awayTeamId: string;
  period: number;
  playheadMs: number;
  isPlaying: boolean;
  selectedEventId?: string | null;
  onSelectEvent?: (id: string) => void;
}

type Glyph = { root: THREE.Group; ring: THREE.Mesh; ripple: THREE.Mesh; path: THREE.Mesh | null; curve: THREE.QuadraticBezierCurve3 | null; comet: THREE.Sprite | null; glow: THREE.Sprite; age: number; event: PitchEvent };
type SceneRuntime = { scene: THREE.Scene; renderer: THREE.WebGLRenderer; camera: THREE.PerspectiveCamera; controls: OrbitControls; events: THREE.Group; glyphs: Glyph[]; resetCamera: (top: boolean) => void; };
const clock = (ms: number) => `${Math.floor(ms / 60000).toString().padStart(2, '0')}:${Math.floor(ms / 1000 % 60).toString().padStart(2, '0')}`;
const eventLabel = (event: PitchEvent) => event.kind === 'SHOT' ? (event.detail.outcome === 'goal' ? 'Goal' : 'Shot') : event.kind === 'PASS' ? (event.detail.completed ? 'Completed pass' : 'Incomplete pass') : event.kind === 'CARRY' ? 'Ball carry' : event.kind.toLowerCase();

/** Animate a diagram revealing a known event, never a fabricated player or tracking trajectory. */
function createGlyph({ event, point, start, color }: DisplayEvent, selected: boolean): Glyph {
  const root = new THREE.Group(), pos = fieldPosition(point), isShot = event.kind === 'SHOT';
  const ringMaterial = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: .85, side: THREE.DoubleSide, depthWrite: false });
  const ring = new THREE.Mesh(new THREE.RingGeometry(isShot ? 1.05 : .67, isShot ? 1.5 : 1.02, 48), ringMaterial);
  ring.rotation.x = -Math.PI/2; ring.position.copy(pos); root.add(ring);
  const ripple = new THREE.Mesh(new THREE.RingGeometry(.95, 1.05, 48), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: .4, side: THREE.DoubleSide, depthWrite: false }));
  ripple.rotation.x = -Math.PI/2; ripple.position.copy(pos).y = .15; root.add(ripple);
  const light = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color, transparent: true, opacity: .5, depthWrite: false, blending: THREE.AdditiveBlending }));
  light.position.copy(pos).y = .7; light.scale.set(isShot ? 9 : 5, isShot ? 9 : 5, 1); root.add(light);
  const bead = new THREE.Mesh(new THREE.SphereGeometry(isShot ? .46 : .3, 14, 10), new THREE.MeshBasicMaterial({ color: '#f7f8f0' })); bead.position.copy(pos).y = .37; root.add(bead);
  let path: THREE.Mesh | null = null, curve: THREE.QuadraticBezierCurve3 | null = null, comet: THREE.Sprite | null = null;
  if (start && (event.kind === 'PASS' || event.kind === 'CARRY')) {
    const from = fieldPosition(start, .25), to = fieldPosition(point, .25), middle = from.clone().lerp(to, .5);
    middle.y = event.kind === 'CARRY' ? .3 : Math.min(10, from.distanceTo(to)*.19);
    curve = new THREE.QuadraticBezierCurve3(from, middle, to);
    path = new THREE.Mesh(new THREE.TubeGeometry(curve, 48, event.kind === 'PASS' ? .13 : .1, 5, false), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: .8, depthWrite: false })); root.add(path);
    const direction = to.clone().sub(curve.getPoint(.94)).normalize();
    const arrow = new THREE.Mesh(new THREE.ConeGeometry(.55, 1.8, 8), new THREE.MeshBasicMaterial({ color }));
    arrow.position.copy(to).addScaledVector(direction, -.7); arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction); root.add(arrow);
    const source = new THREE.Mesh(new THREE.RingGeometry(.35, .55, 20), ringMaterial); source.rotation.x = -Math.PI/2; source.position.copy(from); root.add(source);
    // A light reveals the recorded arrow; it is a diagram effect, not a ball-position estimate.
    comet = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color: '#effff8', transparent: true, opacity: .8, depthWrite: false, blending: THREE.AdditiveBlending })); comet.scale.set(3.8,3.8,1); root.add(comet);
  }
  if (isShot) {
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(.06, .3, selected ? 8 : 5, 12, 1, true), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: .5, depthWrite: false, side: THREE.DoubleSide }));
    beam.position.copy(pos).y = selected ? 4 : 2.5; root.add(beam);
    const target = new THREE.Mesh(new THREE.RingGeometry(2.15, 2.23, 48), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: .45, side: THREE.DoubleSide, depthWrite: false })); target.rotation.x = -Math.PI/2; target.position.copy(pos).y=.16; root.add(target);
  }
  root.traverse(object => { object.userData.eventId = event.event_id; });
  return { root, ring, ripple, path, curve, comet, glow: light, age: 0, event };
}

function PitchFallback({ markers }: { markers: DisplayEvent[] }) {
  return <svg className="pitch-fallback" viewBox="0 0 120 80" role="img" aria-label="Schematic football pitch with observed event markers">
    <defs><pattern id="pitch-turf" width="12" height="80" patternUnits="userSpaceOnUse"><rect width="6" height="80" fill="#26713f"/><rect x="6" width="6" height="80" fill="#2d7a46"/></pattern></defs>
    <rect x="5" y="5" width="110" height="70" rx="1" fill="url(#pitch-turf)"/>
    <g stroke="#d7e7cf" opacity=".8" strokeWidth=".35" fill="none"><rect x="8" y="8" width="104" height="64"/><path d="M60 8v64"/><circle cx="60" cy="40" r="9"/><path d="M8 21h16v38H8M112 21H96v38h16M8 31h5v18H8M112 31h-5v18h5"/></g>
    {markers.map(({ event, point, start, color }) => <g key={event.event_id} stroke={color} fill={color}>{start && <path fill="none" strokeWidth=".6" d={`M${8+start.x*1.04},${8+start.y*.64} Q${8+(start.x+point.x)*.52},${8+(start.y+point.y)*.32-4} ${8+point.x*1.04},${8+point.y*.64}`}/>}<circle cx={8+point.x*1.04} cy={8+point.y*.64} r={event.kind==='SHOT'?1.8:1}/></g>)}
  </svg>;
}

export function PitchScene(props: PitchSceneProps) {
  const host = useRef<HTMLDivElement>(null), viewport = useRef<HTMLDivElement>(null), current = useRef(props), runtime = useRef<SceneRuntime | null>(null);
  const [webgl, setWebgl] = useState(false), [topDown, setTopDown] = useState(false), [assetReady, setAssetReady] = useState(false), [expanded, setExpanded] = useState(false);
  const [motion, setMotion] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const settings = useRef({ motion, topDown }); settings.current = { motion, topDown }; current.current = props;
  const markerData = useMemo(() => displayEvents(props.events, props.homeTeamId, props.awayTeamId, props.period, props.playheadMs, props.selectedEventId), [props.events, props.homeTeamId, props.awayTeamId, props.period, props.playheadMs, props.selectedEventId]);
  // Polling does not continually rebuild geometry or restart arrival animations.
  const markerKey = JSON.stringify(markerData.map(m => [m.event.event_id, m.event.kind, m.point, m.start, m.event.detail, m.color]));
  const markers = useMemo(() => markerData, [markerKey]);

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const change = () => setMotion(!query.matches); query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, []);

  useEffect(() => {
    const container = host.current; if (!container) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' }); } catch { return; }
    let disposed = false, visible = true;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5)); renderer.setClearColor(PITCH_BACKGROUND, 1);
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.15;
    renderer.domElement.setAttribute('aria-hidden', 'true'); renderer.domElement.style.touchAction = 'pan-y'; container.appendChild(renderer.domElement);
    const scene = new THREE.Scene(); scene.fog = new THREE.Fog(PITCH_BACKGROUND, 260, 520);
    const camera = new THREE.PerspectiveCamera(38, 2, .3, 700); camera.position.set(0, 126, 136);
    const controls = new OrbitControls(camera, renderer.domElement);
    renderer.domElement.style.touchAction = 'pan-y';
    controls.target.set(0, 1, 0); controls.enableDamping = true; controls.dampingFactor = .12; controls.enablePan = false; controls.enableZoom = false;
    controls.minPolarAngle = .06; controls.maxPolarAngle = 1.05; controls.rotateSpeed = .4;
    controls.touches.ONE = THREE.TOUCH.PAN; controls.touches.TWO = THREE.TOUCH.DOLLY_ROTATE;
    const events = new THREE.Group(); scene.add(events);
    const resetCamera = (top: boolean) => {
      const tangent = Math.tan(THREE.MathUtils.degToRad(camera.fov/2));
      const distance = Math.max(168/(2*tangent*camera.aspect), (top?126:116)/(2*tangent))*1.04;
      if (top) camera.position.set(0, distance, .1);
      else camera.position.set(distance*.16, distance*.78, distance*.61);
      controls.target.set(0, 1, 0); controls.update();
    };
    runtime.current = { scene, renderer, camera, controls, events, glyphs: [], resetCamera };
    buildStadium(scene, () => !disposed, loaded => { setAssetReady(loaded); });
    const resize = () => { const w = container.clientWidth, h = container.clientHeight; if (!w || !h) return; camera.aspect=w/h; camera.updateProjectionMatrix(); resetCamera(settings.current.topDown); renderer.setSize(w,h); };
    const observer = new ResizeObserver(resize); observer.observe(container); resize();
    const intersection = new IntersectionObserver(entries => { visible=entries[0]?.isIntersecting??true; }); intersection.observe(container);
    const ray = new THREE.Raycaster(); let pointerStart = { x: 0, y: 0 };
    const down = (e: PointerEvent) => { pointerStart = { x:e.clientX, y:e.clientY }; };
    const select = (e: PointerEvent) => {
      if (!current.current.onSelectEvent || Math.hypot(e.clientX-pointerStart.x,e.clientY-pointerStart.y)>5) return;
      const bounds=container.getBoundingClientRect(); ray.setFromCamera(new THREE.Vector2((e.clientX-bounds.left)/bounds.width*2-1,-(e.clientY-bounds.top)/bounds.height*2+1),camera);
      const hit=ray.intersectObjects(events.children,true).find(h=>h.object.userData.eventId);
      if(hit) current.current.onSelectEvent(hit.object.userData.eventId as string);
    };
    container.addEventListener('pointerdown',down); container.addEventListener('pointerup',select);
    let frame=0,lastFrame=0,visualClock=0;
    const render=(now:number)=>{
      if(disposed)return; frame=requestAnimationFrame(render); if(now-lastFrame<32)return;
      const dt=Math.min((now-lastFrame)/1000,.06); lastFrame=now;
      if (!visible || document.hidden) return;
      const animated=settings.current.motion && current.current.isPlaying;
      if(animated) visualClock+=dt;
      const context=runtime.current; if(!context)return;
      for(const glyph of context.glyphs){
        if(animated)glyph.age+=dt;
        const reveal=settings.current.motion ? Math.min(1,glyph.age/.52) : 1;
        const historical=current.current.selectedEventId!=null;
        const age=Math.max(0,current.current.playheadMs-glyph.event.event_time_ms);
        const opacity=historical?1:Math.max(.24,1-age/110000);
        (glyph.ring.material as THREE.MeshBasicMaterial).opacity=opacity;
        (glyph.glow.material as THREE.SpriteMaterial).opacity=opacity*(.25+(animated?Math.sin(visualClock*2.5)*.08:0));
        glyph.ring.scale.setScalar(historical?1.25:1);
        if(glyph.path){
          const indexCount=glyph.path.geometry.index?.count??0;
          glyph.path.geometry.setDrawRange(0, Math.floor(indexCount*(current.current.isPlaying?reveal:1)/30)*30);
          (glyph.path.material as THREE.MeshBasicMaterial).opacity=opacity*.9;
        }
        if(glyph.comet&&glyph.curve){glyph.comet.visible=animated&&reveal<1;glyph.comet.position.copy(glyph.curve.getPoint(reveal));}
        const rippleAge=glyph.age%1.7;
        glyph.ripple.visible=animated&&glyph.age<3.4;
        glyph.ripple.scale.setScalar(1+rippleAge*3);
        (glyph.ripple.material as THREE.MeshBasicMaterial).opacity=Math.max(0,.45*(1-rippleAge/1.7))*opacity;
      }
      controls.autoRotate=settings.current.motion&&!settings.current.topDown&&context.glyphs.length===0&&current.current.events.length===0;
      controls.autoRotateSpeed=.18;
      controls.enableDamping=settings.current.motion&&(current.current.isPlaying||current.current.events.length===0);
      // Pointer and reset handlers update the camera directly. Avoid recomputing
      // its matrices on frozen frames, which can jitter antialiased shadow edges.
      if(controls.autoRotate||controls.enableDamping)controls.update(dt);
      renderer.render(scene,camera);
    };
    frame=requestAnimationFrame(render); setWebgl(true);
    const lost=(e:Event)=>{e.preventDefault();setWebgl(false);};
    renderer.domElement.addEventListener('webglcontextlost',lost);
    return()=>{disposed=true;cancelAnimationFrame(frame);observer.disconnect();intersection.disconnect();controls.dispose();container.removeEventListener('pointerdown',down);container.removeEventListener('pointerup',select);renderer.domElement.removeEventListener('webglcontextlost',lost);disposeObject(scene);renderer.dispose();runtime.current=null;renderer.domElement.remove();};
  }, []);

  useEffect(() => {
    const context=runtime.current;if(!context)return;
    const existing=new Map(context.glyphs.map(g=>[g.event.event_id,g]));
    while(context.events.children.length){const child=context.events.children[0];context.events.remove(child);disposeObject(child);}
    context.glyphs=markers.map(marker=>{
      const glyph=createGlyph(marker,!!props.selectedEventId);glyph.age=existing.get(marker.event.event_id)?.age??(props.selectedEventId?5:0);context.events.add(glyph.root);return glyph;
    });
  }, [markers, props.selectedEventId, webgl]);

  useEffect(()=>{runtime.current?.resetCamera(topDown);},[topDown]);
  useEffect(()=>{
    const changed=()=>setExpanded(document.fullscreenElement===viewport.current);
    const close=(event:KeyboardEvent)=>{
      if(event.key==='Escape'&&document.fullscreenElement===viewport.current){
        event.preventDefault();void document.exitFullscreen().catch(()=>{});
      }
    };
    document.addEventListener('fullscreenchange',changed);
    document.addEventListener('keydown',close);
    return()=>{document.removeEventListener('fullscreenchange',changed);document.removeEventListener('keydown',close);};
  },[]);
  const toggleFullscreen=()=>{
    if(document.fullscreenElement===viewport.current)void document.exitFullscreen();
    else if(viewport.current?.requestFullscreen)void viewport.current.requestFullscreen().catch(()=>{});
  };

  const latest=markers.at(-1)?.event;
  return <div className={`pitch-viewport ${expanded?'pitch-expanded':''}`} ref={viewport} data-testid="pitch-scene" data-stadium-loaded={assetReady}>
    {!webgl&&<PitchFallback markers={markers}/>}
    <div className={`pitch-canvas ${webgl?'is-ready':''}`} ref={host}/>
    <div className="pitch-vignette" aria-hidden="true"/>
    <div className="pitch-top-label"><span className="pitch-status-dot"/> Schematic event view</div>
    <div className="pitch-view-controls">
      <button type="button" onClick={()=>setTopDown(!topDown)} aria-pressed={topDown} title="Change pitch camera"><MoveUpRight size={14}/><span>{topDown?'Broadcast':'Top view'}</span></button>
      <button type="button" onClick={()=>setMotion(!motion)} aria-pressed={motion} title="Toggle event animation"><Waves size={14}/><span>Motion {motion?'on':'off'}</span></button>
      <button type="button" onClick={()=>runtime.current?.resetCamera(topDown)} title="Reset pitch camera" aria-label="Reset pitch camera"><RotateCcw size={14}/></button>
      <button type="button" onClick={toggleFullscreen} title={expanded?'Close expanded pitch':'Expand pitch'} aria-label={expanded?'Close expanded pitch':'Expand pitch'} aria-pressed={expanded}><Maximize2 size={14}/></button>
    </div>
    <div className="pitch-bottom-label"><span><i className="pitch-team-dot home"/>{props.homeTeamId} <i className="pitch-team-dot away"/>{props.awayTeamId}</span><span>{props.period===2?'Second half · ends switched':'First half'}<b>Drag to explore</b></span></div>
    <p className="pitch-event-equivalent">{latest?`${props.selectedEventId?'Selected':'Latest'}: ${eventLabel(latest)} · ${clock(latest.event_time_ms)}`:'Stadium view · event locations appear during replay'}</p>
  </div>;
}
