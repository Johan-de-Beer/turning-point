import { afterEach, describe, expect, it, vi } from 'vitest';
import { z } from 'zod';
import { request } from './api';

afterEach(() => vi.unstubAllGlobals());
describe('API transport safeguards', () => {
  it('sends capabilities only in authorization headers and reuses the caller idempotency key', async () => {
    vi.stubGlobal('window', globalThis);
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ready' }) });
    vi.stubGlobal('fetch', fetchMock);
    const schema = z.strictObject({ status: z.literal('ready') });
    const options = { method: 'POST', capability: 'test_capability', idempotencyKey: 'test_stable_key', body: { action: 'pause' } };
    await request('/sessions/safe/controls', schema, options);
    await request('/sessions/safe/controls', schema, options);
    for (const [url, init] of fetchMock.mock.calls) {
      expect(url).not.toContain(options.capability);
      expect(init.headers.Authorization).toBe('Bearer test_capability');
      expect(init.headers['Idempotency-Key']).toBe('test_stable_key');
    }
  });
  it('rejects malformed responses instead of rendering fabricated fallback data', async () => {
    vi.stubGlobal('window', globalThis);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ready', final_score: 'spoiler' }) }));
    await expect(request('/matches', z.strictObject({ status: z.literal('ready') }))).rejects.toMatchObject({ code: 'invalid_response', retryable: false });
  });
});
