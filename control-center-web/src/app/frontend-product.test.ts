import { describe, expect, it } from 'vitest';
import { resolveFrontendProduct } from './frontend-product';

describe('resolveFrontendProduct', () => {
  it('keeps the legacy shell as the migration-safe default', () => {
    expect(resolveFrontendProduct()).toBe('legacy');
  });

  it('allows an explicit PAWOS query override for local acceptance', () => {
    expect(resolveFrontendProduct({ search: '?frontend=paw-os' })).toBe('paw-os');
    expect(resolveFrontendProduct({ search: '?frontend=legacy', configured: 'paw-os' })).toBe('legacy');
  });

  it('uses the build-time product when no query override is present', () => {
    expect(resolveFrontendProduct({ configured: 'paw-os' })).toBe('paw-os');
  });

  it('fails closed instead of silently selecting a shell for an unknown value', () => {
    expect(() => resolveFrontendProduct({ search: '?frontend=tutti' }))
      .toThrow('Unsupported frontend product: tutti');
    expect(() => resolveFrontendProduct({ configured: 'desktop' }))
      .toThrow('Unsupported frontend product: desktop');
  });
});
