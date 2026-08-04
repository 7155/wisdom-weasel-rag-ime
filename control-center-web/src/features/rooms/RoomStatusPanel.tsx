import {
  ListChecks,
  LoaderCircle,
  PanelRightClose,
  Radar,
  TriangleAlert,
} from 'lucide-react';
import { forwardRef } from 'react';
import { Button, IconButton } from '@/components/primitives';
import type {
  RoomActivityProjection,
  RoomMessageProjection,
  RoomProjectionState,
  RoomTurnProjection,
} from '@/contracts/room-reducer';
import type { RoomKernelProjection, RootProjection } from '@/contracts/room-kernel-reducer';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import type { RoomSummary } from './room-types';
import { roomActivityNeedsSessionAction } from './runtime/room-execution-lanes';
import { roomProjection, useRoomLiveStore, type RoomKernelSyncProjection } from './state/live-store';
import '../agent/agent.css';

export const RoomStatusPanel = forwardRef<HTMLElement, {
  room?: RoomSummary;
  roomId?: string;
  projection?: RoomProjectionState;
  open: boolean;
  modal?: boolean;
  onClose: () => void;
  onOpenProgress?: () => void;
}>(function RoomStatusPanel({
  room,
  roomId = '',
  projection: providedProjection,
  open,
  modal = false,
  onClose,
  onOpenProgress,
}, ref) {
  const effectiveRoomId = roomId || room?.id || '';
  useRoomLiveStore((state) => (
    open && !providedProjection
      ? state.roomRevisions[effectiveRoomId] ?? 0
      : 0
  ));
  const kernelProjection = useRoomLiveStore(
    (state) => open ? state.kernelProjections[effectiveRoomId] ?? null : null,
  );
  const kernelSync = useRoomLiveStore(
    (state) => open ? state.kernelSyncByRoomId[effectiveRoomId] : undefined,
  );
  const projection = providedProjection ?? roomProjection(effectiveRoomId);
  const currentRoot = kernelProjection
    ? Object.values(kernelProjection.rootsById).sort((left, right) => (
      Math.max(right.updatedAtMs ?? 0, right.createdAtMs ?? 0)
        - Math.max(left.updatedAtMs ?? 0, left.createdAtMs ?? 0)
      || left.rootId.localeCompare(right.rootId)
    ))[0]
    : undefined;
  const currentRootTasks = currentRoot && kernelProjection
    ? Object.values(kernelProjection.tasksById).filter((task) => (
      task.rootId === currentRoot.rootId && task.taskKind !== 'report'
    ))
    : [];
  const currentRootDispatches = currentRoot && kernelProjection
    ? Object.values(kernelProjection.dispatchesById).filter((dispatch) => (
      dispatch.rootId === currentRoot.rootId
      && kernelProjection.tasksById[dispatch.taskId]?.taskKind !== 'report'
    ))
    : [];
  const latestFinalPost = currentRoot && roomRootIsTerminal(currentRoot) && kernelProjection
    ? kernelProjection.postOrder
      .map((postId) => kernelProjection.postsById[postId])
      .filter((post) => post?.rootId === currentRoot.rootId)
      .sort((left, right) => right!.createdAtMs - left!.createdAtMs)[0]
    : undefined;
  const individualTasks = currentRootTasks.filter((task) => task.taskKind !== 'review');
  const reviewTasks = currentRootTasks.filter((task) => task.taskKind === 'review');
  const sharedCheckVisible = reviewTasks.length > 0 || (
    individualTasks.length > 0
    && individualTasks.every((task) => ['completed', 'failed', 'cancelled'].includes(task.state))
  ) || Boolean(latestFinalPost);
  const turn = latestRoomTurn(projection);
  const activities = turn?.activityIds.map((id) => projection.activitiesById[id]).filter(Boolean) ?? [];
  const messages = turn?.messageIds.map((id) => projection.messagesById[id]).filter(Boolean) ?? [];
  const projectedStatus = roomProjectedStatus(turn, activities, messages);
  return (
    <aside
      ref={ref}
      aria-hidden={!open}
      aria-label="协作进展"
      aria-modal={modal || undefined}
      className="agent-status-panel room-status-panel"
      data-open={open}
      inert={open ? undefined : true}
      role={modal ? 'dialog' : undefined}
      tabIndex={-1}
    >
      <header>
        <span><strong>协作进展</strong><small>{currentRoot ? ROOM_STATUS_ROOT_STATE_LABELS[currentRoot.state] : turn ? roomProjectedStatusLabel(projectedStatus) : '等你开始新一轮'}</small></span>
        <IconButton icon={<PanelRightClose size={17} />} label="收起进展面板" onClick={onClose} tooltip />
      </header>
      <div className="agent-status-panel__body">
        {kernelSync && kernelSync.state !== 'idle' ? (
          <RoomProgressFreshness
            sync={kernelSync}
            onOpenProgress={turn ? undefined : onOpenProgress}
          />
        ) : null}
        {currentRoot ? (
          <RoomPhaseContinuity
            dispatches={currentRootDispatches}
            finalReplyVisible={Boolean(latestFinalPost)}
            root={currentRoot}
            sharedCheckVisible={sharedCheckVisible}
            tasks={currentRootTasks}
          />
        ) : (
          <RoomPhaseFallback
            hasRoom={Boolean(room)}
            status={projectedStatus}
            sync={kernelSync}
            turn={turn}
          />
        )}
        {turn && room?.roomKind !== 'roleplay' && onOpenProgress ? <section className="room-status-task-wayfinder">
          <ListChecks aria-hidden="true" size={16} />
          <span>
            <strong>完整任务过程在任务页</strong>
            <small>查看每位伙伴的分工、Todo、工具、文件改动、成果与临时协作者。</small>
          </span>
          <Button onClick={onOpenProgress} size="small" variant="quiet">打开任务页</Button>
        </section> : null}
      </div>
    </aside>
  );
});

const roomStatusTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
});

const ROOM_PROGRESS_SYNC_LABELS: Record<RoomKernelSyncProjection['state'], string> = {
  idle: '等待任务进度',
  loading: '正在读取任务进度',
  synced: '实时进度已连接',
  reconnecting: '正在重新连接进度',
  recovering: '正在恢复最新进度',
  stale: '实时更新暂时中断',
  denied: '当前不可查看任务进度',
  error: '任务进度暂时无法读取',
};

function RoomProgressFreshness({
  sync,
  onOpenProgress,
}: {
  sync: RoomKernelSyncProjection;
  onOpenProgress?: () => void;
}) {
  const failed = sync.state === 'denied' || sync.state === 'error';
  const canOpenProgress = Boolean(onOpenProgress) && (
    failed || sync.state === 'stale' || sync.state === 'recovering'
  );
  const reconnecting = ['loading', 'reconnecting', 'recovering'].includes(sync.state);
  const StatusIcon = failed ? TriangleAlert : reconnecting ? LoaderCircle : Radar;
  return (
    <section
      aria-label="任务进度连接"
      className="room-status-freshness"
      data-state={sync.state}
      role={failed ? 'alert' : 'status'}
    >
      <StatusIcon aria-hidden="true" className={reconnecting ? 'ui-spin' : undefined} size={15} />
      <span>
        <strong>{ROOM_PROGRESS_SYNC_LABELS[sync.state]}</strong>
        <small>{sync.detail || '新进展会自动显示，不需要手动刷新。'}</small>
      </span>
      {sync.updatedAtMs > 0 ? (
        <time dateTime={new Date(sync.updatedAtMs).toISOString()}>
          更新于 {roomStatusTimeFormatter.format(new Date(sync.updatedAtMs))}
        </time>
      ) : null}
      {canOpenProgress ? (
        <Button onClick={onOpenProgress} size="small" variant="quiet">
          打开任务进度
        </Button>
      ) : null}
    </section>
  );
}

function roomRootIsTerminal(root: RootProjection): boolean {
  return ['completed', 'failed', 'cancelled', 'cancelled_with_unknowns'].includes(root.state);
}

const ROOM_STATUS_ROOT_STATE_LABELS: Record<RootProjection['state'], string> = {
  pending: '等待开始',
  running: '工作进行中',
  waiting: '等待下一步',
  blocked: '需要处理阻塞',
  cancelling: '正在停止',
  completed: '已完成',
  failed: '未完成',
  cancelled: '已停止',
  cancelled_with_unknowns: '已停止，后台状态待确认',
};

