import { FitAddon } from '@xterm/addon-fit';
import { Terminal as Xterm } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Folder, LoaderCircle, Plus, TriangleAlert, X } from 'lucide-react';
import { type KeyboardEvent, useEffect, useId, useRef, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { PawWindowChromePortal, usePawWindowChromeTarget } from '@/paw-os/shell/PawWindowChrome';
import './paw-os-terminal-app.css';

type TerminalState = 'running' | 'exited' | 'closed';

interface TerminalSession {
  terminalId: string;
  title: string;
  cwd: string;
  shell: string;
  pid: number;
  cols: number;
  rows: number;
  status: TerminalState;
  exitCode: number | null;
  baseCursor: number;
  nextCursor: number;
  createdAtMs: number;
}

interface TerminalListResponse {
  schemaVersion: 'rag-ime.system-terminal.v1';
  ok: boolean;
  items: TerminalSession[];
}

interface TerminalReadResponse {
  schemaVersion: 'rag-ime.system-terminal.v1';
  ok: boolean;
  terminal: TerminalSession;
  cursor: number;
  nextCursor: number;
  truncated: boolean;
  text: string;
}

const terminalKeys = { root: ['system-terminal'] as const };
const emptySessions: TerminalSession[] = [];

export function PawOsTerminalApp() {
  const transport = useControlTransport();
  const windowChromeTarget = usePawWindowChromeTarget();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState('');
  const [cursor, setCursor] = useState(0);
  const [interactionError, setInteractionError] = useState('');
  const terminalTabsId = useId();
  const terminalHostRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Xterm | null>(null);
  const terminalTabRefs = useRef(new Map<string, HTMLButtonElement>());
  const autoCreated = useRef(false);

  const sessionsQuery = useQuery({
    queryKey: terminalKeys.root,
    queryFn: ({ signal }) => transport.request<TerminalListResponse>({ pathId: 'terminal.sessions.list', signal }),
    refetchInterval: 2_000,
  });
  const sessions = sessionsQuery.data?.items ?? emptySessions;
  const selected = sessions.find((item) => item.terminalId === selectedId) ?? null;
  const invalidate = async () => queryClient.invalidateQueries({ queryKey: terminalKeys.root });

  const create = useMutation({
    mutationFn: () => transport.request<{ terminal: TerminalSession }>({
      pathId: 'terminal.session.create',
      body: { title: 'Terminal', cols: 120, rows: 35 },
    }),
    onSuccess: async (value) => {
      await invalidate();
      setSelectedId(value.terminal.terminalId);
    },
  });

  const close = useMutation({
    mutationFn: (terminalId: string) => transport.request({
      pathId: 'terminal.session.close',
      body: { terminalId },
    }),
    onSuccess: invalidate,
  });

  useEffect(() => {
    if (autoCreated.current) return;
    if (!sessionsQuery.isPending && !sessions.some((item) => item.status === 'running')) {
      autoCreated.current = true;
      void create.mutateAsync();
    }
  }, [create, sessions, sessionsQuery.isPending]);

  useEffect(() => {
    if (!sessions.length) return;
    setSelectedId((current) => sessions.some((item) => item.terminalId === current) ? current : sessions.at(-1)?.terminalId ?? '');
  }, [sessions]);

  useEffect(() => {
    setCursor(0);
    setInteractionError('');
  }, [selectedId]);

  useEffect(() => {
    const host = terminalHostRef.current;
    if (!host || !selectedId) return;
    host.replaceChildren();
    const terminal = new Xterm({
      allowProposedApi: false,
      convertEol: true,
      cursorBlink: true,
      cursorStyle: 'bar',
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      fontSize: 13,
      lineHeight: 1.2,
      scrollback: 20_000,
      theme: {
        background: '#111214', foreground: '#e6e7ea', cursor: '#f4f4f5', selectionBackground: '#3b82f655',
        black: '#27272a', red: '#f87171', green: '#34d399', yellow: '#fbbf24', blue: '#60a5fa', magenta: '#c084fc', cyan: '#22d3ee', white: '#f4f4f5',
        brightBlack: '#71717a', brightRed: '#fca5a5', brightGreen: '#6ee7b7', brightYellow: '#fde68a', brightBlue: '#93c5fd', brightMagenta: '#d8b4fe', brightCyan: '#67e8f9', brightWhite: '#ffffff',
      },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(host);
    terminalRef.current = terminal;
    let pendingInput = '';
    let inputTimer = 0;
    let lastSize = '';

    const flushInput = () => {
      inputTimer = 0;
      const text = pendingInput;
      pendingInput = '';
      if (!text) return;
      void transport.request({ pathId: 'terminal.session.write', body: { terminalId: selectedId, text } })
        .catch((error: unknown) => setInteractionError(publicError(error)));
    };
    const dataSubscription = terminal.onData((data) => {
      pendingInput += data;
      if (!inputTimer) inputTimer = window.setTimeout(flushInput, 12);
    });
    const fitTerminal = () => {
      fit.fit();
      const size = `${terminal.cols}:${terminal.rows}`;
      if (size === lastSize) return;
      lastSize = size;
      void transport.request({ pathId: 'terminal.session.resize', body: { terminalId: selectedId, cols: terminal.cols, rows: terminal.rows } })
        .catch((error: unknown) => setInteractionError(publicError(error)));
    };
    const observer = new ResizeObserver(fitTerminal);
    observer.observe(host);
    const frame = window.requestAnimationFrame(() => {
      fitTerminal();
      terminal.focus();
    });

    return () => {
      if (inputTimer) window.clearTimeout(inputTimer);
      flushInput();
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      dataSubscription.dispose();
      terminal.dispose();
      if (terminalRef.current === terminal) terminalRef.current = null;
    };
  }, [selectedId, transport]);

  const readQuery = useQuery({
    queryKey: [...terminalKeys.root, 'read', selectedId, cursor],
    enabled: Boolean(selectedId),
    queryFn: ({ signal }) => transport.request<TerminalReadResponse>({
      pathId: 'terminal.session.read',
      body: { terminalId: selectedId, cursor, maxBytes: 262_144 },
      signal,
    }),
    refetchInterval: selected?.status === 'running' ? 120 : 1_000,
    retry: false,
  });

  useEffect(() => {
    const chunk = readQuery.data;
    const terminal = terminalRef.current;
    if (!chunk || !terminal) return;
    if (chunk.truncated) terminal.reset();
    if (chunk.text) terminal.write(chunk.text);
    if (chunk.nextCursor !== cursor) setCursor(chunk.nextCursor);
  }, [cursor, readQuery.data]);

  const error = sessionsQuery.error || create.error || close.error || readQuery.error;
  const terminalPanelId = `${terminalTabsId}-panel`;
  const selectedTabId = selected ? `${terminalTabsId}-tab-${selected.terminalId}` : undefined;

  const selectTerminalTab = (terminalId: string, focus = false) => {
    setSelectedId(terminalId);
    if (focus) terminalTabRefs.current.get(terminalId)?.focus();
  };

  const onTerminalTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex: number | undefined;
    if (event.key === 'ArrowLeft') nextIndex = (index - 1 + sessions.length) % sessions.length;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % sessions.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = sessions.length - 1;
    if (nextIndex === undefined) return;
    event.preventDefault();
    const nextTerminal = sessions[nextIndex];
    if (nextTerminal) selectTerminalTab(nextTerminal.terminalId, true);
  };

  const terminalTabs = (
    <div className="paw-terminal-app__toolbar" data-window-chrome={windowChromeTarget ? true : undefined}>
      <div aria-label="PAWOS 终端" aria-orientation="horizontal" className="paw-terminal-tabs" role="tablist">
        {sessions.map((terminal, index) => {
          const active = terminal.terminalId === selectedId;
          const title = terminal.title || `终端 ${index + 1}`;
          const tabId = `${terminalTabsId}-tab-${terminal.terminalId}`;
          return (
            <div className="paw-terminal-tab" data-selected={active || undefined} key={terminal.terminalId} role="presentation">
              <button
                aria-controls={terminalPanelId}
                aria-selected={active}
                className="paw-terminal-tab-main"
                id={tabId}
                onClick={() => selectTerminalTab(terminal.terminalId)}
                onKeyDown={(event) => onTerminalTabKeyDown(event, index)}
                ref={(node) => {
                  if (node) terminalTabRefs.current.set(terminal.terminalId, node);
                  else terminalTabRefs.current.delete(terminal.terminalId);
                }}
                role="tab"
                tabIndex={active ? 0 : -1}
                title={title}
                type="button"
              >
                <span>{title}</span><i data-state={terminal.status} />
              </button>
              <button
                aria-busy={close.isPending && close.variables === terminal.terminalId ? true : undefined}
                aria-label={`结束终端会话 ${title}`}
                className="paw-tab-close"
                disabled={close.isPending}
                onClick={() => void close.mutateAsync(terminal.terminalId)}
                title={`结束终端会话 ${title}`}
                type="button"
              >
                <X size={11} />
              </button>
            </div>
          );
        })}
        {sessions.length ? (
          <button aria-busy={create.isPending || undefined} aria-label="新建终端" className="paw-terminal-tab-new" disabled={create.isPending} onClick={() => create.mutate()} type="button">
            {create.isPending ? <LoaderCircle className="ui-spin" size={13} /> : <Plus size={13} />}
          </button>
        ) : null}
      </div>
    </div>
  );

  return (
    <>
      {windowChromeTarget ? <PawWindowChromePortal>{terminalTabs}</PawWindowChromePortal> : null}
      <section className="paw-terminal-app" data-error={(error || interactionError) ? true : undefined} data-tabs-in-window-chrome={windowChromeTarget ? true : undefined}>
        <h1 className="sr-only">Terminal</h1>
        {windowChromeTarget ? null : terminalTabs}

        {error || interactionError ? <div className="paw-terminal-error" role="alert"><TriangleAlert size={15} /><span>{interactionError || publicError(error)}</span></div> : null}

        <div className="paw-terminal-app__workspace">
          <main
            aria-labelledby={selectedTabId}
            className="paw-terminal-console"
            data-session={selected ? true : undefined}
            id={terminalPanelId}
            role={selected ? 'tabpanel' : undefined}
          >
            {selected ? <div aria-label="终端输入输出" className="paw-terminal-xterm" onClick={() => terminalRef.current?.focus()} ref={terminalHostRef} /> : <div className="paw-terminal-console__empty"><p>还没有终端会话</p><button aria-busy={create.isPending || undefined} disabled={create.isPending} onClick={() => create.mutate()} type="button">{create.isPending ? <LoaderCircle className="ui-spin" size={14} /> : <Plus size={14} />}{create.isPending ? '正在创建' : '新建终端'}</button></div>}
            {selected ? (
              <footer className="paw-terminal-statusbar">
                <span className="paw-terminal-cwd" title={selected.cwd}><Folder size={11} />{selected.cwd}</span>
                <i aria-hidden="true" />
                <strong className="paw-terminal-shell" title={selected.shell || '/bin/zsh'}>{selected.shell || '/bin/zsh'}</strong>
                <i aria-hidden="true" />
                <span>pid {selected.pid}</span>
                <i aria-hidden="true" />
                <span>UTF-8</span>
                <i aria-hidden="true" />
                <span>{selected.cols}×{selected.rows}</span>
                <span className="paw-terminal-state-tag">
                  {selected.status === 'running'
                    ? <span className="paw-terminal-running-badge"><i aria-hidden="true" />运行中</span>
                    : <span className="paw-terminal-exited-badge">已退出 ({selected.exitCode ?? 0})</span>}
                </span>
              </footer>
            ) : null}
          </main>
        </div>
      </section>
    </>
  );
}

function publicError(error: unknown): string {
  return error instanceof Error && error.message.trim() ? error.message : '系统终端暂时不可用。';
}
