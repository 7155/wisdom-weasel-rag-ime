import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { GlobalFeedbackProvider } from '@/components/feedback';
import { MockControlTransport } from '@/test/mock-transport';
import { PawDesktopProvider } from '../runtime/desktop-context';
import { pawApps, type PawAppId } from '../runtime/app-registry';
import { PawDesktop } from './PawDesktop';
import desktopSource from './PawDesktop.tsx?raw';

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

  it('names the menu bar 桌面 when no window is focused instead of borrowing Workbench', () => {
    renderDesktop();
    const current = document.querySelector('.paw-menu-app') as HTMLElement;
    expect(current).toHaveAttribute('data-idle');
    expect(current).toHaveTextContent('桌面');
    expect(current.querySelector('[data-paw-app-icon]')).toBeNull();
  });

  it('opens hide and overview commands from the menu bar App name', () => {
    renderDesktop('agent');
    fireEvent.click(screen.getByRole('button', { name: 'Agent 菜单' }));
    expect(screen.getByRole('menu', { name: 'Agent 菜单' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('menuitem', { name: '隐藏窗口' }));
    expect(document.querySelector('[data-paw-window-id="agent"]')).toBeNull();
    const agentDock = within(screen.getByRole('navigation', { name: 'PAWOS 工具架' })).getByRole('button', { name: 'Agent' });
    expect(agentDock).toHaveAttribute('data-open');
    expect(agentDock).toHaveAttribute('data-minimized');
  });

  it('filters Launchpad Apps from the archive search field', () => {
    renderDesktop();
    fireEvent.click(screen.getByRole('button', { name: '全部 App' }));
    const launcher = screen.getByRole('dialog', { name: '全部 App' });
    fireEvent.change(within(launcher).getByRole('searchbox', { name: '搜索 App' }), { target: { value: 'Terminal' } });
    expect(within(launcher).getByRole('button', { name: /Terminal/ })).toBeInTheDocument();
    expect(within(launcher).queryByRole('button', { name: /Agent/ })).not.toBeInTheDocument();
    expect(within(launcher).getByRole('heading', { name: '工具' })).toBeInTheDocument();
  });

  it('gives every Launchpad group header its own cascade beat ahead of its tiles', () => {
    renderDesktop();
    fireEvent.click(screen.getByRole('button', { name: '全部 App' }));
    const launcher = screen.getByRole('dialog', { name: '全部 App' });

    const beats = Array.from(launcher.querySelectorAll<HTMLElement>('[style*="--paw-tile-i"]'))
      .map((element) => ({
        header: element.classList.contains('paw-launchpad-group'),
        beat: Number.parseInt(element.style.getPropertyValue('--paw-tile-i'), 10),
      }));
    expect(beats.length).toBeGreaterThan(pawApps.length);
    // One shared clock in document order: header, then its tiles, then the
    // next header — every element knows exactly one beat.
    beats.forEach(({ beat }, index) => expect(beat).toBe(index));
    expect(beats[0]?.header).toBe(true);
    expect(beats.filter(({ header }) => header).length).toBeGreaterThanOrEqual(3);
  });

  it('leads the first viewport with a dense Wayfinder list of every desktop entry', () => {
    renderDesktop();
    const shortcuts = screen.getByLabelText('桌面 App');
    const rows = within(shortcuts).getAllByRole('button');
    // One compact row per identity — label only, no taglines or marketing
    // copy competing with the fog field.
    expect(rows.map((row) => row.textContent)).toEqual(['项目', 'Agent', '文件', '浏览器', '终端']);
    for (const row of rows) {
      expect(row.querySelector('[data-paw-app-icon]')).toBeInTheDocument();
    }
  });

  it('projects the Dock running language onto Wayfinder rows without renaming them', () => {
    // Reduced motion lets minimize complete synchronously, as in the Dock test.
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
    const shortcuts = screen.getByLabelText('桌面 App');
    const agentRow = within(shortcuts).getByRole('button', { name: 'Agent' });
    expect(agentRow).toHaveAttribute('data-open');
    expect(agentRow).not.toHaveAttribute('data-minimized');
    expect(within(shortcuts).getByRole('button', { name: '文件' })).not.toHaveAttribute('data-open');

    fireEvent.click(screen.getByRole('button', { name: '最小化窗口' }));
    expect(agentRow).toHaveAttribute('data-open');
    expect(agentRow).toHaveAttribute('data-minimized');
    // The state lives in title/shape, so the accessible name stays the bare
    // label and every exact-name query in this suite keeps working.
    expect(agentRow).toHaveAttribute('title', 'Agent · 已最小化');
  });

  it('walks desktop shortcuts with roving arrow keys instead of tabbing out', () => {
    renderDesktop();
    const shortcuts = screen.getByLabelText('桌面 App');
    const buttons = within(shortcuts).getAllByRole('button');
    expect(buttons.length).toBeGreaterThanOrEqual(5);

    buttons[0]!.focus();
    fireEvent.keyDown(shortcuts, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(buttons[1]);
    fireEvent.keyDown(shortcuts, { key: 'End' });
    expect(document.activeElement).toBe(buttons.at(-1));
    fireEvent.keyDown(shortcuts, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(buttons.at(-1));
    fireEvent.keyDown(shortcuts, { key: 'Home' });
    expect(document.activeElement).toBe(buttons[0]);
    fireEvent.keyDown(shortcuts, { key: 'ArrowUp' });
    expect(document.activeElement).toBe(buttons[0]);
  });

  it('opens System Settings from the advertised keyboard shortcut', () => {
    renderDesktop();
    fireEvent.keyDown(window, { key: ',', metaKey: true });
    expect(document.querySelector('[data-paw-window-id="system-settings"]')).toBeInTheDocument();
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
    // Prefer reduced-motion so minimize completes synchronously for Dock state.
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

  it('gives every Dock control a hover name label that stays out of the accessible name', () => {
    renderDesktop('agent');
    const dock = screen.getByRole('navigation', { name: 'PAWOS 工具架' });

    // The exact-name queries above only stay stable if the visual label is
    // aria-hidden; the button keeps its aria-label as the accessible name.
    const agentTip = within(dock).getByRole('button', { name: 'Agent' }).querySelector('.paw-dock-tip');
    expect(agentTip).toHaveAttribute('aria-hidden', 'true');
    expect(agentTip).toHaveTextContent('Agent');
    expect(within(dock).getByRole('button', { name: '窗口总览' }).querySelector('.paw-dock-tip')).toHaveTextContent('窗口总览');
    expect(within(dock).getByRole('button', { name: '全部 App' }).querySelector('.paw-dock-tip')).toHaveTextContent('全部 App');
  });

  it('closes all PAWOS windows from the desktop menu in one projection-only action', () => {
    renderDesktop('agent');
    const desktop = screen.getByRole('main');

    fireEvent.contextMenu(desktop, { clientX: 120, clientY: 90 });
    fireEvent.click(screen.getByRole('menuitem', { name: '关闭全部窗口' }));

    expect(document.querySelectorAll('[data-paw-window-id]')).toHaveLength(0);
  });

  it('routes a Browser host command into PAWOS before the Browser App is mounted', async () => {
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
    // Persistence lands one debounce beat after the interaction.
    await waitFor(() => {
      const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
        windows?: Record<string, { target?: { commandId?: string; url?: string } }>;
      };
      expect(snapshot.windows?.browser?.target).toMatchObject({
        commandId: 'command-1',
        url: 'https://inside.example',
      });
    });
  });

  it('pauses the ambient wallpaper while an App window owns focus and resumes on an empty desktop', () => {
    // Reduced motion lets minimize complete synchronously, as in the Dock test.
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
    const desktop = document.querySelector('.paw-desktop') as HTMLElement;
    // A focused window covers the field: every weather clock freezes.
    expect(desktop).toHaveAttribute('data-ambient-paused');

    fireEvent.click(screen.getByRole('button', { name: '最小化窗口' }));
    // The bare desktop is the only surface anyone can watch the scenery on.
    expect(desktop).not.toHaveAttribute('data-ambient-paused');
  });

  it('pauses the ambient wallpaper under the Launchpad veil and while the document is hidden', () => {
    renderDesktop();
    const desktop = document.querySelector('.paw-desktop') as HTMLElement;
    expect(desktop).not.toHaveAttribute('data-ambient-paused');

    // The Launchpad's full-screen backdrop blur must never re-blur a stepping
    // wallpaper underneath it.
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    expect(desktop).toHaveAttribute('data-ambient-paused');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(desktop).not.toHaveAttribute('data-ambient-paused');

    try {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
      fireEvent(document, new Event('visibilitychange'));
      expect(desktop).toHaveAttribute('data-ambient-paused');
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
      fireEvent(document, new Event('visibilitychange'));
      expect(desktop).not.toHaveAttribute('data-ambient-paused');
    } finally {
      delete (document as unknown as Record<string, unknown>).visibilityState;
    }
  });

  it('never subscribes shell chrome to the whole windows record', () => {
    // Bounds commits after every drag/resize/viewport refit and runtime
    // title/target binds replace state.windows; menu bar, Wayfinder, Dock and
    // Launchpad must not re-render on that churn. Menus subscribe to the
    // structural signature (id, App, placement) instead, and the half-minute
    // clock tick owns its own leaf so it re-renders one <span>.
    expect(desktopSource).not.toMatch(/usePawDesktopStore\(\(state\) => state\.windows\)/);
    expect(desktopSource).toContain('const menuSignature = usePawDesktopStore');
    expect(desktopSource).toContain('function PawMenuClock()');
    expect(desktopSource).toMatch(/<PawMenuClock \/>/);
  });

  it('still reflects placement changes in the window menu through the structural signature', () => {
    renderDesktop('agent');
    const windowShell = document.querySelector('[data-paw-window-id="agent"]') as HTMLElement;
    fireEvent.contextMenu(windowShell, { clientX: 300, clientY: 200 });
    fireEvent.click(screen.getByRole('menuitem', { name: '最大化' }));

    fireEvent.contextMenu(windowShell, { clientX: 300, clientY: 200 });
    expect(screen.getByRole('menuitem', { name: '还原窗口' })).toBeInTheDocument();
  });

  it('coalesces desktop persistence into one trailing write instead of one per mutation', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    renderDesktop();

    // A burst of desktop mutations: open two Apps back to back.
    fireEvent.keyDown(window, { key: ',', metaKey: true });
    fireEvent.contextMenu(screen.getByRole('main'), { clientX: 120, clientY: 90 });
    fireEvent.click(screen.getByRole('menuitem', { name: '新建 Agent 工作' }));

    // Nothing serializes on the interaction path itself…
    const writesBefore = setItem.mock.calls.filter(([key]) => key === 'pawos.desktop.v1');
    expect(writesBefore).toHaveLength(0);

    // …and the whole burst lands as one trailing snapshot.
    await waitFor(() => {
      expect(setItem.mock.calls.filter(([key]) => key === 'pawos.desktop.v1')).toHaveLength(1);
    });
    const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
      windows?: Record<string, unknown>;
    };
    expect(Object.keys(snapshot.windows ?? {})).toEqual(expect.arrayContaining(['system-settings', 'agent']));
    setItem.mockRestore();
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
