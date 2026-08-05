import {
  ArrowRight,
  Bot,
  CircleAlert,
  CircleCheck,
  CircleStop,
  ChevronRight,
  Clock3,
  GitBranch,
  ListChecks,
  ShieldCheck,
} from 'lucide-react';
import { useId, type CSSProperties, type ReactNode } from 'react';

import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import type { RoomDispatchEnvelopeV2 } from '@/contracts/generated/room-dispatch-envelope.v2';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import type { RoomPostV2 } from '@/contracts/generated/room-post.v2';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import type {
  PrivateSessionProjection,
  RootProjection,
} from '@/contracts/room-kernel-reducer';
import type {
  RoomActivityProjection,
  RoomParticipantPublicProgressProjection,
} from '@/contracts/room-reducer';
import {
  PublicToolError,
  PublicToolFields,
  PublicToolOutput,
  PublicToolRequest,
  SemanticToolPreview,
  ToolRunningPreview,
} from '@/features/agent/timeline/ActivitySummary';
import { publicToolResultView } from '@/features/agent/timeline/public-tool-result';
import {
  hasToolArtifacts,
  ToolArtifactOutput,
} from '@/features/agent/timeline/ToolArtifactOutput';
import { canonicalToolId } from '@/features/agent/tool-presentation';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { roomParticipantPublicProgressSummary } from '../room-copy';
import type { RoomWorkItem } from '../room-types';
import {
  roomPublicActivityText,
  roomPublicToolResultView,
} from '../timeline/room-tool-presentation';
import { RoomTaskUpdatedAt } from './RoomTaskUpdatedAt';
import {
  roomTaskTodoSummary,
  RoomTaskDeliveryDetails,
  RoomTaskTodoDetails,
} from './RoomTaskAuthorityDetails';
import { projectRoomTaskAuthority } from './room-task-authority';

type FlowVisualState = 'waiting' | 'active' | 'complete' | 'attention' | 'cancelled';
type TaskColumn = 2 | 3 | 4;

type TaskGraphNode = {
  task: RoomTaskV3;
  dispatches: RoomDispatchEnvelopeV2[];
  dependencyIds: string[];
  dependencyOwnerParticipantIds: string[];
  parentId?: string;
  downstreamIds: string[];
  downstreamOwnerParticipantIds: string[];
  childIds: string[];
  externalDependencyCount: number;
  progress?: RoomParticipantPublicProgressProjection;
  result?: string;
  column: TaskColumn;
  row: number;
};

type GraphPoint = {
  left: number;
  right: number;
  y: number;
};

type GraphEdge = {
  id: string;
  from: { x: number; y: number };
  to: { x: number; y: number };
  state: FlowVisualState;
};

type TaskVerification = {
  label: string;
  state: 'waiting' | 'checking' | 'verified' | 'attention';
};

type WorkspaceLifecycleState = NonNullable<RoomTaskV3['workspaceLifecycleState']>;

export type RoomTaskWorkspaceLifecycleView = {
  attention: boolean;
  detail: string;
  state: RoomActivityProjection['status'];
  title: string;
};

const FLOW_ROW_HEIGHT = 220;
const MAX_VISIBLE_SUBAGENT_RUNS = 4;
const TASK_COLUMN_BOUNDS: Readonly<Record<TaskColumn, { left: number; right: number }>> = {
  2: { left: 150, right: 385 },
  3: { left: 395, right: 625 },
  4: { left: 635, right: 865 },
};

const subagentTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
});

export type RoomTaskSubagentRun = Pick<
  AgentSubagentRunV1,
  | 'state'
  | 'task'
  | 'templateId'
  | 'ordinal'
  | 'budget'
  | 'usage'
  | 'createdAtMs'
  | 'startedAtMs'
  | 'updatedAtMs'
  | 'completedAtMs'
> & {
  resultSummary: string;
  error: string;
};

/**
 * The canonical Report task is an internal final-delivery stage. It feeds the
 * single result node and final Post, but it is not another peer assignment.
 */
export function roomTaskIsVisibleWork(task: RoomTaskV3): boolean {
  return String(task.taskKind) !== 'report';
}

export function RoomTaskFlowGraph({
  dispatches,
  finalPostCount,
  goal,
  participantLabels,
  participantPersonas = {},
  participantProgress,
  posts,
  root,
  tasks,
  terminalReceipt,
}: {
  dispatches: RoomDispatchEnvelopeV2[];
  finalPostCount: number;
  goal: string;
  participantLabels: Record<string, string>;
  participantPersonas?: Record<string, AgentPersonaV1>;
  participantProgress: RoomParticipantPublicProgressProjection[];
  posts: RoomPostV2[];
  root: RootProjection;
  tasks: RoomTaskV3[];
  subagentsByTaskId?: Record<string, RoomTaskSubagentRun[]>;
  terminalReceipt?: RoomKernelReceiptV1;
}) {
  const visibleTasks = tasks.filter(roomTaskIsVisibleWork);
  const markerId = `room-task-edge-${useId().replace(/:/g, '')}`;
  const nodes = taskGraphNodes(visibleTasks, dispatches, participantProgress, posts);
  const rowCount = Math.max(1, ...nodes.map((node) => node.row));
  const flowRowHeight = FLOW_ROW_HEIGHT;
  const graphHeight = rowCount * flowRowHeight;
  const graphMidpoint = graphHeight / 2;
  const points = new Map(nodes.map((node) => [node.task.taskId, taskGraphPoint(node, flowRowHeight)]));
  const edges = taskGraphEdges(nodes, points, graphMidpoint);
  const counts = {
    completed: visibleTasks.filter((task) => task.state === 'completed').length,
    active: visibleTasks.filter((task) => ['active', 'review'].includes(task.state)).length,
    waiting: visibleTasks.filter((task) => ['pending', 'waiting'].includes(task.state)).length,
    attention: visibleTasks.filter((task) => ['blocked', 'failed', 'cancelled'].includes(task.state)).length,
  };
  const finalState = rootFlowState(root);
  const canvasStyle = {
    '--room-task-flow-height': `${graphHeight}px`,
    '--room-task-flow-row-count': rowCount,
  } as CSSProperties;
  const hasContinuation = nodes.some((node) => node.column === 3);
  const hasReview = nodes.some((node) => node.column === 4);

  return <section
    aria-label="任务依赖图"
    aria-live="polite"
    className="room-task-flow"
    data-root-state={finalState}
  >
    <header className="room-task-flow__header">
      <span>
        <strong>任务依赖图</strong>
        <small>这里只看先后关系和当前状态；详细进展在下方工作卡中展开</small>
      </span>
      <b>{visibleTasks.length
        ? `${visibleTasks.length} 项 · ${counts.completed} 已完成 · ${counts.active} 执行中 · ${counts.waiting} 等待中${counts.attention ? ` · ${counts.attention} 需关注` : ''}`
        : '等待拆分任务'}</b>
    </header>
    <ul aria-label="任务状态图例" className="room-task-flow__state-legend">
      <li data-state="complete">已完成</li>
      <li data-state="active">正在执行</li>
      <li data-state="review">正在复核</li>
      <li data-state="waiting">等待前置</li>
      <li data-state="attention">需要处理</li>
    </ul>
    <div className="room-task-flow__stage-labels" aria-hidden="true">
      <span><GitBranch size={14} />共同目标</span>
      <span><ListChecks size={14} />分工</span>
      {hasContinuation ? <span><ArrowRight size={14} />接续 / 汇总</span> : <span />}
      {hasReview ? <span><ShieldCheck size={14} />复核</span> : <span />}
      <span><CircleCheck size={14} />结果</span>
    </div>
    <div className="room-task-flow__canvas" style={canvasStyle}>
      <svg
        aria-hidden="true"
        className="room-task-flow__edges"
        preserveAspectRatio="none"
        viewBox={`0 0 1000 ${graphHeight}`}
      >
        <defs>
          <marker
            id={markerId}
            markerHeight="7"
            markerWidth="7"
            orient="auto"
            refX="6"
            refY="3.5"
            viewBox="0 0 7 7"
          >
            <path d="M 0 0 L 7 3.5 L 0 7 z" />
          </marker>
        </defs>
        {edges.map((edge) => <g data-state={edge.state} key={edge.id}>
          <path
            d={taskGraphEdgePath(edge)}
            markerEnd={`url(#${markerId})`}
          />
        </g>)}
      </svg>
      <CompactFlowNode
        className="room-task-flow__root-node"
        detail={visibleTasks.length ? `已拆成 ${visibleTasks.length} 项工作` : '等待协调伙伴分工'}
        icon={<GitBranch size={16} />}
        label={goal || '共同目标'}
        stage="goal"
        state={visibleTasks.length ? 'complete' : rootFlowState(root)}
        stateLabel={visibleTasks.length ? '已拆分' : rootStateLabel(root)}
        style={{ gridRow: `1 / span ${rowCount}` }}
        title="共同目标"
      />
      {nodes.map((node) => <TaskNode
        key={node.task.taskId}
        node={node}
        participantLabels={participantLabels}
        participantPersonas={participantPersonas}
        style={{ gridColumn: node.column, gridRow: node.row }}
      />)}
      <CompactFlowNode
        className="room-task-flow__result-node"
        detail={finalPostCount
          ? '最终结果已公开'
          : terminalReceipt
            ? '完成确认已到达'
            : '等待所有前置任务交付'}
        icon={<CircleCheck size={16} />}
        label={rootFinalLabel(root)}
        stage="result"
        state={finalState}
        stateLabel={rootStateLabel(root)}
        style={{ gridRow: `1 / span ${rowCount}` }}
        title="共同结果"
      />
    </div>
    <ol className="room-task-flow__accessible-summary">
      <li>共同目标：{goal || '等待确认'}。</li>
      <li>{visibleTasks.length
        ? `${visibleTasks.length} 项任务中，${counts.completed} 项已完成，${counts.active} 项正在执行，${counts.waiting} 项等待开始或等待前置任务，${counts.attention} 项需要关注。`
        : '尚未拆分任务。'}</li>
      {nodes.map((node) => <li key={`summary:${node.task.taskId}`}>
        {roomPublicActivityText(node.result || node.task.objective) || '协作任务'}；负责人 {participantLabel(node.task.currentOwnerParticipantId, participantLabels)}；
        {taskNodeStateLabel(node)}。
      </li>)}
      <li>{rootFinalLabel(root)}，{rootStateLabel(root)}。</li>
    </ol>
  </section>;
}

