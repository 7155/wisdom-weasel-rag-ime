import {
  Bot,
  CircleAlert,
  CircleCheck,
  Clock3,
  ExternalLink,
  FolderOpen,
  GitBranch,
  ListChecks,
  ShieldCheck,
} from 'lucide-react';
import type { CSSProperties, ReactNode } from 'react';

import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import { subagentStateLabel } from '@/features/agent/status/subagent-presentation';
import type { RoomExecutionOverviewItem } from './runtime/room-execution-lanes';
import type { RoomSummary, RoomWorkItem, RoomWorkState } from './room-types';
import {
  type RoomTaskSessionFact,
  useRoomTaskSessionFacts,
} from './use-room-task-session-facts';

type TaskGraphState = 'waiting' | 'active' | 'review' | 'complete' | 'attention' | 'cancelled';
type TaskGraphColumn = 2 | 3;

type TaskGraphNode = {
  id: string;
  label: string;
  detail: string;
  detailRows: TaskGraphDetailRow[];
  acceptanceCriteria: string[];
  state: TaskGraphState;
  column: TaskGraphColumn;
  row: number;
  parentId: string;
  participantId: string;
  participantName: string;
  sessionId: string;
  workspaceRoots: string[];
  evidenceRefs: string[];
  artifactRefs: string[];
};

type TaskGraphDetailRow = {
  label: string;
  value: string;
};

type TaskGraphPoint = { left: number; right: number; y: number };
type TaskGraphEdge = {
  id: string;
  from: { x: number; y: number };
  to: { x: number; y: number };
  state: TaskGraphState;
};

const FLOW_ROW_HEIGHT = 116;
const COLUMN_BOUNDS: Record<TaskGraphColumn, { left: number; right: number }> = {
  2: { left: 205, right: 485 },
  3: { left: 515, right: 795 },
};

