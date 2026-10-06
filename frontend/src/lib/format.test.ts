import { describe, expect, it } from 'vitest';
import { formatPercent, matchClock, matchMinute, relativeDelta, windowLabel } from './format';

describe('observed-data presentation', () => {
  it('preserves period endpoints and clamps negative clock values', () => {
    expect(matchClock(-200)).toBe('00:00');
    expect(matchClock(2700000)).toBe('45:00');
    expect(matchClock(5400000)).toBe('90:00');
    expect(windowLabel({ start_ms: 0, end_ms: 180000 })).toBe('00:00 – 03:00');
  });
  it('rounds the clock up to broadcast match minutes', () => {
    expect(matchMinute(0)).toBe(1);
    expect(matchMinute(1350000)).toBe(23);
    expect(matchMinute(1380000)).toBe(23);
    expect(matchMinute(1380001)).toBe(24);
    expect(matchMinute(5400000)).toBe(90);
  });
  it('shows missing possession denominators and prior windows as unavailable', () => {
    expect(formatPercent(null)).toBe('—');
    expect(formatPercent(0)).toBe('0%');
    expect(relativeDelta(3, null)).toBe('No prior window');
    expect(relativeDelta(3, 0)).toBe('+3 vs prior window');
  });
});
