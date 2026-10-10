import { useEffect, useRef, useState } from 'react';
import type { Session } from './contracts';

const REFRESH_MS = 5000;

/**
 * Polls a session report on a real-time cadence while the observed match moves on, and at
 * once on restart or correction. Keeps the last good report while a refresh fails.
 */
export function useLiveReport<T>(state: Session, load: (signal?: AbortSignal) => Promise<T>): { report: T | null; failed: boolean } {
  const [report, setReport] = useState<T | null>(null);
  const [failed, setFailed] = useState(false);
  const fetched = useRef({ key: '', at: 0 });
  const latest = useRef(state); latest.current = state;
  const loader = useRef(load); loader.current = load;

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const refresh = async (force = false) => {
      const current = latest.current;
      const key = `${current.session_id}:${current.generation}:${current.data_epoch}:${Math.floor(current.playhead_ms / 1000)}`;
      if (!force && (key === fetched.current.key || Date.now() - fetched.current.at < REFRESH_MS)) return;
      fetched.current = { key, at: Date.now() };
      try {
        const next = await loader.current(controller.signal);
        if (!cancelled) { setReport(next); setFailed(false); }
      } catch { if (!cancelled) setFailed(true); }
    };
    void refresh(true);
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => { cancelled = true; controller.abort(); window.clearInterval(timer); };
  }, [state.session_id, state.generation, state.data_epoch, state.status]);

  return { report, failed };
}
