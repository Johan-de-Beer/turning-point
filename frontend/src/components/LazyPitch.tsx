import { lazy, Suspense } from 'react';
import { usePitchView } from '../lib/pitchView';
import { FlatPitch } from './FlatPitch';
import type { PitchSceneProps } from './pitchShared';

// The WebGL stadium carries most of the bundle; it loads only when someone picks 3D.
const PitchScene = lazy(() => import('./PitchScene').then((module) => ({ default: module.PitchScene })));

export function LazyPitch(props: PitchSceneProps) {
  const [view] = usePitchView();
  if (view === '2d') return <FlatPitch {...props} />;
  return <Suspense fallback={<div className="pitch-viewport pitch-loading" role="status"><span className="pitch-loading-dot" />Loading the schematic stadium…</div>}>
    <PitchScene {...props} />
  </Suspense>;
}
