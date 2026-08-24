import type {
  RoomActivityProjection,
  RoomMessageProjection,
  RoomProjectionState,
} from '@/contracts/room-reducer';
import type { RoomSummary, RoomWorkItem, RoomWorkState } from '@/features/rooms/room-types';

export type RoomFocusState =
  | 'idle'
  | 'waiting'
  | 'running'
  | 'review'
  | 'blocked'
  | 'completed'
  | 'failed'
  | 'stopped'
  | 'disconnected';

export interface RoomFocusEvidence {
  ref: string;
  kind: 'artifact' | 'evidence';
}

export interface RoomFocusBlocker {
  reason: string;
  nextStep?: string;
}

export interface RoomFocusWorkItem {
  id: string;
  parentId?: string;
  source: 'work-item' | 'runtime';
  objective: string;
  expectedOutput?: string;
  acceptanceCriteria: string[];
  ownerParticipantId?: string;
  offeredToParticipantId?: string;
  accountableParticipantId?: string;
  state: RoomFocusState;
  currentAction?: string;
  blocker?: RoomFocusBlocker;
  reviewRequired: boolean;
  latestResult?: string;
  evidence: RoomFocusEvidence[];
  dispatchId?: string;
  updatedAtMs: number;
}

export interface RoomFocusPartner {
  participantId: string;
  sessionId: string;
  displayName: string;
  celestialName: string;
  collaborationRole?: string;
  state: RoomFocusState;
  ownedWorkItemIds: string[];
  currentAction: string;
  latestReceipt?: string;
  unread: boolean;
}

export interface RoomFocusHandoff {
  id: string;
  sourceParticipantId: string;
  targetParticipantId: string;
  workItemId?: string;
  dispatchId?: string;
  artifactOrContract?: string;
  task?: string;
  state: 'offered' | 'dispatched' | 'completed' | 'failed' | 'stopped';
  createdAtMs: number;
}

export interface RoomFocusProjection {
  goal: {
    title: string;
    description: string;
    rootId: string;
    state: RoomFocusState;
    rootResult?: RoomMessageProjection;
  };
  workItems: RoomFocusWorkItem[];
  partners: RoomFocusPartner[];
  handoffs: RoomFocusHandoff[];
  rootEvidence: RoomFocusEvidence[];
  counts: {
    active: number;
    review: number;
    blocked: number;
    completed: number;
  };
}

const celestialNames = ['Earth', 'Mars', 'Venus', 'Jupiter', 'Saturn', 'Mercury', 'Neptune', 'Uranus'];

export function roomFocusCelestialName(ordinal: number): string {
  return celestialNames[ordinal] ?? `Planet ${ordinal + 1}`;
}

