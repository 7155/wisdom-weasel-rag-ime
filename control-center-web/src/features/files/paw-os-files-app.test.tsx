import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
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
    const heading = screen.getByRole('heading', { name: 'a-very-long-preview-file-name.png', level: 2 });
    expect(heading).toHaveAttribute('title', 'a-very-long-preview-file-name.png');
    expect(heading.parentElement?.querySelector('small')).toHaveAttribute('title', binaryPath);
    expect(container.querySelector('.paw-files-statusbar__selection')).toHaveAttribute('title', `${binaryPath} · 80 KB`);
    expect(container.querySelector('.agent-file-code')).toBeNull();
  });
});

function renderApp(transport: MockControlTransport, child: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ControlTransportProvider transport={transport}>{child}</ControlTransportProvider>
    </QueryClientProvider>,
  );
}
