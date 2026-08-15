import {
  CircleAlert,
  CircleCheck,
  Clock3,
  GitBranch,
  ListChecks,
  ShieldCheck,
} from 'lucide-react';
import type { CSSProperties, ReactNode } from 'react';

import type { RoomExecutionOverviewItem } from './runtime/room-execution-lanes';
import type { RoomSummary, RoomWorkItem, RoomWorkState } from './room-types';

type TaskGraphState = 'waiting' | 'active' | 'review' | 'complete' | 'attention' | 'cancelled';
type TaskGraphColumn = 2 | 3;

type TaskGraphNode = {
  id: string;
  label: string;
  detail: string;
  state: TaskGraphState;
  column: TaskGraphColumn;
  row: number;
  parentId: string;
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
      {nodes.length ? <div
        aria-label={`${nodes.length} 项工作，${completeCount} 项已完成`}
        aria-valuemax={nodes.length}
        aria-valuemin={0}
        aria-valuenow={completeCount}
        className="room-task-flow__overall-progress"
        role="progressbar"
      >
        <span aria-hidden="true"><i style={{ transform: `scaleX(${completeCount / nodes.length})` }} /></span>
        <b>{completeCount} / {nodes.length}</b>
      </div> : <b>等待拆分任务</b>}
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
        detail={nodes.length ? `已投影 ${nodes.length} 项实际工作` : '等待主持伙伴从对话中拆分工作'}
        icon={<GitBranch size={16} />}
        label={goal}
        state={nodes.length ? 'complete' : 'waiting'}
        stateLabel={nodes.length ? '目标已确认' : '等待拆分'}
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
    nodes.push({
      id: work.id,
      label: work.objective,
      detail: registeredWorkDetail(room, work, runtime),
      state: registeredWorkState(work.state),
      column: work.depth > 1 || Boolean(work.parentWorkId) || work.state === 'review' ? 3 : 2,
      parentId: work.parentWorkId,
    });
  }

  for (const work of runtimeWorkItems) {
    if (consumedRuntimeIds.has(work.id)) continue;
    nodes.push({
      id: work.id,
      label: work.objective,
      detail: runtimeWorkDetail(work),
      state: runtimeWorkState(work.status),
      column: 2,
      parentId: '',
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
  const owner = room.participants.find((participant) => participant.id === work.currentOwnerParticipantId)?.displayName
    || '主持伙伴';
  const runtimeDetail = runtime
    ? ` · ${runtime.participantIds.length || 1} 位伙伴${runtime.toolCount ? ` · ${runtime.toolCount} 个工具步骤` : ''}`
    : '';
  return `${owner}${runtimeDetail}${work.resultSummary ? ` · ${work.resultSummary}` : ''}`;
}

function runtimeWorkDetail(work: RoomExecutionOverviewItem): string {
  return `${work.participantIds.length || 1} 位伙伴${work.toolCount ? ` · ${work.toolCount} 个工具步骤` : ''}${work.lastSummary ? ` · ${work.lastSummary}` : ''}`;
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
