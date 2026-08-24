import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { PawOsFilesApp } from './PawOsFilesApp';
import { PawWindowFrame } from '@/paw-os/shell/PawWindowLayer';
import filesCss from './paw-os-files-app.css?raw';

afterEach(cleanup);

describe('PawOsFilesApp', () => {
  it('keeps its accessible title out of the workspace grid at every window width', () => {
    const transport = new MockControlTransport({ routes: { 'agent.sessions.list': { ok: true, items: [] } } });
    renderApp(transport, <PawOsFilesApp />);

    expect(screen.getByRole('heading', { name: 'Session 文件', level: 1 })).toHaveClass('paw-files-app__title');
    expect(filesCss).toMatch(/\.paw-files-app__title\s*\{[^}]*position:\s*absolute;/s);
  });

  it('browses only the selected Session authorized roots and previews a file', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [
            {
              id: 'session-work',
              title: 'PAWOS 迁移',
              updatedAtMs: 1,
              workspaceRoots: ['/workspace/paw'],
              status: 'idle',
            },
            {
              id: 'session-empty',
              title: '无项目对话',
              updatedAtMs: 0,
              workspaceRoots: [],
              status: 'idle',
            },
          ],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [
            { path: '/workspace/paw/docs', name: 'docs', kind: 'directory' },
            { path: '/workspace/paw/AGENTS.md', name: 'AGENTS.md', kind: 'file', byteSize: 128 },
          ],
        },
        'agent.session.workspace.read': {
          ok: true,
          path: '/workspace/paw/AGENTS.md',
          content: '# Project guide\nRead docs before work.',
          byteSize: 38,
          truncated: false,
        },
      },
    });

    renderApp(transport, <PawOsFilesApp />);

    expect(await screen.findByRole('heading', { name: 'Session 文件', level: 1 })).toBeInTheDocument();
    expect(screen.getByText('/workspace/paw')).toBeInTheDocument();
    expect(screen.queryByText('/Users')).not.toBeInTheDocument();
    await user.click(await screen.findByRole('treeitem', { name: '打开文件 AGENTS.md' }));
    expect(await screen.findByRole('heading', { name: 'AGENTS.md', level: 2 })).toBeInTheDocument();
    expect(screen.getByText('Project guide')).toBeInTheDocument();
    expect(screen.getByText(/已选 AGENTS\.md · 128 B/)).toBeInTheDocument();
    expect(screen.getByText('1 个授权工作区')).toBeInTheDocument();

    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.session.workspace.read'
      && call.request.params?.sessionId === 'session-work'
      && call.request.query?.path === '/workspace/paw/AGENTS.md'
    ))).toBe(true));
  });

  it('projects its live Session selector and refresh action into window chrome', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-one',
          items: [
            { id: 'session-one', title: 'Project One', updatedAtMs: 2, workspaceRoots: ['/workspace/one'], status: 'idle' },
            { id: 'session-two', title: 'Project Two', updatedAtMs: 1, workspaceRoots: ['/workspace/two'], status: 'idle' },
          ],
        },
        'agent.session.workspace.list': (request: ControlRequest) => ({ ok: true, path: request.query?.path, items: [] }),
      },
    });

    renderApp(transport, (
      <PawWindowFrame
        active
        appId="files"
        bounds={{ x: 0, y: 0, width: 900, height: 640 }}
        onBoundsCommit={() => undefined}
        onClose={() => undefined}
        onFocus={() => undefined}
        onMinimize={() => undefined}
        onToggleMaximize={() => undefined}
        title="Files"
        windowChrome="files-tools"
        windowId="files"
        zIndex={10}
      >
        <PawOsFilesApp />
      </PawWindowFrame>
    ));

    const titlebar = screen.getByText('Files').closest('.paw-window-titlebar') as HTMLElement;
    const selector = await within(titlebar).findByRole('combobox', { name: '选择文件所属 Session' });
    expect(document.querySelector('.paw-window-body .paw-files-app__toolbar')).toBeNull();
    await user.selectOptions(selector, 'session-two');
    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.session.workspace.list'
      && call.request.params?.sessionId === 'session-two'
      && call.request.query?.path === '/workspace/two'
    ))).toBe(true));
    const requestsBeforeRefresh = transport.requests.filter((call) => call.request.pathId === 'agent.session.workspace.list').length;
    await user.click(within(titlebar).getByRole('button', { name: '刷新文件' }));
    await waitFor(() => expect(transport.requests.filter((call) => call.request.pathId === 'agent.session.workspace.list')).toHaveLength(requestsBeforeRefresh + 1));
  });

  it('uses one roving keyboard tree and refreshes every expanded directory', async () => {
    const user = userEvent.setup();
    const directoryReads: string[] = [];
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': (request: ControlRequest) => {
          const path = String(request.query?.path ?? '');
          directoryReads.push(path);
          if (path === '/workspace/paw/docs') return {
            ok: true,
            path,
            items: [{ path: `${path}/guide.md`, name: 'guide.md', kind: 'file', byteSize: 42 }],
          };
          return {
            ok: true,
            path,
            items: [
              { path: '/workspace/paw/docs', name: 'docs', kind: 'directory' },
              { path: '/workspace/paw/AGENTS.md', name: 'AGENTS.md', kind: 'file', byteSize: 128 },
            ],
          };
        },
        'agent.session.workspace.read': (request: ControlRequest) => ({
          ok: true,
          path: request.query?.path,
          content: '# Guide',
          byteSize: 7,
          truncated: false,
        }),
      },
    });

    renderApp(transport, <PawOsFilesApp />);

    const tree = await screen.findByRole('tree', { name: '项目文件' });
    const root = await within(tree).findByRole('treeitem', { name: /收起工作区 paw/ });
    const docs = await within(tree).findByRole('treeitem', { name: '展开目录 docs' });
    expect(within(tree).getAllByRole('treeitem').filter((item) => item.tabIndex === 0)).toEqual([root]);

    root.focus();
    await user.keyboard('{ArrowDown}');
    expect(docs).toHaveFocus();
    await user.keyboard('{ArrowRight}');
    const guide = await within(tree).findByRole('treeitem', { name: '打开文件 guide.md' });
    expect(docs).toHaveAttribute('aria-expanded', 'true');
    await user.keyboard('{ArrowRight}');
    expect(guide).toHaveFocus();
    await user.keyboard('{End}');
    expect(within(tree).getByRole('treeitem', { name: '打开文件 AGENTS.md' })).toHaveFocus();
    await user.keyboard('{Home}');
    expect(root).toHaveFocus();
    guide.focus();
    await user.keyboard('{ArrowLeft}');
    expect(docs).toHaveFocus();
    await user.keyboard('{ArrowLeft}');
    expect(docs).toHaveAttribute('aria-expanded', 'false');
    expect(within(tree).queryByRole('treeitem', { name: '打开文件 guide.md' })).not.toBeInTheDocument();

    await user.click(docs);
    await within(tree).findByRole('treeitem', { name: '打开文件 guide.md' });
    const nestedReadsBeforeRefresh = directoryReads.filter((path) => path === '/workspace/paw/docs').length;
    await user.click(screen.getByRole('button', { name: '刷新文件' }));
    await waitFor(() => expect(directoryReads.filter((path) => path === '/workspace/paw/docs').length).toBeGreaterThan(nestedReadsBeforeRefresh));
    expect(await within(tree).findByRole('treeitem', { name: '打开文件 guide.md' })).toBeInTheDocument();
  });

  it('renders binary payloads as an explicit state and preserves full truncated labels', async () => {
    const user = userEvent.setup();
    const binaryPath = '/workspace/paw/assets/a-very-long-preview-file-name.png';
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [{ path: binaryPath, name: 'a-very-long-preview-file-name.png', kind: 'file', byteSize: 82_304 }],
        },
        'agent.session.workspace.read': {
          ok: true,
          path: binaryPath,
          content: '\u0000PNG\r\n\u001a\n',
          byteSize: 82_304,
          truncated: false,
        },
      },
    });

    const { container } = renderApp(transport, <PawOsFilesApp />);
    await user.click(await screen.findByRole('treeitem', { name: '打开文件 a-very-long-preview-file-name.png' }));

    expect(await screen.findByText('二进制文件不能作为文本预览。')).toBeInTheDocument();
    // The reader names its active lens and points at the real escape hatch.
    expect(screen.getByText('二进制')).toBeInTheDocument();
    expect(screen.getByText('可从上方复制完整路径，用 Terminal 或 Agent 工具检查原始内容。')).toBeInTheDocument();
    const heading = screen.getByRole('heading', { name: 'a-very-long-preview-file-name.png', level: 2 });
    expect(heading).toHaveAttribute('title', 'a-very-long-preview-file-name.png');
    expect(heading.parentElement?.querySelector('small')).toHaveAttribute('title', binaryPath);
    expect(container.querySelector('.paw-files-statusbar__selection')).toHaveAttribute('title', `${binaryPath} · 80 KB`);
    expect(container.querySelector('.agent-file-code')).toBeNull();
  });

  it('leaves the shared code reader on its --color-code-bg/--color-code-text pair', async () => {
    // Regression: Files once repainted only the code-surface background with a
    // light colour, leaving the shared light code text unreadable in the plain
    // fallback reader. The Files owner must not restyle the code surface paint.
    expect(filesCss).not.toMatch(/\.agent-file-code[^{}]*\{[^}]*background/s);
    // The Files header owns the filename and the copy actions, so the shared
    // reader's duplicate filename strip stays hidden inside this App.
    expect(filesCss).toMatch(/\.agent-file-code figcaption[^{]*\{[^}]*display:\s*none/s);

    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [{ path: '/workspace/paw/notes.txt', name: 'notes.txt', kind: 'file', byteSize: 27 }],
        },
        'agent.session.workspace.read': {
          ok: true,
          path: '/workspace/paw/notes.txt',
          content: 'plain text stays readable\n',
          byteSize: 27,
          truncated: false,
        },
      },
    });

    const { container } = renderApp(transport, <PawOsFilesApp />);
    await user.click(await screen.findByRole('treeitem', { name: '打开文件 notes.txt' }));

    expect(await screen.findByText('plain text stays readable')).toBeInTheDocument();
    expect(container.querySelector('.agent-file-code')).not.toBeNull();
  });

  it('shows an explicit empty-file state instead of a blank code reader', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [{ path: '/workspace/paw/todo.md', name: 'todo.md', kind: 'file', byteSize: 0 }],
        },
        'agent.session.workspace.read': {
          ok: true,
          path: '/workspace/paw/todo.md',
          content: '',
          byteSize: 0,
          truncated: false,
        },
      },
    });

    const { container } = renderApp(transport, <PawOsFilesApp />);
    await user.click(await screen.findByRole('treeitem', { name: '打开文件 todo.md' }));

    expect(await screen.findByText('这个文件是空的。')).toBeInTheDocument();
    expect(container.querySelector('.agent-file-code')).toBeNull();
    expect(container.querySelector('.agent-file-markdown')).toBeNull();
  });

  it('labels a truncated preview and counts loaded entries truthfully', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [{ path: '/workspace/paw/big.log', name: 'big.log', kind: 'file', byteSize: 131_072 }],
        },
        'agent.session.workspace.read': {
          ok: true,
          path: '/workspace/paw/big.log',
          content: 'line 1\nline 2\n',
          byteSize: 131_072,
          offset: 0,
          nextOffset: 65_536,
          truncated: true,
        },
      },
    });

    renderApp(transport, <PawOsFilesApp />);
    expect(await screen.findByText('已加载 1 项')).toBeInTheDocument();
    await user.click(screen.getByRole('treeitem', { name: '打开文件 big.log' }));

    expect(await screen.findByText('已显示前 64 KB · 共 128 KB')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /继续读取/ })).toBeInTheDocument();
    expect(screen.getByText(/已选 big\.log · 128 KB/)).toBeInTheDocument();
    // Loaded-line and renderer readouts stay honest about the partial window.
    expect(screen.getByText('已载 2 行')).toBeInTheDocument();
    expect(screen.getByText('纯文本')).toBeInTheDocument();
  });

  it('continues a bounded read from the served nextOffset and retires the bar when complete', async () => {
    const user = userEvent.setup();
    const readOffsets: number[] = [];
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [{ path: '/workspace/paw/big.log', name: 'big.log', kind: 'file', byteSize: 131_072 }],
        },
        'agent.session.workspace.read': (request: ControlRequest) => {
          const offset = Number(request.query?.offset ?? 0);
          readOffsets.push(offset);
          if (offset === 0) return {
            ok: true,
            path: '/workspace/paw/big.log',
            content: 'chunk one\n',
            byteSize: 131_072,
            offset: 0,
            nextOffset: 65_536,
            truncated: true,
          };
          return {
            ok: true,
            path: '/workspace/paw/big.log',
            content: 'chunk two\n',
            byteSize: 131_072,
            offset,
            nextOffset: 131_072,
            truncated: false,
          };
        },
      },
    });

    renderApp(transport, <PawOsFilesApp />);
    await user.click(await screen.findByRole('treeitem', { name: '打开文件 big.log' }));

    expect(await screen.findByText('已显示前 64 KB · 共 128 KB')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /继续读取/ }));

    expect(await screen.findByText(/chunk two/)).toBeInTheDocument();
    expect(screen.getByText(/chunk one/)).toBeInTheDocument();
    expect(screen.queryByText(/已显示前/)).not.toBeInTheDocument();
    expect(readOffsets).toEqual([0, 65_536]);
  });

  it('marks the 512 KB reading cap on the gauge scale of an oversized file', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [{ path: '/workspace/paw/trace.log', name: 'trace.log', kind: 'file', byteSize: 2_097_152 }],
        },
        'agent.session.workspace.read': {
          ok: true,
          path: '/workspace/paw/trace.log',
          content: 'first window\n',
          byteSize: 2_097_152,
          offset: 0,
          nextOffset: 65_536,
          truncated: true,
        },
      },
    });

    renderApp(transport, <PawOsFilesApp />);
    await user.click(await screen.findByRole('treeitem', { name: '打开文件 trace.log' }));

    const gauge = await screen.findByRole('progressbar', { name: '已读取 64 KB，共 2 MB' });
    // The printed percentage never claims more than the bytes on screen.
    expect(gauge).toHaveAttribute('aria-valuenow', '3');
    expect(screen.getByText('3%')).toBeInTheDocument();
    // 64 KB ticks would blur into noise on a 2 MB scale, so they retire.
    expect(gauge.style.getPropertyValue('--paw-files-tick')).toBe('');
    // The in-App reading cap sits at its true position on this file's scale.
    expect(gauge.style.getPropertyValue('--paw-files-cap')).toBe('25%');
    expect(gauge.querySelector('b')).toHaveAttribute('title', '512 KB 预览上限');
  });

  it('reads out the active renderer, loaded lines, and the rail scan coverage', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [
            { path: '/workspace/paw/docs', name: 'docs', kind: 'directory' },
            { path: '/workspace/paw/AGENTS.md', name: 'AGENTS.md', kind: 'file', byteSize: 38 },
          ],
        },
        'agent.session.workspace.read': {
          ok: true,
          path: '/workspace/paw/AGENTS.md',
          content: '# Project guide\nRead docs before work.',
          byteSize: 38,
          truncated: false,
        },
      },
    });

    renderApp(transport, <PawOsFilesApp />);

    // The rail head reports exactly what has been scanned: one listed
    // directory (the root) holding two entries.
    expect(await screen.findByText('1 目录 · 2 项')).toBeInTheDocument();

    await user.click(screen.getByRole('treeitem', { name: '打开文件 AGENTS.md' }));
    expect(await screen.findByRole('heading', { name: 'AGENTS.md', level: 2 })).toBeInTheDocument();
    // A complete two-line Markdown file names its lens and its full extent.
    expect(await screen.findByText('Markdown')).toBeInTheDocument();
    expect(screen.getByText('2 行')).toBeInTheDocument();
  });

  it('teaches the real keyboard path on the empty reading desk', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': { ok: true, path: '/workspace/paw', items: [] },
      },
    });

    renderApp(transport, <PawOsFilesApp />);

    expect(await screen.findByText('选择要检查的文件')).toBeInTheDocument();
    expect(screen.getByText('Enter')).toBeInTheDocument();
    expect(screen.getByText('打开')).toBeInTheDocument();
    expect(screen.getByText('展开目录')).toBeInTheDocument();
  });

  it('reports an honest display limit when a directory listing is truncated by the route', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          truncated: true,
          items: [
            { path: '/workspace/paw/a.txt', name: 'a.txt', kind: 'file', byteSize: 1 },
            { path: '/workspace/paw/b.txt', name: 'b.txt', kind: 'file', byteSize: 2 },
          ],
        },
      },
    });

    renderApp(transport, <PawOsFilesApp />);
    expect(await screen.findByText('目录条目已达显示上限，仅列出前 2 项。')).toBeInTheDocument();
  });

  it('renders a complete SVG as a safe image with a source toggle', async () => {
    const user = userEvent.setup();
    const svgContent = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>';
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [{ path: '/workspace/paw/logo.svg', name: 'logo.svg', kind: 'file', byteSize: 104 }],
        },
        'agent.session.workspace.read': {
          ok: true,
          path: '/workspace/paw/logo.svg',
          content: svgContent,
          byteSize: 104,
          truncated: false,
        },
      },
    });

    const { container } = renderApp(transport, <PawOsFilesApp />);
    await user.click(await screen.findByRole('treeitem', { name: '打开文件 logo.svg' }));

    const image = await screen.findByRole('img', { name: 'logo.svg 矢量图预览' });
    expect(image).toHaveAttribute('src', `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgContent)}`);
    expect(container.querySelector('.agent-file-code')).toBeNull();

    await user.click(screen.getByRole('button', { name: '源码' }));
    expect(container.querySelector('.agent-file-code')).not.toBeNull();
    expect(screen.queryByRole('img', { name: 'logo.svg 矢量图预览' })).not.toBeInTheDocument();
  });

  it('recovers a failed file read through the in-place retry action', async () => {
    const user = userEvent.setup();
    let readAttempts = 0;
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [{ path: '/workspace/paw/notes.txt', name: 'notes.txt', kind: 'file', byteSize: 20 }],
        },
        'agent.session.workspace.read': (request: ControlRequest) => {
          readAttempts += 1;
          if (readAttempts === 1) throw new Error('读取超时。');
          return { ok: true, path: request.query?.path, content: 'recovered content\n', byteSize: 20, truncated: false };
        },
      },
    });

    renderApp(transport, <PawOsFilesApp />);
    await user.click(await screen.findByRole('treeitem', { name: '打开文件 notes.txt' }));

    const failure = await screen.findByRole('alert');
    expect(failure).toHaveTextContent('读取超时。');
    await user.click(within(failure).getByRole('button', { name: '重试' }));
    expect(await screen.findByText('recovered content')).toBeInTheDocument();
    expect(readAttempts).toBe(2);
  });

  it('returns from the narrow reader to the tree with expansion and focus preserved', async () => {
    // jsdom cannot evaluate @container queries, so this emulates the exact
    // <=560px rules from paw-os-files-app.css: an open file replaces the tree
    // and the Back affordance becomes visible.
    const narrowEmulation = document.createElement('style');
    narrowEmulation.textContent = `
      .paw-files-app__workspace[data-file-open] .paw-files-tree { display: none; }
      .paw-files-preview__back { display: inline-flex; }
    `;
    document.head.append(narrowEmulation);

    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': (request: ControlRequest) => {
          const path = String(request.query?.path ?? '');
          if (path === '/workspace/paw/docs') return {
            ok: true,
            path,
            items: [{ path: `${path}/guide.md`, name: 'guide.md', kind: 'file', byteSize: 42 }],
          };
          return {
            ok: true,
            path,
            items: [{ path: '/workspace/paw/docs', name: 'docs', kind: 'directory' }],
          };
        },
        'agent.session.workspace.read': (request: ControlRequest) => ({
          ok: true,
          path: request.query?.path,
          content: '# Guide',
          byteSize: 7,
          truncated: false,
        }),
      },
    });

    try {
      renderApp(transport, <PawOsFilesApp />);
      await user.click(await screen.findByRole('treeitem', { name: '展开目录 docs' }));
      await user.click(await screen.findByRole('treeitem', { name: '打开文件 guide.md' }));
      expect(await screen.findByRole('heading', { name: 'guide.md', level: 2 })).toBeInTheDocument();

      const back = screen.getByRole('button', { name: '返回文件列表' });
      // The narrow return path is a labelled pill, not a bare icon.
      expect(back).toHaveTextContent('返回');
      await waitFor(() => expect(back).toHaveFocus());
      await user.click(back);

      expect(screen.queryByRole('heading', { name: 'guide.md', level: 2 })).not.toBeInTheDocument();
      const reopened = screen.getByRole('treeitem', { name: '打开文件 guide.md' });
      expect(reopened).toHaveFocus();
      expect(screen.getByRole('treeitem', { name: '收起目录 docs' })).toHaveAttribute('aria-expanded', 'true');
    } finally {
      narrowEmulation.remove();
    }
  });

  it('presents directories first with natural name order regardless of service order', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [
            { path: '/workspace/paw/zeta.md', name: 'zeta.md', kind: 'file', byteSize: 1 },
            { path: '/workspace/paw/beta', name: 'beta', kind: 'directory' },
            { path: '/workspace/paw/alpha10.ts', name: 'alpha10.ts', kind: 'file', byteSize: 1 },
            { path: '/workspace/paw/alpha2.ts', name: 'alpha2.ts', kind: 'file', byteSize: 1 },
            { path: '/workspace/paw/Alpha', name: 'Alpha', kind: 'directory' },
          ],
        },
      },
    });

    renderApp(transport, <PawOsFilesApp />);

    const tree = await screen.findByRole('tree', { name: '项目文件' });
    await within(tree).findByRole('treeitem', { name: '打开文件 zeta.md' });
    const names = within(tree).getAllByRole('treeitem').slice(1).map((item) => item.querySelector('span:nth-of-type(2), span > span')?.textContent ?? item.textContent);
    expect(names.map((name) => name?.trim())).toEqual(['Alpha', 'beta', 'alpha2.ts', 'alpha10.ts', 'zeta.md']);
  });

  it('filters loaded entries with truthful coverage and opens a match directly', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': (request: ControlRequest) => {
          const path = String(request.query?.path ?? '');
          if (path === '/workspace/paw/docs') return {
            ok: true,
            path,
            items: [{ path: `${path}/guide.md`, name: 'guide.md', kind: 'file', byteSize: 42 }],
          };
          return {
            ok: true,
            path,
            items: [
              { path: '/workspace/paw/docs', name: 'docs', kind: 'directory' },
              { path: '/workspace/paw/AGENTS.md', name: 'AGENTS.md', kind: 'file', byteSize: 128 },
            ],
          };
        },
        'agent.session.workspace.read': (request: ControlRequest) => ({
          ok: true,
          path: request.query?.path,
          content: '# Guide',
          byteSize: 7,
          truncated: false,
        }),
      },
    });

    renderApp(transport, <PawOsFilesApp />);

    await user.click(await screen.findByRole('treeitem', { name: '展开目录 docs' }));
    await screen.findByRole('treeitem', { name: '打开文件 guide.md' });

    const filter = screen.getByRole('searchbox', { name: '筛选已加载的文件' });
    await user.type(filter, 'gui');
    // The filter names its coverage: it only searches already-loaded entries.
    expect(screen.getByText('在已加载的 3 项中匹配 1 项')).toBeInTheDocument();
    expect(screen.queryByRole('tree', { name: '项目文件' })).not.toBeInTheDocument();

    await user.click(within(screen.getByRole('list', { name: '筛选结果' })).getByRole('button', { name: '打开文件 guide.md' }));
    expect(await screen.findByRole('heading', { name: 'guide.md', level: 2 })).toBeInTheDocument();

    await user.clear(filter);
    await user.type(filter, 'no-such-entry');
    expect(screen.getByText('在已加载的 3 项中匹配 0 项')).toBeInTheDocument();
    expect(screen.getByText('没有匹配已加载的条目。')).toBeInTheDocument();

    // Escape clears the filter and restores the tree.
    await user.keyboard('{Escape}');
    expect(await screen.findByRole('tree', { name: '项目文件' })).toBeInTheDocument();
  });

  it('locates a crumb directory in the tree from the reader header', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': (request: ControlRequest) => {
          const path = String(request.query?.path ?? '');
          if (path === '/workspace/paw/docs') return {
            ok: true,
            path,
            items: [{ path: `${path}/guide.md`, name: 'guide.md', kind: 'file', byteSize: 42 }],
          };
          return {
            ok: true,
            path,
            items: [{ path: '/workspace/paw/docs', name: 'docs', kind: 'directory' }],
          };
        },
        'agent.session.workspace.read': (request: ControlRequest) => ({
          ok: true,
          path: request.query?.path,
          content: '# Guide',
          byteSize: 7,
          truncated: false,
        }),
      },
    });

    renderApp(transport, <PawOsFilesApp />);
    await user.click(await screen.findByRole('treeitem', { name: '展开目录 docs' }));
    await user.click(await screen.findByRole('treeitem', { name: '打开文件 guide.md' }));
    expect(await screen.findByRole('heading', { name: 'guide.md', level: 2 })).toBeInTheDocument();

    // The crumb line names the root-relative chain: workspace root, then docs.
    await user.click(screen.getByRole('button', { name: '在目录树中定位 docs' }));

    // The wide layout keeps the file open beside the located directory row.
    expect(screen.getByRole('heading', { name: 'guide.md', level: 2 })).toBeInTheDocument();
    const docs = screen.getByRole('treeitem', { name: '收起目录 docs' });
    expect(docs).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() => expect(docs).toHaveFocus());

    await user.click(screen.getByRole('button', { name: '在目录树中定位 paw' }));
    await waitFor(() => expect(screen.getByRole('treeitem', { name: /收起工作区 paw/ })).toHaveFocus());
  });

  it('reports directory child counts, the filter match count, and the honest loaded share', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': (request: ControlRequest) => {
          const path = String(request.query?.path ?? '');
          if (path === '/workspace/paw/docs') return {
            ok: true,
            path,
            items: [{ path: `${path}/guide.md`, name: 'guide.md', kind: 'file', byteSize: 42 }],
          };
          return {
            ok: true,
            path,
            items: [
              { path: '/workspace/paw/docs', name: 'docs', kind: 'directory' },
              { path: '/workspace/paw/big.log', name: 'big.log', kind: 'file', byteSize: 131_072 },
            ],
          };
        },
        'agent.session.workspace.read': {
          ok: true,
          path: '/workspace/paw/big.log',
          content: 'line 1\nline 2\n',
          byteSize: 131_072,
          offset: 0,
          nextOffset: 65_536,
          truncated: true,
        },
      },
    });

    const { container } = renderApp(transport, <PawOsFilesApp />);

    // A loaded directory states how many entries it holds; unread ones claim nothing.
    const docs = await screen.findByRole('treeitem', { name: '展开目录 docs' });
    expect(docs).not.toHaveTextContent('项');
    await user.click(docs);
    await screen.findByRole('treeitem', { name: '打开文件 guide.md' });
    expect(screen.getByRole('treeitem', { name: '收起目录 docs' })).toHaveTextContent('1 项');

    // The bounded-read meter mirrors the stated byte range: 64 KB of 128 KB,
    // with one gauge tick per 64 KB request and no cap marker below 512 KB.
    await user.click(screen.getByRole('treeitem', { name: '打开文件 big.log' }));
    expect(await screen.findByText('已显示前 64 KB · 共 128 KB')).toBeInTheDocument();
    const meter = container.querySelector('.paw-files-preview__meter') as HTMLElement | null;
    expect(meter?.style.getPropertyValue('--paw-files-loaded')).toBe('50%');
    expect(meter?.style.getPropertyValue('--paw-files-tick')).toBe('50%');
    expect(meter?.querySelector('b')).toBeNull();
    expect(screen.getByText('50%')).toBeInTheDocument();

    // The filter chip repeats the truthful match count beside the query.
    await user.type(screen.getByRole('searchbox', { name: '筛选已加载的文件' }), 'guide');
    expect(container.querySelector('.paw-files-filter__count')?.textContent).toBe('1');
  });

  it('copies loaded file content and states the truncation boundary truthfully', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn(async () => undefined);
    const hadClipboard = 'clipboard' in navigator;
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [{ path: '/workspace/paw/big.log', name: 'big.log', kind: 'file', byteSize: 131_072 }],
        },
        'agent.session.workspace.read': {
          ok: true,
          path: '/workspace/paw/big.log',
          content: 'line 1\nline 2\n',
          byteSize: 131_072,
          offset: 0,
          nextOffset: 65_536,
          truncated: true,
        },
      },
    });

    try {
      renderApp(transport, <PawOsFilesApp />);
      await user.click(await screen.findByRole('treeitem', { name: '打开文件 big.log' }));
      const copyContent = await screen.findByRole('button', { name: '复制文件内容' });
      expect(copyContent).toHaveAttribute('title', '复制已加载的前 64 KB 内容');
      await user.click(copyContent);
      await waitFor(() => expect(writeText).toHaveBeenCalledWith('line 1\nline 2\n'));
      expect(await screen.findByRole('button', { name: '已复制文件内容' })).toBeInTheDocument();
    } finally {
      if (!hadClipboard) delete (navigator as { clipboard?: unknown }).clipboard;
    }
  });

  it('refuses to copy binary payloads as text', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-work',
          items: [{ id: 'session-work', title: 'PAWOS', updatedAtMs: 1, workspaceRoots: ['/workspace/paw'], status: 'idle' }],
        },
        'agent.session.workspace.list': {
          ok: true,
          path: '/workspace/paw',
          items: [{ path: '/workspace/paw/image.png', name: 'image.png', kind: 'file', byteSize: 900 }],
        },
        'agent.session.workspace.read': {
          ok: true,
          path: '/workspace/paw/image.png',
          content: '\u0000PNG\r\n\u001a\n',
          byteSize: 900,
          truncated: false,
        },
      },
    });

    renderApp(transport, <PawOsFilesApp />);
    await user.click(await screen.findByRole('treeitem', { name: '打开文件 image.png' }));

    expect(await screen.findByText('二进制文件不能作为文本预览。')).toBeInTheDocument();
    const copyContent = screen.getByRole('button', { name: '复制文件内容' });
    expect(copyContent).toBeDisabled();
    expect(copyContent).toHaveAttribute('title', '二进制内容不能复制为文本');
  });

  it('distinguishes a missing Session from an unbound workspace', async () => {
    const noSessions = new MockControlTransport({
      routes: { 'agent.sessions.list': { ok: true, items: [] } },
    });
    renderApp(noSessions, <PawOsFilesApp />);
    expect(await screen.findByText('还没有可浏览的 Session。')).toBeInTheDocument();
    expect(screen.queryByText('这个 Session 还没有绑定工作区。')).not.toBeInTheDocument();
    cleanup();

    const unbound = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          activeSessionId: 'session-empty',
          items: [{ id: 'session-empty', title: '无项目对话', updatedAtMs: 0, workspaceRoots: [], status: 'idle' }],
        },
      },
    });
    renderApp(unbound, <PawOsFilesApp />);
    expect(await screen.findByText('这个 Session 还没有绑定工作区。')).toBeInTheDocument();
    expect(screen.queryByText('还没有可浏览的 Session。')).not.toBeInTheDocument();
  });
});

function renderApp(transport: MockControlTransport, child: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ControlTransportProvider transport={transport}>
        <TooltipProvider>{child}</TooltipProvider>
      </ControlTransportProvider>
    </QueryClientProvider>,
  );
}