export function RoomTaskWorkList({
  activities = [],
  dispatches,
  participantLabels,
  participantPersonas = {},
  participantProgress,
  posts,
  root,
  sessionsById = {},
  subagentsByTaskId = {},
  taskUpdatedAtMsById = {},
  tasks,
  workItems = [],
}: {
  activities?: RoomActivityProjection[];
  dispatches: RoomDispatchEnvelopeV2[];
  participantLabels: Record<string, string>;
  participantPersonas?: Record<string, AgentPersonaV1>;
  participantProgress: RoomParticipantPublicProgressProjection[];
  posts: RoomPostV2[];
  root: RootProjection;
  sessionsById?: Record<string, PrivateSessionProjection>;
  subagentsByTaskId?: Record<string, RoomTaskSubagentRun[]>;
  taskUpdatedAtMsById?: Record<string, number>;
  tasks: RoomTaskV3[];
  workItems?: RoomWorkItem[];
}) {
  const nodes = taskGraphNodes(
    tasks.filter(roomTaskIsVisibleWork),
    dispatches,
    participantProgress,
    posts,
  );
  if (!nodes.length) return null;
  return <section aria-label="每项工作的详细进展" className="room-task-work-list">
    <header>
      <span>
        <strong>每项工作的详细进展</strong>
        <small>默认只显示摘要、负责人、状态和完成情况</small>
      </span>
      <b>{nodes.length} 项</b>
    </header>
    <div>{nodes.map((node) => {
      const task = node.task;
      const owner = participantLabel(task.currentOwnerParticipantId, participantLabels);
      const ownerPersona = participantPersonas[task.currentOwnerParticipantId];
      const state = taskFlowState(task.state);
      const verification = taskVerification(task, node.dispatches);
      const taskActivities = taskPublicActivities(task, node.dispatches, activities);
      const latestActivity = taskActivities.at(-1);
      const holdReason = taskHoldReason(node, participantLabels);
      const objective = roomPublicActivityText(task.objective) || '协作任务';
      const expectedOutput = roomPublicActivityText(task.expectedOutput) || '按约定完成交付';
      const workspaceAttention = roomTaskWorkspaceNeedsAttention(task);
      const summaryState = workspaceAttention ? 'attention' : state;
      const summary = node.result
        || (latestActivity && publicTaskActivitySummary(latestActivity))
        || objective;
      const currentOrNextAction = latestActivity && ['active', 'review'].includes(task.state)
        ? publicTaskActivitySummary(latestActivity)
        : taskCurrentOrNextAction(node, participantLabels, root);
      const subagents = subagentsByTaskId[task.taskId] ?? [];
      const authority = projectRoomTaskAuthority({
        dispatches: node.dispatches,
        generation: root.generation,
        sessionsById,
        task,
        workItems,
      });
      const todoSummary = roomTaskTodoSummary(authority.todo);
      return <details
        aria-label={`${objective}，负责人 ${owner}，${taskNodeStateLabel(node)}`}
        className="room-task-work-card"
        data-has-persona={ownerPersona ? 'true' : undefined}
        data-state={summaryState}
        data-task-state={state}
        data-workspace-attention={workspaceAttention || undefined}
        key={task.taskId}
      >
        <summary>
          <span className="room-task-work-card__state" aria-hidden="true">
            <FlowStateIcon state={summaryState} />
          </span>
          {ownerPersona ? <PersonaAvatar
            fallbackName={owner}
            persona={ownerPersona}
            presence={summaryState === 'active'
              ? 'thinking'
              : summaryState === 'complete'
                ? 'done'
                : summaryState === 'attention'
                  ? 'warning'
                  : 'listening'}
            size="small"
          /> : null}
          <span className="room-task-work-card__summary">
            <strong>{summary}</strong>
            <small>{owner} · {taskNodeStateLabel(node)}{latestActivity ? <> · <TaskActivityTime activity={latestActivity} /></> : null}</small>
            {todoSummary ? <small className="room-task-work-card__todo-summary">{todoSummary}</small> : null}
          </span>
          <span
            className="room-task-work-card__completion"
            data-attention={workspaceAttention || undefined}
          >
            <small>完成情况</small>
            <strong>{workspaceAttention ? '需要处理' : verification.label}</strong>
          </span>
          <ChevronRight aria-hidden="true" size={15} />
        </summary>
        <div className="room-task-work-card__body">
          <dl className="room-task-work-card__facts">
            <div><dt>工作目标</dt><dd>{objective}</dd></div>
            <div><dt>预期交付</dt><dd>{expectedOutput}</dd></div>
            <div><dt>{['active', 'review'].includes(task.state) ? '当前动作' : '下一步'}</dt><dd>{currentOrNextAction}</dd></div>
            {holdReason ? <div><dt>等待原因</dt><dd>{holdReason}</dd></div> : null}
            <div><dt>完成情况</dt><dd>{verification.label}</dd></div>
          </dl>
          {taskHasWorkspaceProjection(task) ? <TaskWorkspaceDetails
            owner={owner}
            task={task}
            updatedAtMs={taskUpdatedAtMsById[task.taskId]}
          /> : null}
          <RoomTaskDeliveryDetails
            delivery={authority.delivery}
            owner={owner}
            roleResult={authority.roleResult}
            workItem={authority.workItem}
          />
          {taskActivities.length ? <section className="room-task-work-card__activities" aria-label="公开活动">
            <header><strong>公开活动</strong><small>{taskActivities.length} 条，按发生时间排列</small></header>
            <ol>{taskActivities.map((activity) => {
              const sourceEventType = taskActivitySourceType(activity);
              const toolActivity = sourceEventType.startsWith('tool_');
              return <li data-state={activity.status} key={activity.id}>
                <span><FlowStateIcon state={activityFlowState(activity.status)} /></span>
                <span>
                  <strong>{taskActivityKindLabel(activity)}</strong>
                  <small>{publicTaskActivitySummary(activity)}</small>
                </span>
                <TaskActivityTime activity={activity} />
                {toolActivity ? <RoomTaskToolOutput activity={activity} /> : null}
              </li>;
            })}</ol>
          </section> : <p className="room-task-work-card__empty">这项工作还没有公开活动。</p>}
          {subagents.length ? <RoomTaskSubagentRuns heading={objective} runs={subagents} /> : null}
          <RoomTaskTodoDetails owner={owner} todo={authority.todo} />
        </div>
      </details>;
    })}</div>
  </section>;
}

