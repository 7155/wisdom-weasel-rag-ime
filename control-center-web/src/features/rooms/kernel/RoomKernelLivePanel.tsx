import { CircleAlert, Workflow } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, EmptyState } from '@/components/primitives';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import type { RoomEventEnvelopeV2 } from '@/contracts/generated/room-event-envelope.v2';
import {
  applyRoomKernelSnapshot,
  createRoomKernelProjection,
  reduceRoomKernelEvent,
  type RoomKernelProjection,
  type RoomKernelSnapshot,
  type CancellationSurfaceProjection,
} from '@/contracts/room-kernel-reducer';
import {
  selectRoomParticipantPublicProgress,
  type RoomActivityProjection,
} from '@/contracts/room-reducer';
import { parseContract } from '@/contracts/validators';
import { useOptionalControlTransport } from '@/app/control-transport';
import type { ControlTransport } from '@/platform/transport';
import { RoomKernelControlPlane } from './RoomKernelControlPlane';
import type { RoomTaskSubagentRun } from './RoomTaskFlowGraph';
import { parseRoomRequirementsReadProjection, type RoomRequirementsReadProjection } from '../requirements/room-requirements-read-model';
import type { RoomCollaborationRole, RoomWorkItem } from '../room-types';
import { roomPublicActivityText } from '../timeline/room-tool-presentation';
import {
  useRoomLiveStore,
  type RoomKernelLiveState,
  type RoomKernelSyncProjection,
} from '../state/live-store';
import { createControlRoomKernelCommandTransport } from './room-kernel-command-transport';
import { evaluateRoomKernelControlGate, type RoomKernelControlGate } from './room-kernel-control-gate';
const ROOM_SUBAGENT_ACTIVE_POLL_MS = 1_000;
const ROOM_SUBAGENT_POTENTIAL_POLL_MS = 5_000;
const MAX_ROOM_SUBAGENT_BATCHES_PER_SESSION = 50;
const MAX_ROOM_SUBAGENT_RUNS_PER_BATCH = 2;
const MAX_ROOM_SUBAGENT_RUNS_PER_TASK = 8;
const MAX_DATE_EPOCH_MS = 8_640_000_000_000_000;

export type RoomTaskSubagentSessionProjection = {
  runsByTaskId: Record<string, RoomTaskSubagentRun[]>;
  hasActive: boolean;
};

type RoomTaskSubagentReadModel = {
  scopeKey: string;
  sessions: Record<string, RoomTaskSubagentSessionProjection>;
};

export type RoomTaskSubagentLineage = {
  rootId: string;
  generation: number;
  validDispatchIds: ReadonlySet<string>;
};

