import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { PawOsTerminalApp } from './PawOsTerminalApp';
import { PawWindowFrame } from '@/paw-os/shell/PawWindowLayer';
import terminalCss from './paw-os-terminal-app.css?raw';

const xtermConstructorOptions = vi.hoisted(() => [] as Record<string, unknown>[]);

vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }));
vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    cols = 104;
    rows = 30;
    private host?: HTMLElement;
    private onDataCallback: (data: string) => void = () => undefined;

    constructor(options: Record<string, unknown>) {
      xtermConstructorOptions.push(options);
    }

    loadAddon() {}
    open(host: HTMLElement) {
      this.host = host;
      const input = document.createElement('textarea');
      input.setAttribute('aria-label', '终端输入');
      input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') this.onDataCallback('\r');
        else if (event.key.length === 1) this.onDataCallback(event.key);
      });
      host.append(input);
    }
    onData(callback: (data: string) => void) {
      this.onDataCallback = callback;
      return { dispose() {} };
    }
    focus() {}
    reset() { this.host?.replaceChildren(); }
    write(text: string) {
      const output = document.createElement('pre');
      output.textContent = text;
      this.host?.append(output);
    }
    dispose() {}
  },
}));

afterEach(() => {
  cleanup();
  xtermConstructorOptions.length = 0;
  delete document.documentElement.dataset.reduceMotion;
  delete (window as Window & { pawTerminalHost?: unknown }).pawTerminalHost;
});

