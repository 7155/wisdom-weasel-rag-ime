import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { GlobalFeedbackProvider } from '@/components/feedback';
import { MockControlTransport } from '@/test/mock-transport';
import { PawDesktopProvider } from '../runtime/desktop-context';
import { pawApps, type PawAppId } from '../runtime/app-registry';
import { PawDesktop } from './PawDesktop';

const originalAnimate = Object.getOwnPropertyDescriptor(Element.prototype, 'animate');
const originalGetAnimations = Object.getOwnPropertyDescriptor(Element.prototype, 'getAnimations');

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(Element.prototype, 'animate', { configurable: true, value: vi.fn(() => ({ cancel: vi.fn() })) });
  Object.defineProperty(Element.prototype, 'getAnimations', { configurable: true, value: vi.fn(() => []) });
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
});
afterEach(() => {
  cleanup();
  delete window.pawBrowserHost;
  vi.unstubAllGlobals();
  restoreElementMethod('animate', originalAnimate);
  restoreElementMethod('getAnimations', originalGetAnimations);
});

describe('PAWOS desktop', () => {
  it('opens and closes the App launcher with the advertised keyboard shortcut', () => {
    renderDesktop();

    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    expect(screen.getByRole('dialog', { name: '全部 App' })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '全部 App' })).not.toBeInTheDocument();
  });

  it('closes the launcher after opening an App', () => {
    renderDesktop();

    fireEvent.click(screen.getByRole('button', { name: '全部 App' }));
    const launcher = screen.getByRole('dialog', { name: '全部 App' });
    fireEvent.click(within(launcher).getByRole('button', { name: /Agent/ }));

    expect(screen.queryByRole('dialog', { name: '全部 App' })).not.toBeInTheDocument();
  });

  it('renders every registered App in Launchpad with its original SVG identity', () => {
    const { container } = renderDesktop();
    fireEvent.click(screen.getByRole('button', { name: '全部 App' }));
    const launcher = screen.getByRole('dialog', { name: '全部 App' });

    for (const app of pawApps) {
      const appButton = within(launcher).getByRole('button', { name: new RegExp(app.label) });
      const icon = appButton.querySelector(`[data-paw-app-icon="${app.id}"]`);
      expect(icon).toBeInTheDocument();
      expect(icon).toHaveAttribute('aria-hidden', 'true');
    }
    expect(container.querySelectorAll('.paw-launchpad [data-paw-app-icon]')).toHaveLength(pawApps.length);
    expect(launcher.querySelector('.paw-os-app-icon, .paw-app-glyph')).toBeNull();
    expect(launcher.querySelector('[data-lucide]')).toBeNull();
  });

  it('pairs the current App label with the same original identity in the top bar', () => {
    renderDesktop('agent');

    expect(screen.getByRole('button', { name: '打开全部 App' })).toHaveTextContent('PAW');
    expect(document.querySelector('.paw-menu-bar > strong')).toBeNull();
    const current = document.querySelector('.paw-menu-app') as HTMLElement;
    expect(current).toHaveTextContent('Agent');
    expect(current.querySelector('[data-paw-app-icon="agent"]')).toHaveAttribute('aria-hidden', 'true');
    expect(current.querySelector('[data-lucide], .paw-os-app-icon, .paw-app-glyph')).toBeNull();
  });

  it('replaces the browser context menu with desktop and App commands', () => {
    renderDesktop();

    const desktop = screen.getByRole('main');
    const desktopMenu = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 120, clientY: 90 });
    fireEvent(desktop, desktopMenu);

    expect(desktopMenu.defaultPrevented).toBe(true);
    expect(screen.getByRole('menu', { name: '桌面菜单' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '新建 Agent 工作' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '打开 Browser' })).toBeInTheDocument();

    const shortcuts = screen.getByLabelText('桌面 App');
    fireEvent.contextMenu(within(shortcuts).getByRole('button', { name: 'Agent' }), { clientX: 240, clientY: 180 });
    expect(screen.getByRole('menu', { name: 'Agent 菜单' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '打开 Agent' })).toBeInTheDocument();
  });

  it('routes Dock right-click to the App menu and closes every window for that App', () => {
    renderDesktop('agent');
    const dock = screen.getByRole('navigation', { name: 'PAWOS 工具架' });
    const agentDockButton = within(dock).getByRole('button', { name: 'Agent' });

    fireEvent.contextMenu(agentDockButton, { clientX: 240, clientY: 680 });

    expect(screen.getByRole('menu', { name: 'Agent 菜单' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('menuitem', { name: '关闭 Agent 的全部窗口' }));
    expect(document.querySelector('[data-paw-window-id="agent"]')).toBeNull();
  });

  it('marks a Dock App that only has minimized windows and restores it on click', () => {
    // 减少动态效果让最小化退出路径同步完成，测试关注 Dock 状态而非动画。
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    renderDesktop('agent');
    const dock = screen.getByRole('navigation', { name: 'PAWOS 工具架' });
    const agentDockButton = within(dock).getByRole('button', { name: 'Agent' });
    expect(agentDockButton).toHaveAttribute('data-open');
    expect(agentDockButton).not.toHaveAttribute('data-minimized');

    fireEvent.click(screen.getByRole('button', { name: '最小化窗口' }));
    expect(agentDockButton).toHaveAttribute('data-open');
    expect(agentDockButton).toHaveAttribute('data-minimized');
    expect(agentDockButton).toHaveAttribute('title', 'Agent 已最小化，点击恢复');

    fireEvent.click(agentDockButton);
    expect(agentDockButton).not.toHaveAttribute('data-minimized');
    expect(document.querySelector('[data-paw-window-id="agent"]')).toBeInTheDocument();
  });

  it('closes all PAWOS windows from the desktop menu in one projection-only action', () => {
    renderDesktop('agent');
    const desktop = screen.getByRole('main');

    fireEvent.contextMenu(desktop, { clientX: 120, clientY: 90 });
    fireEvent.click(screen.getByRole('menuitem', { name: '关闭全部窗口' }));

    expect(document.querySelectorAll('[data-paw-window-id]')).toHaveLength(0);
  });

  it('routes a Browser host command into PAWOS before the Browser App is mounted', () => {
    let commandListener: ((command: { action: 'new_tab'; commandId: string; url: string }) => void) | undefined;
    window.pawBrowserHost = desktopBrowserHost((listener) => {
      commandListener = listener;
      return () => { commandListener = undefined; };
    });
    renderDesktop();

    act(() => commandListener?.({
      action: 'new_tab',
      commandId: 'command-1',
      url: 'https://inside.example',
    }));

    expect(document.querySelector('[data-paw-window-id="browser"]')).toBeInTheDocument();
    const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
      windows?: Record<string, { target?: { commandId?: string; url?: string } }>;
    };
    expect(snapshot.windows?.browser?.target).toMatchObject({
      commandId: 'command-1',
      url: 'https://inside.example',
    });
  });

  it('selects desktop Apps with a lasso instead of webpage text selection', () => {
    renderDesktop();
    const viewport = screen.getByRole('main');
    const shortcuts = screen.getByLabelText('桌面 App');
    const agent = within(shortcuts).getByRole('button', { name: 'Agent' });
    const browser = within(shortcuts).getByRole('button', { name: '浏览器' });
    Object.defineProperty(viewport, 'getBoundingClientRect', {
      value: () => domRect(0, 0, 900, 700),
    });
    Object.defineProperty(agent, 'getBoundingClientRect', {
      value: () => domRect(680, 80, 78, 70),
    });
    Object.defineProperty(browser, 'getBoundingClientRect', {
      value: () => domRect(680, 180, 78, 70),
    });

    fireEvent.pointerDown(viewport, { button: 0, clientX: 650, clientY: 50, pointerId: 4 });
    fireEvent.pointerMove(window, { clientX: 790, clientY: 270, pointerId: 4 });

    expect(screen.getByTestId('paw-selection-lasso')).toBeInTheDocument();
    expect(agent).toHaveAttribute('aria-selected', 'true');
    expect(browser).toHaveAttribute('aria-selected', 'true');

    fireEvent.pointerUp(window, { clientX: 790, clientY: 270, pointerId: 4 });
    expect(screen.queryByTestId('paw-selection-lasso')).not.toBeInTheDocument();
  });
});