export function RoomKernelLivePanel({
  participantLabels = {},
  participantSessionIds = [],
  participantRoles = {},
  roomId,
  subagentsByTaskId: providedSubagentsByTaskId,
  visible = true,
  workItems = [],
}: {
  participantLabels?: Record<string, string>;
  participantSessionIds?: readonly string[];
  participantRoles?: Record<string, RoomCollaborationRole>;
  roomId: string;
  subagentsByTaskId?: Record<string, RoomTaskSubagentRun[]>;
  visible?: boolean;
  workItems?: RoomWorkItem[];
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
  const publicActivities = useMemo(
    () => publicProjection
      ? publicProjection.activityOrder
          .map((activityId) => publicProjection.activitiesById[activityId])
          .filter((activity): activity is RoomActivityProjection => Boolean(activity))
      : [],
    [publicProjection],
  );
  const polledSubagentsByTaskId = useRoomTaskSubagents({
    enabled: visible && providedSubagentsByTaskId === undefined,
    participantSessionIds,
    projection,
    roomId,
    transport,
  });
  const subagentsByTaskId = providedSubagentsByTaskId ?? polledSubagentsByTaskId;
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
      activities={publicActivities}
      projection={projection}
      budgetsByRootId={{}}
      contextReceiptsByRootId={{}}
      capabilityReceiptsByRootId={capabilityReceipts(projection)}
      commandTransport={controlGate?.commandEnabled && commandTransport ? commandTransport : undefined}
      commandDisabledReason={kernelCommandDisabledReason(controlGate)}
      panicEnabled={controlGate?.panicEnabled === true}
      participantLabels={participantLabels}
      participantRoles={participantRoles}
      participantProgress={participantProgress}
      subagentsByTaskId={subagentsByTaskId}
      requirementsByRootId={requirementsByRootId}
      workItems={workItems}
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
export function useRoomTaskSubagents({
  enabled,
  participantSessionIds,
  projection,
  roomId,
  transport,
}: {
  enabled: boolean;
  participantSessionIds: readonly string[];
  projection: RoomKernelProjection | null;
  roomId: string;
  transport: ControlTransport | null;
}): Record<string, RoomTaskSubagentRun[]> {
  const sessionIds = uniqueRoomParticipantSessionIds(participantSessionIds);
  const lineageByTaskId = roomTaskSubagentLineage(projection);
  const lineageKey = roomTaskSubagentLineageKey(lineageByTaskId);
  const taskIds = [...lineageByTaskId.keys()].sort();
  const sessionKey = JSON.stringify(sessionIds);
  const scopeKey = JSON.stringify([roomId, sessionIds, lineageKey]);
  const potentiallyActive = roomKernelMayHaveActiveSubagents(projection);
  const [readModel, setReadModel] = useState<RoomTaskSubagentReadModel>({
    scopeKey: '',
    sessions: {},
  });
  const readModelRef = useRef(readModel);
  const pollingRevisionRef = useRef(0);
  readModelRef.current = readModel;

  useEffect(() => {
    const revision = ++pollingRevisionRef.current;
    const current = readModelRef.current;
    let retained = current.scopeKey === scopeKey ? { ...current.sessions } : {};
    const publish = () => {
      const next = { scopeKey, sessions: { ...retained } };
      readModelRef.current = next;
      setReadModel(next);
    };
    if (!enabled || !transport || !roomId || !sessionIds.length || !taskIds.length) {
      if (current.scopeKey !== scopeKey || Object.keys(current.sessions).length) {
        retained = {};
        publish();
      }
      return;
    }

    const roomTransport = transport;
    const allowedLineage = lineageByTaskId;
    let active = true;
    const controllers = new Set<AbortController>();
    const timers = new Set<number>();

    if (current.scopeKey !== scopeKey) publish();

    const schedule = (sessionId: string, delayMs: number | null) => {
      if (!active || revision !== pollingRevisionRef.current || delayMs === null) return;
      const handle = window.setTimeout(() => {
        timers.delete(handle);
        void pollSession(sessionId);
      }, delayMs);
      timers.add(handle);
    };

    async function pollSession(sessionId: string): Promise<void> {
      if (!active || revision !== pollingRevisionRef.current) return;
      const controller = new AbortController();
      controllers.add(controller);
      try {
        const value = await roomTransport.request({
          pathId: 'agent.subagents.list',
          query: { sessionId, limit: MAX_ROOM_SUBAGENT_BATCHES_PER_SESSION },
          signal: controller.signal,
        });
        if (!active || revision !== pollingRevisionRef.current) return;
        const parsed = parseRoomTaskSubagentResponse(
          value,
          roomId,
          sessionId,
          allowedLineage,
        );
        retained = { ...retained, [sessionId]: parsed };
        publish();
        schedule(sessionId, roomSubagentPollDelay(parsed.hasActive, potentiallyActive));
      } catch (error) {
        if (!active || revision !== pollingRevisionRef.current || isAbort(error)) return;
        const previous = retained[sessionId];
        schedule(
          sessionId,
          roomSubagentPollDelay(previous?.hasActive === true, potentiallyActive),
        );
      } finally {
        controllers.delete(controller);
      }
    }

    for (const sessionId of sessionIds) void pollSession(sessionId);
    return () => {
      active = false;
      for (const timer of timers) window.clearTimeout(timer);
      for (const controller of controllers) controller.abort();
    };
  }, [enabled, lineageKey, potentiallyActive, roomId, scopeKey, sessionKey, transport]);

  if (readModel.scopeKey !== scopeKey) return {};
  return mergeRoomTaskSubagentSessions(readModel.sessions, new Set(taskIds));
}

export function parseRoomTaskSubagentResponse(
  value: unknown,
  roomId: string,
  parentSessionId: string,
  lineageByTaskId: ReadonlyMap<string, RoomTaskSubagentLineage>,
): RoomTaskSubagentSessionProjection {
  const runsByTaskAndId = new Map<string, Map<string, RoomTaskSubagentRun>>();
  const response = record(value);
  if (response.ok !== true || !Array.isArray(response.items)) {
    throw new TypeError('Subagent status response is invalid');
  }
  const batches = response.items.slice(0, MAX_ROOM_SUBAGENT_BATCHES_PER_SESSION);
  for (const valueBatch of batches) {
    const batch = record(valueBatch);
    const batchId = protocolText(batch.id);
    const causalMetadata = record(batch.causalMetadata);
    const taskId = protocolText(causalMetadata.taskId);
    const lineage = lineageByTaskId.get(taskId);
    const rootId = protocolText(causalMetadata.rootId);
    const dispatchId = protocolText(causalMetadata.dispatchId);
    const generation = safeNonNegativeInteger(causalMetadata.generation);
    const runs = array(batch.runs);
    if (
      batch.schemaVersion !== 'rag-ime.agent-subagent-batch.v1'
      || !batchId
      || protocolText(batch.parentSessionId) !== parentSessionId
      || causalMetadata.roomBound !== true
      || protocolText(causalMetadata.roomId) !== roomId
      || !lineage
      || rootId !== lineage.rootId
      || generation !== lineage.generation
      || !lineage.validDispatchIds.has(dispatchId)
      || runs.length < 1
      || runs.length > MAX_ROOM_SUBAGENT_RUNS_PER_BATCH
    ) continue;

    const taskRuns = runsByTaskAndId.get(taskId) ?? new Map<string, RoomTaskSubagentRun>();
    for (const valueRun of runs) {
      const parsed = parseRoomTaskSubagentRun(valueRun, batchId);
      if (!parsed) continue;
      const current = taskRuns.get(parsed.id);
      if (!current || parsed.run.updatedAtMs >= current.updatedAtMs) {
        taskRuns.set(parsed.id, parsed.run);
      }
    }
    if (taskRuns.size) runsByTaskAndId.set(taskId, taskRuns);
  }

  const runsByTaskId = Object.fromEntries(
    [...runsByTaskAndId.entries()].map(([taskId, taskRuns]) => [
      taskId,
      [...taskRuns.values()].sort(roomTaskSubagentOrder),
    ]),
  );
  return {
    runsByTaskId,
    hasActive: Object.values(runsByTaskId).some((runs) => runs.some((run) => (
      run.state === 'queued' || run.state === 'running'
    ))),
  };
}

export function roomSubagentPollDelay(
  hasActiveRuns: boolean,
  roomMayStillRun: boolean,
): number | null {
  if (hasActiveRuns) return ROOM_SUBAGENT_ACTIVE_POLL_MS;
  if (roomMayStillRun) return ROOM_SUBAGENT_POTENTIAL_POLL_MS;
  return null;
}

function parseRoomTaskSubagentRun(
  value: unknown,
  batchId: string,
): { id: string; run: RoomTaskSubagentRun } | null {
  const item = record(value);
  const id = protocolText(item.id);
  const task = boundedPublicText(roomPublicActivityText(protocolText(item.task)), 180);
  const budget = record(item.budget);
  const usage = record(item.usage);
  const templates: AgentSubagentRunV1['templateId'][] = [
    'researcher',
    'planner',
    'worker',
    'reviewer',
    'delegate',
  ];
  const states: AgentSubagentRunV1['state'][] = [
    'queued',
    'running',
    'completed',
    'failed',
    'aborted',
    'timed_out',
  ];
  const ordinal = safeNonNegativeInteger(item.ordinal);
  const maxTurns = safeNonNegativeInteger(budget.maxTurns);
  const maxToolCalls = safeNonNegativeInteger(budget.maxToolCalls);
  const maxTotalTokens = safeNonNegativeInteger(budget.maxTotalTokens);
  const maxDurationMs = safeNonNegativeInteger(budget.maxDurationMs);
  const maxOutputChars = safeNonNegativeInteger(budget.maxOutputChars);
  const turnCount = safeNonNegativeInteger(usage.turnCount);
  const toolCount = safeNonNegativeInteger(usage.toolCount);
  const totalTokens = safeNonNegativeInteger(usage.totalTokens);
  const createdAtMs = safeEpochMs(item.createdAtMs);
  const updatedAtMs = safeEpochMs(item.updatedAtMs);
  const startedAtMs = safeNullableEpochMs(item.startedAtMs);
  const completedAtMs = safeNullableEpochMs(item.completedAtMs);
  if (
    item.schemaVersion !== 'rag-ime.agent-subagent-run.v1'
    || !id
    || protocolText(item.batchId) !== batchId
    || !task
    || !templates.includes(item.templateId as AgentSubagentRunV1['templateId'])
    || !states.includes(item.state as AgentSubagentRunV1['state'])
    || ordinal === null
    || maxTurns === null
    || maxToolCalls === null
    || maxTotalTokens === null
    || maxDurationMs === null
    || maxOutputChars === null
    || turnCount === null
    || toolCount === null
    || totalTokens === null
    || createdAtMs === null
    || updatedAtMs === null
    || startedAtMs === undefined
    || completedAtMs === undefined
  ) return null;

  return {
    id,
    run: {
      templateId: item.templateId as AgentSubagentRunV1['templateId'],
      ordinal,
      task,
      state: item.state as AgentSubagentRunV1['state'],
      budget: {
        maxTurns,
        maxToolCalls,
        maxTotalTokens,
        maxDurationMs,
        maxOutputChars,
      },
      usage: { turnCount, toolCount, totalTokens },
      resultSummary: boundedPublicText(
        roomPublicActivityText(protocolText(record(item.result).summary)),
        220,
      ),
      error: roomTaskSubagentPublicError(item.state as AgentSubagentRunV1['state']),
      createdAtMs,
      startedAtMs,
      updatedAtMs,
      completedAtMs,
    },
  };
}

function mergeRoomTaskSubagentSessions(
  sessions: Record<string, RoomTaskSubagentSessionProjection>,
  allowedTaskIds: ReadonlySet<string>,
): Record<string, RoomTaskSubagentRun[]> {
  const merged = new Map<string, RoomTaskSubagentRun[]>();
  for (const sessionId of Object.keys(sessions).sort()) {
    const session = sessions[sessionId];
    if (!session) continue;
    for (const [taskId, runs] of Object.entries(session.runsByTaskId)) {
      if (!allowedTaskIds.has(taskId)) continue;
      merged.set(taskId, [...(merged.get(taskId) ?? []), ...runs]);
    }
  }
  return Object.fromEntries(
    [...merged.entries()].map(([taskId, runs]) => [
      taskId,
      runs.sort(roomTaskSubagentOrder).slice(0, MAX_ROOM_SUBAGENT_RUNS_PER_TASK),
    ]),
  );
}

function roomTaskSubagentOrder(
  left: RoomTaskSubagentRun,
  right: RoomTaskSubagentRun,
): number {
  return roomTaskSubagentStatePriority(left.state) - roomTaskSubagentStatePriority(right.state)
    || left.ordinal - right.ordinal
    || right.updatedAtMs - left.updatedAtMs
    || left.templateId.localeCompare(right.templateId)
    || left.task.localeCompare(right.task);
}

function roomTaskSubagentStatePriority(state: AgentSubagentRunV1['state']): number {
  if (state === 'failed' || state === 'timed_out') return 0;
  if (state === 'running') return 1;
  if (state === 'queued') return 2;
  if (state === 'aborted') return 3;
  return 4;
}

function roomTaskSubagentPublicError(state: AgentSubagentRunV1['state']): string {
  if (state === 'failed') return '任务内协作者未能完成；负责人可检查任务状态后决定是否重试。';
  if (state === 'timed_out') return '任务内协作者未在限定时间内完成；负责人可决定是否重试。';
  return '';
}

function roomTaskSubagentLineage(
  projection: RoomKernelProjection | null,
): Map<string, RoomTaskSubagentLineage> {
  const lineage = new Map<string, RoomTaskSubagentLineage>();
  if (!projection) return lineage;
  const dispatchIdsByTaskId = new Map<string, Set<string>>();
  for (const dispatch of Object.values(projection.dispatchesById)) {
    const task = projection.tasksById[dispatch.taskId];
    const root = task ? projection.rootsById[task.rootId] : undefined;
    if (
      !task
      || !root
      || dispatch.rootId !== task.rootId
      || dispatch.generation !== root.generation
    ) continue;
    const dispatchIds = dispatchIdsByTaskId.get(task.taskId) ?? new Set<string>();
    dispatchIds.add(dispatch.dispatchId);
    dispatchIdsByTaskId.set(task.taskId, dispatchIds);
  }
  for (const task of Object.values(projection.tasksById)) {
    const root = projection.rootsById[task.rootId];
    if (!root) continue;
    lineage.set(task.taskId, {
      rootId: task.rootId,
      generation: root.generation,
      validDispatchIds: dispatchIdsByTaskId.get(task.taskId) ?? new Set<string>(),
    });
  }
  return lineage;
}

function roomTaskSubagentLineageKey(
  lineageByTaskId: ReadonlyMap<string, RoomTaskSubagentLineage>,
): string {
  return JSON.stringify([...lineageByTaskId.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([taskId, lineage]) => [
      taskId,
      lineage.rootId,
      lineage.generation,
      [...lineage.validDispatchIds].sort(),
    ]));
}

function roomKernelMayHaveActiveSubagents(projection: RoomKernelProjection | null): boolean {
  if (!projection) return false;
  return Object.values(projection.rootsById).some((root) => (
    !['completed', 'failed', 'cancelled', 'cancelled_with_unknowns'].includes(root.state)
  )) || Object.values(projection.tasksById).some((task) => (
    !['completed', 'failed', 'cancelled'].includes(task.state)
  ));
}

function uniqueRoomParticipantSessionIds(values: readonly string[]): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const sessionId = protocolText(value);
    if (!sessionId || seen.has(sessionId)) continue;
    seen.add(sessionId);
    result.push(sessionId);
  }
  return result.sort();
}

