import { usePitchView } from '../lib/pitchView';

export function PitchViewToggle() {
  const [view, setView] = usePitchView();
  return <div className="segmented-control view-toggle" role="group" aria-label="Pitch view">
    <button type="button" aria-label="2D pitch" aria-pressed={view === '2d'} className={view === '2d' ? 'active' : ''} onClick={() => setView('2d')}>2D</button>
    <button type="button" aria-label="3D stadium" aria-pressed={view === '3d'} className={view === '3d' ? 'active' : ''} onClick={() => setView('3d')}>3D</button>
  </div>;
}
