import type { RoomDispatchEnvelopeV2 } from '@/contracts/generated/room-dispatch-envelope.v2';
import type { RoomPostV2 } from '@/contracts/generated/room-post.v2';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import type {
  RoomKernelProjection,
  RootProjection,
} from '@/contracts/room-kernel-reducer';

export type RoomScreenBusyState = 'running' | 'blocked';

export interface RoomScreenWait {
  kind: string;
  reason: string;
  requiresUserAction: boolean;
}

export interface RoomScreenHeaderModel {
  state: RootProjection['state'] | 'idle';
  label: string;
  busyState?: RoomScreenBusyState;
  needsAttention: boolean;
}

export interface RoomScreenComposerModel {
  taskBusyState?: RoomScreenBusyState;
  acceptsIntervention: boolean;
  disabledReason: string;
}

export interface RoomScreenModel {
  activeRoot?: RootProjection;
  roots: RootProjection[];
  rootFrames: RoomScreenRootFrame[];
  phase: string;
  wait?: RoomScreenWait;
  tasks: RoomTaskV3[];
  dispatchAttempts: RoomDispatchEnvelopeV2[];
  finalDelivery?: RoomPostV2;
  header: RoomScreenHeaderModel;
  composer: RoomScreenComposerModel;
}

export interface RoomScreenRootFrame {
  root: RootProjection;
  tasks: RoomTaskV3[];
  dispatchAttempts: RoomDispatchEnvelopeV2[];
  posts: RoomPostV2[];
  finalDelivery?: RoomPostV2;
}

export function buildRoomScreenModel(
  projection: RoomKernelProjection | null | undefined,
): RoomScreenModel {
  if (!projection) return emptyRoomScreenModel();

  const roots = Object.values(projection.rootsById).sort(compareRoots);
  const activeRoot = selectActiveRoot(projection, roots);
  const rootFrames = roots.map((root) => buildRootFrame(
    projection,
    root,
    root.rootId === activeRoot?.rootId,
  ));
  const activeFrame = rootFrames.find((frame) => frame.root.rootId === activeRoot?.rootId);
  const tasks = activeFrame?.tasks ?? [];
  const dispatchAttempts = activeFrame?.dispatchAttempts ?? [];
  const wait = selectWait(projection, activeRoot);
  const phase = selectPhase(projection, activeRoot);
  const finalDelivery = activeFrame?.finalDelivery;
  const header = selectHeader(activeRoot);

  return {
    activeRoot,
    roots,
    rootFrames,
    phase,
    wait,
    tasks,
    dispatchAttempts,
    finalDelivery,
    header,
    composer: {
      taskBusyState: header.busyState,
      acceptsIntervention: Boolean(activeRoot && !isTerminalRoot(activeRoot)),
      disabledReason: composerDisabledReason(activeRoot),
    },
  };
}

function emptyRoomScreenModel(): RoomScreenModel {
  return {
    roots: [],
    rootFrames: [],
    phase: 'idle',
    tasks: [],
    dispatchAttempts: [],
    header: {
      state: 'idle',
      label: '先把目标聊清楚',
      needsAttention: false,
    },
    composer: {
      acceptsIntervention: false,
      disabledReason: '',
    },
  };
}

function selectActiveRoot(
  projection: RoomKernelProjection,
  roots: RootProjection[],
): RootProjection | undefined {
  if (projection.screenState) {
    return typeof projection.screenState.activeRootId === 'string'
      ? projection.rootsById[projection.screenState.activeRootId]
      : undefined;
  }
  return roots[0];
}

function selectPhase(
  projection: RoomKernelProjection,
  root: RootProjection | undefined,
): string {
  if (projection.screenState) {
    return projection.screenState.phase;
  }
  if (!root) return 'idle';
  return {
    pending: 'planning',
    running: 'execution',
    waiting: 'waiting',
    blocked: 'blocked',
    cancelling: 'cancelling',
    completed: 'completed',
    failed: 'failed',
    cancelled: 'cancelled',
    cancelled_with_unknowns: 'cancelled',
  }[root.state];
}

