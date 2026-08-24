import { ListChecks } from 'lucide-react';
import { useMemo } from 'react';

import type { RoomProjectionState } from '@/contracts/room-reducer';
import { Disclosure } from '@/components/primitives';
import { formatTime } from '@/features/overview/management-ui';
import { roomWorkStateLabel } from '@/features/rooms/room-presentation';
import { selectRoomExecutionOverview } from '@/features/rooms/runtime/room-execution-lanes';
import type { RoomSummary, RoomWorkItem, RoomWorkState } from '@/features/rooms/room-types';

export function PawRoomExecution({ projection, room }: {
  projection?: RoomProjectionState;
  room: RoomSummary;
}) {
  const runtimeItems = useMemo(() => projection ? selectRoomExecutionOverview(projection) : [], [projection]);
  const workItems = useMemo(() => [...(room.workItems ?? [])].sort((left, right) => (
    left.depth - right.depth || left.createdAtMs - right.createdAtMs
  )), [room.workItems]);
  const activeCount = workItems.length
    ? workItems.filter((item) => !['done', 'failed', 'cancelled'].includes(item.state)).length
    : runtimeItems.filter((item) => ['queued', 'running'].includes(item.status)).length;
  const participantName = (participantId: string) => room.participants.find((item) => item.id === participantId)?.displayName || '待分派';

  return <section aria-label="Room 任务流" className="paw-room-execution">
    <header className="paw-room-execution__summary">
      <span>{workItems.length ? `${workItems.length} 项任务` : `${runtimeItems.length} 个运行回合`}</span>
      <small>{activeCount ? `${activeCount} 项仍在推进` : workItems.length || runtimeItems.length ? '当前流转已收口' : '等待真实分派'}</small>
    </header>
    {workItems.length ? <ol aria-label="Room 任务拆解" className="paw-room-execution__list">
      {workItems.map((item) => <RoomExecutionWorkItem item={item} key={item.id} owner={participantName(item.currentOwnerParticipantId || item.accountableParticipantId)} />)}
    </ol> : runtimeItems.length ? <ol aria-label="Room 运行任务流" className="paw-room-execution__list">
      {runtimeItems.map((item) => <li data-depth="0" data-state={roomExecutionRuntimeState(item.status)} key={item.id}>
        <span aria-hidden="true" className="paw-room-execution__node"><i /></span>
        <article>
          <header><span>{item.participantIds.map(participantName).join(' · ') || 'Root'}</span><b>{roomExecutionRuntimeLabel(item.status)}</b></header>
          <strong>{item.objective}</strong>
          {item.lastSummary ? <p>{item.lastSummary}</p> : null}
          <footer><span>{item.laneCount} 条执行线 · {item.toolCount} 个工具步骤</span><time>{item.updatedAtMs ? formatTime(item.updatedAtMs) : ''}</time></footer>
        </article>
      </li>)}
    </ol> : <div className="paw-room-execution__empty"><ListChecks size={18} /><span><strong>还没有任务流</strong><small>发生分派或拆出任务后，这里会实时形成节点。</small></span></div>}
  </section>;
}

function RoomExecutionWorkItem({ item, owner }: { item: RoomWorkItem; owner: string }) {
  const detail = item.resultSummary.trim() || item.expectedOutput.trim();
  return <li data-depth={Math.min(3, Math.max(0, item.depth))} data-state={item.state}>
    <span aria-hidden="true" className="paw-room-execution__node"><i /></span>
    <article>
      <header><span>{owner}</span><b>{roomWorkStateLabel(item.state)}</b></header>
      <strong>{item.objective}</strong>
      {detail ? <p>{detail}</p> : null}
      <footer><span>任务 r{item.revision}</span><time>{item.updatedAtMs ? formatTime(item.updatedAtMs) : ''}</time></footer>
      {item.acceptanceCriteria.length ? (
        <Disclosure
          className="paw-room-execution__acceptance"
          summary={`验收条件 · ${item.acceptanceCriteria.length}`}
        >
          <ul>{item.acceptanceCriteria.map((criterion) => <li key={criterion}>{criterion}</li>)}</ul>
        </Disclosure>
      ) : null}
    </article>
  </li>;
}

function roomExecutionRuntimeState(status: 'queued' | 'running' | 'completed' | 'failed' | 'aborted'): RoomWorkState {
  return ({ queued: 'queued', running: 'active', completed: 'done', failed: 'failed', aborted: 'cancelled' })[status] as RoomWorkState;
}

function roomExecutionRuntimeLabel(status: 'queued' | 'running' | 'completed' | 'failed' | 'aborted'): string {
  return ({ queued: '待开始', running: '执行中', completed: '已完成', failed: '失败', aborted: '已停止' })[status];
}
