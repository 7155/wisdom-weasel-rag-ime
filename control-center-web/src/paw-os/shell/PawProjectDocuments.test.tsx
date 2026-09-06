import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { SessionSummary } from '@/features/agent/types';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { PawProjectDocuments } from './PawProjectDocuments';
import { projectWayfinderWork, type WayfinderWorkProject } from './wayfinder-work-projection';

afterEach(cleanup);
const ROOT = '/workspace/project';
const session = (id = 'session-one', roots = [ROOT]): SessionSummary => ({
  id, title: id, mode: 'coordinator', status: 'idle', updatedAtMs: 1,
  roleId: 'default', roleVersion: '1', roleBookRevisionId: 'revision', workspaceRoots: roots,
});
const projectFor = (sessions: SessionSummary[]) => projectWayfinderWork({ nowMs: 2, sessions, rooms: [] }).projects[0]!;
const file = (name: string, directory = ROOT) => ({ name, path: `${directory}/${name}`, kind: 'file' });
const folder = (name: string, directory = ROOT) => ({ name, path: `${directory}/${name}`, kind: 'directory' });
function view(transport: MockControlTransport, sessions = [session()], project: WayfinderWorkProject = projectFor(sessions), onOpenFile = vi.fn(), onOpenWork = vi.fn()) {
  return <ControlTransportProvider transport={transport}><PawProjectDocuments project={project} sessions={sessions} onOpenFile={onOpenFile} onOpenWork={onOpenWork} /></ControlTransportProvider>;
}