export function RoomTaskGraph({
  room,
  runtimeWorkItems,
}: {
  room: RoomSummary;
  runtimeWorkItems: readonly RoomExecutionOverviewItem[];
}) {
  const nodes = buildTaskGraphNodes(room, runtimeWorkItems);
  const sessionFacts = useRoomTaskSessionFacts(nodes.map((node) => node.sessionId));
  if (!nodes.length) {
    return <section aria-label="任务状态" aria-live="polite" className="room-task-flow__empty">
      <GitBranch aria-hidden="true" size={20} />
      <span>
        <strong>还没有实际分工</strong>
        <small>在“对话”里发送目标后，这里才会显示真实的分工和进度。</small>
      </span>
    </section>;
  }
  const rowCount = Math.max(
    1,
    nodes.filter((node) => node.column === 2).length,
    nodes.filter((node) => node.column === 3).length,
  );
  const graphHeight = rowCount * FLOW_ROW_HEIGHT;
  const points = new Map(nodes.map((node) => [node.id, taskGraphPoint(node)]));
  const edges = taskGraphEdges(nodes, points, graphHeight / 2);
  const completeCount = nodes.filter((node) => node.state === 'complete').length;
  const finalState = taskGraphFinalState(nodes);
  const goal = taskGraphGoal(room, runtimeWorkItems);
  const canvasStyle = {
    '--room-task-flow-height': `${graphHeight}px`,
    '--room-task-flow-row-count': rowCount,
  } as CSSProperties;

  return <section aria-label="任务图" aria-live="polite" className="room-task-flow" data-root-state={finalState}>
    <header className="room-task-flow__header">
      <span>
        <strong>任务图</strong>
        <small>显示共同目标、实际分工、接续关系和结果状态；没有关系数据时不会猜测依赖。</small>
      </span>
      <div
        aria-label={`${nodes.length} 项工作，${completeCount} 项已完成`}
        aria-valuemax={nodes.length}
        aria-valuemin={0}
        aria-valuenow={completeCount}
        className="room-task-flow__overall-progress"
        role="progressbar"
      >
        <span aria-hidden="true"><i style={{ transform: `scaleX(${completeCount / nodes.length})` }} /></span>
        <b>{completeCount} / {nodes.length} 已完成</b>
      </div>
    </header>

    <ul aria-label="任务状态图例" className="room-task-flow__state-legend">
      <li data-state="complete">已完成</li>
      <li data-state="active">正在执行</li>
      <li data-state="review">正在复核</li>
      <li data-state="waiting">等待开始</li>
      <li data-state="attention">需要处理</li>
    </ul>

    <div aria-hidden="true" className="room-task-flow__stage-labels">
      <span><GitBranch size={14} />共同目标</span>
      <span><ListChecks size={14} />分工</span>
      <span><ShieldCheck size={14} />接续 / 复核</span>
      <span><CircleCheck size={14} />结果</span>
    </div>

    <div className="room-task-flow__canvas" style={canvasStyle}>
      <svg aria-hidden="true" className="room-task-flow__edges" preserveAspectRatio="none" viewBox={`0 0 1000 ${graphHeight}`}>
        {edges.map((edge) => <g data-state={edge.state} key={edge.id}>
          <path d={edgePath(edge)} />
        </g>)}
      </svg>

      <FlowNode
        className="room-task-flow__root-node"
        detail={`已投影 ${nodes.length} 项实际工作`}
        icon={<GitBranch size={16} />}
        label={goal}
        state="complete"
        stateLabel="目标已确认"
        style={{ gridRow: `1 / span ${rowCount}` }}
      />

      {nodes.map((node) => <article
        aria-label={`${node.label}，${taskGraphStateLabel(node.state)}`}
        className="room-task-flow__task-node"
        data-state={node.state}
        data-task-stage={node.column === 3 ? '接续 / 复核' : '分工'}
        key={node.id}
        style={{ gridColumn: node.column, gridRow: node.row }}
        title={node.detail}
      >
        <header>
          <small>{node.column === 3 ? '接续 / 复核' : '分工'}</small>
          <strong>{node.label}</strong>
        </header>
        <span className="room-task-flow__task-detail">{taskGraphStateIcon(node.state)}<small>{node.detail}</small></span>
        <i>{taskGraphStateLabel(node.state)}</i>
      </article>)}

      <FlowNode
        className="room-task-flow__result-node"
        detail={taskGraphResultDetail(nodes, finalState)}
        icon={<CircleCheck size={16} />}
        label={taskGraphResultLabel(nodes, finalState)}
        state={finalState}
        stateLabel={taskGraphStateLabel(finalState)}
        style={{ gridRow: `1 / span ${rowCount}` }}
      />
    </div>

    <section aria-label="分工与进度" className="room-task-flow__work-details">
      <header>
        <strong>分工与进度</strong>
        <small>只显示 Runtime 或 WorkItem 已经记录的事实。</small>
      </header>
      <div>
        {nodes.map((node) => <article className="room-task-flow__work-card" data-state={node.state} key={node.id}>
          <header>
            <span>
              <small>{node.column === 3 ? '接续 / 复核' : '分工'}</small>
              <strong>{node.label}</strong>
            </span>
            <i>{taskGraphStateLabel(node.state)}</i>
          </header>
          {node.detailRows.length ? <dl>
            {node.detailRows.map((row) => <div key={`${node.id}:${row.label}`}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>)}
          </dl> : null}
          {node.acceptanceCriteria.length ? <section aria-label={`${node.label}的验收标准`}>
            <strong>验收</strong>
            <ul>{node.acceptanceCriteria.map((criterion) => <li key={criterion}>{criterion}</li>)}</ul>
          </section> : null}
          {node.workspaceRoots.length ? <section aria-label={`${node.label}的工作目录`} className="room-task-flow__workspaces">
            <strong><FolderOpen aria-hidden="true" size={14} />工作目录</strong>
            <ul>{node.workspaceRoots.map((path) => <li key={path}><code>{path}</code></li>)}</ul>
          </section> : null}
          <TaskSessionDetails
            fact={sessionFacts.get(node.sessionId)}
            participantName={node.participantName}
            sessionId={node.sessionId}
          />
          <TaskReferenceList label="证据" references={node.evidenceRefs} />
          <TaskReferenceList label="产物" references={node.artifactRefs} />
        </article>)}
      </div>
    </section>
  </section>;
}

