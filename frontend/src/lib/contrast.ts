function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) throw new Error(`Expected a #rrggbb colour, received ${hex}`);
  const value = parseInt(match[1], 16);
  return 0.2126 * channel(value >> 16 & 255) + 0.7152 * channel(value >> 8 & 255) + 0.0722 * channel(value & 255);
}

/** WCAG 2.x contrast ratio between two opaque colours. */
export function contrastRatio(foreground: string, background: string): number {
  const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}