function RoomPhaseContinuity({
  dispatches,
  finalReplyVisible,
  root,
  sharedCheckVisible,
  tasks,
}: {
  dispatches: RoomKernelProjection['dispatchesById'][string][];
  finalReplyVisible: boolean;
  root: RootProjection;
  sharedCheckVisible: boolean;
  tasks: RoomTaskV3[];
}) {
  const individualTasks = tasks.filter((task) => task.taskKind !== 'review');
  const reviewTasks = tasks.filter((task) => task.taskKind === 'review');
  const completedTasks = individualTasks.filter((task) => task.state === 'completed').length;
  const completedReviews = reviewTasks.filter((task) => task.state === 'completed').length;
  const completedAllTasks = tasks.filter((task) => task.state === 'completed').length;
  const settledDispatches = dispatches.filter((dispatch) => (
    ['committed', 'dead_letter', 'failed', 'cancelled'].includes(dispatch.state)
  )).length;
  const activeDispatches = Math.max(0, dispatches.length - settledDispatches);
  return <section
    aria-label="当前协作阶段"
    className="room-status-phase"
    data-phase={finalReplyVisible ? 'final-reply' : sharedCheckVisible ? 'shared-check' : 'parallel-work'}
  >
    <header>
      <span><small>当前阶段</small><strong>{finalReplyVisible
        ? '最终回复已送达'
        : sharedCheckVisible
          ? '一起检查'
          : '各自工作'}</strong></span>
      <i>{finalReplyVisible ? '已结束' : ROOM_STATUS_ROOT_STATE_LABELS[root.state]}</i>
    </header>
    <dl className="room-status-phase__summary" aria-label="整体任务与分工进度">
      <div><dt>整体任务</dt><dd>{ROOM_STATUS_ROOT_STATE_LABELS[root.state]}</dd></div>
      <div><dt>分工完成</dt><dd>{tasks.length ? `${completedAllTasks} / ${tasks.length}` : '等待安排'}</dd></div>
      <div><dt>伙伴执行</dt><dd>{dispatches.length
        ? activeDispatches
          ? `${activeDispatches} 项进行中`
          : `${settledDispatches} 项已结束`
        : '等待开始'}</dd></div>
    </dl>
    <ol>
      <li data-state={sharedCheckVisible ? 'complete' : 'current'}>
        <span>1</span><strong>各自工作</strong><small>{individualTasks.length
          ? `${completedTasks} / ${individualTasks.length} 项完成`
          : '等待具体分工'}</small>
      </li>
      {sharedCheckVisible ? <li data-state={finalReplyVisible ? 'complete' : 'current'}>
        <span>2</span><strong>一起检查</strong><small>{finalReplyVisible
          ? '检查已结束'
          : reviewTasks.length
            ? `${completedReviews} / ${reviewTasks.length} 位伙伴完成检查`
            : '等待伙伴开始检查'}</small>
      </li> : null}
      {finalReplyVisible ? <li data-state="complete">
        <span>3</span><strong>最终回复</strong><small>公开结果已送达</small>
      </li> : null}
    </ol>
  </section>;
}

function RoomPhaseFallback({
  hasRoom,
  status,
  sync,
  turn,
}: {
  hasRoom: boolean;
  status: RoomProjectedStatus;
  sync?: RoomKernelSyncProjection;
  turn?: RoomTurnProjection;
}) {
  const reading = !turn && ['loading', 'reconnecting', 'recovering'].includes(sync?.state ?? 'idle');
  const label = !hasRoom
    ? '等待选择协作空间'
    : reading
      ? '正在恢复任务进度'
      : turn
        ? roomProjectedStatusLabel(status)
        : '等待开始';
  const detail = !hasRoom
    ? '从左侧选择一个协作空间，或开始新的协作。'
    : reading
      ? '已保留公开对话，正在核对最新任务状态。'
      : roomProjectedStatusDetail(status, Boolean(turn));
  return <section
    aria-label="当前协作阶段"
    className="room-status-phase room-status-phase--fallback"
    data-phase={reading ? 'recovering' : status}
  >
    <header>
      <span><small>当前阶段</small><strong>{label}</strong></span>
      <i>{reading ? '同步中' : turn ? '公开进度' : '未开始'}</i>
    </header>
    <p>{detail}</p>
  </section>;
}

