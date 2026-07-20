import { GitBranch, ListTodo, RadioTower } from 'lucide-react';
import type { RootProjection } from '@/contracts/room-kernel-reducer';
import type { RoomDispatchProjectionFixture, RoomTaskProjectionFixture } from './capability-center-fixtures';
import './capability-center.css';

export function RoomExecutionTopology({
  dispatchesByRootId,
  roots,
  tasksByRootId,
}: {
  roots: Array<Pick<RootProjection, 'rootId' | 'generation' | 'state' | 'isFinal'>>;
  tasksByRootId: Record<string, RoomTaskProjectionFixture[]>;
  dispatchesByRootId: Record<string, RoomDispatchProjectionFixture[]>;
}) {
  return <section className="room-execution-topology" aria-label="Root Task Dispatch 拓扑">
    <header><span><GitBranch size={15} /><strong>执行拓扑</strong></span><small>Root / Task / Dispatch 分层投影</small></header>
    {roots.map((root) => <article key={`${root.rootId}:${root.generation}`}>
      <header><span><small>Root · generation {root.generation}</small><strong>{root.rootId}</strong></span><i data-state={root.state}>{root.state}{root.isFinal ? ' · final receipt' : ''}</i></header>
      <div className="room-execution-topology__lanes">
        <section aria-label={`${root.rootId} Tasks`}><header><ListTodo size={13} /><strong>Tasks</strong></header>{(tasksByRootId[root.rootId] ?? []).map((task) => <div key={task.taskId}><span><strong>{task.title}</strong><small>{task.taskId}</small></span><i>{task.state}</i><b>{task.receiptId}</b></div>)}</section>
        <section aria-label={`${root.rootId} Dispatches`}><header><RadioTower size={13} /><strong>Dispatches</strong></header>{(dispatchesByRootId[root.rootId] ?? []).map((dispatch) => <div key={dispatch.dispatchId}><span><strong>{dispatch.targetSessionId}</strong><small>{dispatch.dispatchId} · attempt {dispatch.attempt}</small></span><i>{dispatch.state}</i><b>{dispatch.receiptId}</b></div>)}</section>
      </div>
    </article>)}
  </section>;
}