export function buildRoomFocusProjection(
  room: RoomSummary,
  projection?: RoomProjectionState,
): RoomFocusProjection {
  const activities = orderedActivities(projection);
  const messages = orderedMessages(projection);
  const explicit = orderedWorkItems(room.workItems ?? []).map((item) => explicitFocusWork(item, activities));
  const rootByTurn = new Map<string, RoomFocusWorkItem>();
  for (const item of room.workItems ?? []) {
    if (item.parentWorkId) continue;
    const focus = explicit.find((candidate) => candidate.id === item.id);
    if (focus && item.rootTurnId) rootByTurn.set(item.rootTurnId, focus);
  }
  const defaultRoot = explicit.find((item) => !item.parentId);
  const runtime = runtimeFocusWork(activities, rootByTurn, defaultRoot);
  const workItems = [...explicit, ...runtime];
  const partners = room.participants
    .slice()
    .sort((left, right) => left.ordinal - right.ordinal || left.id.localeCompare(right.id))
    .map((participant) => {
      const owned = workItems.filter((item) => [
        item.ownerParticipantId,
        item.offeredToParticipantId,
        item.accountableParticipantId,
      ].includes(participant.id));
      const latestActivity = [...activities].reverse().find((activity) => activity.participantId === participant.id);
      const latestMessage = [...messages].reverse().find((message) => message.participantId === participant.id && message.role === 'assistant');
      const state = participant.status === 'active'
        ? strongestState([
            ...owned.map((item) => item.state),
            ...(latestActivity ? [activityState(latestActivity.status)] : []),
          ])
        : 'disconnected';
      return {
        participantId: participant.id,
        sessionId: participant.sessionId,
        displayName: participant.displayName,
        celestialName: roomFocusCelestialName(participant.ordinal),
        collaborationRole: participant.collaborationRole,
        state,
        ownedWorkItemIds: owned.map((item) => item.id),
        currentAction: latestActivity?.summary.trim()
          || owned.find((item) => ['running', 'review', 'blocked', 'waiting'].includes(item.state))?.objective
          || owned.at(0)?.objective
          || '等待新的任务',
        latestReceipt: latestMessage?.text.trim()
          || owned.find((item) => item.latestResult)?.latestResult
          || (latestActivity?.status === 'completed' ? latestActivity.summary.trim() : undefined),
        unread: false,
      } satisfies RoomFocusPartner;
    });
  const handoffs = focusHandoffs(room, activities);
  const rootResult = [...messages].reverse().find((message) => (
    message.role === 'assistant'
    && message.status === 'completed'
    && ['result', 'work_result', 'review_result', 'handoff'].includes(message.postKind ?? 'result')
  ));
  const activeTopic = room.topics?.find((topic) => topic.id === room.activeTopicId)
    ?? room.topics?.find((topic) => topic.status === 'active');
  const rootWork = (room.workItems ?? []).find((item) => !item.parentWorkId)
    ?? room.workItems?.at(0);
  const rootId = rootWork?.rootTurnId
    || projection?.turnOrder.at(-1)
    || room.id;
  const turnState = projection?.turnOrder
    .map((turnId) => projection.turnsById[turnId])
    .filter(Boolean)
    .map((turn) => turnStateValue(turn.status)) ?? [];
  const goalState = strongestState([
    ...workItems.map((item) => item.state),
    ...turnState,
  ]);
  const rootEvidence = uniqueEvidence((room.workItems ?? []).flatMap((item) => [
    ...item.artifactRefs.map((ref) => ({ ref, kind: 'artifact' as const })),
    ...item.evidenceRefs.map((ref) => ({ ref, kind: 'evidence' as const })),
  ]));

  return {
    goal: {
      title: activeTopic?.title.trim() || rootWork?.objective.trim() || room.title,
      description: activeTopic?.summary.trim() || room.description?.trim() || rootWork?.expectedOutput.trim() || '',
      rootId,
      state: goalState,
      ...(rootResult ? { rootResult } : {}),
    },
    workItems,
    partners,
    handoffs,
    rootEvidence,
    counts: {
      active: workItems.filter((item) => item.state === 'running' || item.state === 'waiting').length,
      review: workItems.filter((item) => item.state === 'review').length,
      blocked: workItems.filter((item) => item.state === 'blocked' || item.state === 'failed').length,
      completed: workItems.filter((item) => item.state === 'completed').length,
    },
  };
}

export function roomFocusStateLabel(state: RoomFocusState): string {
  return ({
    idle: '待命',
    waiting: '等待',
    running: '进行中',
    review: '等待复核',
    blocked: '阻塞',
    completed: '已完成',
    failed: '需要关注',
    stopped: '已停止',
    disconnected: '已离线',
  } satisfies Record<RoomFocusState, string>)[state];
}

/** 跟随状态兜底给一句用户可读的话，而不是机器事件名。焦点面板与卫星
 *  页脚共用同一套兜底文案，跨窗口读到的口径保持一致。 */
