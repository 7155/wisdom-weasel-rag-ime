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
import { selectRoomParticipantPublicProgress } from '@/contracts/room-reducer';
import { parseContract } from '@/contracts/validators';
import { useOptionalControlTransport } from '@/app/control-transport';
import { RoomKernelControlPlane } from './RoomKernelControlPlane';
import { parseRoomRequirementsReadProjection, type RoomRequirementsReadProjection } from '../requirements/room-requirements-read-model';
import {
  useRoomLiveStore,
  type RoomKernelLiveState,
  type RoomKernelSyncProjection,
} from '../state/live-store';
import { createControlRoomKernelCommandTransport } from './room-kernel-command-transport';
import { evaluateRoomKernelControlGate, type RoomKernelControlGate } from './room-kernel-control-gate';


export function RoomKernelLivePanel({
  participantLabels = {},
  roomId,
  visible = true,
}: {
  participantLabels?: Record<string, string>;
  roomId: string;
  visible?: boolean;
}) {
  const transport = useOptionalControlTransport();
  const projection = useRoomLiveStore(
    (state) => visible ? state.kernelProjections[roomId] ?? null : null,
  );
  const sync = useRoomLiveStore(
    (state) => visible ? state.kernelSyncByRoomId[roomId] : undefined,
  );
  const publicProjection = useRoomLiveStore(
    (state) => visible ? state.projections[roomId] : undefined,
  );
  const participantProgress = useMemo(
    () => publicProjection
      ? selectRoomParticipantPublicProgress(publicProjection)
      : [],
    [publicProjection],
  );
  const [requirementsByRootId, setRequirementsByRootId] = useState<Record<string, RoomRequirementsReadProjection>>({});
  const projectionRef = useRef<RoomKernelProjection | null>(projection);
  const [controlGate, setControlGate] = useState<RoomKernelControlGate | null>(null);
  const [recoveryRequest, setRecoveryRequest] = useState(0);
  const commandTransport = useMemo(
    () => transport ? createControlRoomKernelCommandTransport(transport) : null,
    [transport],
  );
  const liveState = sync?.state ?? 'loading';
  const detail = sync?.detail ?? '正在验证任务状态';

  useEffect(() => {
    const store = useRoomLiveStore.getState();
    projectionRef.current = store.kernelProjections[roomId] ?? null;
    if (!transport) {
      setRequirementsByRootId({});
      setControlGate(null);
      store.setKernelSync(roomId, {
        state: 'denied',
        detail: '当前连接不能读取任务状态',
        updatedAtMs: store.kernelSyncByRoomId[roomId]?.updatedAtMs ?? 0,
        failureAtMs: Date.now(),
      });
      return;
    }
    const roomTransport = transport;

    let active = true;
    let unsubscribe: (() => void) | undefined;
    let snapshotController: AbortController | undefined;
    let revision = 0;
    let recoveryQueued = false;

    const publishSync = (
      state: RoomKernelLiveState,
      nextDetail: string,
      options: { updated?: boolean; failed?: boolean } = {},
    ) => {
      if (!active) return;
      const current = useRoomLiveStore.getState().kernelSyncByRoomId[roomId];
      const now = Date.now();
      useRoomLiveStore.getState().setKernelSync(roomId, {
        state,
        detail: nextDetail,
        updatedAtMs: options.updated ? now : current?.updatedAtMs ?? 0,
        ...(options.failed ? { failureAtMs: now } : {}),
      });
    };
    const publishProjection = (next: RoomKernelProjection) => {
      projectionRef.current = next;
      useRoomLiveStore.getState().setKernelProjection(roomId, next);
    };
    const recover = () => {
      if (!active || recoveryQueued) return;
      recoveryQueued = true;
      queueMicrotask(() => {
        recoveryQueued = false;
        if (active) void loadSnapshot();
      });
    };

    async function loadSnapshot(): Promise<void> {
      const currentRevision = ++revision;
      unsubscribe?.();
      unsubscribe = undefined;
      snapshotController?.abort();
      snapshotController = new AbortController();
      publishSync(
        projectionRef.current ? 'recovering' : 'loading',
        projectionRef.current ? '正在恢复任务状态' : '正在读取任务状态',
      );
      try {
        const raw = await roomTransport.request({
          pathId: 'agent.room.kernel.snapshot',
          params: { roomId },
          signal: snapshotController.signal,
        });
        if (!active || currentRevision !== revision) return;
        const snapshot = parseSnapshot(raw, roomId);
        const current = projectionRef.current;
        const snapshotIsCurrent = !current || snapshot.lastSequence >= current.lastSequence;
        const next = snapshotIsCurrent
          ? applyRoomKernelSnapshot(createRoomKernelProjection(roomId), snapshot)
          : current;
        if (snapshotIsCurrent) {
          setRequirementsByRootId(parseRequirementsByRootId(raw));
          publishProjection(next);
        }
        publishSync('synced', '任务状态已更新', { updated: true });
        unsubscribe = roomTransport.subscribe<unknown>(
          {
            pathId: 'agent.room.kernel.events',
            params: { roomId },
            lastEventId: `${roomId}#${next.lastSequence}`,
          },
          {
            open: () => {
              if (!active) return;
              publishSync('synced', '任务进度已连接');
            },
            next: (value) => {
              if (!active) return;
              if (isSnapshotRequired(value)) {
                publishSync('recovering', '任务进度存在缺口，正在恢复最新状态');
                recover();
                return;
              }
              try {
                const event = parseContract('room-event-envelope.v2', value) as RoomEventEnvelopeV2;
                const current = projectionRef.current;
                if (!current) {
                  publishSync('recovering', '正在恢复任务状态');
                  recover();
                  return;
                }
                const reduced = reduceRoomKernelEvent(current, event);
                if (reduced.disposition === 'snapshot-required') {
                  publishProjection(reduced.state);
                  publishSync('recovering', '任务进度存在缺口，正在恢复最新状态');
                  recover();
                  return;
                }
                if (reduced.disposition === 'applied') {
                  publishProjection(reduced.state);
                  publishSync('synced', '任务状态已更新', { updated: true });
                }
              } catch (error) {
                publishSync(
                  'recovering',
                  publicError(error, '任务进度格式无效，正在恢复最新状态'),
                  { failed: true },
                );
                recover();
              }
            },
            error: (error) => {
              if (!active) return;
              publishSync(
                'reconnecting',
                publicError(error, '任务进度连接中断'),
                { failed: true },
              );
            },
            reconnect: (notice) => {
              if (!active) return;
              publishSync(
                'reconnecting',
                `第 ${notice.attempt} 次重连 · ${notice.delayMs}ms`,
                { failed: true },
              );
            },
            snapshotRequired: () => {
              if (!active) return;
              publishSync('recovering', '任务进度存在缺口，正在恢复最新状态');
              recover();
            },
          },
        );
      } catch (error) {
        if (!active || currentRevision !== revision || isAbort(error)) return;
        const denied = errorStatus(error) === 401 || errorStatus(error) === 403;
        if (denied) {
          publishSync(
            'denied',
            '当前连接没有查看任务进度的权限',
            { failed: true },
          );
        } else if (projectionRef.current) {
          publishSync(
            'stale',
            `继续显示上次确认的进度 · ${publicError(error, '实时连接暂时不可用')}`,
            { failed: true },
          );
        } else {
          publishSync(
            'error',
            '任务进度暂时不可用。已有对话和工作文件不会受影响。',
            { failed: true },
          );
        }
      }
    }

    const start = async () => {
      setRequirementsByRootId({});
      setControlGate(null);
      publishSync(
        projectionRef.current ? 'recovering' : 'loading',
        '正在验证任务状态',
      );
      try {
        const gate = await evaluateRoomKernelControlGate(await roomTransport.capabilities());
        if (!active) return;
        setControlGate(gate);
      } catch {
        if (!active) return;
        // Route capabilities only authorize controls. The snapshot request is
        // still the authoritative read check and must not be blocked by stale
        // or temporarily unavailable capability metadata.
        setControlGate(null);
      }
      await loadSnapshot();
    };

    void start();
    return () => {
      active = false;
      revision += 1;
      snapshotController?.abort();
      unsubscribe?.();
    };
  }, [recoveryRequest, roomId, transport]);

  if (!visible) return null;

  return <section className="room-kernel-live" aria-label="协作任务状态" data-live-state={liveState}>
    <p
      aria-live="polite"
      className="room-kernel-live__status"
      role={liveState === 'error' || liveState === 'denied' ? 'alert' : 'status'}
    >
      <span className="room-kernel-live__status-copy">
        <strong>{liveStateLabel(liveState)}</strong>
        <span>{detail}</span>
      </span>
      {sync?.updatedAtMs ? (
        <time dateTime={new Date(sync.updatedAtMs).toISOString()}>
          更新于 {formatKernelUpdateTime(sync.updatedAtMs)}
        </time>
      ) : null}
      {liveState === 'error' || liveState === 'stale' ? (
        <Button
          onClick={() => setRecoveryRequest((current) => current + 1)}
          size="small"
          variant="quiet"
        >
          重新读取
        </Button>
      ) : null}
    </p>
    {projection && Object.keys(projection.rootsById).length > 0 ? <RoomKernelControlPlane
      projection={projection}
      budgetsByRootId={{}}
      contextReceiptsByRootId={{}}
      capabilityReceiptsByRootId={capabilityReceipts(projection)}
      commandTransport={controlGate?.commandEnabled && commandTransport ? commandTransport : undefined}
      commandDisabledReason={kernelCommandDisabledReason(controlGate)}
      panicEnabled={controlGate?.panicEnabled === true}
      participantLabels={participantLabels}
      participantProgress={participantProgress}
      requirementsByRootId={requirementsByRootId}
    /> : liveState === 'error' ? <EmptyState
      description="检查点仍保留。修复连接或运行时问题后，可以从已确认状态继续。"
      icon={CircleAlert}
      title="任务进度暂时无法读取"
    /> : liveState === 'denied' && !projection ? <EmptyState
      description="当前连接没有读取这个协作空间任务进度的权限；已有对话和工作文件不会受影响。"
      icon={CircleAlert}
      title="当前不可查看任务进度"
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

const ROOM_KERNEL_LIVE_LABELS: Record<RoomKernelLiveState, string> = {
  idle: '等待任务',
  loading: '正在同步',
  synced: '进度已同步',
  reconnecting: '正在重新连接',
  recovering: '正在恢复进度',
  stale: '实时更新暂时中断',
  denied: '当前不可查看',
  error: '进度同步异常',
};

const kernelUpdateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

function liveStateLabel(value: RoomKernelLiveState): string {
  return ROOM_KERNEL_LIVE_LABELS[value];
}

function formatKernelUpdateTime(value: number): string {
  return kernelUpdateTimeFormatter.format(new Date(value));
}

function kernelCommandDisabledReason(gate: RoomKernelControlGate | null): string {
  if (!gate) return '任务进度可查看，但任务控制能力尚未验证';
  if (!gate.readEnabled) return '任务进度已连接，但任务控制能力清单尚未确认';
  return gate.reason;
}

function errorStatus(error: unknown): number {
  return typeof error === 'object' && error !== null && 'status' in error && typeof error.status === 'number' ? error.status : 0;
}

function publicError(error: unknown, fallback: string): string {
  const message = error instanceof Error && !(error instanceof TypeError) ? error.message.trim() : '';
  return message && /[\u3400-\u9fff]/u.test(message) ? message : fallback;
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
