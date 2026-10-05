import { useCallback, useEffect, useRef, useState } from 'react';
import { z } from 'zod';
import { request, ApiError } from './api';
import { canAcceptState, defaultPreferences, evidenceSchema, matchesSchema, mergeObservedEvents, preferencesSchema, sessionSchema, validateSessionReferences, type Evidence, type Match, type Preferences, type Session } from './contracts';
import { createCapability } from './format';

const preferencesKey = 'turning-point:preferences:v1';
const sessionKey = 'turning-point:session:v1';
const pendingCreateKey = 'turning-point:pending-create:v1';
const authSchema = z.strictObject({ session_id: z.string().min(1), capability: z.string().regex(/^[a-f0-9]{64}$/) });
const pendingCreateSchema = z.strictObject({ capability: z.string().regex(/^[a-f0-9]{64}$/), idempotency_key: z.string().uuid(), body: z.strictObject({ match_id: z.string(), preferences: preferencesSchema, speed: z.union([z.literal(12), z.literal(60)]) }) });
type Auth = z.infer<typeof authSchema>;
export type ControlAction = 'play' | 'pause' | 'continue_half' | 'restart' | 'set_speed';

function storedPreferences(): Preferences {
  try { return preferencesSchema.parse(JSON.parse(localStorage.getItem(preferencesKey) ?? 'null')); }
  catch { return defaultPreferences; }
}
function storedAuth(): Auth | null {
  try { return authSchema.parse(JSON.parse(sessionStorage.getItem(sessionKey) ?? 'null')); }
  catch { return null; }
}