function renderDesktop(initialAppId?: PawAppId) {
  return render(
    <ControlTransportProvider transport={new MockControlTransport()}>
      <GlobalFeedbackProvider>
        <PawDesktopProvider initialAppId={initialAppId}>
          <PawDesktop />
        </PawDesktopProvider>
      </GlobalFeedbackProvider>
    </ControlTransportProvider>,
  );
}

function domRect(x: number, y: number, width: number, height: number): DOMRect {
  return {
    x,
    y,
    width,
    height,
    top: y,
    right: x + width,
    bottom: y + height,
    left: x,
    toJSON: () => ({}),
  };
}

function restoreElementMethod(name: 'animate' | 'getAnimations', descriptor?: PropertyDescriptor): void {
  if (descriptor) Object.defineProperty(Element.prototype, name, descriptor);
  else delete (Element.prototype as unknown as Record<string, unknown>)[name];
}

function desktopBrowserHost(
  onCommand: NonNullable<typeof window.pawBrowserHost>['onCommand'],
): NonNullable<typeof window.pawBrowserHost> {
  return {
    kind: 'electron-webview',
    partition: 'persist:paw-browser',
    activate: () => undefined,
    clearBrowsingData: async (action) => ({ action, after: 0, before: 0, completedAt: 1 }),
    clearHistory: async () => [],
    getHistory: async () => [],
    getSettings: async () => ({ cacheBytes: 0, cookieCount: 0, downloadPath: '/tmp', partition: 'persist:paw-browser', permissionMode: 'site-request', startPage: 'about:blank' }),
    openDownloads: async () => ({ opened: true, path: '/tmp' }),
    register: () => undefined,
    removeHistoryEntry: async () => [],
    setStartPage: async (startPage) => ({ startPage }),
    takeScreenshot: async () => ({ path: '/tmp/page.png', saved: true }),
    onCommand,
    onGuestClosed: () => () => undefined,
    onHistoryChanged: () => () => undefined,
    onOpenUrl: () => () => undefined,
    onSelectTab: () => () => undefined,
  };
}