function roomProjectedStatusDetail(status: RoomProjectedStatus, hasTurn: boolean): string {
  if (!hasTurn) return '在对话里说出你想完成的事，伙伴会从这里开始。';
  return {
    queued: '伙伴已经接手，正在准备这轮协作。',
    running: '公开进展仍在更新；完整分工与文件成果可在任务页查看。',
    waiting_review: '需要你检查一项内容后，伙伴才能继续。',
    waiting_select: '伙伴正在等你确认一个选项。',
    waiting_input: '伙伴正在等你补充必要信息。',
    blocked: '这轮遇到阻塞；打开任务页查看原因与恢复动作。',
    completed: '这轮已经完成，最终结果保留在对话中。',
    handed_off: '当前结果已经交给下一位伙伴继续。',
    waiting: '当前工作已安全暂停，满足继续条件后可以恢复。',
    aborted: '这轮已经停止，已有公开进展仍然保留。',
    idle: '在对话里说出你想完成的事，伙伴会从这里开始。',
  }[status];
}

function latestRoomTurn(projection: RoomProjectionState): RoomTurnProjection | undefined {
  return [...projection.turnOrder].reverse().map((id) => projection.turnsById[id]).find(Boolean);
}

type RoomProjectedStatus =
  | 'queued'
  | 'running'
  | 'waiting_review'
  | 'waiting_select'
  | 'waiting_input'
  | 'blocked'
  | 'completed'
  | 'handed_off'
  | 'waiting'
  | 'aborted'
  | 'idle';

function roomActivityStatus(
  activity: RoomActivityProjection,
): RoomActivityProjection['status'] {
  if (['completed', 'failed', 'aborted'].includes(activity.status)) {
    return activity.status;
  }
  const automatic = activity.payload.automatic === true
    || text(activity.payload.decisionMode) === 'model'
    || text(activity.payload.mode) === 'model';
  const decision = text(activity.payload.decision)
    || text((activity.payload.approvalModelDecision as Record<string, unknown> | undefined)?.decision);
  const state = text(activity.payload.resolutionState || activity.payload.state);
  if (
    automatic
    && !decision
    && !['approved', 'rejected', 'applied', 'resolved', 'cancelled'].includes(state)
  ) return 'running';
  return activity.status;
}

function roomProjectedStatus(
  turn: RoomTurnProjection | undefined,
  activities: RoomActivityProjection[],
  messages: RoomMessageProjection[],
): RoomProjectedStatus {
  if (!turn) return 'idle';
  const pending = [...activities].reverse().find(roomActivityNeedsSessionAction);
  if (pending) {
    const requestKind = text(pending.payload.requestKind);
    if (
      requestKind === 'plan_review'
      || requestKind === 'memory_review'
      || Boolean(text(pending.payload.approvalId))
    ) return 'waiting_review';
    if (text(pending.payload.method) === 'select' || Array.isArray(pending.payload.options)) {
      return 'waiting_select';
    }
    return 'waiting_input';
  }
  if (turn.status === 'failed') return 'blocked';
  if (turn.status === 'aborted') return 'aborted';
  if (turn.status === 'queued') return 'queued';
  if (turn.status === 'running') return 'running';
  const outcome = messages.reduce((kind, message) => (
    ['result', 'handoff', 'wait', 'blocked'].includes(message.postKind ?? '')
      ? message.postKind ?? kind
      : kind
  ), '');
  if (outcome === 'result') return 'completed';
  if (outcome === 'handoff') return 'handed_off';
  if (outcome === 'wait') return 'waiting';
  if (outcome === 'blocked') return 'blocked';
  return 'completed';
}

function roomProjectedStatusLabel(status: RoomProjectedStatus): string {
  return {
    queued: '等待协作',
    running: '协作中',
    waiting_review: '等待审阅',
    waiting_select: '等待选择',
    waiting_input: '等待回答',
    blocked: '已阻塞',
    completed: '已完成',
    handed_off: '已转交',
    waiting: '等待继续',
    aborted: '已停止',
    idle: '等待后续',
  }[status];
}

function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
