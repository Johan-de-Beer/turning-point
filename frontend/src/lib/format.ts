export function matchClock(ms: number): string {
  const seconds = Math.floor(Math.max(0, ms) / 1000);
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
}

export function windowLabel(window: { start_ms: number; end_ms: number }): string {
  return `${matchClock(window.start_ms)} – ${matchClock(window.end_ms)}`;
}

export function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatPercent(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value)}%`;
}

export function relativeDelta(value: number, baseline: number | null | undefined): string {
  if (baseline == null) return 'No prior window';
  const delta = value - baseline;
  return delta === 0 ? 'Unchanged' : `${delta > 0 ? '+' : ''}${delta} vs prior window`;
}

export function createCapability(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function downloadJson(filename: string, content: unknown): void {
  const url = URL.createObjectURL(new Blob([JSON.stringify(content, null, 2)], { type: 'application/json' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
