import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport, type MockControlTransportOptions } from '@/test/mock-transport';
import type { ControlRequest } from '@/platform/transport';
import { PawDesktopProvider } from '../runtime/desktop-context';
import { PawWayfinderWork, WAYFINDER_DRAG_MIME } from './PawWayfinderWork';

/* The desktop panel is a projection, not a manager: it must fold the raw
 * directory to desktop density, keep its own scroll, and hand every click to
 * the Agent window. These tests drive it through the same transport seam the
 * desktop uses, with the exact clone/repeat shapes that once flooded the
 * screen. */

const NOW = Date.now();

beforeEach(() => window.localStorage.clear());
afterEach(() => cleanup());

describe('PawWayfinderWork', () => {
  it('does not show a Room row when only partner Sessions exist', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [
          sessionRecord('s-1', '迁移作战室 · Agent 1', { roomParticipant: { roomId: 'room-9', participantId: 'p1', status: 'active' } }),
          sessionRecord('s-2', '迁移作战室 · Agent 2', { roomParticipant: { roomId: 'room-9', participantId: 'p2', status: 'active' } }),
          sessionRecord('s-3', '迁移作战室 · Agent 3', { roomParticipant: { roomId: 'room-9', participantId: 'p3', status: 'active' } }),
        ] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    const panel = await screen.findByRole('region', { name: '最近工作' });
    expect(within(panel).getByText('还没有工作记录')).toBeInTheDocument();
    expect(within(panel).queryByText('迁移作战室 · Agent 1')).not.toBeInTheDocument();
  });

  it('collapses repeated goal copy and reveals older runs only on demand', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [
          sessionRecord('s-new', '重构 Wayfinder 列表', { updatedAtMs: NOW - 60_000 }),
          sessionRecord('s-old', '重构 Wayfinder 列表', { updatedAtMs: NOW - 3_600_000 }),
        ] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    expect(await screen.findAllByRole('button', { name: /重构 Wayfinder 列表/ })).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /较早一段/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '同名工作还有 1 段' }));
    expect(screen.getByRole('button', { name: /较早一段/ })).toBeInTheDocument();
  });

  it('filters rows through the panel search without leaving the desktop', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [
          sessionRecord('s-1', '重构列表'),
          sessionRecord('s-2', '整理知识库'),
        ] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    await screen.findByRole('button', { name: /整理知识库/ });
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索最近工作' }), { target: { value: '重构' } });

    expect(screen.getByRole('button', { name: /重构列表/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /整理知识库/ })).not.toBeInTheDocument();
  });

  it('rests the 更早 bucket collapsed so stale history never fills the first screen', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [
          sessionRecord('s-now', '今天的工作'),
          sessionRecord('s-old-1', '上个月的工作 A', { updatedAtMs: NOW - 30 * 86_400_000 }),
          sessionRecord('s-old-2', '上个月的工作 B', { updatedAtMs: NOW - 31 * 86_400_000 }),
        ] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    await screen.findByRole('button', { name: /今天的工作/ });
    expect(screen.queryByRole('button', { name: /上个月的工作/ })).not.toBeInTheDocument();

    const stale = screen.getByRole('button', { name: /更早/ });
    expect(stale).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(stale);
    expect(screen.getAllByRole('button', { name: /上个月的工作/ })).toHaveLength(2);
  });

  it('opens a row straight into the Agent window projection', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [sessionRecord('s-42', '继续修复投影')] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    fireEvent.click(await screen.findByRole('button', { name: /继续修复投影/ }));

    // Desktop persistence is a trailing debounce, so the snapshot lands one
    // beat after the interaction instead of inside it.
    await waitFor(() => {
      const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
        windows?: Record<string, { appId?: string; initialRoute?: string; target?: { kind?: string; id?: string } }>;
      };
      expect(snapshot.windows?.['agent:s-42']).toMatchObject({
        appId: 'agent',
        initialRoute: '/agent?session=s-42',
        target: { kind: 'session', id: 's-42' },
      });
    });
  });

  it('groups a project in place, shows public progress, and opens the canonical Room', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [sessionRecord('s-1', 'Trace 地基', {
          status: 'busy',
          lastMessagePreview: '正在建立 Trace 关联',
          workspaceRoots: ['/work/paw'],
        })] },
        'agent.rooms.list': { ok: true, items: [{
          id: 'room-1', title: '协作检查', status: 'active', updatedAtMs: NOW,
          workspaceRoots: ['/work/paw'], participants: [{ displayName: 'Builder', ordinal: 1 }],
          workItems: [{ state: 'blocked', blocker: { reason: '等待沙盒授权' }, updatedAtMs: NOW }],
        }] },
      },
    });

    const panel = await screen.findByRole('region', { name: '最近工作' });
    expect(within(panel).getAllByText('paw').length).toBeGreaterThanOrEqual(1);
    expect(within(panel).getByText('当前公开内容：正在建立 Trace 关联')).toBeInTheDocument();
    expect(within(panel).getByText('阻塞：等待沙盒授权')).toBeInTheDocument();

    fireEvent.click(within(panel).getByRole('button', { name: /协作检查/ }));
    await waitFor(() => {
      const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
        windows?: Record<string, { initialRoute?: string; target?: { kind?: string; id?: string } }>;
      };
      expect(snapshot.windows?.['agent:room-1']).toMatchObject({
        initialRoute: '/agent?room=room-1',
        target: { kind: 'room', id: 'room-1' },
      });
    });
  });

  it('keeps only one project folder expanded so content panels cannot overlap', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [
          sessionRecord('s-paw', 'PAW 工作', { workspaceRoots: ['/work/paw'] }),
          sessionRecord('s-learn', 'LearnA 工作', { workspaceRoots: ['/work/learnA'] }),
        ] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    const panel = await screen.findByRole('region', { name: '最近工作' });
    const folders = panel.querySelectorAll<HTMLDetailsElement>('[data-project-folder]');
    expect(folders).toHaveLength(2);
    expect(panel.querySelectorAll<HTMLDetailsElement>('[data-project-folder][open]')).toHaveLength(1);

    fireEvent.click(folders[1]!.querySelector('summary')!);
    expect(panel.querySelectorAll<HTMLDetailsElement>('[data-project-folder][open]')).toHaveLength(1);
    expect(folders[1]).toHaveAttribute('open');
    expect(folders[0]).not.toHaveAttribute('open');
  });

  it('opens a non-modal project context sheet with real roots, status and canonical shortcuts', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [sessionRecord('s-context', 'Trace 地基', {
          status: 'busy',
          workspaceRoots: ['/work/paw', '/work/shared'],
        })] },
        'agent.rooms.list': { ok: true, items: [{
          id: 'room-context', title: '协作检查', status: 'active', updatedAtMs: NOW,
          workspaceRoots: ['/work/shared', '/work/paw'],
          participants: [{ displayName: 'Builder', ordinal: 1 }],
          workItems: [{ state: 'blocked', blocker: { reason: '等待沙盒授权' }, updatedAtMs: NOW }],
        }] },
      },
    });

    const panel = await screen.findByRole('region', { name: '最近工作' });
    const contextTrigger = within(panel).getByRole('button', { name: '查看 paw 项目上下文' });
    fireEvent.change(within(panel).getByRole('searchbox', { name: '搜索最近工作' }), { target: { value: 'Trace' } });
    fireEvent.click(contextTrigger);

    const sheet = within(panel).getByRole('dialog', { name: 'paw 项目上下文' });
    expect(sheet).toHaveAttribute('aria-modal', 'false');
    expect(within(sheet).getByText('/work/paw')).toBeInTheDocument();
    expect(within(sheet).getByText('/work/shared')).toBeInTheDocument();
    expect(within(sheet).getByText('Session')).toBeInTheDocument();
    expect(within(sheet).getByText('Room')).toBeInTheDocument();
    expect(within(sheet).getByText('协作检查')).toBeInTheDocument();
    expect(within(sheet).getByText(/等待沙盒授权/)).toBeInTheDocument();
    expect(within(sheet).queryByText('Builder')).not.toBeInTheDocument();
    expect(within(sheet).getByText(/不会创建 Finder\/Git 文件/)).toBeInTheDocument();

    fireEvent.click(within(sheet).getByRole('button', { name: /Trace 地基/ }));
    await waitFor(() => {
      const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
        windows?: Record<string, { initialRoute?: string; target?: { kind?: string; id?: string } }>;
      };
      expect(snapshot.windows?.['agent:s-context']).toMatchObject({
        initialRoute: '/agent?session=s-context',
        target: { kind: 'session', id: 's-context' },
      });
    });

    fireEvent.click(within(sheet).getByRole('button', { name: '系统设置' }));
    fireEvent.click(within(sheet).getByRole('button', { name: 'Trace / Eval' }));
    await waitFor(() => {
      const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
        windows?: Record<string, { appId?: string; initialRoute?: string }>;
      };
      expect(snapshot.windows?.['system-settings']).toMatchObject({ appId: 'system-settings', initialRoute: '/configuration' });
      expect(snapshot.windows?.['system-monitor']).toMatchObject({ appId: 'system-monitor', initialRoute: '/observability' });
    });

    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(within(panel).queryByRole('dialog', { name: 'paw 项目上下文' })).not.toBeInTheDocument());
    expect(document.activeElement).toBe(contextTrigger);
  });

  it('keeps the project context action operable after the folder is folded', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [sessionRecord('s-folded', '折叠后仍可见', { workspaceRoots: ['/work/paw'] })] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    const panel = await screen.findByRole('region', { name: '最近工作' });
    const folder = panel.querySelector('[data-project-folder]');
    const contextTrigger = within(panel).getByRole('button', { name: '查看 paw 项目上下文' });
    expect(folder).not.toBeNull();

    fireEvent.click(folder!.querySelector('summary')!);
    expect(folder).not.toHaveAttribute('open');
    fireEvent.click(contextTrigger);

    expect(within(panel).getByRole('dialog', { name: 'paw 项目上下文' })).toBeInTheDocument();
    expect(folder).not.toHaveAttribute('open');
  });

  it('reveals matching dialogue files after a project folder was folded', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [sessionRecord('s-1', 'Trace 地基', {
          workspaceRoots: ['/work/paw'],
        })] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    const panel = await screen.findByRole('region', { name: '最近工作' });
    const folder = panel.querySelector('[data-project-folder]');
    expect(folder).not.toBeNull();
    fireEvent.click(folder!.querySelector('summary')!);
    expect(folder).not.toHaveAttribute('open');

    fireEvent.change(within(panel).getByRole('searchbox', { name: '搜索最近工作' }), { target: { value: 'Trace' } });
    expect(folder).toHaveAttribute('open');
    expect(within(panel).getByText('Trace 地基')).toBeVisible();
  });

  it('moves a project folder and archives then restores its dialogue icon', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [sessionRecord('s-drag', '一个需要完整显示的长对话名称', { workspaceRoots: ['/work/paw'] })] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    const panel = await screen.findByRole('region', { name: '最近工作' });
    const folder = panel.querySelector('[data-project-folder]') as HTMLDetailsElement;
    const project = panel.querySelector('[data-wayfinder-project]') as HTMLElement;
    const row = panel.querySelector('[data-dialogue-file]') as HTMLButtonElement;
    const canvas = panel.querySelector('[data-wayfinder-canvas]') as HTMLDivElement;

    expect(project).toHaveAttribute('draggable', 'true');
    expect(project).toHaveAttribute('title', 'paw · 1 个对话');
    expect(row).toHaveAttribute('draggable', 'true');
    expect(row).toHaveAttribute('title', expect.stringContaining('一个需要完整显示的长对话名称'));
    expect(folder).toHaveAttribute('open');

    Object.defineProperty(canvas, 'clientWidth', { configurable: true, value: 800 });
    Object.defineProperty(canvas, 'clientHeight', { configurable: true, value: 600 });
    Object.defineProperty(canvas, 'scrollWidth', { configurable: true, value: 800 });
    Object.defineProperty(canvas, 'scrollHeight', { configurable: true, value: 600 });
    Object.defineProperty(canvas, 'getBoundingClientRect', {
      configurable: true,
      value: () => domRect(10, 20, 800, 600),
    });

    const projectTransfer = dragTransfer();
    fireEvent.dragStart(project, { dataTransfer: projectTransfer });
    fireDrop(canvas, projectTransfer, 220, 190);

    await waitFor(() => {
      const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
        wayfinder?: { iconPositions?: Record<string, { x: number; y: number }> };
      };
      expect(snapshot.wayfinder?.iconPositions?.['project:/work/paw']).toEqual({ x: 162, y: 124 });
    });

    const archive = within(panel).getByRole('button', { name: '归档 0 个对话' });
    const rowTransfer = dragTransfer();
    fireEvent.dragStart(row, { dataTransfer: rowTransfer });
    fireDrop(archive, rowTransfer);

    await waitFor(() => {
      expect(panel.querySelector('[data-dialogue-file]')).toBeNull();
      const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
        wayfinder?: { archived?: string[] };
      };
      expect(snapshot.wayfinder?.archived).toContain('session:s-drag');
    });

    const archived = within(panel).getByRole('button', { name: '恢复 一个需要完整显示的长对话名称' });
    fireEvent.click(archived);
    await waitFor(() => expect(panel.querySelector('[data-dialogue-file]')).toBeInTheDocument());
    await waitFor(() => {
      const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
        wayfinder?: { archived?: string[] };
      };
      expect(snapshot.wayfinder?.archived).not.toContain('session:s-drag');
    });
  });

  it('keeps a dialogue file visible after moving it into another project folder', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [
          sessionRecord('s-source', '来源对话', { workspaceRoots: ['/work/source'] }),
          sessionRecord('s-target', '目标对话', { workspaceRoots: ['/work/target'] }),
        ] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    const panel = await screen.findByRole('region', { name: '最近工作' });
    const folders = panel.querySelectorAll<HTMLDetailsElement>('[data-project-folder]');
    expect(folders).toHaveLength(2);
    const sourceFile = within(folders[0]!).getByRole('button', { name: /来源对话/ });
    const targetFolder = folders[1]!;
    const transfer = dragTransfer();

    fireEvent.dragStart(sourceFile, { dataTransfer: transfer });
    fireDrop(targetFolder, transfer);

    await waitFor(() => {
      expect(targetFolder).toHaveAttribute('open');
      expect(within(targetFolder).getByRole('button', { name: /来源对话/ })).toBeInTheDocument();
    });
    await waitFor(() => {
      const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
        wayfinder?: { projectAssignments?: Record<string, string> };
      };
      expect(snapshot.wayfinder?.projectAssignments?.['session:s-source']).toBe('/work/target');
    });
  });

  it('reports an unreadable directory with a retry instead of an empty desktop', async () => {
    renderPanel({ routes: {} });

    expect(await screen.findByRole('alert')).toHaveTextContent('工作记录暂时无法读取');
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });

  it('loads dialogue files beyond the initial bounded Session and Room windows', async () => {
    const sessions = Array.from({ length: 101 }, (_, index) => sessionRecord(
      `session-${index}`,
      index === 100 ? '最早 Session 对话' : `Session ${index}`,
      { updatedAtMs: NOW - index, workspaceRoots: ['/work/paw'] },
    ));
    const rooms = Array.from({ length: 101 }, (_, index) => ({
      id: `room-${index}`,
      title: index === 100 ? '最早 Room 协作' : `Room ${index}`,
      status: 'active',
      updatedAtMs: NOW - index,
      workspaceRoots: ['/work/paw'],
      participants: [],
      workItems: [],
    }));
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': (request: ControlRequest) => ({
        ok: true,
        items: sessions.slice(0, Number(request.query?.limit ?? 100)),
      }),
      'agent.rooms.list': (request: ControlRequest) => ({
        ok: true,
        items: rooms.slice(0, Number(request.query?.limit ?? 100)),
      }),
    } });
    render(
      <ControlTransportProvider transport={transport}>
        <PawDesktopProvider><PawWayfinderWork /></PawDesktopProvider>
      </ControlTransportProvider>,
    );

    const panel = await screen.findByRole('region', { name: '最近工作' });
    expect(within(panel).queryByText('最早 Session 对话')).not.toBeInTheDocument();
    expect(within(panel).queryByText('最早 Room 协作')).not.toBeInTheDocument();
    fireEvent.click(within(panel).getByRole('button', { name: '加载更多工作记录' }));

    await waitFor(() => expect(within(panel).getByText('1 个项目 · 202 个对话')).toBeInTheDocument());
    fireEvent.change(within(panel).getByRole('searchbox', { name: '搜索最近工作' }), { target: { value: '最早' } });
    expect(await within(panel).findByText('最早 Session 对话')).toBeInTheDocument();
    expect(within(panel).getByText('最早 Room 协作')).toBeInTheDocument();
    expect(transport.requests.some(({ request }) => request.pathId === 'agent.sessions.list' && request.query?.limit === 200)).toBe(true);
    expect(transport.requests.some(({ request }) => request.pathId === 'agent.rooms.list' && request.query?.limit === 200)).toBe(true);
  });
});

