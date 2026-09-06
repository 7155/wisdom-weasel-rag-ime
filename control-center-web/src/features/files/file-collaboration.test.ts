import { describe, expect, it } from 'vitest';
import { agentSnapshotFromResponse, applyAgentSnapshot, createAgentProjection } from '@/contracts/agent-reducer';
import { agentEventFixture } from '@/test/fixtures/events';
import { MockControlTransport } from '@/test/mock-transport';
import type { ControlRequest } from '@/platform/transport';
import { collectFileCollaboration, fileToolAccess } from './file-collaboration';

const target = { sessionId: 'session-1', path: '/work/paw/docs/plan.md' };
const session = (id: string, workspaceRoots = ['/work/paw']) => ({ id, title: id, workspaceRoots, updatedAtMs: 10 });
const document = (authorityKind: string, authorityId: string, extra = {}) => ({
  documentId: `workdoc_${authorityId.split('').map((value) => value.charCodeAt(0).toString(16)).join('').slice(0, 32).padEnd(32, '0')}`,
  title: `文档 ${authorityId}`, authorityKind, authorityId, authorityKey: `${authorityKind}:${authorityId}`,
  authorityRevision: 1, documentRevision: 1, contentSha256: 'a'.repeat(64), terminalReceiptId: '', error: '', createdAtMs: 1, updatedAtMs: 2,
  workspaceRoot: '/work/paw', path: 'docs/plan.md', activePath: 'docs/plan.md', archivePath: 'docs/archive/plan.md', state: 'active', ...extra,
});
const documents = (items: ReturnType<typeof document>[]) => ({ schemaVersion: 'rag-ime.work-document-list.v1', items, total: items.length });

