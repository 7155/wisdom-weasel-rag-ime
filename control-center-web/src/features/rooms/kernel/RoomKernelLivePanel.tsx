import { CircleAlert, Workflow } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, EmptyState } from '@/components/primitives';
import type { RoomEventEnvelopeV2 } from '@/contracts/generated/room-event-envelope.v2';
import {
  applyRoomKernelSnapshot,
  createRoomKernelProjection,
  reduceRoomKernelEvent,
  type RoomKernelProjection,
  type RoomKernelSnapshot,
  type CancellationSurfaceProjection,
} from '@/contracts/room-kernel-reducer';
import { parseContract } from '@/contracts/validators';
import { useOptionalControlTransport } from '@/app/control-transport';
import { RoomKernelControlPlane } from './RoomKernelControlPlane';
import { parseRoomRequirementsReadProjection, type RoomRequirementsReadProjection } from '../requirements/room-requirements-read-model';
import { createControlRoomKernelCommandTransport } from './room-kernel-command-transport';
import { evaluateRoomKernelControlGate, type RoomKernelControlGate } from './room-kernel-control-gate';

type LiveState = 'loading' | 'synced' | 'reconnecting' | 'recovering' | 'denied' | 'error';

export function RoomKernelLivePanel({
  participantLabels = {},
  roomId,
}: {
  participantLabels?: Record<string, string>;
  roomId: string;
}) {
  const transport = useOptionalControlTransport();
  const [projection, setProjection] = useState<RoomKernelProjection | null>(null);
  const [requirementsByRootId, setRequirementsByRootId] = useState<Record<string, RoomRequirementsReadProjection>>({});
  const projectionRef = useRef<RoomKernelProjection | null>(null);
  const [controlGate, setControlGate] = useState<RoomKernelControlGate | null>(null);
  const [liveState, setLiveState] = useState<LiveState>('loading');
  const [recoveryRequest, setRecoveryRequest] = useState(0);
  const [detail, setDetail] = useState('正在验证任务状态');
  const commandTransport = useMemo(
    () => transport ? createControlRoomKernelCommandTransport(transport) : null,
    [transport],
  );

  useEffect(() => {
    if (!transport) {
      setProjection(null);
      setRequirementsByRootId({});
      projectionRef.current = null;
      setControlGate(null);
      setLiveState('denied');
      setDetail('当前连接不能读取任务状态');
      return;
    }
    let active = true;
    let unsubscribe: (() => void) | undefined;
    let snapshotController: AbortController | undefined;
    let revision = 0;
    let recoveryQueued = false;

    const recover = () => {
      if (!active || recoveryQueued) return;
      recoveryQueued = true;
      queueMicrotask(() => {
        recoveryQueued = false;
        if (active) void loadSnapshot();
      });
    };

    const loadSnapshot = async () => {
      const currentRevision = ++revision;
      unsubscribe?.();
      unsubscribe = undefined;
      snapshotController?.abort();
      snapshotController = new AbortController();
      setLiveState((current) => current === 'loading' ? 'loading' : 'recovering');
      setDetail((current) => current === '正在验证任务状态' ? current : '正在恢复任务状态');
      try {
        const raw = await transport.request({
          pathId: 'agent.room.kernel.snapshot',
          params: { roomId },
          signal: snapshotController.signal,
        });
        if (!active || currentRevision !== revision) return;
        const snapshot = parseSnapshot(raw, roomId);
        setRequirementsByRootId(parseRequirementsByRootId(raw));
        const next = applyRoomKernelSnapshot(createRoomKernelProjection(roomId), snapshot);
        projectionRef.current = next;
        setProjection(next);
        setLiveState('synced');
        setDetail('任务状态已更新');
        unsubscribe = transport.subscribe<unknown>(
          {
            pathId: 'agent.room.kernel.events',
            params: { roomId },
            lastEventId: `${roomId}#${next.lastSequence}`,
          },
          {
            open: () => {
              if (!active) return;
              setLiveState('synced');
              setDetail('任务进度已连接');
            },
            next: (value) => {
              if (!active || isSnapshotRequired(value)) return;
              try {
                const event = parseContract('room-event-envelope.v2', value) as RoomEventEnvelopeV2;
                const current = projectionRef.current;
                if (!current) return;
                const reduced = reduceRoomKernelEvent(current, event);
                projectionRef.current = reduced.state;
                setProjection(reduced.state);
                if (reduced.disposition === 'snapshot-required') recover();
                if (reduced.disposition === 'applied') {
                  setLiveState('synced');
                  setDetail('任务状态已更新');
                }
              } catch (error) {
                setLiveState('error');
                setDetail(publicError(error, '任务进度格式无效'));
              }
            },
            error: (error) => {
              if (!active) return;
              setLiveState('reconnecting');
              setDetail(publicError(error, '任务进度连接中断'));
            },
            reconnect: (notice) => {
              if (!active) return;
              setLiveState('reconnecting');
              setDetail(`第 ${notice.attempt} 次重连 · ${notice.delayMs}ms`);
            },
            snapshotRequired: () => {
              if (!active) return;
              setLiveState('recovering');
              setDetail('任务进度存在缺口，正在恢复最新状态');
              recover();
            },
          },
        );
      } catch (error) {
        if (!active || currentRevision !== revision || isAbort(error)) return;
        const denied = errorStatus(error) === 401 || errorStatus(error) === 403;
        setLiveState(denied ? 'denied' : 'error');
        setDetail(denied
          ? '当前连接没有查看任务进度的权限'
          : '任务进度暂时不可用。已有对话和工作文件不会受影响。');
      }
    };

    const start = async () => {
      setProjection(null);
      projectionRef.current = null;
      setControlGate(null);
      setLiveState('loading');
      setDetail('正在验证任务状态');
      try {
        const gate = await evaluateRoomKernelControlGate(await transport.capabilities());
        if (!active) return;
        setControlGate(gate);
        if (!gate.readEnabled) {
          setLiveState('denied');
          setDetail(gate.reason);
          return;
        }
        await loadSnapshot();
      } catch (error) {
        if (!active) return;
        setLiveState('error');
        setDetail('任务进度暂时不可用。已有对话和工作文件不会受影响。');
      }
    };

    void start();
    return () => {
      active = false;
      revision += 1;
      snapshotController?.abort();
      unsubscribe?.();
    };
  }, [recoveryRequest, roomId, transport]);

  return <section className="room-kernel-live" aria-label="协作任务状态" data-live-state={liveState}>
    <p className="room-kernel-live__status" role={liveState === 'error' || liveState === 'denied' ? 'alert' : 'status'}>
      <strong>{liveStateLabel(liveState)}</strong><span>{detail}</span>
      {liveState === 'error' ? <Button onClick={() => setRecoveryRequest((current) => current + 1)} size="small" variant="quiet">重新读取</Button> : null}
    </p>
    {projection && Object.keys(projection.rootsById).length > 0 ? <RoomKernelControlPlane
      projection={projection}
      budgetsByRootId={{}}
      contextReceiptsByRootId={{}}
      capabilityReceiptsByRootId={capabilityReceipts(projection)}
      commandTransport={controlGate?.commandEnabled && commandTransport ? commandTransport : undefined}
      commandDisabledReason={controlGate?.reason}
      panicEnabled={controlGate?.panicEnabled === true}
      participantLabels={participantLabels}
      requirementsByRootId={requirementsByRootId}
    /> : liveState === 'error' ? <EmptyState
      description="检查点仍保留。修复连接或运行时问题后，可以从已确认状态继续。"
      icon={CircleAlert}
      title="任务进度暂时无法读取"
    /> : projection ? <EmptyState
      description="发送任务后，每位伙伴的接手、工具执行、交接和验收会在这里持续更新。"
      icon={Workflow}
      title="还没有任务"
    /> : null}
  </section>;
}

