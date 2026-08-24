import { describe, expect, it } from 'vitest';
import { resolveAgentSurfaceLayout } from './surface-layout';

describe('resolveAgentSurfaceLayout', () => {
  it('uses the PAWOS App window width instead of the browser viewport', () => {
    expect(resolveAgentSurfaceLayout({
      browserMobile: false,
      browserStatusOverlay: false,
      surface: { width: 700 },
    })).toEqual({ compact: true, overlayInspectors: true });
  });

  it('keeps a wide Agent App in its three-pane layout', () => {
    expect(resolveAgentSurfaceLayout({
      browserMobile: false,
      browserStatusOverlay: false,
      surface: { width: 1240 },
    })).toEqual({ compact: false, overlayInspectors: false });
  });

  it('preserves legacy browser breakpoints when no App surface exists', () => {
    expect(resolveAgentSurfaceLayout({
      browserMobile: true,
      browserStatusOverlay: true,
      surface: null,
    })).toEqual({ compact: true, overlayInspectors: true });
  });
});