function TaskSessionDetails({
  fact,
  participantName,
  sessionId,
}: {
  fact?: RoomTaskSessionFact;
  participantName: string;
  sessionId: string;
}) {
  if (!sessionId) return null;
  const counts = fact?.workflow?.todo.counts;
  const openTasks = fact?.workflow?.todo.phases
    .flatMap((phase) => phase.tasks)
    .filter((task) => task.status !== 'completed' && task.status !== 'abandoned')
    .slice(0, 4) ?? [];
  return <section aria-label={`${participantName || sessionId}的 Session 运行详情`} className="room-task-flow__session-facts">
    <header>
      <strong>Session 运行</strong>
      <a
        aria-label={`打开${participantName || sessionId}的对话`}
        href={`#/agent?session=${encodeURIComponent(sessionId)}`}
      >打开对话<ExternalLink aria-hidden="true" size={13} /></a>
    </header>
    {fact?.status === 'loading' ? <small>正在读取 Todo 与 Tool Agent…</small> : null}
    {fact?.status === 'unavailable' ? <small role="status">Session 运行详情暂时无法读取。</small> : null}
    {counts?.total ? <div className="room-task-flow__todo-facts">
      <strong>Todo {counts.completed} / {counts.total}</strong>
      {openTasks.length ? <ul>{openTasks.map((task) => <li key={`${task.status}:${task.content}`}>
        <span>{task.content}</span><i>{todoTaskStateLabel(task.status)}</i>
      </li>)}</ul> : <small>本轮 Todo 已收束。</small>}
    </div> : null}
    {fact?.subagents.length ? <div className="room-task-flow__subagent-facts">
      {fact.subagents.slice(0, 4).map((run) => <SubagentFact key={run.id} run={run} />)}
    </div> : null}
    {fact && fact.status !== 'loading' && !counts?.total && !fact.subagents.length
      ? <small>当前 Session 尚无 Todo 或 Tool Agent。</small>
      : null}
  </section>;
}

function SubagentFact({ run }: { run: AgentSubagentRunV1 }) {
  return <article>
    <Bot aria-hidden="true" size={14} />
    <span><strong>{run.task}</strong><small>Tool Agent · {subagentStateLabel(run)}</small></span>
    {run.childSessionId ? <a
      aria-label={`打开 Tool Agent 对话：${run.task}`}
      href={`#/agent?session=${encodeURIComponent(run.childSessionId)}`}
    ><ExternalLink aria-hidden="true" size={13} /></a> : null}
  </article>;
}

function TaskReferenceList({
  label,
  references,
}: {
  label: '证据' | '产物';
  references: readonly string[];
}) {
  if (!references.length) return null;
  return <section aria-label={`${label}引用`} className="room-task-flow__references">
    <strong>{label}</strong>
    <ul>{references.map((reference) => <li key={reference}><code>{reference}</code></li>)}</ul>
  </section>;
}

function FlowNode({
  className,
  detail,
  icon,
  label,
  state,
  stateLabel,
  style,
}: {
  className: string;
  detail: string;
  icon: ReactNode;
  label: string;
  state: TaskGraphState;
  stateLabel: string;
  style: CSSProperties;
}) {
  return <article className={`room-task-flow__node ${className}`} data-state={state} style={style}>
    <span aria-hidden="true" className="room-task-flow__node-icon">{icon}</span>
    <span className="room-task-flow__node-copy"><small>{detail}</small><strong>{label}</strong></span>
    <i>{stateLabel}</i>
  </article>;
}