type WorkspaceAuditField = {
  id: string;
  label: string;
  value: string;
};

function TaskWorkspaceDetails({
  owner,
  task,
  updatedAtMs,
}: {
  owner: string;
  task: RoomTaskV3;
  updatedAtMs?: number;
}) {
  const attention = roomTaskWorkspaceNeedsAttention(task);
  const auditFields = taskWorkspaceAuditFields(task);
  const terminalReason = taskWorkspacePublicReason(task);
  return <section
    aria-label="工作区、交付与收尾"
    className="room-task-workspace"
    data-attention={attention || undefined}
  >
    <header>
      <span><GitBranch aria-hidden="true" size={14} /><strong>工作区与交付</strong></span>
      <span className="room-task-workspace__status">
        <small>{taskWorkspaceOverview(task)}</small>
        <RoomTaskUpdatedAt updatedAtMs={updatedAtMs} />
      </span>
    </header>
    <dl className="room-task-workspace__business">
      <div><dt>隔离工作区</dt><dd>{taskWorkspaceIsolationLabel(task)}</dd></div>
      <div><dt>负责人和责任</dt><dd>{owner} · {taskWorkspaceResponsibilityLabel(task)}</dd></div>
      <div><dt>共同基线</dt><dd>{taskWorkspaceBaselineLabel(task)}</dd></div>
      <div><dt>工作区进展</dt><dd>{taskWorkspaceLifecycleLabel(task)}</dd></div>
      <div><dt>交付状态</dt><dd>{taskWorkspaceDeliveryLabel(task)}</dd></div>
      <div><dt>整合状态</dt><dd>{taskWorkspaceIntegrationLabel(task)}</dd></div>
      <div><dt>收尾状态</dt><dd>{taskWorkspaceCleanupLabel(task)}</dd></div>
    </dl>
    {attention ? <p className="room-task-workspace__attention" role="alert">
      <CircleAlert aria-hidden="true" size={14} />
      <span><strong>需要处理</strong><small>{terminalReason}</small></span>
    </p> : null}
    {auditFields.length ? <details className="room-task-workspace__audit">
      <summary>
        <ShieldCheck aria-hidden="true" size={14} />
        <span><strong>审计详情</strong><small>路径、校验值与内部关联</small></span>
        <ChevronRight aria-hidden="true" size={14} />
      </summary>
      <dl>{auditFields.map((field) => <div key={field.id}>
        <dt>{field.label}</dt>
        <dd><code>{field.value}</code></dd>
      </div>)}</dl>
    </details> : null}
  </section>;
}

function taskHasWorkspaceProjection(task: RoomTaskV3): boolean {
  return Boolean(
    task.workspacePolicy
    || task.workspaceRoot
    || task.workspaceBaseRoot
    || task.workspaceBaseCommit
    || task.workspaceSnapshotSha256
    || task.workspaceBindingId
    || task.workspaceRepositoryId
    || task.workspaceLifecycleState
    || task.workspaceCleanupState
    || task.workspaceAttentionRequired !== undefined
    || task.workspaceDeliveryRevision
    || task.workspaceDeliveryHead
    || task.workspaceDeliverySnapshotSha256
    || task.workspaceDelivery
    || task.workspaceIntegrationPatchSha256
    || task.workspaceIntegratedRevision
    || task.workspaceIntegratedSnapshotSha256
    || task.workspaceTerminalReason
    || task.workspaceIntegrationState
    || task.workspaceIntegrationRef
    || task.workspaceRestorePolicy
  );
}

export function roomTaskWorkspaceNeedsAttention(task: RoomTaskV3): boolean {
  return task.workspaceAttentionRequired === true
    || [
      'conflict',
      'failed',
      'blocked',
      'cancelled',
      'orphaned',
      'incomplete',
      'cleanup_failed',
    ].includes(task.workspaceLifecycleState ?? '')
    || task.workspaceCleanupState === 'failed';
}

const taskWorkspaceLifecycleViews: Readonly<Record<
  WorkspaceLifecycleState,
  Omit<RoomTaskWorkspaceLifecycleView, 'attention'>
>> = {
  reserved: {
    title: '已预留独立工作区',
    detail: '等待从共同基线准备',
    state: 'waiting',
  },
  materialized: {
    title: '工作区已准备',
    detail: '已从共同基线准备，负责人可以开始工作',
    state: 'running',
  },
  work_started: {
    title: '负责人正在独立工作',
    detail: '正在自己的工作区完成分工',
    state: 'running',
  },
  delivered: {
    title: '结果已经交回',
    detail: '协调伙伴可以检查并准备整合',
    state: 'completed',
  },
  integration_started: {
    title: '正在纳入共同工作',
    detail: '协调伙伴正在整合已交回的结果',
    state: 'running',
  },
  integrated: {
    title: '结果已纳入共同工作',
    detail: '这项交付已经进入共同结果',
    state: 'completed',
  },
  conflict: {
    title: '整合发生冲突，需要处理',
    detail: '工作区已保留，负责人需要修复或重新整合',
    state: 'failed',
  },
  failed: {
    title: '工作区任务未完成',
    detail: '需要负责人检查失败原因并决定如何继续',
    state: 'failed',
  },
  blocked: {
    title: '工作区任务受阻',
    detail: '需要负责人解除阻塞后再继续',
    state: 'failed',
  },
  cancelled: {
    title: '工作区任务已停止',
    detail: '工作区已保留，需要负责人检查并完成收尾',
    state: 'aborted',
  },
  orphaned: {
    title: '工作区失去负责人，需要重新接管',
    detail: '工作区仍保留，确认新负责人后才能继续',
    state: 'failed',
  },
  incomplete: {
    title: '工作区收尾不完整',
    detail: '交付或收尾仍有缺口，需要负责人检查',
    state: 'failed',
  },
  retained: {
    title: '工作区已保留',
    detail: '现场与结果保留，等待后续处理',
    state: 'waiting',
  },
  retry_bound: {
    title: '工作区已留给下一次尝试',
    detail: '下一次尝试会继续使用这份工作区',
    state: 'waiting',
  },
  abandoned: {
    title: '工作区已确认放弃',
    detail: '协调伙伴已凭交付记录明确结束这份工作区',
    state: 'completed',
  },
  cleanup_failed: {
    title: '工作区清理失败',
    detail: '现场已保留，需要检查清理失败原因',
    state: 'failed',
  },
  cleaned: {
    title: '工作区已安全清理',
    detail: '结果已收束，临时工作区已经清理',
    state: 'completed',
  },
};