export function roomFocusStateFallbackCopy(state: RoomFocusState): string {
  if (state === 'running') return '正在推进当前工作';
  if (state === 'completed') return '活动已完成';
  if (state === 'failed' || state === 'blocked') return '最近一项活动需要关注';
  if (state === 'waiting' || state === 'review') return '等待下一步安排';
  return '等待新的任务';
}

/** 「原始记录」判定：JSON、绝对路径、长哈希、技术墙。这类正文不适合直接
 *  作为摘要给人读，只能折进披露；判定被焦点面板与全部卫星窗共用。 */
export function roomFocusRawDetail(source: string): boolean {
  return /```|(?:^|\s)[{[]\s*["']/u.test(source)
    || /\/(?:Users|Volumes|home|private|tmp|var)\//u.test(source)
    || /\b[a-f\d]{48,}\b/iu.test(source)
    || /["'](?:path|sha256|payload|metadata)["']\s*:/iu.test(source)
    || roomFocusTechnicalWall(source);
}

/** 不含任何中日韩文字、又带着代码痕迹（RLE/AABB 这类缩写、camelCase、
 * snake_case、`::`、`=>`…）的英文开发日志，对用户就是一堵技术墙：摘要位
 * 改说人话，整段留在原文披露里，一次点击仍可完整读到。 */
function roomFocusTechnicalWall(source: string): boolean {
  if (source.length < 30 || /[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]/u.test(source)) return false;
  return source.length > 90
    || /\b[A-Z]{2,8}\b|[a-z][A-Z]|\w+_\w+|::|=>|->|\(\)/u.test(source);
}

/** 形如 participant_activity 的事件枚举是机器串，不能作为给人看的摘要。 */
function roomFocusMachineToken(source: string): boolean {
  return /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/iu.test(source);
}

/** 把一段真实正文压成一行可读摘要：剥掉 Markdown 痕迹、折叠空白、150 字
 *  截断；原始记录与机器串直接换成 fallback。摘要只改显示投影，完整正文
 *  始终留在各自的披露里。 */
export function roomFocusReadableText(detail: string, fallback: string): string {
  const source = detail.trim();
  if (!source || roomFocusRawDetail(source) || roomFocusMachineToken(source)) return fallback;
  const compact = source
    .replace(/```[\s\S]*?```/gu, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/gu, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gmu, '')
    .replace(/[*_`]/gu, '')
    .replace(/(?:^|\s)[>~-]+/gu, ' ')
    .replace(/\s+/gu, ' ')
    .trim();
  if (!compact) return fallback;
  return compact.length > 150 ? `${compact.slice(0, 147).trimEnd()}…` : compact;
}

function explicitFocusWork(item: RoomWorkItem, activities: RoomActivityProjection[]): RoomFocusWorkItem {
  const ownerId = item.currentOwnerParticipantId || item.offeredToParticipantId || item.accountableParticipantId || undefined;
  const latestActivity = [...activities].reverse().find((activity) => (
    activity.turnId === item.rootTurnId
    && (!ownerId || activity.participantId === ownerId)
  ));
  const blocker = focusBlocker(item.blocker);
  return {
    id: item.id,
    ...(item.parentWorkId ? { parentId: item.parentWorkId } : {}),
    source: 'work-item',
    objective: item.objective,
    expectedOutput: item.expectedOutput || undefined,
    acceptanceCriteria: item.acceptanceCriteria,
    ownerParticipantId: ownerId,
    offeredToParticipantId: item.offeredToParticipantId || undefined,
    accountableParticipantId: item.accountableParticipantId || undefined,
    state: workState(item.state),
    currentAction: latestActivity?.summary.trim() || undefined,
    blocker,
    reviewRequired: item.state === 'review',
    latestResult: item.resultSummary.trim() || undefined,
    evidence: uniqueEvidence([
      ...item.artifactRefs.map((ref) => ({ ref, kind: 'artifact' as const })),
      ...item.evidenceRefs.map((ref) => ({ ref, kind: 'evidence' as const })),
    ]),
    updatedAtMs: item.updatedAtMs,
  };
}