function parseRequirementsByRootId(value: unknown): Record<string, RoomRequirementsReadProjection> {
  const source = record(record(value).requirementsByRootId);
  return Object.fromEntries(Object.entries(source).map(([rootId, projection]) => {
    const parsed = parseRoomRequirementsReadProjection(projection);
    if (parsed.rootId !== rootId) throw new TypeError('Requirements projection key does not match Root');
    return [rootId, parsed];
  }));
}

function capabilityReceipts(projection: RoomKernelProjection) {
  return Object.values(projection.sessionsById).reduce<Record<string, {
    revision: string;
    status: 'sealed' | 'rejected';
    contentHash: string;
  }>>((result, session) => {
    const capability = session.capabilityManifest;
    if (!capability || !session.rootId) return result;
    result[session.rootId] = {
      revision: `${capability.manifestId} / epoch ${capability.capabilityEpoch}`,
      status: capability.status === 'active' ? 'sealed' : 'rejected',
      contentHash: `sha256:${capability.manifestHash}`,
    };
    return result;
  }, {});
}

export function parseSnapshot(value: unknown, roomId: string): RoomKernelSnapshot {
  const item = record(value);
  if (item.roomId !== roomId) throw new TypeError('Room Kernel snapshot belongs to another Room');
  if (!Number.isInteger(item.lastSequence) || Number(item.lastSequence) < 0) throw new TypeError('Room Kernel snapshot sequence is invalid');
  if (typeof item.snapshotHash !== 'string' || !/^sha256:[a-f0-9]{64}$/.test(item.snapshotHash)) {
    throw new TypeError('Room Kernel snapshot hash is invalid');
  }
  return {
    roomId,
    lastSequence: Number(item.lastSequence),
    snapshotHash: item.snapshotHash,
    roots: array(item.roots).map((entry) => parseContract('room-root-execution.v3', entry)),
    tasks: array(item.tasks).map((entry) => parseContract('room-task.v3', entry)),
    dispatches: array(item.dispatches).map((entry) => parseContract('room-dispatch-envelope.v2', entry)),
    posts: array(item.posts).map((entry) => parseContract('room-post.v2', entry)),
    sessions: array(item.sessions) as RoomKernelSnapshot['sessions'],
    receipts: array(item.receipts).map((entry) => parseContract('room-kernel-receipt.v1', entry)),
    cancellationSurfaces: array(item.cancellationSurfaces).map(parseCancellationSurface),
  };
}