describe('PawOsTerminalApp', () => {
  it('writes commands to a real system terminal route without wrapping them in an Agent prompt', async () => {
    const user = userEvent.setup();
    let output = '';
    const terminal = {
      terminalId: 'terminal-system',
      title: 'System Terminal',
      cwd: '/workspace/paw',
      shell: '/bin/zsh',
      pid: 4242,
      cols: 104,
      rows: 30,
      status: 'running',
      exitCode: null,
      baseCursor: 0,
      nextCursor: 0,
      createdAtMs: 1,
    };
    const transport = new MockControlTransport({
      routes: {
        'terminal.sessions.list': () => ({
          schemaVersion: 'rag-ime.system-terminal.v1',
          ok: true,
          items: [{ ...terminal, nextCursor: output.length }],
        }),
        'terminal.session.read': (request: ControlRequest) => {
          const body = asRecord(request.body);
          const cursor = Number(body.cursor ?? 0);
          return {
            schemaVersion: 'rag-ime.system-terminal.v1',
            ok: true,
            terminal: { ...terminal, nextCursor: output.length },
            cursor,
            nextCursor: output.length,
            truncated: false,
            text: output.slice(cursor),
          };
        },
        'terminal.session.write': (request: ControlRequest) => {
          output += String(asRecord(request.body).text ?? '');
          return { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminalId: terminal.terminalId, bytesWritten: output.length };
        },
        'terminal.session.resize': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminalId: terminal.terminalId },
        'terminal.session.create': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminal },
        'terminal.session.close': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminal: { ...terminal, status: 'closed' } },
      },
    });

    renderApp(transport, <PawOsTerminalApp />);

    expect(await screen.findByRole('heading', { name: 'Terminal', level: 1 })).toBeInTheDocument();
    expect(await screen.findByText('/workspace/paw')).toBeInTheDocument();
    expect(screen.getByText('pid 4242')).toBeInTheDocument();
    expect(screen.getByText('UTF-8')).toBeInTheDocument();
    await user.type(await screen.findByRole('textbox', { name: '终端输入' }), 'printf PAW_PTY_OK{Enter}');

    await waitFor(() => expect(transport.requests
      .filter((call) => call.request.pathId === 'terminal.session.write')
      .map((call) => String(asRecord(call.request.body).text ?? ''))
      .join(''))
      .toBe('printf PAW_PTY_OK\r'));
    expect(output).toBe('printf PAW_PTY_OK\r');
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(false);
  });

  it('keeps live terminal tabs, creation, selection, and close in window chrome', async () => {
    const user = userEvent.setup();
    const terminal = terminalSession('terminal-one', 'Terminal One');
    let terminals = [terminal];
    const transport = new MockControlTransport({
      routes: {
        'terminal.sessions.list': () => ({ schemaVersion: 'rag-ime.system-terminal.v1', ok: true, items: terminals }),
        'terminal.session.read': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminal, cursor: 0, nextCursor: 0, truncated: false, text: '' },
        'terminal.session.resize': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminalId: terminal.terminalId },
        'terminal.session.create': () => {
          const created = terminalSession('terminal-two', 'Terminal Two');
          terminals = [...terminals, created];
          return { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminal: created };
        },
        'terminal.session.close': (request: ControlRequest) => {
          const terminalId = String(asRecord(request.body).terminalId ?? '');
          terminals = terminals.filter((item) => item.terminalId !== terminalId);
          return { schemaVersion: 'rag-ime.system-terminal.v1', ok: true };
        },
      },
    });

    renderApp(transport, (
      <PawWindowFrame
        active
        appId="terminal"
        bounds={{ x: 0, y: 0, width: 900, height: 640 }}
        onBoundsCommit={() => undefined}
        onClose={() => undefined}
        onFocus={() => undefined}
        onMinimize={() => undefined}
        onToggleMaximize={() => undefined}
        title="Terminal"
        windowChrome="terminal-tabs"
        windowId="terminal"
        zIndex={10}
      >
        <PawOsTerminalApp />
      </PawWindowFrame>
    ));

    const titlebar = screen.getByLabelText('Terminal窗口').querySelector('.paw-window-titlebar') as HTMLElement;
    const tablist = await within(titlebar).findByRole('tablist', { name: 'PAWOS 终端' });
    const firstTab = await within(tablist).findByRole('tab', { name: /Terminal One/ });
    const terminalPanel = screen.getByRole('tabpanel', { name: /Terminal One/ });
    expect(firstTab.querySelector(':scope > svg')).toBeNull();
    expect(firstTab).toHaveAttribute('aria-controls', terminalPanel.id);
    expect(firstTab).toHaveAttribute('tabindex', '0');
    expect(terminalPanel).toHaveAttribute('aria-labelledby', firstTab.id);
    expect(document.querySelector('.paw-window-body .paw-terminal-app__toolbar')).toBeNull();
    expect(within(titlebar).getByRole('button', { name: '关闭窗口' })).toBeInTheDocument();
    expect(within(tablist).getByRole('button', { name: '结束终端会话 Terminal One' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '关闭当前终端' })).not.toBeInTheDocument();
    // The new-terminal action must not scroll away with an overflowing tab strip.
    const newTerminalButton = within(titlebar).getByRole('button', { name: '新建终端' });
    expect(tablist.contains(newTerminalButton)).toBe(false);
    await user.click(newTerminalButton);
    await waitFor(() => expect(within(tablist).getAllByRole('tab')).toHaveLength(2));
    const secondTab = within(tablist).getByRole('tab', { name: /Terminal Two/ });
    expect(secondTab).toHaveAttribute('aria-selected', 'true');
    expect(secondTab).toHaveAttribute('tabindex', '0');
    expect(firstTab).toHaveAttribute('tabindex', '-1');

    secondTab.focus();
    await user.keyboard('{ArrowLeft}');
    expect(firstTab).toHaveAttribute('aria-selected', 'true');
    expect(firstTab).toHaveFocus();
    await user.keyboard('{End}');
    expect(secondTab).toHaveAttribute('aria-selected', 'true');
    expect(secondTab).toHaveFocus();
    await user.keyboard('{Home}');
    expect(firstTab).toHaveAttribute('aria-selected', 'true');
    expect(firstTab).toHaveFocus();
    await user.keyboard('{ArrowLeft}');
    expect(secondTab).toHaveAttribute('aria-selected', 'true');
    expect(secondTab).toHaveFocus();

    await user.click(within(tablist).getByRole('button', { name: '结束终端会话 Terminal Two' }));
    await waitFor(() => expect(within(tablist).getAllByRole('tab')).toHaveLength(1));
  });

  it('uses an action-oriented empty state without repeating Terminal App identity', async () => {
    const pendingCreate = new Promise<never>(() => undefined);
    const transport = new MockControlTransport({
      routes: {
        'terminal.sessions.list': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, items: [] },
        'terminal.session.create': () => pendingCreate,
      },
    });

    const { container } = renderTerminal(transport, <PawOsTerminalApp />);

    expect(await screen.findByText('还没有终端会话')).toBeInTheDocument();
    expect(container.querySelector('.paw-terminal-console__empty > svg')).toBeNull();
    expect(screen.queryByText('PAWOS 终端')).not.toBeInTheDocument();
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.getByRole('button', { name: /^(?:新建终端|正在创建)$/ })).toBeInTheDocument();
  });

  it('always creates the PAWOS embedded PTY and ignores a legacy external-terminal bridge', async () => {
    const calls: string[] = [];
    const terminal = terminalSession('terminal-embedded', 'Terminal');
    let terminals: ReturnType<typeof terminalSession>[] = [];
    (window as Window & { pawTerminalHost?: unknown }).pawTerminalHost = {
      kind: 'electron-terminal-host',
      closeSurface: async () => { calls.push('close'); return { ok: true }; },
      focusSurface: async () => { calls.push('focus'); return { ok: false }; },
      getStatus: async () => ({ ok: true, external: true }),
      listSurfaces: async () => ({ ok: true, external: true, items: [] }),
      openBackgroundJob: async () => { calls.push('background'); return { ok: false }; },
      openShell: async () => { calls.push('open'); return { ok: false }; },
    };
    const transport = new MockControlTransport({
      routes: {
        'terminal.sessions.list': () => ({ schemaVersion: 'rag-ime.system-terminal.v1', ok: true, items: terminals }),
        'terminal.session.create': () => {
          terminals = [terminal];
          return { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminal };
        },
        'terminal.session.read': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminal, cursor: 0, nextCursor: 0, truncated: false, text: '' },
        'terminal.session.resize': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminalId: terminal.terminalId },
      },
    });

    renderApp(transport, <PawOsTerminalApp />);

    expect(await screen.findByLabelText('终端输入输出')).toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'terminal.session.create')).toBe(true);
    expect(calls).toEqual([]);
    expect(screen.queryByText('外部终端')).not.toBeInTheDocument();
  });

  it('numbers repeated session titles so every tab keeps a distinct identity and scrolls the selection into view', async () => {
    const user = userEvent.setup();
    const scrollIntoView = vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockImplementation(() => undefined);
    const first = terminalSession('terminal-one', 'Terminal');
    const second = terminalSession('terminal-two', 'Terminal');
    const transport = new MockControlTransport({
      routes: {
        'terminal.sessions.list': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, items: [first, second] },
        'terminal.session.read': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminal: second, cursor: 0, nextCursor: 0, truncated: false, text: '' },
        'terminal.session.resize': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminalId: second.terminalId },
      },
    });

    try {
      renderApp(transport, <PawOsTerminalApp />);

      const firstTab = await screen.findByRole('tab', { name: 'Terminal 1' });
      const secondTab = screen.getByRole('tab', { name: 'Terminal 2' });
      expect(firstTab).toHaveAttribute('title', 'Terminal 1 · /bin/zsh · /workspace/paw');
      expect(secondTab).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByRole('button', { name: '结束终端会话 Terminal 1' })).toBeInTheDocument();
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());

      scrollIntoView.mockClear();
      await user.click(firstTab);
      expect(firstTab).toHaveAttribute('aria-selected', 'true');
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
    } finally {
      scrollIntoView.mockRestore();
    }
  });

  it('keeps an ended session readable, states the exit truthfully, and never reruns or forwards input', async () => {
    const user = userEvent.setup();
    const exited = { ...terminalSession('terminal-exited', 'Terminal'), status: 'exited' as const, exitCode: 1 };
    let terminals = [exited];
    const transport = new MockControlTransport({
      routes: {
        'terminal.sessions.list': () => ({ schemaVersion: 'rag-ime.system-terminal.v1', ok: true, items: terminals }),
        'terminal.session.read': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminal: exited, cursor: 0, nextCursor: 0, truncated: false, text: '' },
        'terminal.session.resize': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminalId: exited.terminalId },
        'terminal.session.close': () => {
          terminals = [];
          return { schemaVersion: 'rag-ime.system-terminal.v1', ok: true };
        },
      },
    });

    renderApp(transport, <PawOsTerminalApp />);

    // Viewing an existing exited session must not invent a new one.
    const tab = await screen.findByRole('tab', { name: /Terminal.*已退出（退出码 1）/ });
    expect(transport.requests.some((call) => call.request.pathId === 'terminal.session.create')).toBe(false);
    expect(tab.querySelector('i[data-state="exited"][data-exit-failure]')).not.toBeNull();

    const notice = screen.getByRole('status');
    expect(notice).toHaveTextContent('这个终端会话已退出（退出码 1）。输出仍可回看，输入不会再发送。');
    expect(within(notice).getByRole('button', { name: '新建终端' })).toBeInTheDocument();

    // Typed input is refused locally with a dismissible explanation.
    await user.type(await screen.findByRole('textbox', { name: '终端输入' }), 'x');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('这个终端已退出，输入没有发送。');
    expect(transport.requests.some((call) => call.request.pathId === 'terminal.session.write')).toBe(false);
    await user.click(within(alert).getByRole('button', { name: '关闭错误提示' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    // The notice can end the tab identity explicitly.
    await user.click(within(notice).getByRole('button', { name: '关闭此标签页' }));
    expect(await screen.findByText('还没有终端会话')).toBeInTheDocument();
    expect(transport.requests.filter((call) => call.request.pathId === 'terminal.session.close')).toHaveLength(1);
    expect(transport.requests.some((call) => call.request.pathId === 'terminal.session.create')).toBe(false);
  });

  it('lets a failed create be dismissed instead of leaving a stuck banner', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'terminal.sessions.list': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, items: [] },
        'terminal.session.create': () => {
          throw new Error('后端拒绝了新终端');
        },
      },
    });

    renderApp(transport, <PawOsTerminalApp />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('新建终端失败：后端拒绝了新终端');
    await user.click(within(alert).getByRole('button', { name: '关闭错误提示' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '新建终端' })).toBeInTheDocument();
  });

  it('offers an immediate retry when the session list cannot be read', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'terminal.sessions.list': () => {
          throw new Error('系统终端服务未连接');
        },
      },
    });

    renderApp(transport, <PawOsTerminalApp />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('读取终端会话失败：系统终端服务未连接');
    // A failed list read proves nothing about existing sessions; it must not
    // fall through to the first-load auto-create.
    expect(transport.requests.some((call) => call.request.pathId === 'terminal.session.create')).toBe(false);
    const listCalls = () => transport.requests.filter((call) => call.request.pathId === 'terminal.sessions.list').length;
    const before = listCalls();
    await user.click(within(alert).getByRole('button', { name: '重试' }));
    await waitFor(() => expect(listCalls()).toBeGreaterThan(before));
  });

  it('disables the blinking cursor when PAWOS reduced motion is active', async () => {
    document.documentElement.dataset.reduceMotion = 'true';
    const terminal = terminalSession('terminal-calm', 'Terminal');
    const transport = new MockControlTransport({
      routes: {
        'terminal.sessions.list': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, items: [terminal] },
        'terminal.session.read': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminal, cursor: 0, nextCursor: 0, truncated: false, text: '' },
        'terminal.session.resize': { schemaVersion: 'rag-ime.system-terminal.v1', ok: true, terminalId: terminal.terminalId },
      },
    });

    renderApp(transport, <PawOsTerminalApp />);

    expect(await screen.findByLabelText('终端输入输出')).toBeInTheDocument();
    await waitFor(() => expect(xtermConstructorOptions.length).toBeGreaterThan(0));
    expect(xtermConstructorOptions.at(-1)).toMatchObject({ cursorBlink: false });
  });
});

