import { describe, expect, it } from 'vitest';
import compositionSource from './PawCompositionField.tsx?raw';
import desktopCss from '../styles/paw-os.css?raw';

describe('PAWOS Composition 8 field', () => {
  it('restores only the two raster-subtracted object groups as independent event layers', () => {
    expect(compositionSource).toContain('kandinsky-composition-viii-motion-base-v2.png');
    expect(compositionSource.match(/className="paw-composition__event-layer/g)).toHaveLength(2);
    expect(compositionSource).toContain('data-source-region="upper-notation"');
    expect(compositionSource).toContain('data-source-region="right-grid"');
    expect(compositionSource).toContain("querySelectorAll<SVGGElement>('.paw-composition__event-layer')");
    expect(compositionSource).not.toContain("querySelector<SVGImageElement>('.paw-composition__background')");
  });

  it('keeps the restored objects visible and motionless under reduced motion', () => {
    expect(desktopCss).toMatch(/\.paw-composition__event-layer\s*\{[^}]*opacity:\s*1/s);
    expect(desktopCss).toMatch(/prefers-reduced-motion:[^)]+\)[^{]*\{[\s\S]*\.paw-composition-field \*/);
  });
});