export function buildTaskGraphNodes(
  room: RoomSummary,
  runtimeWorkItems: readonly RoomExecutionOverviewItem[],
): TaskGraphNode[] {
  const runtimeByTurnId = new Map(runtimeWorkItems.map((work) => [work.id, work]));
  const consumedRuntimeIds = new Set<string>();
  const nodes: Omit<TaskGraphNode, 'row'>[] = [];

  for (const work of room.workItems ?? []) {
    const runtime = runtimeByTurnId.get(work.rootTurnId);
    if (runtime) consumedRuntimeIds.add(runtime.id);
    const participantId = work.currentOwnerParticipantId || work.offeredToParticipantId;
    const participant = room.participants.find((candidate) => candidate.id === participantId);
    nodes.push({
      id: work.id,
      label: work.objective,
      detail: registeredWorkDetail(room, work, runtime),
      detailRows: registeredWorkDetailRows(room, work, runtime),
      acceptanceCriteria: work.acceptanceCriteria.filter((criterion) => criterion.trim()),
      state: registeredWorkState(work.state),
      column: work.depth > 1 || Boolean(work.parentWorkId) || work.state === 'review' ? 3 : 2,
      parentId: work.parentWorkId,
      participantId,
      participantName: participant?.displayName.trim() || participantId,
      sessionId: participant?.sessionId.trim() || runtime?.sessionIds[0] || '',
      workspaceRoots: uniqueStrings(room.workspaceRoots ?? []),
      evidenceRefs: uniqueStrings(work.evidenceRefs),
      artifactRefs: uniqueStrings(work.artifactRefs),
    });
  }

  for (const work of runtimeWorkItems) {
    if (consumedRuntimeIds.has(work.id)) continue;
    const participantId = work.participantIds[0] ?? '';
    const participant = room.participants.find((candidate) => candidate.id === participantId);
    nodes.push({
      id: work.id,
      label: work.objective,
      detail: runtimeWorkDetail(work),
      detailRows: runtimeWorkDetailRows(room, work),
      acceptanceCriteria: [],
      state: runtimeWorkState(work.status),
      column: 2,
      parentId: '',
      participantId,
      participantName: participant?.displayName.trim() || participantId,
      sessionId: work.sessionIds[0] || participant?.sessionId.trim() || '',
      workspaceRoots: uniqueStrings(room.workspaceRoots ?? []),
      evidenceRefs: [],
      artifactRefs: [],
    });
  }

  const rowByColumn = new Map<TaskGraphColumn, number>();
  return nodes.map((node) => {
    const row = (rowByColumn.get(node.column) ?? 0) + 1;
    rowByColumn.set(node.column, row);
    return { ...node, row };
  });
}

function taskGraphEdges(
  nodes: readonly TaskGraphNode[],
  points: ReadonlyMap<string, TaskGraphPoint>,
  midpoint: number,
): TaskGraphEdge[] {
  if (!nodes.length) return [{
    id: 'goal:result',
    from: { x: 170, y: midpoint },
    to: { x: 830, y: midpoint },
    state: 'waiting',
  }];

  const ids = new Set(nodes.map((node) => node.id));
  const childCounts = new Map<string, number>();
  const edges: TaskGraphEdge[] = [];
  for (const node of nodes) {
    const point = points.get(node.id)!;
    const parentPoint = node.parentId && ids.has(node.parentId) ? points.get(node.parentId) : undefined;
    if (parentPoint) {
      childCounts.set(node.parentId, (childCounts.get(node.parentId) ?? 0) + 1);
      edges.push({
        id: `${node.parentId}:${node.id}`,
        from: { x: parentPoint.right, y: parentPoint.y },
        to: { x: point.left, y: point.y },
        state: node.state,
      });
    } else {
      edges.push({
        id: `goal:${node.id}`,
        from: { x: 170, y: midpoint },
        to: { x: point.left, y: point.y },
        state: node.state,
      });
    }
  }
  for (const node of nodes.filter((candidate) => !childCounts.has(candidate.id))) {
    const point = points.get(node.id)!;
    edges.push({
      id: `${node.id}:result`,
      from: { x: point.right, y: point.y },
      to: { x: 830, y: midpoint },
      state: node.state,
    });
  }
  return edges;
}

