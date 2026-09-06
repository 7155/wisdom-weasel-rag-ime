import { agentSnapshotFromResponse, applyAgentSnapshot, createAgentProjection, type AgentProjectionState } from '@/contracts/agent-reducer';
import type { ControlTransport } from '@/platform/transport';

export interface FileCollaborationTarget { sessionId: string; path: string }
export interface CollaborationLink { kind: 'session' | 'room' | 'document'; id: string; title: string; route: string }
export interface FileRelation { id: string; kind: 'document' | 'artifact'; title: string; detail: string; links: CollaborationLink[]; stale?: boolean }
export interface FileSessionCandidate { sessionId: string; title: string; workspaceRoots: string[]; reason: string }
export interface FileCollaboration {
  relations: FileRelation[];
  workspace: CollaborationLink[];
  candidates: FileSessionCandidate[];
  issues: string[];
  limited: boolean;
  coverage: { sessions: number | null; rooms: number | null; documents: number | null; checkedRooms: number; relevantRooms: number };
}
export interface FileToolAccess {
  id: string; turnId: string; operation: 'read' | 'write' | 'edit' | 'patch';
  state: 'running' | 'completed' | 'failed' | 'not_executed' | 'unconfirmed'; atMs: number;
}
export interface FileAccessProjection { rows: FileToolAccess[]; unresolvedTargetCount: number }

const SESSION_LIMIT = 40;
const ROOM_LIMIT = 24;
const DOCUMENT_LIMIT = 200;
const ROOM_DETAIL_LIMIT = 3;
const GOAL_LOOKUP_LIMIT = 4;
const CANDIDATE_LIMIT = 12;
const FILE_OPERATIONS: Record<string, FileToolAccess['operation']> = {
  read: 'read', read_file: 'read', workspace_read: 'read',
  write: 'write', write_file: 'write', workspace_write_file: 'write', workspace_write: 'write',
  edit: 'edit', edit_file: 'edit', workspace_edit_file: 'edit', workspace_edit: 'edit', workspace_patch: 'patch',
};

/** Exact API paths only. Display filenames and redacted suffixes are not identities. */
export function fileToolAccess(projection: AgentProjectionState, path: string, workspaceRoots: string[]): FileAccessProjection {
  const target = absolutePath(path);
  const rows: FileToolAccess[] = [];
  let unresolvedTargetCount = 0;
  for (const activity of Object.values(projection.activitiesById)) {
    if (!['tool_started', 'tool_progress', 'tool_finished'].includes(activity.kind)) continue;
    const operation = FILE_OPERATIONS[text(activity.payload.toolName).toLowerCase()];
    if (!operation) continue;
    const publicResult = record(activity.payload.publicResult);
    const args = record(activity.payload.args);
    const toolResult = record(activity.payload.result);
    const receipts = [activity.payload, publicResult, toolResult, record(toolResult.details), record(activity.payload.details)];
    const notExecuted = receipts.some((receipt) => receipt.expectedNoop === true || receipt.governanceBlocked === true || receipt.blocked === true);
    const failed = activity.status === 'failed' || activity.payload.isError === true || receipts.some((receipt) => receipt.ok === false);
    // Unlike fileName, these fields describe the target passed to the Tool.
    const rawPath = text(publicResult.relativePath) || text(publicResult.path)
      || text(args.relativePath) || text(args.file_path) || text(args.path);
    const roots = [...new Set(workspaceRoots.map(absolutePath).filter(Boolean))];
    const explicitDirectory = text(publicResult.cwd) || text(publicResult.root) || text(args.cwd) || text(args.root);
    const directory = explicitDirectory
      ? absolutePath(explicitDirectory)
      : roots.length === 1 && roots[0] !== '/' ? roots[0] : '';
    const resolved = absolutePath(rawPath) || relativeTo(directory, rawPath);
    if (!resolved) {
      unresolvedTargetCount += 1;
      continue;
    }
    if (!target || resolved !== target) continue;
    const turn = projection.turnsById[activity.turnId];
    const live = !projection.needsSnapshot
      && activity.status === 'running' && turn?.status === 'running'
      && activity.turnId === projection.turnOrder.at(-1)
      && ['busy', 'working', 'responding', 'analyzing'].includes(projection.status);
    rows.push({
      id: activity.id, turnId: activity.turnId, operation,
      // A quiescent snapshot can settle an orphaned start. That is not a
      // successful write receipt, so retain it only as an unconfirmed attempt.
      state: notExecuted ? 'not_executed' : failed ? 'failed'
        : activity.kind === 'tool_finished' && activity.status === 'completed' ? 'completed'
          : live ? 'running' : 'unconfirmed',
      atMs: activity.updatedAtMs,
    });
  }
  rows.sort((a, b) => Number(b.state === 'running') - Number(a.state === 'running') || b.atMs - a.atMs);
  return { rows: rows.slice(0, 12), unresolvedTargetCount };
}

