import { act, cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import { agentEventFixture } from '@/test/fixtures/events';
import { MockControlTransport, type MockControlTransportOptions } from '@/test/mock-transport';
import type { ControlRequest } from '@/platform/transport';
import { FileCollaborationPanel } from './FileCollaborationPanel';

afterEach(cleanup);
const path = '/work/paw/docs/plan.md';
const registeredDocuments = { schemaVersion: 'rag-ime.work-document-list.v1', total: 1, items: [{
  documentId: `workdoc_${'a'.repeat(32)}`, title: '阅读计划', authorityKind: 'session_todo', authorityId: 'session-1', authorityKey: 'session_todo:session-1',
  authorityRevision: 1, documentRevision: 1, contentSha256: 'a'.repeat(64), terminalReceiptId: '', error: '', createdAtMs: 1, updatedAtMs: 2,
  workspaceRoot: '/work/paw', path: 'docs/plan.md', activePath: 'docs/plan.md', archivePath: 'docs/archive/plan.md', state: 'active',
}] };
function fixture(overrides: MockControlTransportOptions['routes'] = {}) {
  return new MockControlTransport({ routes: {
    'agent.sessions.list': { items: [{ id: 'session-1', title: '工作 Session', workspaceRoots: ['/work/paw'] }] },
    'agent.rooms.list': { items: [{ id: 'room-1', title: '开发 Room', workspaceRoots: ['/work/paw'] }] },
    'agent.room.get': { room: { id: 'room-1', title: '开发 Room', participants: [], workItems: [], artifacts: [{ id: 'artifact-1', displayName: '计划产物', path }] } },
    'workDocuments.list': registeredDocuments,
    'agent.session.snapshot': snapshot(),
    ...overrides,
  } });
}
function snapshot(filePath = 'docs/plan.md', completed = false, cursor = completed ? 2 : 1) {
  const payload = { toolCallId: 'call-1', toolName: 'edit', publicResult: { path: filePath, fileName: 'plan.md' } };
  return {
    sessionId: 'session-1', status: completed ? 'idle' : 'busy', messages: [], lastSequence: cursor,
    liveEvents: [agentEventFixture(1, 'tool_started', payload), ...(completed ? [agentEventFixture(2, 'tool_finished', payload)] : [])],
  };
}
function surface(transport: MockControlTransport, openRoute = vi.fn(), filePath = path) {
  return <ControlTransportProvider transport={transport}><PawOsDesktopProvider openRoute={openRoute} openWindow={() => {}}>
    <FileCollaborationPanel sessionId="session-1" path={filePath} fileName={filePath.split('/').at(-1)} />
  </PawOsDesktopProvider></ControlTransportProvider>;
}

describe('Files collaboration panel', () => {
  it('loads only when expanded and opens the actual document, Session and Room from their distinct associations', async () => {
    const user = userEvent.setup();
    const transport = fixture();
    const openRoute = vi.fn();
    render(surface(transport, openRoute));
    expect(transport.requests).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: '协作与访问' }));
    const relations = await screen.findByRole('region', { name: '文档责任与产物' });
    await user.click(within(relations).getByRole('button', { name: '打开 Session 工作 Session' }));
    expect(openRoute).toHaveBeenLastCalledWith('/agent?session=session-1');
    await user.click(within(relations).getByRole('button', { name: '打开 Room 开发 Room' }));
    expect(openRoute).toHaveBeenLastCalledWith('/rooms?room=room-1');
    await user.click(within(relations).getByRole('button', { name: '打开工作文档' }));
    expect(openRoute).toHaveBeenLastCalledWith(`/work-documents?document=workdoc_${'a'.repeat(32)}`);
    expect(await screen.findByText('正在修改')).toBeInTheDocument();
    expect(screen.getByText(/核对 1\/1 个相关 Room/)).toBeInTheDocument();
    expect(transport.requests.filter(({ request }) => request.pathId === 'agent.session.snapshot')).toHaveLength(1);
  });

  it('removes current-operation claims after a failed refresh, retains the attempt and retries the same Session', async () => {
    const user = userEvent.setup();
    let reads = 0;
    const transport = fixture({ 'agent.session.snapshot': () => {
      reads += 1;
      if (reads === 2) throw new Error('private transport details');
      return snapshot('docs/plan.md', reads >= 3);
    } });
    render(surface(transport));
    await user.click(screen.getByRole('button', { name: '协作与访问' }));
    expect(await screen.findByText('正在修改')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '刷新访问记录' }));
    expect(await screen.findByText(/状态未知/)).toBeInTheDocument();
    expect(screen.queryByText('正在修改')).not.toBeInTheDocument();
    expect(screen.getByText('修改尝试')).toBeInTheDocument();
    expect(screen.queryByText(/private transport/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '重试访问记录' }));
    expect(await screen.findByText('已修改')).toBeInTheDocument();
    expect(reads).toBe(3);
    expect(transport.requests.filter(({ request }) => request.pathId === 'agent.session.snapshot').every(({ request }) => request.params?.sessionId === 'session-1')).toBe(true);
  });

  it('does not revive a running claim from an older snapshot after a completed receipt', async () => {
    const user = userEvent.setup();
    let reads = 0;
    const transport = fixture({ 'agent.session.snapshot': () => snapshot('docs/plan.md', ++reads === 1) });
    render(surface(transport));
    await user.click(screen.getByRole('button', { name: '协作与访问' }));
    expect(await screen.findByText('已修改')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '刷新访问记录' }));
    expect(await screen.findByText(/状态未知/)).toBeInTheDocument();
    expect(screen.getByText('已修改')).toBeInTheDocument();
    expect(screen.queryByText('正在修改')).not.toBeInTheDocument();
  });

  it('cancels a previous file read and cannot show its late Tool result on the next file', async () => {
    const user = userEvent.setup();
    let finishOld: (value: unknown) => void = () => {};
    let signal: AbortSignal | undefined;
    let reads = 0;
    const oldRead = new Promise((resolve) => { finishOld = resolve; });
    const transport = fixture({ 'agent.session.snapshot': (request: ControlRequest) => {
      reads += 1;
      if (reads > 1) return snapshot('docs/next.md', true);
      signal = request.signal;
      return oldRead;
    } });
    const view = render(surface(transport));
    await user.click(screen.getByRole('button', { name: '协作与访问' }));
    expect(await screen.findByText('正在读取访问记录…')).toBeInTheDocument();
    view.rerender(surface(transport, vi.fn(), '/work/paw/docs/next.md'));
    expect(signal?.aborted).toBe(true);
    await user.click(screen.getByRole('button', { name: '协作与访问' }));
    expect(await screen.findByText('已修改')).toBeInTheDocument();
    await act(async () => { finishOld(snapshot()); });
    expect(screen.queryByText('正在修改')).not.toBeInTheDocument();
    expect(screen.getByText('已修改')).toBeInTheDocument();
  });

  it('keeps workspace membership separate from access and lets an incomplete Room scan continue', async () => {
    const user = userEvent.setup();
    const transport = fixture({
      'agent.rooms.list': { items: Array.from({ length: 5 }, (_, index) => ({ id: `room-${index}`, title: `Room ${index}`, workspaceRoots: ['/work/paw'] })) },
      'agent.room.get': (request: ControlRequest) => ({ room: { id: request.params?.roomId, title: '后续 Room', participants: [], workItems: [], artifacts: request.params?.roomId === 'room-4' ? [{ id: 'late-artifact', path, displayName: '后续产物' }] : [] } }),
      'workDocuments.list': { schemaVersion: 'rag-ime.work-document-list.v1', total: 0, items: [] },
      'agent.session.snapshot': { sessionId: 'session-1', status: 'busy', messages: [], liveEvents: [], lastSequence: 0 },
    });
    render(surface(transport));
    await user.click(screen.getByRole('button', { name: '协作与访问' }));
    expect(await screen.findByText(/核对 3\/5 个相关 Room/)).toBeInTheDocument();
    expect(screen.getByText(/已读取的登记中尚未找到此文件/)).toBeInTheDocument();
    expect(screen.queryByText('正在修改')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '继续查找 Room 关联' }));
    expect(await screen.findByText('后续产物')).toBeInTheDocument();
    expect(screen.getByText(/核对 5\/5 个相关 Room/)).toBeInTheDocument();
    expect(transport.requests.every(({ request }) => !request.body)).toBe(true);
  });

  it('retains a previous document association as stale when only its registry refresh fails', async () => {
    const user = userEvent.setup();
    let failed = false;
    const transport = fixture({ 'workDocuments.list': () => {
      if (failed) throw new Error('registry unavailable');
      return registeredDocuments;
    } });
    render(surface(transport));
    await user.click(screen.getByRole('button', { name: '协作与访问' }));
    expect(await screen.findByText('阅读计划')).toBeInTheDocument();
    failed = true;
    await user.click(screen.getByRole('button', { name: '刷新文档关联' }));
    expect(await screen.findByText(/文档登记暂时读不到/)).toBeInTheDocument();
    expect(screen.getByText('阅读计划')).toBeInTheDocument();
    expect(screen.getByText(/上次读到的关联/)).toBeInTheDocument();
  });
});