function taskGraphPoint(node: TaskGraphNode): TaskGraphPoint {
  const bounds = COLUMN_BOUNDS[node.column];
  return {
    ...bounds,
    y: (node.row - 0.5) * FLOW_ROW_HEIGHT,
  };
}

function edgePath(edge: TaskGraphEdge): string {
  const distance = Math.max(30, (edge.to.x - edge.from.x) * 0.52);
  return `M ${edge.from.x} ${edge.from.y} C ${edge.from.x + distance} ${edge.from.y}, ${edge.to.x - distance} ${edge.to.y}, ${edge.to.x} ${edge.to.y}`;
}

function taskGraphGoal(room: RoomSummary, runtimeWorkItems: readonly RoomExecutionOverviewItem[]): string {
  const topic = room.topics?.find((item) => item.id === room.activeTopicId);
  return topic?.summary.trim()
    || room.workItems?.find((work) => !work.parentWorkId)?.objective.trim()
    || runtimeWorkItems.at(-1)?.objective.trim()
    || room.description?.trim()
    || room.title;
}

function registeredWorkDetail(
  room: RoomSummary,
  work: RoomWorkItem,
  runtime?: RoomExecutionOverviewItem,
): string {
  const owner = roomParticipantName(room, work.currentOwnerParticipantId || work.offeredToParticipantId);
  const runtimeDetail = runtime
    ? ` · ${runtime.participantIds.length || 1} 位伙伴${runtime.toolCount ? ` · ${runtime.toolCount} 个工具步骤` : ''}`
    : '';
  return `${owner || '待接收'}${runtimeDetail}${work.resultSummary ? ` · ${work.resultSummary}` : ''}`;
}

function runtimeWorkDetail(work: RoomExecutionOverviewItem): string {
  return `${work.participantIds.length || 1} 位伙伴${work.toolCount ? ` · ${work.toolCount} 个工具步骤` : ''}${work.lastSummary ? ` · ${work.lastSummary}` : ''}`;
}

function registeredWorkDetailRows(
  room: RoomSummary,
  work: RoomWorkItem,
  runtime?: RoomExecutionOverviewItem,
): TaskGraphDetailRow[] {
  const rows: TaskGraphDetailRow[] = [];
  const owner = roomParticipantName(room, work.currentOwnerParticipantId || work.offeredToParticipantId);
  const accountable = roomParticipantName(room, work.accountableParticipantId);
  if (owner) rows.push({ label: '负责', value: owner });
  if (accountable) rows.push({ label: '复核', value: accountable });
  rows.push({ label: '进度', value: taskGraphStateLabel(registeredWorkState(work.state)) });
  if (work.expectedOutput.trim()) rows.push({ label: '交付', value: work.expectedOutput.trim() });
  if (runtime?.participantIds.length) {
    rows.push({ label: '参与', value: runtimeParticipantNames(room, runtime.participantIds) });
  }
  if (runtime?.toolCount) rows.push({ label: '工具', value: `${runtime.toolCount} 个步骤` });
  if (runtime?.lastSummary.trim()) rows.push({ label: '最新', value: runtime.lastSummary.trim() });
  if (work.revision > 0) rows.push({ label: '修订', value: `第 ${work.revision} 次修订` });
  if (work.resultSummary.trim()) rows.push({ label: '结果', value: work.resultSummary.trim() });
  const blocker = recordText(work.blocker, 'reason');
  if (blocker) rows.push({ label: '阻塞', value: blocker });
  const receipts = [
    work.evidenceRefs.length ? `${work.evidenceRefs.length} 条证据` : '',
    work.artifactRefs.length ? `${work.artifactRefs.length} 个产物` : '',
  ].filter(Boolean).join(' · ');
  if (receipts) rows.push({ label: '凭据', value: receipts });
  return rows;
}