/** Three bounded catalogs, then only relevant Room/Goal owners. No Tool reads until requested. */
export async function collectFileCollaboration(
  transport: ControlTransport, target: FileCollaborationTarget, options: { signal?: AbortSignal; roomDetailLimit?: number } = {},
): Promise<FileCollaboration> {
  const result: FileCollaboration = { relations: [], workspace: [], candidates: [], issues: [], limited: false,
    coverage: { sessions: null, rooms: null, documents: null, checkedRooms: 0, relevantRooms: 0 } };
  const { signal } = options;
  const path = absolutePath(target.path);
  if (!path) return { ...result, issues: ['当前文件没有可核对的完整路径'] };
  async function read(request: Parameters<ControlTransport['request']>[0], issue: string): Promise<Record<string, unknown>> {
    signal?.throwIfAborted();
    try {
      const response = record(await transport.request({ ...request, signal }));
      signal?.throwIfAborted();
      if (response.ok === false) throw new Error('Read rejected');
      return response;
    } catch (error) {
      signal?.throwIfAborted();
      if (!result.issues.includes(issue)) result.issues.push(issue);
      return {};
    }
  }
  const [sessionResponse, roomResponse, documentResponse] = await Promise.all([
    read({ pathId: 'agent.sessions.list', query: { limit: SESSION_LIMIT, includeArchived: true, includeInternal: true, projectionOnly: true } }, 'Session 目录暂时读不到'),
    read({ pathId: 'agent.rooms.list', query: { limit: ROOM_LIMIT, includeArchived: true, projectionOnly: true } }, 'Room 目录暂时读不到'),
    read({ pathId: 'workDocuments.list', query: { limit: DOCUMENT_LIMIT } }, '文档登记暂时读不到'),
  ]);
  for (const [value, keys, issue] of [
    [sessionResponse, ['items', 'sessions'], 'Session 目录暂时读不到'],
    [roomResponse, ['items', 'rooms'], 'Room 目录暂时读不到'],
    [documentResponse, ['items'], '文档登记暂时读不到'],
  ] as const) {
    if (!keys.some((key) => Array.isArray(value[key])) && !result.issues.includes(issue)) result.issues.push(issue);
  }
  const sessions = records(sessionResponse.items ?? sessionResponse.sessions).slice(0, SESSION_LIMIT);
  const rooms = records(roomResponse.items ?? roomResponse.rooms).slice(0, ROOM_LIMIT);
  const documents = records(documentResponse.items).slice(0, DOCUMENT_LIMIT).filter((item) => (
    (absolutePath(text(item.path)) || relativeTo(text(item.workspaceRoot), text(item.path))) === path
  ));
  result.limited = sessionResponse.hasMore === true || sessions.length === SESSION_LIMIT
    || roomResponse.hasMore === true || rooms.length === ROOM_LIMIT
    || Number(documentResponse.total) > DOCUMENT_LIMIT;
  const sessionById = new Map(sessions.filter((item) => text(item.id)).map((item) => [text(item.id), item]));
  const candidateById = new Map<string, FileSessionCandidate>();
  function addCandidate(id: string, reason: string, fallbackTitle = '') {
    if (!id) return;
    const item = sessionById.get(id);
    const previous = candidateById.get(id);
    candidateById.set(id, {
      sessionId: id, title: text(item?.title) || fallbackTitle || id,
      workspaceRoots: strings(item?.workspaceRoots), reason: previous?.reason || reason,
    });
  }
  function sessionLink(id: string, reason: string, fallbackTitle = ''): CollaborationLink {
    addCandidate(id, reason, fallbackTitle);
    return link('session', id, text(sessionById.get(id)?.title) || fallbackTitle || id);
  }
  const relevantRooms = rooms.filter((room) => containsFile(strings(room.workspaceRoots), path)
    || records(room.participants).some((participant) => text(participant.sessionId) === target.sessionId));
  const roomDetailLimit = Math.max(ROOM_DETAIL_LIMIT, Math.min(ROOM_LIMIT, options.roomDetailLimit ?? ROOM_DETAIL_LIMIT));
  if (relevantRooms.length > roomDetailLimit) result.limited = true;
  const details: Record<string, unknown>[] = [];
  // Continuing is explicit, and at most three Room reads are in flight.
  for (let offset = 0; offset < Math.min(relevantRooms.length, roomDetailLimit); offset += ROOM_DETAIL_LIMIT) {
    details.push(...await Promise.all(relevantRooms.slice(offset, Math.min(offset + ROOM_DETAIL_LIMIT, roomDetailLimit)).map(async (room) => {
      const value = await read({ pathId: 'agent.room.get', params: { roomId: text(room.id) } }, '部分 Room 关联暂时读不到');
      const detail = Object.keys(record(value.room)).length ? record(value.room) : value;
      if (text(detail.id) !== text(room.id)) {
        if (!result.issues.includes('部分 Room 关联暂时读不到')) result.issues.push('部分 Room 关联暂时读不到');
        return {};
      }
      result.coverage.checkedRooms += 1;
      return { ...room, ...detail };
    })));
  }
  Object.assign(result.coverage, {
    sessions: result.issues.includes('Session 目录暂时读不到') ? null : sessions.length,
    rooms: result.issues.includes('Room 目录暂时读不到') ? null : rooms.length,
    documents: result.issues.includes('文档登记暂时读不到') ? null : records(documentResponse.items).length,
    relevantRooms: relevantRooms.length,
  });
  for (const room of details) {
    if (records(room.artifacts).length >= 100 || records(room.workItems).length >= 100) result.limited = true;
  }

  const goalDocuments = documents.filter((item) => item.authorityKind === 'session_goal');
  const goalOwners = new Map<string, string>();
  if (goalDocuments.length) {
    const candidates = sessions.filter((item) => text(item.id) === target.sessionId || containsFile(strings(item.workspaceRoots), path))
      .sort((a, b) => Number(text(b.id) === target.sessionId) - Number(text(a.id) === target.sessionId));
    if (candidates.length > GOAL_LOOKUP_LIMIT) result.limited = true;
    await Promise.all(candidates.slice(0, GOAL_LOOKUP_LIMIT).map(async (candidate) => {
      const id = text(candidate.id);
      const workflow = await read({ pathId: 'agent.session.workflow.get', params: { sessionId: id } }, '部分目标责任暂时读不到');
      const goal = record(workflow.goal);
      if (text(workflow.sessionId) === id && (!text(goal.sessionId) || text(goal.sessionId) === id) && text(goal.goalId)) {
        goalOwners.set(text(goal.goalId), id);
      }
    }));
  }
  for (const item of documents) {
    const id = text(item.documentId);
    const links = [link('document', id, '工作文档')];
    const authorityId = text(item.authorityId);
    const state = item.state === 'archived' ? '已归档' : item.state === 'active' ? '已登记' : '文档状态待核对';
    let detail = state;
    if (item.authorityKind === 'session_todo' && authorityId) {
      links.push(sessionLink(authorityId, '文档责任 Session'));
      detail += ' · Session 任务';
    } else if (item.authorityKind === 'session_goal') {
      const owner = goalOwners.get(authorityId);
      if (owner) links.push(sessionLink(owner, '文档目标责任 Session'));
      else result.limited = true;
      detail += owner ? ' · Session 目标' : ' · 目标责任尚未在本次候选中找到';
    } else if (item.authorityKind === 'room_work_item') {
      const room = details.find((candidate) => records(candidate.workItems).some((work) => text(work.id) === authorityId));
      const work = records(room?.workItems).find((candidate) => text(candidate.id) === authorityId);
      if (room && work) {
        links.push(link('room', text(room.id), text(room.title)));
        const participant = records(room.participants).find((candidate) => text(candidate.id) === text(work.currentOwnerParticipantId));
        if (text(participant?.sessionId)) links.push(sessionLink(text(participant?.sessionId), '工作项责任 Session', text(participant?.displayName)));
        detail += ` · ${workState(text(work.state))}${text(work.objective) ? ` · ${text(work.objective)}` : ''}`;
      } else {
        result.limited = true;
        detail += ' · 工作项责任尚未在本次候选中找到';
      }
    }
    result.relations.push({ id, kind: 'document', title: text(item.title) || '已登记文档', detail, links });
  }
  for (const room of details) {
    for (const artifact of records(room.artifacts)) {
      if (absolutePath(text(artifact.path)) !== path) continue;
      const links = [link('room', text(room.id), text(room.title))];
      const ownerIds = new Set([text(artifact.createdByParticipantId)]);
      for (const work of records(room.workItems)) {
        if (strings(work.artifactRefs).some((ref) => ref === text(artifact.id) || absolutePath(ref) === path)) ownerIds.add(text(work.currentOwnerParticipantId));
      }
      for (const participant of records(room.participants)) {
        if (ownerIds.has(text(participant.id)) && text(participant.sessionId)) {
          links.push(sessionLink(text(participant.sessionId), '产物关联 Session', text(participant.displayName)));
        }
      }
      result.relations.push({
        id: text(artifact.id), kind: 'artifact', title: text(artifact.displayName) || 'Room 产物',
        detail: `Room 产物 · ${artifact.status === 'archived' ? '已归档' : '已登记'}`, links,
      });
    }
  }
  for (const item of sessions) {
    if (!containsFile(strings(item.workspaceRoots), path)) continue;
    const id = text(item.id);
    result.workspace.push(link('session', id, text(item.title)));
    addCandidate(id, '同一工作区');
  }
  for (const room of rooms) {
    if (containsFile(strings(room.workspaceRoots), path)) result.workspace.push(link('room', text(room.id), text(room.title)));
  }
  addCandidate(target.sessionId, '当前文件的读取 Session');
  const current = candidateById.get(target.sessionId);
  result.candidates = [...(current ? [current] : []), ...[...candidateById.values()].filter((item) => item.sessionId !== target.sessionId)].slice(0, CANDIDATE_LIMIT);
  if (candidateById.size > CANDIDATE_LIMIT) result.limited = true;
  if (result.issues.length) result.limited = true;
  return result;
}

