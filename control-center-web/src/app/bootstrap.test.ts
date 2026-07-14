import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  delete window.webkit;
  delete document.documentElement.dataset.controlTransport;
});

describe('bootstrapControlCenter', () => {
  it('detects the injected native host before the React tree mounts', async () => {
    window.webkit = {
      messageHandlers: {
        ragImeNativeBridge: { postMessage: () => undefined },
      },
    };
    vi.resetModules();
    const { bootstrapControlCenter } = await import('./bootstrap');

    bootstrapControlCenter();

    expect(document.documentElement.dataset.controlTransport).toBe('native');
  });
});
