/**
 * EvidenceEchoUsage — 实体详情里的「最近被哪些 Session 装配」只读区块。
 *
 * 它不写任何东西，也不新增读取通道：结果全部来自既有的
 * `agent.sessions.list` / `agent.session.contextTraces.list` /
 * `agent.session.contextTrace.get`，在前端按实体标识聚合。点一行会打开
 * Agent App 的那段 Session，并聚焦到装配这条证据的那个节点。
 */

import { GitBranch, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';
import {
  collectEvidenceEchoUsage,
  evidenceEchoSessionRoute,
  type EvidenceEchoAppId,
  type EvidenceEchoUsage as EvidenceEchoUsageResult,
  type EvidenceEchoUsageRow,
} from './evidence-echo';
import './evidence-echo.css';

type LoadState = 'idle' | 'loading' | 'ready' | 'failed';

export function EvidenceEchoUsage({
  appId,
  entityId,
  entityLabel = '',
}: {
  appId: EvidenceEchoAppId;
  entityId: string;
  entityLabel?: string;
}) {
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const [state, setState] = useState<LoadState>('idle');
  const [usage, setUsage] = useState<EvidenceEchoUsageResult>();
  const [revision, setRevision] = useState(0);
  const trimmedId = entityId.trim();

  const openRow = useCallback((row: EvidenceEchoUsageRow) => {
    openPawOsRoute(desktop, evidenceEchoSessionRoute(row));
  }, [desktop]);

  useEffect(() => {
    if (!trimmedId) {
      setState('idle');
      setUsage(undefined);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setState('loading');
    void (async () => {
      try {
        const next = await collectEvidenceEchoUsage(transport, { appId, entityId: trimmedId }, {
          signal: controller.signal,
        });
        if (!active) return;
        setUsage(next);
        setState('ready');
      } catch {
        if (!active) return;
        setUsage(undefined);
        setState('failed');
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [appId, revision, transport, trimmedId]);

  if (!trimmedId) return null;

  const rows = usage?.rows ?? [];
  return (
    <section
      aria-label={entityLabel ? `${entityLabel} 最近被哪些 Session 装配` : '最近被哪些 Session 装配'}
      className="evidence-echo-usage"
      data-state={state}
    >
      <header>
        <span className="evidence-echo-usage__title">
          <GitBranch aria-hidden="true" size={14} />
          <strong>最近被哪些 Session 装配</strong>
        </span>
        <button
          aria-label="重新查找装配记录"
          className="evidence-echo-usage__refresh"
          disabled={state === 'loading'}
          onClick={() => setRevision((value) => value + 1)}
          type="button"
        >
          <RefreshCw className={state === 'loading' ? 'ui-spin' : undefined} size={13} />
        </button>
      </header>
      {state === 'loading' ? <p className="evidence-echo-usage__note" role="status">正在查找最近的装配记录…</p> : null}
      {state === 'failed' ? (
        <p className="evidence-echo-usage__note" role="status">装配记录暂时读不到，这不影响这条内容本身。</p>
      ) : null}
      {state === 'ready' && !rows.length ? (
        <p className="evidence-echo-usage__note" role="status">
          最近 {usage?.scannedSessionCount ?? 0} 段 Session 的 {usage?.scannedTraceCount ?? 0} 次上下文装配里没有用到这一条。
        </p>
      ) : null}
      {rows.length ? (
        <ol className="evidence-echo-usage__list">
          {rows.map((row) => (
            <li key={`${row.sessionId}:${row.traceId}:${row.nodeId}`}>
              <button
                aria-label={`打开 ${row.sessionTitle}，定位到装配节点 ${row.nodeLabel}`}
                data-disposition={row.disposition}
                onClick={() => openRow(row)}
                type="button"
              >
                <span className="evidence-echo-usage__session">{row.sessionTitle}</span>
                <span className="evidence-echo-usage__node">{row.nodeLabel}</span>
                <span className="evidence-echo-usage__meta">
                  {dispositionLabel(row.disposition)}
                  {row.atMs ? ` · ${formatUsageTime(row.atMs)}` : ''}
                </span>
              </button>
            </li>
          ))}
        </ol>
      ) : null}
      {rows.length && usage?.partial ? (
        <p className="evidence-echo-usage__note">
          只统计了最近 {usage.scannedSessionCount} 段 Session 的 {usage.scannedTraceCount} 次装配，更早的记录没有读取。
        </p>
      ) : null}
    </section>
  );
}

function dispositionLabel(disposition: EvidenceEchoUsageRow['disposition']): string {
  return ({
    included: '已进入上下文',
    omitted: '当轮未使用',
    redacted: '已脱敏',
    failed: '装配失败',
  } as const)[disposition] ?? '已记录';
}

function formatUsageTime(atMs: number): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(atMs);
}