/** Present the canonical Task lifecycle without inventing a parallel UI state. */
export function roomTaskWorkspaceLifecycleView(
  task: RoomTaskV3,
): RoomTaskWorkspaceLifecycleView | undefined {
  const lifecycleState = task.workspaceLifecycleState;
  if (!lifecycleState) return undefined;
  const view = taskWorkspaceLifecycleViews[lifecycleState];
  const attention = roomTaskWorkspaceNeedsAttention(task);
  return {
    ...view,
    attention,
    detail: attention && view.state !== 'failed'
      ? `${view.detail}；当前记录要求负责人处理`
      : view.detail,
    state: attention ? 'failed' : view.state,
  };
}

function taskWorkspaceOverview(task: RoomTaskV3): string {
  if (roomTaskWorkspaceNeedsAttention(task)) return '工作区状态需要负责人处理';
  if (task.workspaceCleanupState === 'cleaned' || task.workspaceLifecycleState === 'cleaned') {
    return '结果已收束，工作区已安全清理';
  }
  if (task.workspaceCleanupState === 'retained' || task.workspaceLifecycleState === 'retained') {
    return '结果已保留，工作区等待后续处理';
  }
  if (task.workspaceIntegrationState === 'applied' || task.workspaceLifecycleState === 'integrated') {
    return '结果已纳入共同工作';
  }
  return '显示权威任务记录中的工作区状态';
}

function taskWorkspaceIsolationLabel(task: RoomTaskV3): string {
  if (task.workspacePolicy === 'isolated_writable') return '已绑定独立可写工作区';
  if (task.workspacePolicy === 'shared_single_writer') return '未使用独立工作区，由一位负责人写入共同工作区';
  if (task.workspacePolicy === 'read_only') return '未使用可写工作区，只读取共同基线';
  return '工作区方式尚未上报';
}

function taskWorkspaceResponsibilityLabel(task: RoomTaskV3): string {
  if (task.workspacePolicy === 'isolated_writable') return '在自己的工作区完成并交回结果';
  if (task.workspacePolicy === 'shared_single_writer') return '是共同工作区的唯一写入负责人';
  if (task.workspacePolicy === 'read_only') return '只负责读取与核对，不写入';
  return '负责当前分工';
}

function taskWorkspaceBaselineLabel(task: RoomTaskV3): string {
  if (task.workspaceBaseRoot || task.workspaceBaseCommit || task.workspaceSnapshotSha256) {
    return '已从共同基线准备；具体位置与版本留在审计详情';
  }
  if (task.workspacePolicy) return '共同基线信息尚未上报';
  return '未绑定共同基线';
}

function taskWorkspaceLifecycleLabel(task: RoomTaskV3): string {
  return roomTaskWorkspaceLifecycleView(task)?.title ?? '工作区进展尚未上报';
}

function taskWorkspaceDeliveryLabel(task: RoomTaskV3): string {
  if (
    task.workspaceDeliveryRevision
    || task.workspaceDeliveryHead
    || task.workspaceDeliverySnapshotSha256
    || [
      'delivered',
      'integration_started',
      'integrated',
      'cleaned',
    ].includes(task.workspaceLifecycleState ?? '')
  ) return '结果已交回协调伙伴';
  if (task.workspaceLifecycleState === 'orphaned') return '交付归属需要重新确认';
  if (['failed', 'blocked', 'cancelled', 'incomplete'].includes(task.workspaceLifecycleState ?? '')) {
    return '结果尚未完整交付';
  }
  if (task.workspaceLifecycleState === 'retained') return '结果是否完整交付仍待核对';
  if (task.workspaceLifecycleState === 'conflict') return '整合发生冲突，交付状态待核对';
  if (task.workspaceLifecycleState === 'abandoned') return '已记录放弃，交付状态以留存记录为准';
  if (['reserved', 'materialized', 'work_started'].includes(task.workspaceLifecycleState ?? '')) {
    return '尚在工作，未交回结果';
  }
  return '交付状态尚未上报';
}

function taskWorkspaceIntegrationLabel(task: RoomTaskV3): string {
  if (task.workspaceLifecycleState === 'conflict') return '整合发生冲突，需要负责人处理';
  if (task.workspaceLifecycleState === 'orphaned') return '尚未整合，需要重新确认负责人';
  if (task.workspaceIntegrationState === 'applied' || task.workspaceLifecycleState === 'integrated') {
    return '已纳入共同结果';
  }
  if (task.workspaceIntegrationState === 'pending' || task.workspaceLifecycleState === 'integration_started') {
    return '等待或正在由协调伙伴整合';
  }
  if (task.workspaceIntegrationState === 'not_required') return '这项工作无需单独整合';
  if (task.workspaceLifecycleState === 'delivered') return '已交付，等待整合';
  return '尚未进入整合';
}

function taskWorkspaceCleanupLabel(task: RoomTaskV3): string {
  if (task.workspaceCleanupState === 'cleaned' || task.workspaceLifecycleState === 'cleaned') {
    return '工作区已安全清理';
  }
  if (task.workspaceCleanupState === 'retained' || task.workspaceLifecycleState === 'retained') {
    return '工作区已保留，等待后续处理';
  }
  if (task.workspaceLifecycleState === 'conflict') return '工作区为处理冲突而保留';
  if (task.workspaceLifecycleState === 'cancelled') return '工作区已保留，等待负责人检查和收尾';
  if (task.workspaceLifecycleState === 'orphaned') return '工作区仍保留，等待重新接管';
  if (task.workspaceLifecycleState === 'abandoned') return '放弃决定已记录，等待确认保留或清理结果';
  if (task.workspaceCleanupState === 'failed' || task.workspaceLifecycleState === 'cleanup_failed') {
    return '清理失败，需要处理';
  }
  if (task.workspaceCleanupState === 'authorized') return '已允许清理，尚未完成';
  if (task.workspaceCleanupState === 'not_authorized') return '工作区暂时保留，尚未允许清理';
  if (task.workspaceCleanupState === 'missing') return '工作区已不存在';
  return '尚未进入清理或保留阶段';
}

function taskWorkspacePublicReason(task: RoomTaskV3): string {
  const reason = roomPublicActivityText(task.workspaceTerminalReason ?? '');
  if (reason && /[\u3400-\u9fff]/u.test(reason)) return reason;
  if (task.workspaceLifecycleState === 'conflict') return '整合发生冲突，需要负责人选择修复或重新整合。';
  if (task.workspaceLifecycleState === 'cancelled') return '工作已经停止，工作区会保留到负责人检查并完成收尾。';
  if (task.workspaceLifecycleState === 'orphaned') return '工作区失去当前负责人，需要重新接管后再继续。';
  if (task.workspaceLifecycleState === 'cleanup_failed' || task.workspaceCleanupState === 'failed') {
    return '工作区没有完成安全清理，需要保留现场并检查原因。';
  }
  return '权威任务记录要求负责人检查工作区、交付或收尾状态。';
}

function taskWorkspaceAuditFields(task: RoomTaskV3): WorkspaceAuditField[] {
  const fields: WorkspaceAuditField[] = [];
  const append = (id: string, label: string, value: string | null | undefined) => {
    if (!value) return;
    fields.push({ id, label, value });
  };
  append('workspaceRoot', '负责人工作位置', task.workspaceRoot);
  append('workspaceBaseRoot', '共同基线位置', task.workspaceBaseRoot);
  append('workspaceBaseCommit', '共同基线版本', task.workspaceBaseCommit);
  append('workspaceSnapshotSha256', '开始时快照校验', task.workspaceSnapshotSha256);
  append('workspaceBindingId', '工作区绑定记录', task.workspaceBindingId);
  append('workspaceRepositoryId', '代码库记录', task.workspaceRepositoryId);
  append('workspaceDeliveryRevision', '交付版本', task.workspaceDeliveryRevision);
  append('workspaceDeliveryHead', '交付分支或引用', task.workspaceDeliveryHead);
  append('workspaceDeliverySnapshotSha256', '交付快照校验', task.workspaceDeliverySnapshotSha256);
  append('workspaceIntegrationPatchSha256', '整合补丁校验', task.workspaceIntegrationPatchSha256);
  append('workspaceIntegratedRevision', '已整合版本', task.workspaceIntegratedRevision);
  append('workspaceIntegratedSnapshotSha256', '整合后快照校验', task.workspaceIntegratedSnapshotSha256);
  append('workspaceIntegrationRef', '整合记录', task.workspaceIntegrationRef);
  if (task.workspaceRestorePolicy) {
    append('toolProfileVersion', '工具方案版本', task.workspaceRestorePolicy.toolProfileVersion);
    append('workspaceScopeSha256', '授权工作范围校验', task.workspaceRestorePolicy.workspaceScopeSha256);
  }
  return fields;
}