function renderPanel(options: MockControlTransportOptions) {
  return render(
    <ControlTransportProvider transport={new MockControlTransport(options)}>
      <PawDesktopProvider>
        <PawWayfinderWork />
      </PawDesktopProvider>
    </ControlTransportProvider>,
  );
}

function sessionRecord(id: string, title: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title,
    mode: 'assistant',
    status: 'idle',
    roleId: 'default',
    roleVersion: '1',
    roleBookRevisionId: 'r1',
    updatedAtMs: NOW - 60_000,
    workspaceRoots: [],
    ...overrides,
  };
}

function dragTransfer(): DataTransfer {
  const values = new Map<string, string>();
  return {
    clearData: (format?: string) => {
      if (format) values.delete(format);
      else values.clear();
    },
    dropEffect: 'move',
    effectAllowed: 'move',
    files: [] as unknown as FileList,
    getData: (format: string) => values.get(format) ?? '',
    items: [] as unknown as DataTransferItemList,
    setData: (format: string, value: string) => values.set(format, value),
    setDragImage: () => undefined,
    types: [WAYFINDER_DRAG_MIME, 'text/plain'],
  } as unknown as DataTransfer;
}

function fireDrop(element: HTMLElement, dataTransfer: DataTransfer, clientX = 0, clientY = 0): void {
  const event = new Event('drop', { bubbles: true, cancelable: true });
  Object.defineProperties(event, {
    clientX: { configurable: true, value: clientX },
    clientY: { configurable: true, value: clientY },
    dataTransfer: { configurable: true, value: dataTransfer },
  });
  fireEvent(element, event);
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