function boundedPublicText(value: unknown, maximum: number): string {
  if (typeof value !== 'string') return '';
  const normalized = value
    .replace(/[\u0000-\u001f\u007f-\u009f]+/gu, ' ')
    .replace(/\s+/gu, ' ')
    .trim();
  if (normalized.length <= maximum) return normalized;
  return `${normalized.slice(0, maximum - 1).trimEnd()}…`;
}

function protocolText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function safeNonNegativeInteger(value: unknown): number | null {
  return Number.isSafeInteger(value) && Number(value) >= 0 ? Number(value) : null;
}

function safeEpochMs(value: unknown): number | null {
  const parsed = safeNonNegativeInteger(value);
  if (parsed === null || parsed > MAX_DATE_EPOCH_MS) return null;
  return parsed;
}

function safeNullableEpochMs(value: unknown): number | null | undefined {
  if (value === null) return null;
  return safeEpochMs(value) ?? undefined;
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
    taskUpdatedAtMsById: nonNegativeIntegerRecord(
      item.taskUpdatedAtMsById,
      'taskUpdatedAtMsById',
    ),
    dispatches: array(item.dispatches).map((entry) => parseContract('room-dispatch-envelope.v2', entry)),
    posts: array(item.posts).map((entry) => parseContract('room-post.v2', entry)),
    sessions: array(item.sessions) as RoomKernelSnapshot['sessions'],
    receipts: array(item.receipts).map((entry) => parseContract('room-kernel-receipt.v1', entry)),
    cancellationSurfaces: array(item.cancellationSurfaces).map(parseCancellationSurface),
  };
}

function nonNegativeIntegerRecord(value: unknown, field: string): Record<string, number> {
  if (value === undefined) return {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${field} must be an object`);
  }
  const item = value as Record<string, unknown>;
  const result: Record<string, number> = {};
  for (const [key, entry] of Object.entries(item)) {
    if (!key.trim()) throw new TypeError(`${field} has an empty key`);
    result[key] = nonNegativeInteger(entry, `${field}.${key}`);
  }
  return result;
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
  const safeMessage = roomPublicActivityText(message);
  return safeMessage && /[\u3400-\u9fff]/u.test(safeMessage) ? safeMessage : fallback;
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