function selectWait(
  projection: RoomKernelProjection,
  root: RootProjection | undefined,
): RoomScreenWait | undefined {
  const waitReason = projection.screenState?.waitReason;
  if (waitReason) {
    return {
      kind: waitReason.kind,
      reason: waitReason.reason,
      requiresUserAction: waitReason.requiresUserAction,
    };
  }
  if (root?.state === 'waiting') {
    return {
      kind: 'managed',
      reason: '任务正在安全等待，满足继续条件后会自动推进',
      requiresUserAction: false,
    };
  }
  if (root?.state === 'blocked') {
    return {
      kind: 'blocked',
      reason: '任务遇到需要处理的阻塞',
      requiresUserAction: true,
    };
  }
  return undefined;
}

function buildRootFrame(
  projection: RoomKernelProjection,
  root: RootProjection,
  active: boolean,
): RoomScreenRootFrame {
  const tasks = Object.values(projection.tasksById)
    .filter((task) => task.rootId === root.rootId && task.taskKind !== 'report')
    .sort((left, right) => left.taskId.localeCompare(right.taskId));
  const dispatchAttempts = Object.values(projection.dispatchesById)
    .filter((dispatch) => (
      dispatch.rootId === root.rootId
      && dispatch.generation === root.generation
    ))
    .sort(compareDispatchAttempts);
  const posts = projection.postOrder
    .map((postId) => projection.postsById[postId])
    .filter((post): post is RoomPostV2 => Boolean(
      post
      && post.rootId === root.rootId
      && post.generation === root.generation,
    ))
    .sort((left, right) => right.createdAtMs - left.createdAtMs || right.postId.localeCompare(left.postId));
  return {
    root,
    tasks,
    dispatchAttempts,
    posts,
    finalDelivery: selectFinalDelivery(projection, root, posts, active),
  };
}

function selectFinalDelivery(
  projection: RoomKernelProjection,
  root: RootProjection,
  posts: RoomPostV2[],
  active: boolean,
): RoomPostV2 | undefined {
  if (root.state !== 'completed' || !root.reporterParticipantId) return undefined;

  if (active && projection.screenState) {
    const post = typeof projection.screenState.finalDeliveryPostId === 'string'
      ? projection.postsById[projection.screenState.finalDeliveryPostId]
      : undefined;
    return post && isFinalDeliveryPost(post, root) ? post : undefined;
  }

  return posts.find((post) => isFinalDeliveryPost(post, root));
}

function isFinalDeliveryPost(post: RoomPostV2, root: RootProjection): boolean {
  return post.rootId === root.rootId
    && post.generation === root.generation
    && post.kind === 'result'
    && post.authorActorRef === root.reporterParticipantId
    && post.publicationSource.kind === 'room_commit';
}

function selectHeader(root: RootProjection | undefined): RoomScreenHeaderModel {
  if (!root) {
    return {
      state: 'idle',
      label: '先把目标聊清楚',
      needsAttention: false,
    };
  }
  const busyState = isTerminalRoot(root)
    ? undefined
    : root.state === 'blocked'
      ? 'blocked' as const
      : 'running' as const;
  return {
    state: root.state,
    label: rootStateLabel(root.state),
    busyState,
    needsAttention: root.state === 'blocked'
      || root.state === 'failed'
      || root.state === 'cancelled_with_unknowns',
  };
}

function composerDisabledReason(root: RootProjection | undefined): string {
  if (!root || isTerminalRoot(root)) return '';
  if (root.state === 'blocked') return '当前任务已暂停；请先继续或停止这项任务。';
  return '当前任务仍在执行；可以补充修正、调整优先级、暂停或询问状态。';
}

function compareRoots(left: RootProjection, right: RootProjection): number {
  return rootRecency(right) - rootRecency(left)
    || right.generation - left.generation
    || right.rootId.localeCompare(left.rootId);
}

function compareDispatchAttempts(
  left: RoomDispatchEnvelopeV2,
  right: RoomDispatchEnvelopeV2,
): number {
  return left.attempt - right.attempt
    || left.dispatchId.localeCompare(right.dispatchId);
}

function rootRecency(root: RootProjection): number {
  return Math.max(root.updatedAtMs ?? 0, root.createdAtMs ?? 0);
}

function isTerminalRoot(root: RootProjection): boolean {
  return ['completed', 'failed', 'cancelled', 'cancelled_with_unknowns'].includes(root.state);
}

function rootStateLabel(state: RootProjection['state']): string {
  return {
    pending: '等待开始',
    running: '执行中',
    waiting: '等待中',
    blocked: '需要处理阻塞',
    cancelling: '正在停止',
    completed: '已完成',
    failed: '未完成',
    cancelled: '已停止',
    cancelled_with_unknowns: '已停止，后台状态待确认',
  }[state];
}