describe('PawProjectDocuments', () => {
  it('browses returned documents and folders through their project Session and opens canonical Files', async () => {
    const onOpenFile = vi.fn();
    const transport = new MockControlTransport({ routes: {
      'agent.session.workspace.list': (request: ControlRequest) => ({ items: request.query?.path === ROOT
        ? [file('README.md'), folder('docs'), folder('src'), { ...file('escape.md'), path: '/outside/escape.md' }]
        : [file('guide.md', `${ROOT}/docs`), folder('architecture', `${ROOT}/docs`)], truncated: false }),
      'agent.session.workspace.read': (request: ControlRequest) => ({ path: request.query?.path, content: '# 实际文档\n项目内容', truncated: true }),
    } });
    render(view(transport, [session()], projectFor([session()]), onOpenFile));
    await screen.findByRole('button', { name: 'README.md' });
    expect(screen.queryByRole('button', { name: '打开目录 src' })).not.toBeInTheDocument();
    expect(screen.queryByText('escape.md')).not.toBeInTheDocument();
    expect(transport.requests[0]?.request).toMatchObject({ pathId: 'agent.session.workspace.list', params: { sessionId: 'session-one' }, query: { path: ROOT, depth: 1, limit: 240 } });
    fireEvent.click(screen.getByRole('button', { name: '打开目录 docs' }));
    fireEvent.click(await screen.findByRole('button', { name: 'guide.md' }));
    await screen.findByRole('heading', { name: '实际文档' });
    expect(screen.getByText(/前 64 KB/)).toBeInTheDocument();
    expect(transport.requests.find(({ request }) => request.pathId === 'agent.session.workspace.read')?.request.query).toEqual({ path: `${ROOT}/docs/guide.md`, offset: 0, limit: 65_536 });
    fireEvent.click(screen.getByRole('button', { name: '在 Files 中阅读' }));
    expect(onOpenFile).toHaveBeenCalledWith(`${ROOT}/docs/guide.md`, 'session-one');
    fireEvent.click(within(screen.getByRole('navigation', { name: '文档路径' })).getByRole('button', { name: 'project' }));
    await screen.findByRole('button', { name: 'README.md' });
    expect(screen.queryByRole('heading', { name: '实际文档' })).not.toBeInTheDocument();
  });

  it('does not invent a docs path when the returned directory has none', async () => {
    const transport = new MockControlTransport({ routes: { 'agent.session.workspace.list': { items: [file('package.json'), folder('src')], truncated: true } } });
    render(view(transport));
    await screen.findByText('这个目录暂时没有可查看的文档。');
    expect(screen.getByText(/当前仅显示已读取的部分/)).toBeInTheDocument();
    expect(transport.requests).toHaveLength(1);
    expect(transport.requests[0]?.request.query?.path).toBe(ROOT);
  });

  it('uses only a matching project Room participant when no standalone Session owns the root', async () => {
    const unrelated = session('unrelated');
    const partner = { ...session('partner'), roomParticipant: { roomId: 'room-one', participantId: 'partner-one', status: 'active' } } as SessionSummary;
    const project = projectWayfinderWork({ nowMs: 2, sessions: [partner], rooms: [{ id: 'room-one', title: '协作', updatedAtMs: 1, workspaceRoots: [ROOT] }] }).projects[0]!;
    const transport = new MockControlTransport({ routes: { 'agent.session.workspace.list': { items: [] } } });
    render(view(transport, [unrelated, partner], project));
    await screen.findByText('这个目录暂时没有可查看的文档。');
    expect(transport.requests[0]?.request.params).toEqual({ sessionId: 'partner' });
  });

  it('offers the actual unbound conversation without making file requests', () => {
    const sessions = [session('未绑定对话', [])];
    const onOpenWork = vi.fn();
    const project = projectFor(sessions);
    const transport = new MockControlTransport();
    render(view(transport, sessions, project, vi.fn(), onOpenWork));
    expect(screen.getByText('尚未绑定工作区')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '打开 未绑定对话' }));
    expect(onOpenWork).toHaveBeenCalledWith(project.items[0]);
    expect(transport.requests).toHaveLength(0);
  });

  it('aborts an old preview when the project changes and ignores its late response', async () => {
    let resolveOld!: (value: unknown) => void;
    const pending = new Promise((resolve) => { resolveOld = resolve; });
    const transport = new MockControlTransport({ routes: {
      'agent.session.workspace.list': (request: ControlRequest) => ({ items: [file('README.md', String(request.query?.path))] }),
      'agent.session.workspace.read': () => pending,
    } });
    const rendered = render(view(transport));
    fireEvent.click(await screen.findByRole('button', { name: 'README.md' }));
    await screen.findByText('正在读取文档…');
    const read = transport.requests.find(({ request }) => request.pathId === 'agent.session.workspace.read')!.request;
    const nextSessions = [session('session-two', ['/workspace/other'])];
    rendered.rerender(view(transport, nextSessions));
    await screen.findByRole('button', { name: 'README.md' });
    expect(read.signal?.aborted).toBe(true);
    await act(async () => { resolveOld({ path: `${ROOT}/README.md`, content: '# 过期内容', truncated: false }); });
    expect(screen.queryByText('过期内容')).not.toBeInTheDocument();
    expect(screen.getByText('选择文档，在这里阅读。')).toBeInTheDocument();
  });

  it('recovers a failed directory and a failed document without losing the selected path', async () => {
    let listFails = true;
    let readFails = true;
    const transport = new MockControlTransport({ routes: {
      'agent.session.workspace.list': () => { if (listFails) throw new Error('offline'); return { items: [file('README.md')] }; },
      'agent.session.workspace.read': () => { if (readFails) throw new Error('offline'); return { path: `${ROOT}/README.md`, content: '恢复后的正文', truncated: false }; },
    } });
    render(view(transport));
    await screen.findByText('文档目录暂时无法读取，请重试。');
    listFails = false;
    fireEvent.click(screen.getByRole('button', { name: '重试目录' }));
    fireEvent.click(await screen.findByRole('button', { name: 'README.md' }));
    await screen.findByText('这份文档暂时无法读取，请重试。');
    readFails = false;
    fireEvent.click(screen.getByRole('button', { name: '重试文档' }));
    await screen.findByText('恢复后的正文');
    await waitFor(() => expect(transport.requests.filter(({ request }) => request.pathId === 'agent.session.workspace.read')).toHaveLength(2));
  });
});