describe('paw-os-terminal-app.css contracts', () => {
  it('keeps the ended-session notice inside the console grid without displacing the status footer', () => {
    expect(terminalCss).toMatch(/\.paw-terminal-console\[data-session\]\s*\{[\s\S]*?grid-template-rows:\s*minmax\(0, 1fr\) 30px;/s);
    expect(terminalCss).toMatch(/\.paw-terminal-console\[data-session\]\[data-ended\]\s*\{[\s\S]*?grid-template-rows:\s*minmax\(0, 1fr\) auto 30px;/s);
  });

  it('keeps the tab strip locally scrollable while the new-terminal action stays outside it', () => {
    expect(terminalCss).toMatch(/\.paw-terminal-tabs\s*\{[^}]*overflow-x:\s*auto;[^}]*\}/s);
    expect(terminalCss).toMatch(/\.paw-terminal-tab-new\s*\{[^}]*flex:\s*0 0 auto;/s);
  });

  it('silences terminal motion for both the OS media query and the PAWOS preference', () => {
    expect(terminalCss).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.paw-terminal-ended,[\s\S]*?animation:\s*none;/s);
    expect(terminalCss).toMatch(/:root\[data-reduce-motion='true'\] \.paw-terminal-tab-main i\[data-state="running"\]::after\s*\{\s*animation:\s*none;/s);
  });
});

function terminalSession(terminalId: string, title: string) {
  return {
    terminalId,
    title,
    cwd: '/workspace/paw',
    shell: '/bin/zsh',
    pid: 4242,
    cols: 104,
    rows: 30,
    status: 'running' as const,
    exitCode: null,
    baseCursor: 0,
    nextCursor: 0,
    createdAtMs: 1,
  };
}

function renderApp(transport: MockControlTransport, child: React.ReactNode): void {
  renderTerminal(transport, child);
}

function renderTerminal(transport: MockControlTransport, child: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ControlTransportProvider transport={transport}>{child}</ControlTransportProvider>
    </QueryClientProvider>,
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
