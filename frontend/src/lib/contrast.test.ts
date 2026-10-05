import { describe, expect, it } from 'vitest';
import styles from '../styles.css?raw';
import { contrastRatio } from './contrast';

// Read the real design tokens so the test fails if a token drifts below WCAG AA.
const root = /:root\s*\{([\s\S]*?)\n\}/.exec(styles)?.[1] ?? '';
const tokens = Object.fromEntries([...root.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map(([, name, value]) => [name, value]));

describe('design token contrast (WCAG 2.x)', () => {
  it('parses the colour tokens from the stylesheet', () => {
    expect(tokens.bg).toBe('#0b1220');
    expect(tokens.teal).toBe('#5eead4');
  });
  const surfaces = ['bg', 'bg-raised', 'surface', 'surface-2'];
  it.each(surfaces)('body text tokens meet 4.5:1 on %s', (surface) => {
    for (const text of ['text', 'text-2', 'text-3', 'teal', 'home', 'away', 'success', 'danger', 'warning']) {
      expect(contrastRatio(tokens[text], tokens[surface]), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5);
    }
  });
  it('keeps primary-button text and secondary-button text readable', () => {
    expect(contrastRatio(tokens['teal-ink'], tokens.teal)).toBeGreaterThanOrEqual(7);
    expect(contrastRatio(tokens.teal, tokens['teal-soft'])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(tokens['text-2'], tokens['surface-3'])).toBeGreaterThanOrEqual(4.5);
  });
  it('gives form-control boundaries at least 3:1 against their surroundings', () => {
    for (const surface of ['bg', 'bg-raised', 'surface']) expect(contrastRatio(tokens['border-input'], tokens[surface]), surface).toBeGreaterThanOrEqual(3);
  });
});
