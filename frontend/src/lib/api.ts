import { z } from 'zod';

export class ApiError extends Error {
  code: string;
  retryable: boolean;
  status: number;
  constructor(message: string, code: string, retryable: boolean, status = 0) {
    super(message);
    this.code = code;
    this.retryable = retryable;
    this.status = status;
  }
}

export async function request<T>(path: string, schema: z.ZodType<T>, options: { method?: string; body?: unknown; capability?: string; idempotencyKey?: string; signal?: AbortSignal } = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8000);
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  try {
    const response = await fetch(`/api${path}`, {
      method: options.method ?? 'GET',
      headers: {
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(options.capability ? { Authorization: `Bearer ${options.capability}` } : {}),
        ...(options.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : {}),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
      cache: 'no-store',
    });
    if (!response.ok) {
      const value: unknown = await response.json().catch(() => null);
      const error = z.object({ code: z.string(), message: z.string(), retryable: z.boolean() }).safeParse(value);
      throw new ApiError(error.success ? error.data.message : `Request failed (${response.status})`, error.success ? error.data.code : 'request_failed', error.success ? error.data.retryable : response.status >= 500, response.status);
    }
    const payload: unknown = await response.json();
    const parsed = schema.safeParse(payload);
    if (!parsed.success) throw new ApiError('The server returned data that does not match contract v1.0. The last valid observation is preserved.', 'invalid_response', false);
    return parsed.data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === 'AbortError') throw new ApiError('The server took too long to respond. Reconnecting…', 'timeout', true);
    throw new ApiError('Cannot reach the local replay server. Reconnecting…', 'offline', true);
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener('abort', abort);
  }
}