function parseCancellationSurface(value: unknown): CancellationSurfaceProjection {
  const item = record(value);
  const surfaces = new Set(['provider', 'tool', 'exec', 'retry', 'compaction', 'branch_summary', 'timer', 'continuation', 'session']);
  const states = new Set(['requested', 'acknowledged', 'terminated', 'unknown']);
  if (!surfaces.has(String(item.surface)) || !states.has(String(item.state))) {
    throw new TypeError('Room cancellation surface is invalid');
  }
  return {
    cancelId: requiredText(item.cancelId, 'cancelId'),
    rootId: requiredText(item.rootId, 'rootId'),
    dispatchId: requiredText(item.dispatchId, 'dispatchId'),
    surface: item.surface as CancellationSurfaceProjection['surface'],
    state: item.state as CancellationSurfaceProjection['state'],
    targetRef: typeof item.targetRef === 'string' ? item.targetRef : '',
    detail: record(item.detail),
    updatedAtMs: nonNegativeInteger(item.updatedAtMs, 'updatedAtMs'),
  };
}

function isSnapshotRequired(value: unknown): boolean {
  const item = record(value);
  return item.reason === 'event_replay_gap' || item.eventType === 'snapshot_required';
}

function liveStateLabel(value: LiveState): string {
  return ({ loading: '正在同步', synced: '进度已同步', reconnecting: '正在重新连接', recovering: '正在恢复进度', denied: '当前不可查看', error: '进度同步异常' } as const)[value];
}

function errorStatus(error: unknown): number {
  return typeof error === 'object' && error !== null && 'status' in error && typeof error.status === 'number' ? error.status : 0;
}

function publicError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function array(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function requiredText(value: unknown, field: string): string {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text) throw new TypeError(`${field} is required`);
  return text;
}
function nonNegativeInteger(value: unknown, field: string): number {
  if (!Number.isInteger(value) || Number(value) < 0) throw new TypeError(`${field} is invalid`);
  return Number(value);
}
function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