function runtimeFocusWork(
  activities: RoomActivityProjection[],
  rootByTurn: Map<string, RoomFocusWorkItem>,
  defaultRoot?: RoomFocusWorkItem,
): RoomFocusWorkItem[] {
  const byDispatch = new Map<string, RoomFocusWorkItem>();
  for (const activity of activities) {
    const task = stringValue(activity.payload.task);
    const dispatchId = stringValue(activity.payload.dispatchId || activity.payload.childDispatchId);
    if (!task || !dispatchId) continue;
    const previous = byDispatch.get(dispatchId);
    const parent = rootByTurn.get(activity.turnId) ?? defaultRoot;
    const owner = activity.participantId
      || stringValue(activity.payload.targetParticipantId)
      || undefined;
    byDispatch.set(dispatchId, {
      id: `runtime:${dispatchId}`,
      ...(parent ? { parentId: parent.id } : {}),
      source: 'runtime',
      objective: task,
      expectedOutput: stringValue(activity.payload.expectedOutput) || previous?.expectedOutput,
      acceptanceCriteria: stringArray(activity.payload.acceptanceCriteria).length
        ? stringArray(activity.payload.acceptanceCriteria)
        : previous?.acceptanceCriteria ?? [],
      ownerParticipantId: owner ?? previous?.ownerParticipantId,
      state: activityState(activity.status),
      currentAction: activity.summary.trim() || previous?.currentAction,
      reviewRequired: stringValue(activity.payload.requestKind) === 'plan_review' || activity.status === 'waiting',
      latestResult: activity.status === 'completed' ? activity.summary.trim() : previous?.latestResult,
      evidence: previous?.evidence ?? [],
      dispatchId,
      updatedAtMs: activity.updatedAtMs ?? activity.createdAtMs,
    });
  }
  return [...byDispatch.values()].sort((left, right) => left.updatedAtMs - right.updatedAtMs || left.id.localeCompare(right.id));
}

function focusHandoffs(room: RoomSummary, activities: RoomActivityProjection[]): RoomFocusHandoff[] {
  const rows: RoomFocusHandoff[] = [];
  for (const item of room.workItems ?? []) {
    if (!item.offeredToParticipantId || item.offeredToParticipantId === item.currentOwnerParticipantId) continue;
    const source = item.currentOwnerParticipantId || item.accountableParticipantId || room.moderatorParticipantId;
    if (!source || source === item.offeredToParticipantId) continue;
    rows.push({
      id: `work:${item.id}:${item.revision}`,
      sourceParticipantId: source,
      targetParticipantId: item.offeredToParticipantId,
      workItemId: item.id,
      artifactOrContract: item.expectedOutput || undefined,
      task: item.objective,
      state: 'offered',
      createdAtMs: item.updatedAtMs,
    });
  }
  for (const activity of activities) {
    const target = stringValue(activity.payload.targetParticipantId);
    if (!target) continue;
    const source = stringValue(activity.payload.sourceParticipantId || activity.payload.parentParticipantId)
      || room.moderatorParticipantId;
    if (!source || source === target) continue;
    const dispatchId = stringValue(activity.payload.dispatchId || activity.payload.childDispatchId);
    rows.push({
      id: `activity:${activity.id}`,
      sourceParticipantId: source,
      targetParticipantId: target,
      dispatchId: dispatchId || undefined,
      artifactOrContract: stringValue(activity.payload.expectedOutput) || undefined,
      task: stringValue(activity.payload.task) || activity.summary.trim() || undefined,
      state: activity.status === 'failed'
        ? 'failed'
        : activity.status === 'aborted'
          ? 'stopped'
          : activity.status === 'completed'
            ? 'completed'
            : 'dispatched',
      createdAtMs: activity.createdAtMs,
    });
  }
  const byIdentity = new Map<string, RoomFocusHandoff>();
  for (const row of rows) byIdentity.set(`${row.sourceParticipantId}:${row.targetParticipantId}:${row.workItemId ?? row.dispatchId ?? row.id}`, row);
  return [...byIdentity.values()].sort((left, right) => left.createdAtMs - right.createdAtMs || left.id.localeCompare(right.id));
}