function runtimeWorkDetailRows(
  room: RoomSummary,
  work: RoomExecutionOverviewItem,
): TaskGraphDetailRow[] {
  const rows: TaskGraphDetailRow[] = [];
  if (work.participantIds.length) {
    rows.push({ label: '负责', value: runtimeParticipantNames(room, work.participantIds) });
  }
  rows.push({ label: '进度', value: taskGraphStateLabel(runtimeWorkState(work.status)) });
  if (work.laneCount) rows.push({ label: '执行', value: `${work.laneCount} 条执行线` });
  if (work.toolCount) rows.push({ label: '工具', value: `${work.toolCount} 个步骤` });
  if (work.lastSummary.trim()) rows.push({ label: '最新', value: work.lastSummary.trim() });
  return rows;
}

function roomParticipantName(room: RoomSummary, participantId: string): string {
  if (!participantId) return '';
  return room.participants.find((participant) => participant.id === participantId)?.displayName.trim() || participantId;
}

function runtimeParticipantNames(room: RoomSummary, participantIds: readonly string[]): string {
  return participantIds.map((participantId) => roomParticipantName(room, participantId)).filter(Boolean).join('、');
}

function recordText(value: Record<string, unknown>, key: string): string {
  const candidate = value[key];
  return typeof candidate === 'string' ? candidate.trim() : '';
}

function uniqueStrings(values: readonly string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function todoTaskStateLabel(state: 'pending' | 'in_progress' | 'blocked' | 'completed' | 'abandoned'): string {
  return ({
    pending: '等待开始',
    in_progress: '进行中',
    blocked: '已阻塞',
    completed: '已完成',
    abandoned: '已放弃',
  })[state];
}

function registeredWorkState(state: RoomWorkState): TaskGraphState {
  return ({
    queued: 'waiting',
    active: 'active',
    review: 'review',
    blocked: 'attention',
    done: 'complete',
    failed: 'attention',
    cancelled: 'cancelled',
  } satisfies Record<RoomWorkState, TaskGraphState>)[state];
}

function runtimeWorkState(state: RoomExecutionOverviewItem['status']): TaskGraphState {
  return ({
    queued: 'waiting',
    running: 'active',
    completed: 'complete',
    failed: 'attention',
    aborted: 'cancelled',
  } satisfies Record<RoomExecutionOverviewItem['status'], TaskGraphState>)[state];
}

function taskGraphFinalState(nodes: readonly TaskGraphNode[]): TaskGraphState {
  if (!nodes.length) return 'waiting';
  if (nodes.some((node) => node.state === 'attention')) return 'attention';
  if (nodes.some((node) => node.state === 'active')) return 'active';
  if (nodes.some((node) => node.state === 'review')) return 'review';
  if (nodes.every((node) => ['complete', 'cancelled'].includes(node.state))) return 'complete';
  return 'waiting';
}

function taskGraphResultLabel(nodes: readonly TaskGraphNode[], state: TaskGraphState): string {
  if (!nodes.length) return '等待任务拆分';
  if (state === 'complete') return '协作结果已收束';
  if (state === 'attention') return '处理阻塞后继续';
  if (state === 'review') return '等待复核结论';
  return '等待工作汇合';
}

function taskGraphResultDetail(nodes: readonly TaskGraphNode[], state: TaskGraphState): string {
  if (!nodes.length) return '主持伙伴拆分工作后，这里会显示真实进度';
  if (state === 'complete') return `${nodes.length} 项工作已到达终态`;
  if (state === 'attention') return '至少一项工作需要处理';
  return '所有叶子工作完成后形成结果';
}

function taskGraphStateLabel(state: TaskGraphState): string {
  return {
    waiting: '等待开始',
    active: '正在执行',
    review: '正在复核',
    complete: '已完成',
    attention: '需要处理',
    cancelled: '已停止',
  }[state];
}

function taskGraphStateIcon(state: TaskGraphState): ReactNode {
  if (state === 'complete') return <CircleCheck aria-hidden="true" size={15} />;
  if (state === 'attention') return <CircleAlert aria-hidden="true" size={15} />;
  return <Clock3 aria-hidden="true" size={15} />;
}
