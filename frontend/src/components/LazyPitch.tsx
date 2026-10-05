import { lazy, Suspense } from 'react';
import type { PitchSceneProps } from './PitchScene';

// The WebGL stadium carries most of the bundle; load it after the first paint.
const PitchScene = lazy(() => import('./PitchScene').then((module) => ({ default: module.PitchScene })));

export function LazyPitch(props: PitchSceneProps) {
  return <Suspense fallback={<div className="pitch-viewport pitch-loading" role="status"><span className="pitch-loading-dot" />Loading the schematic stadium…</div>}>
    <PitchScene {...props} />
  </Suspense>;
}
