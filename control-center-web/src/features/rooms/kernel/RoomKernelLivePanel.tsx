import { useEffect, useMemo, useRef, useState } from 'react';
import type { RoomEventEnvelopeV2 } from '@/contracts/generated/room-event-envelope.v2';
import {
  applyRoomKernelSnapshot,
  createRoomKernelProjection,
  reduceRoomKernelEvent,
  type RoomKernelProjection,
  type RoomKernelSnapshot,
} from '@/contracts/room-kernel-reducer';
import { parseContract } from '@/contracts/validators';
import { useOptionalControlTransport } from '@/app/control-transport';
import { RoomKernelControlPlane } from './RoomKernelControlPlane';
import { parseRoomRequirementsReadProjection, type RoomRequirementsReadProjection } from '../requirements/room-requirements-read-model';
import { createControlRoomKernelCommandTransport } from './room-kernel-command-transport';
import { evaluateRoomKernelControlGate, type RoomKernelControlGate } from './room-kernel-control-gate';

type LiveState = 'loading' | 'synced' | 'reconnecting' | 'recovering' | 'denied' | 'error';

export function RoomKernelLivePanel({ roomId }: { roomId: string }) {
  const transport = useOptionalControlTransport();
  const [projection, setProjection] = useState<RoomKernelProjection | null>(null);
  const [requirementsByRootId, setRequirementsByRootId] = useState<Record<string, RoomRequirementsReadProjection>>({});
  const projectionRef = useRef<RoomKernelProjection | null>(null);
  const [controlGate, setControlGate] = useState<RoomKernelControlGate | null>(null);
  const [liveState, setLiveState] = useState<LiveState>('loading');
  const [detail, setDetail] = useState('正在验证控制能力');
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
      setDetail('控制传输尚未挂载');
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
      setDetail((current) => current === '正在验证控制能力' ? current : '正在恢复 canonical snapshot');
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
        setDetail(`已同步到 sequence ${next.lastSequence}`);
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
              setDetail('事件流已连接');
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
                  setDetail(`已同步到 sequence ${reduced.state.lastSequence}`);
                }
              } catch (error) {
                setLiveState('error');
                setDetail(publicError(error, 'Room Kernel 事件不符合 canonical contract'));
              }
            },
            error: (error) => {
              if (!active) return;
              setLiveState('reconnecting');
              setDetail(publicError(error, 'Room Kernel 事件流中断'));
            },
            reconnect: (notice) => {
              if (!active) return;
              setLiveState('reconnecting');
              setDetail(`第 ${notice.attempt} 次重连 · ${notice.delayMs}ms`);
            },
            snapshotRequired: () => {
              if (!active) return;
              setLiveState('recovering');
              setDetail('事件序列存在缺口，正在重新读取 snapshot');
              recover();
            },
          },
        );
      } catch (error) {
        if (!active || currentRevision !== revision || isAbort(error)) return;
        const denied = errorStatus(error) === 401 || errorStatus(error) === 403;
        setLiveState(denied ? 'denied' : 'error');
        setDetail(publicError(error, denied ? '没有 Room Kernel 读取权限' : 'Room Kernel snapshot 读取失败'));
      }
    };

    const start = async () => {
      setProjection(null);
      projectionRef.current = null;
      setControlGate(null);
      setLiveState('loading');
      setDetail('正在验证控制能力');
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
        setDetail(publicError(error, '无法验证 Room Kernel 控制能力'));
      }
    };

    void start();
    return () => {
      active = false;
      revision += 1;
      snapshotController?.abort();
      unsubscribe?.();
    };
  }, [roomId, transport]);

  return <section className="room-kernel-live" aria-label="Room Kernel 实时状态" data-live-state={liveState}>
    <p className="room-kernel-live__status" role={liveState === 'error' || liveState === 'denied' ? 'alert' : 'status'}>
      <strong>{liveStateLabel(liveState)}</strong><span>{detail}</span>
    </p>
    {projection && Object.keys(projection.rootsById).length > 0 ? <RoomKernelControlPlane
      projection={projection}
      budgetsByRootId={{}}
      contextReceiptsByRootId={{}}
      capabilityReceiptsByRootId={capabilityReceipts(projection)}
      commandTransport={controlGate?.commandEnabled && commandTransport ? commandTransport : undefined}
      commandDisabledReason={controlGate?.reason}
      panicEnabled={controlGate?.panicEnabled === true}
      requirementsByRootId={requirementsByRootId}
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
    roots: array(item.roots).map((entry) => parseContract('room-root-execution.v2', entry)),
    tasks: array(item.tasks).map((entry) => parseContract('room-task.v2', entry)),
    dispatches: array(item.dispatches).map((entry) => parseContract('room-dispatch-envelope.v2', entry)),
    posts: array(item.posts).map((entry) => parseContract('room-post.v2', entry)),
    sessions: array(item.sessions) as RoomKernelSnapshot['sessions'],
    receipts: array(item.receipts).map((entry) => parseContract('room-kernel-receipt.v1', entry)),
  };
}

function isSnapshotRequired(value: unknown): boolean {
  const item = record(value);
  return item.reason === 'event_replay_gap' || item.eventType === 'snapshot_required';
}

function liveStateLabel(value: LiveState): string {
  return ({ loading: '正在连接', synced: '实时同步', reconnecting: '连接恢复中', recovering: '状态恢复中', denied: '只读不可用', error: '同步异常' } as const)[value];
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
function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
