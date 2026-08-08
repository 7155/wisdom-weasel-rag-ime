import type { RoomDispatchEnvelopeV2 } from '@/contracts/generated/room-dispatch-envelope.v2';
import type { RoomPostV2 } from '@/contracts/generated/room-post.v2';
import type { RoomScreenStateV1 } from '@/contracts/generated/room-screen-state.v1';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import type {
  RoomKernelProjection,
  RootProjection,
} from '@/contracts/room-kernel-reducer';

export type RoomScreenBusyState = 'running' | 'blocked';
export type RoomScreenCollaborationStage =
  | 'parallel_work'
  | 'independent_review'
  | 'final_delivery';

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
  phase: RoomScreenStateV1['phase'];
  wait?: RoomScreenWait;
  runnableFrontier: RoomScreenStateV1['runnableFrontier'];
  integrationReadiness: RoomScreenStateV1['integrationReadiness'];
  reviewReadiness: RoomScreenStateV1['reviewReadiness'];
  recommendedNextAction: RoomScreenStateV1['recommendedNextAction'];
  collaborationStage: RoomScreenCollaborationStage;
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
  const screenState = authoritativeScreenState(projection);
  const screenStateStale = Boolean(projection.screenState && !screenState);
  const activeRoot = selectActiveRoot(projection, roots, screenState);
  const rootFrames = roots.map((root) => buildRootFrame(
    projection,
    root,
    root.rootId === activeRoot?.rootId,
    screenState,
  ));
  const activeFrame = rootFrames.find((frame) => frame.root.rootId === activeRoot?.rootId);

  if (screenStateStale) {
    return {
      roots,
      rootFrames,
      phase: 'waiting',
      wait: {
        kind: 'managed',
        reason: '正在同步最新任务状态',
        requiresUserAction: false,
      },
      runnableFrontier: emptyFrontier(),
      integrationReadiness: unavailableReadiness(),
      reviewReadiness: unavailableReadiness(),
      recommendedNextAction: 'wait_for_progress',
      collaborationStage: 'parallel_work',
      tasks: [],
      dispatchAttempts: [],
      header: {
        state: 'idle',
        label: '正在同步最新进度',
        busyState: 'running',
        needsAttention: false,
      },
      composer: {
        taskBusyState: 'running',
        acceptsIntervention: false,
        disabledReason: '正在同步最新任务状态，完成后即可继续发送。',
      },
    };
  }
  const tasks = activeFrame?.tasks ?? [];
  const dispatchAttempts = activeFrame?.dispatchAttempts ?? [];
  const wait = selectWait(screenState, activeRoot);
  const phase = selectPhase(screenState, activeRoot);
  const finalDelivery = activeFrame?.finalDelivery;
  const header = selectHeader(activeRoot);
  const authority = selectAuthority(screenState);

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
    ...authority,
    collaborationStage: selectCollaborationStage(
      authority.recommendedNextAction,
      tasks,
      finalDelivery,
    ),
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
    runnableFrontier: emptyFrontier(),
    integrationReadiness: unavailableReadiness(),
    reviewReadiness: unavailableReadiness(),
    recommendedNextAction: 'start_new_task',
    collaborationStage: 'parallel_work',
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

function selectAuthority(
  screenState: RoomScreenStateV1 | undefined,
): Pick<RoomScreenModel,
  | 'runnableFrontier'
  | 'integrationReadiness'
  | 'reviewReadiness'
  | 'recommendedNextAction'
> {
  if (!screenState) {
    return {
      runnableFrontier: emptyFrontier(),
      integrationReadiness: unavailableReadiness(),
      reviewReadiness: unavailableReadiness(),
      recommendedNextAction: 'wait_for_progress',
    };
  }
  return {
    runnableFrontier: {
      taskIds: [...screenState.runnableFrontier.taskIds],
      dispatchIds: [...screenState.runnableFrontier.dispatchIds],
    },
    integrationReadiness: cloneReadiness(screenState.integrationReadiness),
    reviewReadiness: cloneReadiness(screenState.reviewReadiness),
    recommendedNextAction: screenState.recommendedNextAction,
  };
}

function selectCollaborationStage(
  nextAction: RoomScreenStateV1['recommendedNextAction'],
  tasks: RoomTaskV3[],
  finalDelivery: RoomPostV2 | undefined,
): RoomScreenCollaborationStage {
  if (finalDelivery) return 'final_delivery';
  if (
    nextAction === 'complete_independent_review'
    || tasks.some((task) => (
      task.taskKind === 'review'
      && !['completed', 'failed', 'cancelled'].includes(task.state)
    ))
  ) {
    return 'independent_review';
  }
  return 'parallel_work';
}

function emptyFrontier(): RoomScreenStateV1['runnableFrontier'] {
  return { taskIds: [], dispatchIds: [] };
}

function unavailableReadiness(): RoomScreenStateV1['integrationReadiness'] {
  return { ready: false, reason: null, pendingTaskIds: [] };
}

function cloneReadiness(
  readiness: RoomScreenStateV1['integrationReadiness'],
): RoomScreenStateV1['integrationReadiness'] {
  return {
    ready: readiness.ready,
    reason: readiness.reason,
    pendingTaskIds: [...readiness.pendingTaskIds],
  };
}

function authoritativeScreenState(
  projection: RoomKernelProjection,
): RoomScreenStateV1 | undefined {
  const state = projection.screenState;
  if (!state) return undefined;
  if (state.activeRootId === null) {
    return state.activeRootGeneration === null ? state : undefined;
  }
  const root = projection.rootsById[state.activeRootId];
  if (!root || state.activeRootGeneration !== root.generation) return undefined;
  return state;
}

function selectActiveRoot(
  projection: RoomKernelProjection,
  roots: RootProjection[],
  screenState: RoomScreenStateV1 | undefined,
): RootProjection | undefined {
  if (screenState) {
    return typeof screenState.activeRootId === 'string'
      ? projection.rootsById[screenState.activeRootId]
      : undefined;
  }
  if (projection.screenState) return undefined;
  return roots[0];
}

function selectPhase(
  screenState: RoomScreenStateV1 | undefined,
  root: RootProjection | undefined,
): RoomScreenStateV1['phase'] {
  if (screenState) return screenState.phase;
  if (!root) return 'idle';
  const phaseByRootState: Record<
    RootProjection['state'],
    RoomScreenStateV1['phase']
  > = {
    pending: 'planning',
    running: 'execution',
    waiting: 'waiting',
    blocked: 'blocked',
    cancelling: 'cancelling',
    completed: 'completed',
    failed: 'failed',
    cancelled: 'cancelled',
    cancelled_with_unknowns: 'cancelled',
  };
  return phaseByRootState[root.state];
}

function selectWait(
  screenState: RoomScreenStateV1 | undefined,
  root: RootProjection | undefined,
): RoomScreenWait | undefined {
  const waitReason = screenState?.waitReason;
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
  screenState: RoomScreenStateV1 | undefined,
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
    finalDelivery: selectFinalDelivery(projection, root, posts, active, screenState),
  };
}

function selectFinalDelivery(
  projection: RoomKernelProjection,
  root: RootProjection,
  posts: RoomPostV2[],
  active: boolean,
  screenState: RoomScreenStateV1 | undefined,
): RoomPostV2 | undefined {
  if (root.state !== 'completed' || !root.reporterParticipantId) return undefined;

  if (active && screenState) {
    const post = typeof screenState.finalDeliveryPostId === 'string'
      ? projection.postsById[screenState.finalDeliveryPostId]
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