function taskPublicActivities(
  task: RoomTaskV3,
  dispatches: RoomDispatchEnvelopeV2[],
  activities: RoomActivityProjection[],
): RoomActivityProjection[] {
  const dispatchIds = new Set(dispatches.map((dispatch) => dispatch.dispatchId));
  return activities.filter((activity) => {
    const dispatchId = stringValue(activity.payload.dispatchId);
    const taskId = stringValue(activity.payload.taskId);
    return Boolean((dispatchId && dispatchIds.has(dispatchId)) || taskId === task.taskId);
  }).sort((left, right) => (
    (left.updatedAtMs ?? left.createdAtMs) - (right.updatedAtMs ?? right.createdAtMs)
    || left.id.localeCompare(right.id)
  ));
}

function taskActivitySourceType(activity: RoomActivityProjection): string {
  return stringValue(activity.payload.sourceEventType);
}

function taskActivityKindLabel(activity: RoomActivityProjection): string {
  const sourceEventType = taskActivitySourceType(activity);
  if (sourceEventType.startsWith('tool_')) {
    const tool = stringValue(
      activity.payload.toolLabel
      || activity.payload.toolName
      || activity.payload.name,
    );
    return tool ? `工具 · ${tool}` : '工具运行';
  }
  if (sourceEventType === 'reasoning_summary') return '工作摘要';
  if (sourceEventType === 'message_completed') return '阶段结果';
  if (activity.status === 'waiting') return '等待说明';
  if (activity.status === 'failed') return '未完成说明';
  return '工作进展';
}

function publicTaskActivitySummary(activity: RoomActivityProjection): string {
  return roomPublicActivityText(activity.summary)
    || roomPublicActivityText(stringValue(activity.payload.summary || activity.payload.message))
    || taskActivityKindLabel(activity);
}