describe('Files collaboration authority', () => {
  it('resolves Todo Session, Goal owner, and Room WorkItem identities without turning authority ids into Sessions', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': { items: [session('session-1'), session('goal-owner')] },
      'workDocuments.list': documents([document('session_todo', 'session-1'), document('session_goal', 'goal-7'), document('room_work_item', 'work-9')]),
      'agent.session.workflow.get': (request: ControlRequest) => {
        const projection = createAgentProjection(request.params!.sessionId);
        return { schemaVersion: 'rag-ime.agent-workflow-state.v1', ok: true, sessionId: request.params?.sessionId,
          todo: projection.todo, actGate: projection.actGate, goal: { ...projection.goal, sessionId: request.params!.sessionId, goalId: request.params?.sessionId === 'goal-owner' ? 'goal-7' : 'other-goal' } };
      },
      'agent.rooms.list': { items: [{ id: 'room-3', title: '开发 Room', workspaceRoots: ['/work/paw'] }] },
      'agent.room.get': { room: {
        id: 'room-3', title: '开发 Room', status: 'active', workspaceRoots: ['/work/paw'],
        participants: [{ id: 'partner-4', sessionId: 'partner-session', displayName: '实现伙伴' }],
        workItems: [{ id: 'work-9', objective: '实现阅读', state: 'active', currentOwnerParticipantId: 'partner-4' }],
        artifacts: [{ id: 'artifact-1', path: target.path, displayName: '计划产物', createdByParticipantId: 'partner-4', status: 'active' }],
      } },
    } });
    const result = await collectFileCollaboration(transport, target);
    expect(result.issues).toEqual([]);
    expect(result.relations.find((row) => row.title === '文档 goal-7')?.links).toContainEqual(expect.objectContaining({ kind: 'session', id: 'goal-owner', route: '/agent?session=goal-owner' }));
    expect(result.relations.find((row) => row.title === '文档 work-9')?.links).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'room', id: 'room-3', route: '/rooms?room=room-3' }),
      expect.objectContaining({ kind: 'session', id: 'partner-session' }),
    ]));
    expect(result.relations.find((row) => row.id === 'artifact-1')?.links).toContainEqual(expect.objectContaining({ id: 'room-3' }));
    expect(result.relations.flatMap((row) => row.links).filter((link) => link.kind === 'session').map((link) => link.id)).not.toEqual(expect.arrayContaining(['goal-7', 'work-9']));
    expect(result.candidates.map((candidate) => candidate.sessionId)).toContain('partner-session');
  });

  it('matches the current registered path and exact workspace, not basename or a reserved active path after archival', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': { items: [session('session-1'), session('other-workspace', ['/work/paw-copy']), session('unrestricted', ['/'])] },
      'agent.rooms.list': { items: [] },
      'workDocuments.list': documents([
        document('session_todo', 'right-owner'),
        document('session_todo', 'other-owner', { workspaceRoot: '/work/paw-copy' }),
        document('session_todo', 'archived-owner', { state: 'archived', path: 'docs/archive/plan.md' }),
      ]),
    } });
    const result = await collectFileCollaboration(transport, target);
    expect(result.issues).toEqual([]);
    expect(result.relations.map((row) => row.title)).toEqual(['文档 right-owner']);
    expect(result.workspace.map((row) => row.id)).toEqual(['session-1']);
    expect(result.candidates.map((row) => row.sessionId)).not.toContain('other-workspace');
    expect(result.candidates.map((row) => row.sessionId)).not.toContain('unrestricted');
  });

  it('bounds detail reads to relevant Rooms, forwards cancellation, and keeps partial associations on one failed source', async () => {
    const controller = new AbortController();
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': { items: [session('session-1')] },
      'workDocuments.list': () => { throw new Error('private error details'); },
      'agent.rooms.list': { items: Array.from({ length: 30 }, (_, index) => ({ id: `room-${index}`, title: `Room ${index}`, workspaceRoots: index < 8 ? ['/work/paw'] : ['/elsewhere'] })), hasMore: true },
      'agent.room.get': (request: ControlRequest) => ({ room: { id: request.params?.roomId, title: 'Room', participants: [], artifacts: [{ id: `artifact-${request.params?.roomId}`, path: target.path }], workItems: [] } }),
    } });
    const result = await collectFileCollaboration(transport, target, { signal: controller.signal });
    expect(result.relations.length).toBeGreaterThan(0);
    expect(result.issues).toContain('文档登记暂时读不到');
    expect(result.coverage.documents).toBeNull();
    expect(result.issues.join(' ')).not.toContain('private error');
    expect(result.limited).toBe(true);
    const reads = transport.requests.map(({ request }) => request).filter((request) => request.pathId === 'agent.room.get');
    expect(reads).toHaveLength(3);
    expect(reads.every((request) => request.signal === controller.signal)).toBe(true);
    expect(transport.requests.some(({ request }) => request.pathId === 'agent.session.snapshot')).toBe(false);
  });

  it('does not accept a foreign Room detail as the requested Room association', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': { items: [session('session-1')] },
      'workDocuments.list': documents([document('room_work_item', 'work-9')]),
      'agent.rooms.list': { items: [{ id: 'requested-room', title: '相关 Room', workspaceRoots: ['/work/paw'] }] },
      'agent.room.get': { room: { id: 'foreign-room', title: '其他 Room', workItems: [{ id: 'work-9', state: 'active' }], artifacts: [{ id: 'foreign-artifact', path: target.path }] } },
    } });
    const result = await collectFileCollaboration(transport, target);
    expect(result.relations.some((row) => row.kind === 'artifact')).toBe(false);
    expect(result.relations.flatMap((row) => row.links).some((item) => item.kind === 'room')).toBe(false);
    expect(result.issues).toContain('部分 Room 关联暂时读不到');
    expect(result.coverage.checkedRooms).toBe(0);
  });

  it('always retains the file-bound Session when more than twelve candidates share its workspace', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': { items: Array.from({ length: 13 }, (_, index) => session(`session-${index + 1}`)) },
      'agent.rooms.list': { items: [] },
      'workDocuments.list': documents([]),
    } });
    const result = await collectFileCollaboration(transport, { ...target, sessionId: 'session-13' });
    expect(result.candidates).toHaveLength(12);
    expect(result.candidates.some((item) => item.sessionId === 'session-13')).toBe(true);
    expect(result.limited).toBe(true);
  });
});