function orderedWorkItems(items: RoomWorkItem[]): RoomWorkItem[] {
  const byParent = new Map<string, RoomWorkItem[]>();
  for (const item of items) {
    const parent = item.parentWorkId || '';
    const group = byParent.get(parent) ?? [];
    group.push(item);
    byParent.set(parent, group);
  }
  for (const group of byParent.values()) group.sort((left, right) => left.createdAtMs - right.createdAtMs || left.id.localeCompare(right.id));
  const result: RoomWorkItem[] = [];
  const visit = (item: RoomWorkItem) => {
    if (result.some((candidate) => candidate.id === item.id)) return;
    result.push(item);
    for (const child of byParent.get(item.id) ?? []) visit(child);
  };
  for (const root of byParent.get('') ?? []) visit(root);
  for (const item of items) visit(item);
  return result;
}

function orderedActivities(projection?: RoomProjectionState): RoomActivityProjection[] {
  if (!projection) return [];
  return projection.activityOrder
    .map((id) => projection.activitiesById[id])
    .filter((item): item is RoomActivityProjection => Boolean(item))
    .sort((left, right) => (left.sequence ?? left.createdAtMs) - (right.sequence ?? right.createdAtMs) || left.id.localeCompare(right.id));
}

function orderedMessages(projection?: RoomProjectionState): RoomMessageProjection[] {
  if (!projection) return [];
  return projection.messageOrder
    .map((id) => projection.messagesById[id])
    .filter((item): item is RoomMessageProjection => Boolean(item))
    .sort((left, right) => (left.sequence ?? left.createdAtMs) - (right.sequence ?? right.createdAtMs) || left.id.localeCompare(right.id));
}

function workState(state: RoomWorkState): RoomFocusState {
  return ({
    queued: 'waiting',
    active: 'running',
    review: 'review',
    blocked: 'blocked',
    done: 'completed',
    failed: 'failed',
    cancelled: 'stopped',
  } satisfies Record<RoomWorkState, RoomFocusState>)[state];
}

function activityState(status: RoomActivityProjection['status']): RoomFocusState {
  return ({
    running: 'running',
    waiting: 'review',
    completed: 'completed',
    failed: 'failed',
    aborted: 'stopped',
  } satisfies Record<RoomActivityProjection['status'], RoomFocusState>)[status];
}

function turnStateValue(status: 'queued' | 'running' | 'completed' | 'failed' | 'aborted'): RoomFocusState {
  return ({ queued: 'waiting', running: 'running', completed: 'completed', failed: 'failed', aborted: 'stopped' })[status] as RoomFocusState;
}

function strongestState(states: RoomFocusState[]): RoomFocusState {
  const priority: RoomFocusState[] = ['blocked', 'failed', 'review', 'running', 'waiting', 'disconnected', 'completed', 'stopped', 'idle'];
  return priority.find((state) => states.includes(state)) ?? 'idle';
}

function focusBlocker(value: Record<string, unknown>): RoomFocusBlocker | undefined {
  const reason = stringValue(value.reason);
  if (!reason) return undefined;
  const nextStep = stringValue(value.nextStep);
  return { reason, ...(nextStep ? { nextStep } : {}) };
}

function uniqueEvidence(items: RoomFocusEvidence[]): RoomFocusEvidence[] {
  const byRef = new Map<string, RoomFocusEvidence>();
  for (const item of items) if (item.ref.trim()) byRef.set(item.ref, item);
  return [...byRef.values()];
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())) : [];
}
