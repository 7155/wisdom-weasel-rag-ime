import { BrainCircuit, ExternalLink, Settings2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useOptionalControlTransport } from '@/app/control-transport';
import { Disclosure } from '@/components/primitives';
import type { AgentContextTraceV1 } from '@/contracts/generated/agent-context-trace.v1';
import {
  evidenceEchoNodeEntities,
  evidenceEchoSessionRoute,
  openEvidenceEchoEntity,
  type EvidenceEchoEntity,
} from '@/features/evidence-echo/evidence-echo';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';
import type { ControlTransport } from '@/platform/transport';

export type MemoryRecallReceiptView = {
  sessionId: string;
  traceId: string;
  turnId: string;
  nodeId: string;
  count: number;
  durationMs: number;
  sourceTitles: string[];
  entities: EvidenceEchoEntity[];
};

export function MemoryRecallReceipt({ receipt }: { receipt: MemoryRecallReceiptView }) {
  const desktop = usePawOsDesktop();
  return (
    <Disclosure
      className="agent-memory-recall-receipt"
      summary={(
        <>
          <BrainCircuit aria-hidden="true" size={14} />
          <strong>记忆召回 · {receipt.count} 条 · {receipt.durationMs} ms</strong>
          <span aria-hidden="true">›</span>
        </>
      )}
    >
      <div className="agent-memory-recall-receipt__body">
        {receipt.sourceTitles.length ? (
          <ul aria-label="记忆召回来源标题">
            {receipt.sourceTitles.map((title) => <li key={title}>{title}</li>)}
          </ul>
        ) : <p>这次召回没有附带可公开的来源标题。</p>}
        <div className="agent-memory-recall-receipt__actions">
          {receipt.entities.map((entity) => (
            <button
              aria-label={`在记忆中打开 ${entity.label}`}
              key={`${entity.appId}:${entity.entityId}`}
              onClick={() => openEvidenceEchoEntity(desktop, entity)}
              type="button"
            >
              打开记忆来源 <ExternalLink aria-hidden="true" size={12} />
            </button>
          ))}
          <button
            aria-label="查看本轮上下文轨迹"
            onClick={() => openPawOsRoute(desktop, evidenceEchoSessionRoute(receipt))}
            type="button"
          >
            查看上下文轨迹 <ExternalLink aria-hidden="true" size={12} />
          </button>
          <button
            aria-label="打开记忆召回设置"
            onClick={() => openPawOsRoute(desktop, '/memory?view=preferences')}
            type="button"
          >
            召回设置 <Settings2 aria-hidden="true" size={12} />
          </button>
        </div>
      </div>
    </Disclosure>
  );
}

export function memoryRecallReceiptFromTrace(
  trace: AgentContextTraceV1,
): MemoryRecallReceiptView | undefined {
  const node = trace.nodes.find((candidate) => (
    candidate.stage === 'memory_recall' && candidate.disposition === 'included'
  ));
  if (!node) return undefined;
  const count = finiteInteger(node.metadata.hitCount);
  if (!count || count < 1) return undefined;
  return {
    sessionId: trace.sessionId,
    traceId: trace.traceId,
    turnId: trace.turnId,
    nodeId: node.nodeId,
    count,
    durationMs: Math.max(0, finiteInteger(node.durationMs) ?? 0),
    sourceTitles: commaSeparated(node.metadata.sourceTitles, 12),
    entities: evidenceEchoNodeEntities(node, { sessionId: trace.sessionId })
      .filter((entity) => entity.appId === 'memory'),
  };
}

export function useMemoryRecallReceipts(
  sessionId: string,
  turnIds: string[],
  hasActiveTurn: boolean,
): Record<string, MemoryRecallReceiptView> {
  const transport = useOptionalControlTransport();
  const [receipts, setReceipts] = useState<Record<string, MemoryRecallReceiptView>>({});
  const settledCache = useRef(new Map<string, MemoryRecallReceiptView | undefined>());
  const turnIdsKey = useMemo(() => turnIds.join('\u001f'), [turnIds]);

  useEffect(() => {
    settledCache.current.clear();
    setReceipts({});
  }, [sessionId]);

  useEffect(() => {
    if (!transport || !sessionId || turnIds.length === 0) return undefined;
    const controller = new AbortController();
    let loading = false;
    const load = async () => {
      if (loading) return;
      loading = true;
      try {
        const next = await loadMemoryRecallReceipts(
          transport,
          sessionId,
          new Set(turnIds),
          settledCache.current,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setReceipts((current) => receiptMapsEqual(current, next) ? current : next);
        }
      } catch {
        // Context trace is an observability projection. Conversation remains
        // authoritative and usable when the projection is temporarily absent.
      } finally {
        loading = false;
      }
    };
    void load();
    const interval = hasActiveTurn ? window.setInterval(() => void load(), 3_000) : 0;
    return () => {
      controller.abort();
      if (interval) window.clearInterval(interval);
    };
  }, [hasActiveTurn, sessionId, transport, turnIdsKey]);
  return receipts;
}

async function loadMemoryRecallReceipts(
  transport: ControlTransport,
  sessionId: string,
  turnIds: Set<string>,
  settledCache: Map<string, MemoryRecallReceiptView | undefined>,
  signal: AbortSignal,
): Promise<Record<string, MemoryRecallReceiptView>> {
  const response = await transport.request({
    pathId: 'agent.session.contextTraces.list',
    params: { sessionId },
    query: { limit: 64 },
    signal,
  });
  const summaries = array(record(response).items)
    .map(record)
    .filter((item) => turnIds.has(text(item.turnId)) && Boolean(text(item.traceId)));
  const latestByTurn = new Map<string, Record<string, unknown>>();
  for (const summary of summaries) {
    const turnId = text(summary.turnId);
    if (!latestByTurn.has(turnId)) latestByTurn.set(turnId, summary);
  }
  const pairs = await Promise.all([...latestByTurn.entries()].map(async ([turnId, summary]) => {
    const traceId = text(summary.traceId);
    const settled = text(summary.status) !== 'building';
    if (settled && settledCache.has(traceId)) return [turnId, settledCache.get(traceId)] as const;
    try {
      const trace = await transport.request<AgentContextTraceV1>({
        pathId: 'agent.session.contextTrace.get',
        params: { sessionId, traceId },
        signal,
      });
      const receipt = memoryRecallReceiptFromTrace(trace);
      if (settled) settledCache.set(traceId, receipt);
      return [turnId, receipt] as const;
    } catch {
      return [turnId, undefined] as const;
    }
  }));
  return Object.fromEntries(pairs.filter((pair): pair is readonly [string, MemoryRecallReceiptView] => Boolean(pair[1])));
}

function receiptMapsEqual(
  left: Record<string, MemoryRecallReceiptView>,
  right: Record<string, MemoryRecallReceiptView>,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function commaSeparated(value: unknown, limit: number): string[] {
  if (typeof value !== 'string') return [];
  return value.split(',').map((item) => item.trim()).filter(Boolean).slice(0, limit);
}

function finiteInteger(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : undefined;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
