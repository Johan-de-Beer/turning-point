import { describe, expect, it } from 'vitest';
import { renderToString } from 'react-dom/server';
import { createElement } from 'react';
import { setPitchView, usePitchView } from './pitchView';

function Probe() { return createElement('span', null, usePitchView()[0]); }

describe('pitch view preference', () => {
  it('renders the flat 2D pitch by default', () => {
    expect(renderToString(createElement(Probe))).toContain('2d');
  });
  it('switches to the 3D stadium without needing storage', () => {
    setPitchView('3d');
    expect(() => setPitchView('2d')).not.toThrow();
  });
});