function RoomTaskToolOutput({ activity }: { activity: RoomActivityProjection }) {
  const payload = activity.payload;
  const sourceEventType = taskActivitySourceType(activity);
  const result = recordValue(payload.result);
  const error = stringValue(payload.error);
  const publicResult = error && !result.error ? { ...result, error } : result;
  const view = roomPublicToolResultView(publicToolResultView({
    kind: sourceEventType || activity.kind,
    status: activity.status,
    payload: {
      ...payload,
      args: recordValue(payload.arguments),
      publicResult,
    },
  }));
  const toolId = view.toolId || canonicalToolId(stringValue(payload.toolName));
  const basicToolKind = ['read', 'edit', 'write', 'bash'].includes(toolId)
    ? toolId as 'read' | 'edit' | 'write' | 'bash'
    : 'standard';
  const streaming = basicToolKind !== 'standard'
    && activity.status === 'running'
    && ['tool_started', 'tool_progress'].includes(sourceEventType);
  const mutationAwaitingDiff = streaming && (toolId === 'edit' || toolId === 'write');
  const showArtifacts = hasToolArtifacts(view.artifacts) && !mutationAwaitingDiff;
  const target = view.request.find((field) => field.id === 'path' || field.id === 'file')?.value
    || view.fields.find((field) => field.id === 'file')?.value
    || '';
  const hasDetail = showArtifacts
    || Boolean(view.request.length || view.output || view.preview || view.fields.length || view.error)
    || streaming;
  return <details className="room-task-work-card__tool-output" open={streaming || undefined}>
    <summary>查看工具返回</summary>
    <div className="room-task-work-card__tool-output-body">
      {view.summary ? <p>{view.summary}</p> : null}
      {showArtifacts ? <ToolArtifactOutput
        artifacts={view.artifacts}
        autoExpandDiff={activity.status === 'completed'}
      /> : null}
      {!showArtifacts && view.request.length ? <PublicToolRequest view={view} /> : null}
      {streaming && (!view.output || mutationAwaitingDiff)
        ? <ToolRunningPreview target={target} toolId={basicToolKind} />
        : null}
      {!showArtifacts && !mutationAwaitingDiff && view.output
        ? <PublicToolOutput streaming={streaming} view={view} />
        : null}
      {!showArtifacts && view.preview ? <SemanticToolPreview preview={view.preview} /> : null}
      {!showArtifacts && view.fields.length ? <PublicToolFields view={view} /> : null}
      {view.error ? <PublicToolError reason={view.error} /> : null}
      {!hasDetail && !view.summary
        ? <p>这个工具没有公开返回内容。</p>
        : null}
    </div>
  </details>;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function TaskActivityTime({ activity }: { activity: RoomActivityProjection }) {
  const atMs = activity.updatedAtMs ?? activity.createdAtMs;
  return <time dateTime={new Date(atMs).toISOString()}>
    {roomPublicTaskTimeFormatter.format(new Date(atMs))}
  </time>;
}

const roomPublicTaskTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

function activityFlowState(status: RoomActivityProjection['status']): FlowVisualState {
  if (status === 'completed') return 'complete';
  if (status === 'failed') return 'attention';
  if (status === 'aborted') return 'cancelled';
  if (status === 'running') return 'active';
  return 'waiting';
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function TaskNode({
  node,
  participantLabels,
  participantPersonas,
  style,
}: {
  node: TaskGraphNode;
  participantLabels: Record<string, string>;
  participantPersonas: Record<string, AgentPersonaV1>;
  style: CSSProperties;
}) {
  const { task } = node;
  const taskLabel = roomPublicActivityText(node.result || task.objective) || '协作任务';
  const expectedOutput = roomPublicActivityText(task.expectedOutput) || '按约定完成交付';
  const owner = participantLabel(task.currentOwnerParticipantId, participantLabels);
  const ownerPersona = participantPersonas[task.currentOwnerParticipantId];
  const state = taskFlowState(task.state);
  const dependencyCount = node.dependencyIds.length;
  const dependencyLabel = dependencyCount
    ? `等待 ${dependencyCount} 项真实前置任务`
    : '无前置任务，可并行';
  const action = taskNodeAction(node, expectedOutput);
  return <article
    aria-label={`${taskLabel}，负责人 ${owner}，${taskNodeStateLabel(node)}`}
    className="room-task-flow__task-node"
    data-state={state}
    data-task-kind={task.taskKind}
    data-task-stage={taskStageLabel(node)}
    style={style}
    title={`交付目标：${expectedOutput}\n前置关系：${dependencyLabel}`}
  >
    <header>
      <small>{node.result ? '任务结果' : taskStageLabel(node)} · {dependencyLabel}</small>
      <strong>{taskLabel}</strong>
    </header>
    <div className="room-task-flow__task-owner">
      {ownerPersona ? <PersonaAvatar
        fallbackName={owner}
        persona={ownerPersona}
        presence={state === 'active'
          ? 'thinking'
          : state === 'complete'
            ? 'done'
            : state === 'attention'
              ? 'warning'
              : 'listening'}
        size="small"
      /> : <span aria-hidden="true">{Array.from(owner.trim())[0] || '伙'}</span>}
      <span><small>负责人</small><strong>{owner}</strong></span>
    </div>
    <div className="room-task-flow__task-state">
      <FlowStateIcon state={state} />
      <span><small>当前状态</small><strong>{taskNodeStateLabel(node)}</strong></span>
    </div>
    <div className="room-task-flow__task-action">
      <ArrowRight aria-hidden="true" size={14} />
      <span><small>{action.label}</small><strong>{action.detail}</strong></span>
    </div>
  </article>;
}

function taskNodeAction(
  node: TaskGraphNode,
  expectedOutput: string,
): { label: string; detail: string } {
  const progress = node.progress
    ? roomPublicActivityText(roomParticipantPublicProgressSummary(node.progress))
    : '';
  const concreteProgress = /(?:有新进展|进度已经更新|公开进度已经更新|Provider|公开思考|思考摘要)/iu.test(progress)
    ? ''
    : progress;
  if (node.task.state === 'active' || node.task.state === 'review') {
    return {
      label: node.task.state === 'review' ? '正在复核' : '正在做',
      detail: concreteProgress || expectedOutput,
    };
  }
  if (node.task.state === 'completed') {
    return { label: '已交付', detail: node.result || expectedOutput };
  }
  if (node.task.state === 'blocked' || node.task.state === 'failed') {
    return { label: '恢复后继续', detail: concreteProgress || '由协调伙伴处理并重新安排' };
  }
  if (node.task.state === 'cancelled') {
    return { label: '已停止', detail: '这项工作不会继续执行' };
  }
  return node.dependencyIds.length
    ? { label: '下一步', detail: `等待 ${node.dependencyIds.length} 项前置任务完成` }
    : { label: '下一步', detail: expectedOutput };
}

export function RoomTaskSubagentRuns({
  heading,
  runs,
}: {
  heading?: string;
  runs: RoomTaskSubagentRun[];
}) {
  const publicHeading = heading ? roomPublicActivityText(heading) : '';
  const ordered = [...runs].sort((left, right) => (
    subagentDisplayPriority(left.state) - subagentDisplayPriority(right.state)
    || left.ordinal - right.ordinal
    || left.templateId.localeCompare(right.templateId)
    || left.createdAtMs - right.createdAtMs
    || left.task.localeCompare(right.task)
  ));
  const visible = ordered.slice(0, MAX_VISIBLE_SUBAGENT_RUNS);
  const hiddenCount = ordered.length - visible.length;
  return <section
    aria-label={`负责人调用了 ${ordered.length} 个临时协作者`}
    className="room-task-flow__subagents"
  >
    <header>
      <span><Bot aria-hidden="true" size={14} /><strong>临时协作者 · {ordered.length}</strong></span>
      <small>{publicHeading ? `协助：${publicHeading}` : '临时协助负责人，不会成为新的主要伙伴'}</small>
    </header>
    <ol>
      {visible.map((run, index) => {
        const state = subagentFlowState(run.state);
        const detail = subagentResultDetail(run);
        const timing = subagentTiming(run);
        const publicTask = roomPublicActivityText(run.task) || '协助当前工作';
        return <li
          aria-label={`${subagentTemplateLabel(run.templateId, run.ordinal)}，${subagentStateLabel(run.state)}，${publicTask}`}
          data-state={state}
          key={`${run.ordinal}:${run.templateId}:${run.createdAtMs}:${index}`}
          title={publicTask}
        >
          <span className="room-task-flow__subagent-rail" aria-hidden="true">
            <i />
            <Bot size={13} />
          </span>
          <span className="room-task-flow__subagent-copy">
            <strong>{subagentTemplateLabel(run.templateId, run.ordinal)}</strong>
            <small>{publicTask}</small>
            <small className="room-task-flow__subagent-budget">{subagentBudgetLabel(run)}</small>
          </span>
          <em aria-atomic="true" aria-live="polite">
            <FlowStateIcon state={state} />
            <span>{subagentStateLabel(run.state)}</span>
            <time dateTime={new Date(timing.atMs).toISOString()}>{timing.label}</time>
          </em>
          {detail ? <p data-kind={detail.kind} title={detail.text}>{detail.text}</p> : null}
        </li>;
      })}
    </ol>
    {hiddenCount ? <p className="room-task-flow__subagent-overflow">
      另有 {hiddenCount} 个临时协作者未展开
    </p> : null}
  </section>;
}

function subagentTemplateLabel(templateId: AgentSubagentRunV1['templateId'], ordinal: number): string {
  const labels: Record<AgentSubagentRunV1['templateId'], string> = {
    planner: '规划助手',
    researcher: '研究助手',
    worker: '执行助手',
    reviewer: '复核助手',
    delegate: '协作助手',
  };
  return `${labels[templateId]} ${ordinal + 1}`;
}

function subagentStateLabel(state: AgentSubagentRunV1['state']): string {
  const labels: Record<AgentSubagentRunV1['state'], string> = {
    queued: '等待调用',
    running: '正在执行',
    completed: '已返回',
    failed: '调用失败',
    aborted: '已停止',
    timed_out: '调用超时',
  };
  return labels[state];
}

function subagentFlowState(state: AgentSubagentRunV1['state']): FlowVisualState {
  if (state === 'running') return 'active';
  if (state === 'completed') return 'complete';
  if (state === 'failed' || state === 'timed_out') return 'attention';
  if (state === 'aborted') return 'cancelled';
  return 'waiting';
}

function subagentDisplayPriority(state: AgentSubagentRunV1['state']): number {
  if (state === 'failed' || state === 'timed_out') return 0;
  if (state === 'running') return 1;
  if (state === 'queued') return 2;
  if (state === 'aborted') return 3;
  return 4;
}

function subagentBudgetLabel(run: RoomTaskSubagentRun): string {
  return `${run.usage.turnCount} / ${run.budget.maxTurns} 回合 · ${run.usage.toolCount} / ${run.budget.maxToolCalls} 次工具`;
}

function subagentResultDetail(
  run: RoomTaskSubagentRun,
): { kind: 'result' | 'error'; text: string } | null {
  const error = roomPublicActivityText(run.error);
  const result = roomPublicActivityText(run.resultSummary);
  if (error) return { kind: 'error', text: error };
  if (result) return { kind: 'result', text: result };
  return null;
}

function subagentTiming(run: RoomTaskSubagentRun): { atMs: number; label: string } {
  const atMs = run.completedAtMs ?? run.updatedAtMs;
  const prefix = run.completedAtMs === null ? '更新' : '结束';
  return { atMs, label: `${prefix} ${subagentTimeFormatter.format(new Date(atMs))}` };
}

function CompactFlowNode({
  className,
  detail,
  icon,
  label,
  stage,
  state,
  stateLabel,
  style,
  title,
}: {
  className: string;
  detail: string;
  icon: ReactNode;
  label: string;
  stage: 'goal' | 'result';
  state: FlowVisualState;
  stateLabel: string;
  style: CSSProperties;
  title: string;
}) {
  return <article
    aria-label={`${title}，${label}，${stateLabel}`}
    className={`room-task-flow__node ${className}`}
    data-flow-stage={stage}
    data-state={state}
    style={style}
  >
    <span className="room-task-flow__node-icon">{icon}</span>
    <span className="room-task-flow__node-copy">
      <small>{title}</small>
      <strong title={label}>{label}</strong>
      <small>{detail}</small>
    </span>
    <i><FlowStateIcon state={state} />{stateLabel}</i>
  </article>;
}

function FlowStateIcon({ state }: { state: FlowVisualState }) {
  if (state === 'complete') return <CircleCheck aria-hidden="true" size={13} />;
  if (state === 'attention') return <CircleAlert aria-hidden="true" size={13} />;
  if (state === 'cancelled') return <CircleStop aria-hidden="true" size={13} />;
  if (state === 'active') return <ArrowRight aria-hidden="true" size={13} />;
  return <Clock3 aria-hidden="true" size={13} />;
}

function taskGraphNodes(
  tasks: RoomTaskV3[],
  dispatches: RoomDispatchEnvelopeV2[],
  participantProgress: RoomParticipantPublicProgressProjection[],
  posts: RoomPostV2[],
): TaskGraphNode[] {
  const taskById = new Map(tasks.map((task) => [task.taskId, task]));
  const dispatchById = new Map(dispatches.map((dispatch) => [dispatch.dispatchId, dispatch]));
  const dispatchesByTaskId = new Map<string, RoomDispatchEnvelopeV2[]>();
  for (const dispatch of dispatches) {
    const current = dispatchesByTaskId.get(dispatch.taskId);
    if (current) current.push(dispatch);
    else dispatchesByTaskId.set(dispatch.taskId, [dispatch]);
  }
  const resultByTaskId = new Map<string, RoomPostV2>();
  for (const post of posts) {
    if (
      !post.taskId
      || !taskById.has(post.taskId)
      || post.visibility !== 'room'
      || post.publicationSource.kind !== 'room_commit'
      || !['finding', 'handoff', 'result'].includes(post.kind)
    ) continue;
    const current = resultByTaskId.get(post.taskId);
    if (!current || post.createdAtMs >= current.createdAtMs) {
      resultByTaskId.set(post.taskId, post);
    }
  }
  const dependenciesByTaskId = new Map<string, string[]>();
  const externalDependenciesByTaskId = new Map<string, number>();
  const downstreamByTaskId = new Map(tasks.map((task) => [task.taskId, [] as string[]]));
  const childIdsByTaskId = new Map(tasks.map((task) => [task.taskId, [] as string[]]));
  for (const task of tasks) {
    if (
      task.parentTaskId
      && task.parentTaskId !== task.taskId
      && taskById.has(task.parentTaskId)
    ) {
      childIdsByTaskId.get(task.parentTaskId)?.push(task.taskId);
    }
  }
  for (const task of tasks) {
    const dependencyIds = new Set(task.reviewOfTaskIds.filter((taskId) => (
      taskId !== task.taskId && taskById.has(taskId)
    )));
    const externalDispatchIds = new Set<string>();
    for (const dispatch of dispatchesByTaskId.get(task.taskId) ?? []) {
      for (const dependencyDispatchId of dispatch.dependsOnDispatchIds ?? []) {
        const dependency = dispatchById.get(dependencyDispatchId);
        if (!dependency) {
          externalDispatchIds.add(dependencyDispatchId);
          continue;
        }
        if (dependency.taskId !== task.taskId && taskById.has(dependency.taskId)) {
          dependencyIds.add(dependency.taskId);
        }
      }
    }
    const orderedDependencies = [...dependencyIds].sort();
    dependenciesByTaskId.set(task.taskId, orderedDependencies);
    externalDependenciesByTaskId.set(task.taskId, externalDispatchIds.size);
    for (const dependencyId of orderedDependencies) {
      downstreamByTaskId.get(dependencyId)?.push(task.taskId);
    }
  }
  const sortedTasks = [...tasks].sort((left, right) => left.taskId.localeCompare(right.taskId));
  const columnTasks: Record<TaskColumn, RoomTaskV3[]> = { 2: [], 3: [], 4: [] };
  for (const task of sortedTasks) {
    // parentTaskId describes responsibility hierarchy, not execution order.
    // Only an explicit review/dependency contract moves work into a later
    // stage; otherwise a child task is allowed to run beside its parent.
    const hasPredecessor = Boolean(
      dependenciesByTaskId.get(task.taskId)?.length,
    );
    const column: TaskColumn = task.taskKind === 'review' ? 4 : hasPredecessor ? 3 : 2;
    columnTasks[column].push(task);
  }
  return ([2, 3, 4] as const).flatMap((column) => (
    columnTasks[column].map((task, index) => {
      const taskDispatches = dispatchesByTaskId.get(task.taskId) ?? [];
      return {
        task,
        dispatches: taskDispatches,
        dependencyIds: dependenciesByTaskId.get(task.taskId) ?? [],
        parentId: task.parentTaskId && taskById.has(task.parentTaskId)
          ? task.parentTaskId
          : undefined,
        dependencyOwnerParticipantIds: [
          ...new Set((dependenciesByTaskId.get(task.taskId) ?? [])
            .map((taskId) => taskById.get(taskId)?.currentOwnerParticipantId ?? '')
            .filter(Boolean)),
        ],
        downstreamIds: downstreamByTaskId.get(task.taskId) ?? [],
        childIds: childIdsByTaskId.get(task.taskId) ?? [],
        downstreamOwnerParticipantIds: [
          ...new Set((downstreamByTaskId.get(task.taskId) ?? [])
            .map((taskId) => taskById.get(taskId)?.currentOwnerParticipantId ?? '')
            .filter(Boolean)),
        ],
        externalDependencyCount: externalDependenciesByTaskId.get(task.taskId) ?? 0,
        progress: latestTaskProgress(task, taskDispatches, participantProgress),
        result: roomPublicActivityText(resultByTaskId.get(task.taskId)?.content ?? '') || undefined,
        column,
        row: index + 1,
      };
    })
  ));
}

function taskGraphPoint(node: TaskGraphNode, rowHeight: number): GraphPoint {
  const bounds = TASK_COLUMN_BOUNDS[node.column];
  return {
    ...bounds,
    y: (node.row - 0.5) * rowHeight,
  };
}

function taskGraphEdges(
  nodes: TaskGraphNode[],
  points: Map<string, GraphPoint>,
  graphMidpoint: number,
): GraphEdge[] {
  if (!nodes.length) {
    return [{
      id: 'goal:result',
      from: { x: 130, y: graphMidpoint },
      to: { x: 885, y: graphMidpoint },
      state: 'waiting',
    }];
  }
  const edges: GraphEdge[] = [];
  for (const node of nodes) {
    const target = points.get(node.task.taskId)!;
    const predecessorIds = node.dependencyIds;
    if (!predecessorIds.length) {
      edges.push({
        id: `goal:${node.task.taskId}`,
        from: { x: 130, y: graphMidpoint },
        to: { x: target.left, y: target.y },
        state: taskFlowState(node.task.state),
      });
    }
    for (const dependencyId of predecessorIds) {
      const source = points.get(dependencyId);
      if (!source) continue;
      edges.push({
        id: `${dependencyId}:${node.task.taskId}`,
        from: { x: source.right, y: source.y },
        to: {
          x: source.right < target.left ? target.left : target.right,
          y: target.y,
        },
        state: taskFlowState(nodes.find((candidate) => candidate.task.taskId === dependencyId)?.task.state ?? 'pending'),
      });
    }
    if (!node.downstreamIds.length) {
      edges.push({
        id: `${node.task.taskId}:result`,
        from: { x: target.right, y: target.y },
        to: { x: 885, y: graphMidpoint },
        state: taskFlowState(node.task.state),
      });
    }
  }
  return edges;
}

function taskGraphEdgePath(edge: GraphEdge): string {
  const { from, to } = edge;
  if (from.x < to.x) {
    const midpoint = (from.x + to.x) / 2;
    return `M ${from.x} ${from.y} C ${midpoint} ${from.y}, ${midpoint} ${to.y}, ${to.x} ${to.y}`;
  }
  const gutter = Math.min(970, from.x + 26);
  return `M ${from.x} ${from.y} C ${gutter} ${from.y}, ${gutter} ${to.y}, ${to.x} ${to.y}`;
}

function latestTaskProgress(
  task: RoomTaskV3,
  dispatches: RoomDispatchEnvelopeV2[],
  progress: RoomParticipantPublicProgressProjection[],
): RoomParticipantPublicProgressProjection | undefined {
  const dispatchIds = new Set(dispatches.map((dispatch) => dispatch.dispatchId));
  let latest: RoomParticipantPublicProgressProjection | undefined;
  let latestIsExact = false;
  for (const candidate of progress) {
    if (candidate.rootId !== task.rootId) continue;
    const exact = Boolean(candidate.dispatchId && dispatchIds.has(candidate.dispatchId));
    const ownerMatch = candidate.participantId === task.currentOwnerParticipantId;
    if (!exact && !ownerMatch) continue;
    if (
      !latest
      || (exact && !latestIsExact)
      || (exact === latestIsExact && candidate.updatedAtMs >= latest.updatedAtMs)
    ) {
      latest = candidate;
      latestIsExact = exact;
    }
  }
  return latest;
}

function taskCurrentOrNextAction(
  node: TaskGraphNode,
  labels: Record<string, string>,
  root: RootProjection,
): string {
  const { task } = node;
  if (task.state === 'active' || task.state === 'review') {
    if (node.progress) {
      return roomPublicActivityText(roomParticipantPublicProgressSummary(node.progress))
        || '正在推进当前任务';
    }
    const running = latestDispatch(node.dispatches, ['leased', 'running']);
    return running
      ? dispatchIntentLabel(running.intentKind)
      : task.state === 'review'
        ? '复核交付结果'
        : `推进：${roomPublicActivityText(task.expectedOutput) || '按约定完成交付'}`;
  }
  if (task.state === 'completed') {
    const nextOwners = node.downstreamOwnerParticipantIds.map((participantId) => (
      participantLabel(participantId, labels)
    ));
    if (nextOwners.length) return `交给 ${nextOwners.join('、')} 接续`;
    if (root.isFinal) return '已纳入最终结果';
    if (task.reviewState === 'required' || task.reviewState === 'in_review') return '等待独立复核';
    return '等待后续任务或最终整合';
  }
  if (task.state === 'blocked') return '由协调伙伴处理阻塞或重新分配';
  if (task.state === 'failed') return '由协调伙伴决定修复或重新分配';
  if (task.state === 'cancelled') return '已停止，不再继续';
  if (node.dependencyIds.length) return '前置任务完成后开始';
  return `由 ${participantLabel(task.currentOwnerParticipantId, labels)} 接手`;
}

function taskHoldReason(
  node: TaskGraphNode,
  labels: Record<string, string>,
): string {
  const { task } = node;
  if (task.state === 'blocked' || task.state === 'failed') {
    if (node.progress && ['waiting', 'failed', 'aborted'].includes(node.progress.status)) {
      return roomPublicActivityText(roomParticipantPublicProgressSummary(node.progress))
        || '具体原因尚未公开';
    }
    return '具体原因尚未公开';
  }
  if (node.dependencyIds.length && ['pending', 'waiting'].includes(task.state)) {
    const dependencyOwners = node.dependencyOwnerParticipantIds.map((participantId) => (
      participantLabel(participantId, labels)
    ));
    return dependencyOwners.length
      ? `等待 ${dependencyOwners.join('、')} 完成前置任务`
      : `等待 ${node.dependencyIds.length} 项前置任务`;
  }
  const waitingDispatch = latestDispatch(node.dispatches, ['retry_wait', 'timer_wait', 'unknown']);
  if (waitingDispatch?.state === 'retry_wait') return '等待下一次执行';
  if (waitingDispatch?.state === 'timer_wait') return '等待计划时间到达';
  if (waitingDispatch?.state === 'unknown') return '等待确认上一次执行是否结束';
  return '';
}

function taskVerification(task: RoomTaskV3, dispatches: RoomDispatchEnvelopeV2[]): TaskVerification {
  if (task.state === 'blocked' || task.state === 'failed' || task.state === 'cancelled') {
    return { state: 'attention', label: '未通过验收' };
  }
  if (task.reviewState === 'changes_requested') return { state: 'attention', label: '复核未通过，等待修改' };
  if (task.reviewState === 'accepted') return { state: 'verified', label: '独立复核已通过' };
  if (task.reviewState === 'in_review' || task.state === 'review') return { state: 'checking', label: '正在独立复核' };
  if (task.reviewState === 'required') return { state: 'waiting', label: '等待独立复核' };
  if (task.state === 'completed') {
    return task.contextEvidenceRefs.length
      ? {
          state: 'checking',
          label: `已记录 ${task.contextEvidenceRefs.length} 项验证证据，等待验收`,
        }
      : { state: 'attention', label: '任务已完成，缺少验证记录' };
  }
  if (dispatches.some((dispatch) => dispatch.state === 'committed')) {
    return { state: 'checking', label: '结果已回传，等待验收' };
  }
  return { state: 'waiting', label: '尚未验证' };
}

function latestDispatch(
  dispatches: RoomDispatchEnvelopeV2[],
  states: RoomDispatchEnvelopeV2['state'][],
): RoomDispatchEnvelopeV2 | undefined {
  let latest: RoomDispatchEnvelopeV2 | undefined;
  for (const dispatch of dispatches) {
    if (!states.includes(dispatch.state)) continue;
    if (!latest || dispatch.attempt >= latest.attempt) latest = dispatch;
  }
  return latest;
}


function taskStageLabel(node: TaskGraphNode): string {
  if (node.task.taskKind === 'review') return '复核任务';
  if (node.column === 3) return '接续 / 整合任务';
  if (node.task.taskKind === 'invitation') return '邀请任务';
  return '任务目标';
}

function taskFlowState(state: RoomTaskV3['state']): FlowVisualState {
  if (state === 'completed') return 'complete';
  if (state === 'blocked' || state === 'failed') return 'attention';
  if (state === 'cancelled') return 'cancelled';
  if (state === 'active' || state === 'review') return 'active';
  return 'waiting';
}

function rootFlowState(root: RootProjection): FlowVisualState {
  if (root.isFinal && root.state === 'completed') return 'complete';
  if (root.state === 'blocked' || root.state === 'failed' || root.state === 'cancelled_with_unknowns') return 'attention';
  if (root.state === 'cancelled') return 'cancelled';
  if (root.state === 'running' || root.state === 'cancelling') return 'active';
  return 'waiting';
}

function taskStateLabel(state: RoomTaskV3['state']): string {
  return ({
    pending: '待开始',
    active: '执行中',
    review: '复核中',
    waiting: '等待前置任务',
    blocked: '已阻塞',
    completed: '已完成',
    failed: '未完成',
    cancelled: '已停止',
  } as const)[state];
}

function taskNodeStateLabel(node: TaskGraphNode): string {
  if (node.task.state === 'pending') return '等待开始';
  if (node.task.state === 'waiting') {
    return node.dependencyIds.length ? '等待前置工作' : '等待继续';
  }
  return taskStateLabel(node.task.state);
}

function dispatchIntentLabel(intent: RoomDispatchEnvelopeV2['intentKind']): string {
  return ({
    align: '理解需求',
    execute: '执行当前任务',
    review: '复核交付结果',
    revise: '按意见修改',
    resume: '继续当前任务',
    retry: '重新执行',
    wake: '恢复当前任务',
    callback: '回传任务结果',
    close: '整理并交付结果',
  } as const)[intent];
}

function rootFinalLabel(root: RootProjection): string {
  if (root.isFinal && root.state === 'completed') return '共同结果已完成';
  if (root.state === 'blocked') return '等待处理阻塞';
  if (root.state === 'failed') return '共同工作未完成';
  if (root.state === 'cancelled' || root.state === 'cancelled_with_unknowns') return '共同工作已停止';
  return '等待共同结果';
}

function rootStateLabel(root: RootProjection): string {
  if (root.isFinal && root.state === 'completed') return '已验证';
  if (root.state === 'blocked') return '已阻塞';
  if (root.state === 'failed') return '未完成';
  if (root.state === 'cancelled') return '已停止';
  if (root.state === 'cancelled_with_unknowns') return '停止待确认';
  if (root.state === 'cancelling') return '正在停止';
  if (root.state === 'running') return '推进中';
  return '等待开始';
}

function participantLabel(participantId: string, labels: Record<string, string>): string {
  return labels[participantId] || '协作伙伴';
}
