import { describe, expect, it } from 'vitest';
import { resolveFrontendProduct } from './frontend-product';

describe('resolveFrontendProduct', () => {
  it('uses PAWOS as the product default after migration', () => {
    expect(resolveFrontendProduct()).toBe('paw-os');
  });

  it('allows an explicit PAWOS query override for local acceptance', () => {
    expect(resolveFrontendProduct({ search: '?frontend=paw-os' })).toBe('paw-os');
    expect(resolveFrontendProduct({ search: '?frontend=legacy', configured: 'paw-os' })).toBe('legacy');
  });

  it('uses the build-time product when no query override is present', () => {
    expect(resolveFrontendProduct({ configured: 'paw-os' })).toBe('paw-os');
  });

  it('keeps the legacy shell out of production builds even when a query tries to select it', () => {
    expect(resolveFrontendProduct({ buildChannel: 'production', configured: 'paw-os' })).toBe('paw-os');
    expect(() => resolveFrontendProduct({
      buildChannel: 'production',
      configured: 'paw-os',
      search: '?frontend=legacy',
    })).toThrow('Legacy frontend product is only available outside production');
    expect(() => resolveFrontendProduct({
      buildChannel: 'production',
      configured: 'legacy',
    })).toThrow('Legacy frontend product is only available outside production');
  });

  it('fails closed instead of silently selecting a shell for an unknown value', () => {
    expect(() => resolveFrontendProduct({ search: '?frontend=tutti' }))
      .toThrow('Unsupported frontend product: tutti');
    expect(() => resolveFrontendProduct({ configured: 'desktop' }))
      .toThrow('Unsupported frontend product: desktop');
  });
});