export function useMatch() {
  const [match, setMatch] = useState<Match | null>(null);
  const [state, setState] = useState<Session | null>(null);
  const [preferences, setPreferences] = useState<Preferences>(storedPreferences);
  const [auth, setAuth] = useState<Auth | null>(storedAuth);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [connection, setConnection] = useState<'online' | 'reconnecting' | 'offline'>('online');
  const stateRef = useRef<Session | null>(null);
  const busyRef = useRef(false);
  const retryRef = useRef(0);
  const matchRef = useRef<Match | null>(null);
  const authRef = useRef<Auth | null>(auth);
  authRef.current = auth;
  matchRef.current = match;

  const accept = useCallback((incoming: Session) => {
    if (matchRef.current) validateSessionReferences(incoming, matchRef.current);
    if (!canAcceptState(stateRef.current, incoming)) return;
    const merged = mergeObservedEvents(stateRef.current, incoming);
    stateRef.current = merged;
    setState(merged);
    setPreferences(incoming.preferences);
    localStorage.setItem(preferencesKey, JSON.stringify(incoming.preferences));
    setConnection('online');
    setError(null);
    retryRef.current = 0;
  }, []);

  const fail = useCallback((reason: unknown, sessionRequest = false) => {
    const failure = reason instanceof ApiError ? reason : new ApiError(reason instanceof Error ? reason.message : 'Could not validate observed data', 'invalid_response', false);
    if (sessionRequest && failure.status === 404) {
      sessionStorage.removeItem(sessionKey);
      stateRef.current = null;
      authRef.current = null;
      setState(null);
      setAuth(null);
      setConnection('online');
      retryRef.current = 0;
      setError(new ApiError('Your replay session is no longer available. Start a fresh replay; your preferences are saved.', 'expired_session', false, 404));
      return;
    }
    setError(failure);
    if (failure.retryable) {
      retryRef.current++;
      setConnection(retryRef.current > 2 ? 'offline' : 'reconnecting');
    }
  }, []);

  const loadMetadata = useCallback(async () => {
    setLoading(true);
    try {
      const result = await request('/matches', matchesSchema);
      if (!result.matches.length) throw new ApiError('No synthetic fixture is available on the local server.', 'empty_fixture', false);
      matchRef.current = result.matches[0];
      setMatch(result.matches[0]);
      setError(null);
    } catch (reason) { fail(reason); }
    finally { setLoading(false); }
  }, [fail]);

  useEffect(() => { void loadMetadata(); }, [loadMetadata]);

  useEffect(() => {
    if (!auth || !match) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    async function poll() {
      if (cancelled) return;
      if (!busyRef.current) {
        try {
          const cursor = stateRef.current?.next_cursor;
          const path = cursor ? `/sessions/${auth!.session_id}/updates?cursor=${encodeURIComponent(cursor)}` : `/sessions/${auth!.session_id}/state`;
          const incoming = await request(path, sessionSchema, { capability: auth!.capability, signal: controller.signal });
          if (!cancelled && !busyRef.current) accept(incoming);
        } catch (reason) {
          if (!cancelled) {
            fail(reason, true);
          }
        }
      }
      if (!cancelled) timer = setTimeout(poll, Math.min(4000, 450 * 2 ** retryRef.current));
    }
    void poll();
    return () => { cancelled = true; controller.abort(); clearTimeout(timer); };
  }, [auth, match, accept, fail]);

  const lock = (value: boolean) => { busyRef.current = value; setBusy(value); };

  async function start() {
    if (!match || busyRef.current) return;
    lock(true);
    try {
      const stored = pendingCreateSchema.safeParse(JSON.parse(sessionStorage.getItem(pendingCreateKey) ?? 'null'));
      const pending = stored.success && stored.data.body.match_id === match.match_id ? stored.data : { capability: createCapability(), idempotency_key: crypto.randomUUID(), body: { match_id: match.match_id, preferences, speed: 12 as const } };
      sessionStorage.setItem(pendingCreateKey, JSON.stringify(pending));
      const capability = pending.capability;
      const created = await request('/sessions', sessionSchema, { method: 'POST', body: pending.body, capability, idempotencyKey: pending.idempotency_key });
      const sessionAuth = { session_id: created.session_id, capability };
      sessionStorage.setItem(sessionKey, JSON.stringify(sessionAuth));
      sessionStorage.removeItem(pendingCreateKey);
      setAuth(sessionAuth);
      authRef.current = sessionAuth;
      accept(created);
      const playing = await request(`/sessions/${created.session_id}/controls`, sessionSchema, { method: 'POST', body: { action: 'play', expected_generation: created.generation }, capability, idempotencyKey: crypto.randomUUID() });
      accept(playing);
    } catch (reason) { fail(reason, Boolean(authRef.current)); }
    finally { lock(false); }
  }

  async function control(action: ControlAction, speed?: 1 | 12 | 60) {
    const current = stateRef.current;
    const sessionAuth = authRef.current;
    if (!current || !sessionAuth || busyRef.current) return;
    lock(true);
    try {
      const idempotencyKey = crypto.randomUUID();
      const options = { method: 'POST', body: { action, expected_generation: current.generation, ...(action === 'set_speed' ? { speed } : {}) }, capability: sessionAuth.capability, idempotencyKey };
      let incoming: Session;
      try { incoming = await request(`/sessions/${current.session_id}/controls`, sessionSchema, options); }
      catch (reason) {
        if (!(reason instanceof ApiError) || !reason.retryable) throw reason;
        incoming = await request(`/sessions/${current.session_id}/controls`, sessionSchema, options);
      }
      accept(incoming);
    } catch (reason) { fail(reason, true); }
    finally { lock(false); }
  }

  async function updatePreferences(next: Preferences) {
    const current = stateRef.current;
    const sessionAuth = authRef.current;
    if (!current || !sessionAuth) {
      setPreferences(next);
      localStorage.setItem(preferencesKey, JSON.stringify(next));
      return;
    }
    if (busyRef.current) return;
    lock(true);
    try {
      const incoming = await request(`/sessions/${current.session_id}/preferences`, sessionSchema, { method: 'PATCH', body: { ...next, expected_preferences_version: current.preferences_version }, capability: sessionAuth.capability });
      accept(incoming);
    } catch (reason) { fail(reason, true); }
    finally { lock(false); }
  }

  async function getEvidence(insightId: string): Promise<Evidence> {
    const current = stateRef.current;
    const sessionAuth = authRef.current;
    if (!current || !sessionAuth) throw new ApiError('Start the replay to inspect an insight.', 'no_session', false);
    const evidence = await request(`/sessions/${current.session_id}/insights/${encodeURIComponent(insightId)}/evidence`, evidenceSchema, { capability: sessionAuth.capability });
    const latest = stateRef.current;
    if (!latest || evidence.session_id !== latest.session_id || evidence.generation !== latest.generation || evidence.data_epoch !== latest.data_epoch) throw new ApiError('This evidence changed during a replay update. Open the insight again.', 'stale_evidence', true);
    return evidence;
  }

  async function retry() {
    retryRef.current = 0;
    setConnection('reconnecting');
    if (!match) return loadMetadata();
    const sessionAuth = authRef.current;
    if (!sessionAuth) { setError(null); setConnection('online'); return; }
    try { accept(await request(`/sessions/${sessionAuth.session_id}/state`, sessionSchema, { capability: sessionAuth.capability })); }
    catch (reason) { fail(reason, true); }
  }

  return { match, state, preferences, loading, busy, error, connection, start, control, updatePreferences, getEvidence, retry };
}
