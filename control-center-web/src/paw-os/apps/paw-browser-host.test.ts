import { describe, expect, it, vi } from 'vitest';
import { loadPawBrowserUrl, PAW_BROWSER_PARTITION, pawBrowserHost } from './paw-browser-host';

describe('PAW Electron Browser host', () => {
  it('accepts only the fixed persistent Browser partition', () => {
    window.pawBrowserHost = {
      kind: 'electron-webview',
      partition: PAW_BROWSER_PARTITION,
      activate: () => undefined,
      clearBrowsingData: async () => ({ action: 'cache', after: 0, before: 0, completedAt: 1 }),
      clearHistory: async () => [],
      getHistory: async () => [],
      getSettings: async () => ({ cacheBytes: 0, cookieCount: 0, downloadPath: '/tmp', extensionCount: 0, extensionsPath: '/tmp/Extensions', partition: PAW_BROWSER_PARTITION, permissionMode: 'site-request', startPage: 'about:blank' }),
      listExtensions: async () => [],
      loadUnpackedExtension: async () => null,
      openExtensionsFolder: async () => ({ opened: true, path: '/tmp/Extensions' }),
      openDownloads: async () => ({ opened: true, path: '/tmp' }),
      register: () => undefined,
      removeExtension: async () => [],
      removeHistoryEntry: async () => [],
      setStartPage: async () => ({ startPage: 'about:blank' }),
      takeScreenshot: async () => ({ path: '/tmp/page.png', saved: true }),
      onCommand: () => () => undefined,
      onGuestClosed: () => () => undefined,
      onHistoryChanged: () => () => undefined,
      onOpenUrl: () => () => undefined,
      onSelectTab: () => () => undefined,
    };
    expect(pawBrowserHost()).toBe(window.pawBrowserHost);

    window.pawBrowserHost = { ...window.pawBrowserHost, partition: 'persist:other' };
    expect(pawBrowserHost()).toBeNull();
    delete window.pawBrowserHost;
  });

  it('navigates the real guest instead of requesting a screenshot', () => {
    const loadURL = vi.fn(async () => undefined);
    const ref = { current: { loadURL } } as never;
    expect(loadPawBrowserUrl(ref, 'https://example.com')).toBe(true);
    expect(loadURL).toHaveBeenCalledWith('https://example.com');
  });
});
