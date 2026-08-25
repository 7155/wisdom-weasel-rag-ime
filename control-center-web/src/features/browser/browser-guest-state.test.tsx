import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport } from '@/test/mock-transport';
import { PawBrowserApp } from '@/paw-os/apps/PawBrowserApp';

beforeEach(() => {
  delete window.pawBrowserHost;
});

afterEach(() => {
  cleanup();
  delete window.pawBrowserHost;
});

describe('PAW Browser real guest state', () => {
  it('reflects real loading in the tab and load hairline and swaps reload for stop', async () => {
    renderBrowser();
    const webview = guest();
    const stop = vi.fn();
    Object.assign(webview, { stop });
    expect(await screen.findByRole('button', { name: '刷新网页' })).toBeInTheDocument();
    // No loading theatre before the guest reports anything.
    expect(document.querySelector('.paw-browser-loadbar')).toBeNull();

    fireEvent(webview, new Event('did-start-loading'));
    expect(document.querySelector('.paw-browser-tab-icon .ui-spin')).not.toBeNull();
    expect(document.querySelector('.paw-browser-loadbar')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '停止加载' }));
    expect(stop).toHaveBeenCalledTimes(1);

    fireEvent(webview, new Event('did-stop-loading'));
    expect(screen.getByRole('button', { name: '刷新网页' })).toBeInTheDocument();
    expect(document.querySelector('.paw-browser-tab-icon .ui-spin')).toBeNull();
    expect(document.querySelector('.paw-browser-loadbar')).toBeNull();
  });

  it('shows the real page favicon reported by the guest', async () => {
    renderBrowser();
    const webview = guest();
    await screen.findByRole('textbox', { name: '页面地址' });
    fireEvent(webview, Object.assign(new Event('page-favicon-updated'), {
      favicons: ['https://example.com/favicon.ico'],
    }));
    await waitFor(() => expect(document.querySelector('.paw-browser-tab-icon img'))
      .toHaveAttribute('src', 'https://example.com/favicon.ico'));
  });

  it('surfaces only main-frame failures and retries the exact URL in the same guest', async () => {
    renderBrowser();
    const webview = guest();
    const loadURL = vi.fn(async () => undefined);
    Object.assign(webview, { loadURL });
    await screen.findByRole('textbox', { name: '页面地址' });

    fireEvent(webview, Object.assign(new Event('did-fail-load'), {
      errorCode: -3, errorDescription: 'ERR_ABORTED', validatedURL: 'https://aborted.example/', isMainFrame: true,
    }));
    fireEvent(webview, Object.assign(new Event('did-fail-load'), {
      errorCode: -106, errorDescription: 'ERR_INTERNET_DISCONNECTED', validatedURL: 'https://sub.example/frame', isMainFrame: false,
    }));
    expect(screen.queryByRole('alert')).toBeNull();

    fireEvent(webview, Object.assign(new Event('did-fail-load'), {
      errorCode: -105, errorDescription: 'ERR_NAME_NOT_RESOLVED', validatedURL: 'https://missing.example/', isMainFrame: true,
    }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('找不到这个网站');
    expect(alert).toHaveTextContent('https://missing.example/');
    expect(document.querySelector('.paw-browser-tab[data-failed]')).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(loadURL).toHaveBeenCalledWith('https://missing.example/');
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('announces a gone page process and reloads the same guest', async () => {
    renderBrowser();
    const webview = guest();
    const reload = vi.fn();
    Object.assign(webview, { reload });
    await screen.findByRole('textbox', { name: '页面地址' });

    fireEvent(webview, Object.assign(new Event('render-process-gone'), { reason: 'crashed' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('页面渲染进程崩溃');

    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(reload).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('enables back and forward only when the guest history allows it, with a truthful lock', async () => {
    renderBrowser();
    const webview = guest();
    await screen.findByRole('textbox', { name: '页面地址' });
    expect(screen.getByRole('button', { name: '后退' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '前进' })).toBeDisabled();

    Object.assign(webview, {
      getTitle: () => 'Example',
      getURL: () => 'https://secure.example/',
      getWebContentsId: () => 77,
      canGoBack: () => true,
      canGoForward: () => false,
    });
    fireEvent(webview, new Event('dom-ready'));

    await waitFor(() => expect(screen.getByRole('button', { name: '后退' })).toBeEnabled());
    expect(screen.getByRole('button', { name: '前进' })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole('textbox', { name: '页面地址' })).toHaveValue('https://secure.example/'));
    expect(screen.getByTitle('连接已加密')).toBeInTheDocument();
  });
});

function renderBrowser() {
  window.pawBrowserHost = electronBrowserHost();
  render(
    <ControlTransportProvider transport={browserTransport()}>
      <PawBrowserApp />
    </ControlTransportProvider>,
  );
}

function guest(): HTMLElement {
  const element = document.querySelector('webview');
  if (!element) throw new Error('missing webview guest');
  return element as HTMLElement;
}

function browserTransport() {
  return new MockControlTransport({
    routes: {
      'browser.tabs': { ok: true, items: [] },
      'browser.traces': { ok: true, items: [] },
      'browser.command': { ok: true, status: 'completed' },
      'browser.stop': { ok: true, cancelled: 0 },
    },
  });
}

function electronBrowserHost(): NonNullable<typeof window.pawBrowserHost> {
  return {
    kind: 'electron-webview',
    partition: 'persist:paw-browser',
    activate: () => undefined,
    clearBrowsingData: async (action) => ({ action, after: 0, before: 0, completedAt: 3 }),
    clearHistory: async () => [],
    getHistory: async () => [],
    getSettings: async () => ({
      cacheBytes: 0,
      cookieCount: 0,
      downloadPath: '/tmp',
      extensionCount: 0,
      extensionsPath: '/tmp/Extensions',
      partition: 'persist:paw-browser',
      permissionMode: 'site-request',
      startPage: 'about:blank',
    }),
    listExtensions: async () => [],
    loadUnpackedExtension: async () => null,
    openExtensionsFolder: async () => ({ opened: true, path: '/tmp/Extensions' }),
    openDownloads: async () => ({ opened: true, path: '/tmp' }),
    register: () => undefined,
    removeExtension: async () => [],
    removeHistoryEntry: async () => [],
    setStartPage: async (startPage) => ({ startPage }),
    takeScreenshot: async () => ({ path: '/tmp/page.png', saved: true }),
    onCommand: () => () => undefined,
    onGuestClosed: () => () => undefined,
    onHistoryChanged: () => () => undefined,
    onOpenUrl: () => () => undefined,
    onSelectTab: () => () => undefined,
  };
}
