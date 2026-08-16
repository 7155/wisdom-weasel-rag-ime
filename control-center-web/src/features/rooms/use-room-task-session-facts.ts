import { useEffect, useMemo, useState } from 'react';

import { useControlTransport } from '@/app/control-transport';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import type { AgentWorkflowStateV1 } from '@/contracts/generated/agent-workflow-state.v1';
import {
  hasActiveSubagentRuns,
  subagentRuns,
} from '@/features/agent/status/subagent-data';
import { usePageVisibility } from '@/platform/use-page-visibility';

export interface RoomTaskSessionFact {
  sessionId: string;
  status: 'loading' | 'ready' | 'partial' | 'unavailable';
  workflow?: AgentWorkflowStateV1;
  subagents: AgentSubagentRunV1[];
}

const MAX_PROJECTED_SESSIONS = 8;
const ACTIVE_REFRESH_MS = 2_000;
const IDLE_REFRESH_MS = 10_000;

export function useRoomTaskSessionFacts(
  requestedSessionIds: readonly string[],
): ReadonlyMap<string, RoomTaskSessionFact> {
  const transport = useControlTransport();
  const pageVisible = usePageVisibility();
  const sessionKey = useMemo(() => [...new Set(requestedSessionIds
    .map((sessionId) => sessionId.trim())
    .filter(Boolean))]
    .slice(0, MAX_PROJECTED_SESSIONS)
    .sort()
    .join('\u001f'), [requestedSessionIds]);
  const sessionIds = useMemo(
    () => sessionKey ? sessionKey.split('\u001f') : [],
    [sessionKey],
  );
  const [facts, setFacts] = useState<Record<string, RoomTaskSessionFact>>({});

  useEffect(() => {
    if (!sessionIds.length) {
      setFacts({});
      return;
    }
    setFacts((current) => Object.fromEntries(sessionIds.map((sessionId) => [
      sessionId,
      current[sessionId] ?? {
        sessionId,
        status: 'loading',
        subagents: [],
      },
    ])));
  }, [sessionKey]); // sessionKey is the stable identity of sessionIds.

  useEffect(() => {
    if (!pageVisible || !sessionIds.length) return;
    let disposed = false;
    let refreshHandle: number | undefined;
    const controller = new AbortController();

    const refresh = async () => {
      const next = await Promise.all(sessionIds.map(async (sessionId): Promise<RoomTaskSessionFact> => {
        const [workflowResult, subagentResult] = await Promise.allSettled([
          transport.request({
            pathId: 'agent.session.workflow.get',
            params: { sessionId },
            signal: controller.signal,
          }),
          transport.request({
            pathId: 'agent.subagents.list',
            query: { sessionId, limit: 20 },
            signal: controller.signal,
          }),
        ]);
        const workflow = workflowResult.status === 'fulfilled'
          ? agentWorkflowState(workflowResult.value, sessionId)
          : undefined;
        const runs = subagentResult.status === 'fulfilled'
          ? subagentRuns(subagentResult.value)
          : [];
        const successCount = Number(Boolean(workflow))
          + Number(subagentResult.status === 'fulfilled');
        return {
          sessionId,
          status: successCount === 2 ? 'ready' : successCount === 1 ? 'partial' : 'unavailable',
          workflow,
          subagents: runs,
        };
      }));
      if (disposed) return;
      setFacts(Object.fromEntries(next.map((fact) => [fact.sessionId, fact])));
      const hasLiveWork = next.some((fact) => (
        hasActiveSubagentRuns(fact.subagents)
        || Boolean(fact.workflow?.todo.counts.inProgress)
      ));
      refreshHandle = window.setTimeout(
        () => void refresh(),
        hasLiveWork ? ACTIVE_REFRESH_MS : IDLE_REFRESH_MS,
      );
    };

    void refresh();
    return () => {
      disposed = true;
      controller.abort();
      if (refreshHandle !== undefined) window.clearTimeout(refreshHandle);
    };
  }, [pageVisible, sessionKey, transport]);

  return useMemo(
    () => new Map(sessionIds.flatMap((sessionId) => (
      facts[sessionId] ? [[sessionId, facts[sessionId]!] as const] : []
    ))),
    [facts, sessionKey],
  );
}

function agentWorkflowState(
  value: unknown,
  sessionId: string,
): AgentWorkflowStateV1 | undefined {
  const source = record(value);
  const todo = record(source.todo);
  const counts = record(todo.counts);
  if (
    source.schemaVersion !== 'rag-ime.agent-workflow-state.v1'
    || source.ok !== true
    || source.sessionId !== sessionId
    || todo.schemaVersion !== 'rag-ime.agent-todo.v1'
    || !Array.isArray(todo.phases)
    || !Number.isFinite(counts.total)
    || !Number.isFinite(counts.completed)
  ) return undefined;
  return value as AgentWorkflowStateV1;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