/** A single selected candidate, using the existing Runtime snapshot reducer. */
export async function readFileActivity(
  transport: ControlTransport, candidate: FileSessionCandidate, options: { signal?: AbortSignal; previous?: AgentProjectionState } = {},
): Promise<AgentProjectionState> {
  const response = record(await transport.request({ pathId: 'agent.session.snapshot', params: { sessionId: candidate.sessionId }, query: { view: 'recent' }, signal: options.signal }));
  options.signal?.throwIfAborted();
  if (response.ok === false || text(response.sessionId) !== candidate.sessionId || !Array.isArray(response.liveEvents) || typeof response.status !== 'string') {
    throw new Error('当前 Session 的工具记录尚未取得');
  }
  const snapshot = agentSnapshotFromResponse(response);
  if (options.previous && snapshot.lastSequence < options.previous.lastSequence) throw new Error('工具记录暂时落后于已读状态');
  return applyAgentSnapshot(options.previous ?? createAgentProjection(candidate.sessionId), snapshot);
}

function link(kind: CollaborationLink['kind'], id: string, title: string): CollaborationLink {
  const query = new URLSearchParams({ [kind === 'document' ? 'document' : kind]: id });
  return { kind, id, title: title || id, route: `${kind === 'session' ? '/agent' : kind === 'room' ? '/rooms' : '/work-documents'}?${query}` };
}
function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function records(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.map(record) : []; }
function strings(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []; }
function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
function safePath(value: string): boolean { return Boolean(value) && !/[\x00-\x1f\x7f]/.test(value) && !value.includes('…') && !/\[.*REDACTED.*\]/i.test(value) && !value.startsWith('~/') && !value.split('/').includes('..'); }
function absolutePath(value: string): string { return safePath(value) && value.startsWith('/') ? `/${value.split('/').filter((part) => part && part !== '.').join('/')}` : ''; }
function relativeTo(root: string, value: string): string {
  const base = absolutePath(root);
  return base && safePath(value) && !value.startsWith('/') && !/^[a-z]:/i.test(value) ? absolutePath(`${base}/${value}`) : '';
}
function containsFile(roots: string[], path: string): boolean {
  return roots.some((value) => { const root = absolutePath(value); return root && root !== '/' && path.startsWith(`${root}/`); });
}
function workState(value: string): string {
  return ({ queued: '工作项待处理', active: '工作项进行中', review: '工作项待检查', blocked: '工作项遇阻', done: '工作项已完成', failed: '工作项失败', cancelled: '工作项已取消' } as Record<string, string>)[value] || '工作项已登记';
}