describe('Files exact tool access', () => {
  function projection(status: string, payload: Record<string, unknown>, finish = false) {
    const events = [agentEventFixture(1, 'tool_started', { toolCallId: 'call-1', toolName: 'edit', ...payload })];
    if (finish) events.push(agentEventFixture(2, 'tool_finished', { toolCallId: 'call-1', toolName: 'edit', ...payload }));
    return applyAgentSnapshot(createAgentProjection('session-1'), agentSnapshotFromResponse({
      sessionId: 'session-1', status, messages: [], liveEvents: events, lastSequence: events.length,
    }));
  }

  it('uses the real path over a display filename and keeps active access separate from settled history', () => {
    const payload = { publicResult: { fileName: 'plan.md', path: 'docs/plan.md' } };
    const active = fileToolAccess(projection('busy', payload), target.path, ['/work/paw']);
    expect(active.rows).toEqual([expect.objectContaining({ id: 'call-1', operation: 'edit', state: 'running' })]);
    expect(fileToolAccess(projection('idle', payload, true), target.path, ['/work/paw']).rows[0]?.state).toBe('completed');
    // A stale tool start replayed into a quiescent snapshot proves an attempt,
    // not that it is still executing or that its file mutation succeeded.
    expect(fileToolAccess(projection('idle', payload), target.path, ['/work/paw']).rows[0]?.state).toBe('unconfirmed');
  });

  it.each([
    { path: '…/work/paw/docs/plan.md', fileName: 'plan.md' },
    { fileName: 'plan.md' },
    { path: '/work/paw-copy/docs/plan.md' },
    { path: '../paw/docs/plan.md' },
  ])('never turns an ambiguous or different target into this file: %j', (publicResult) => {
    const result = fileToolAccess(projection('busy', { publicResult }), target.path, ['/work/paw']);
    expect(result.rows).toEqual([]);
  });

  it('requires an explicit working directory when a Session has several workspace roots', () => {
    const roots = ['/work/paw', '/work/other'];
    const ambiguous = fileToolAccess(projection('busy', { publicResult: { path: 'docs/plan.md' } }), target.path, roots);
    expect(ambiguous.rows).toEqual([]);
    expect(ambiguous.unresolvedTargetCount).toBe(1);
    const exact = fileToolAccess(projection('busy', { publicResult: { path: 'docs/plan.md', cwd: '/work/paw' } }), target.path, roots);
    expect(exact.rows[0]?.state).toBe('running');
  });

  it('does not use a new active Turn to resurrect an older orphaned file Tool start', () => {
    const state = applyAgentSnapshot(createAgentProjection('session-1'), agentSnapshotFromResponse({
      sessionId: 'session-1', status: 'busy', messages: [], lastSequence: 2,
      liveEvents: [
        agentEventFixture(1, 'tool_started', { toolCallId: 'old-call', toolName: 'edit', publicResult: { path: 'docs/plan.md' } }),
        { ...agentEventFixture(2, 'tool_started', { toolCallId: 'new-call', toolName: 'read', publicResult: { path: 'docs/other.md' } }), turnId: 'new-turn' },
      ],
    }));
    expect(fileToolAccess(state, target.path, ['/work/paw']).rows[0]?.state).toBe('unconfirmed');
  });

  it.each([
    { isError: true, result: { details: { ok: false, error: 'Act Gate blocked workspace mutation (goal_paused): 当前 Goal 已暂停，恢复后才能继续写入。' } } },
    { result: { details: { blocked: true, blockedBy: 'act_gate', requiredAction: 'review_workflow_state', retryable: false } } },
  ])('keeps a completed but blocked Tool receipt out of successful file modifications: %j', (receipt) => {
    const state = projection('idle', { publicResult: { path: 'docs/plan.md' }, ...receipt }, true);
    expect(fileToolAccess(state, target.path, ['/work/paw']).rows[0]?.state).toBe('not_executed');
  });
});
