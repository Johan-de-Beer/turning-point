import { useSyncExternalStore } from 'react';

/** Which pitch the viewer prefers. A per-browser convenience, so it lives in localStorage. */
export type PitchView = '2d' | '3d';
const KEY = 'turning-point:pitch-view';
const listeners = new Set<() => void>();

function read(): PitchView {
  try { return localStorage.getItem(KEY) === '3d' ? '3d' : '2d'; } catch { return '2d'; }
}
let value: PitchView = read();

export function setPitchView(next: PitchView): void {
  value = next;
  try { localStorage.setItem(KEY, next); } catch { /* storage unavailable: keep the in-memory choice */ }
  for (const listener of listeners) listener();
}

export function usePitchView(): [PitchView, (next: PitchView) => void] {
  const view = useSyncExternalStore((listener) => { listeners.add(listener); return () => listeners.delete(listener); }, () => value, () => '2d' as PitchView);
  return [view, setPitchView];
}
