import { X } from 'lucide-react';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useOptionalControlTransport } from '@/app/control-transport';
import {
  Popover,
  PopoverClose,
  PopoverContent,
  PopoverTrigger,
} from '@/components/primitives';
import { normalizeDebugContextResponse } from '@/features/context-debug/model';
import { buildContextXraySnapshot, type ContextXraySnapshot } from './ContextXrayPanel';
import {
  buildContextUsageView,
  formatContextTokenCount,
  type ContextUsageView,
} from './context-usage-model';
import './ContextUsagePopover.css';

export type ContextUsageTelemetry = {
  tokens: number | null;
  contextWindow: number;
  percent: number | null;
  compactionCount?: number;
  latestCompaction?: {
    status: string;
    tokensBefore?: number;
    estimatedTokensAfter?: number;
  };
};

export function ContextUsagePopover({
  sessionId,
  telemetry,
}: {
  sessionId?: string;
  telemetry?: ContextUsageTelemetry | null;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [snapshot, setSnapshot] = useState<ContextXraySnapshot | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const transport = useOptionalControlTransport();
  const view = useMemo(
    () => buildContextUsageView({ telemetry, snapshot }),
    [snapshot, telemetry],
  );

  useEffect(() => {
    if (!open || !sessionId || !transport) return;
    let cancelled = false;
    setLoading(true);
    void transport.request({
      pathId: 'agent.session.debugContext.get',
      params: { sessionId },
    }).then((value) => {
      if (cancelled) return;
      setSnapshot(buildContextXraySnapshot(normalizeDebugContextResponse(value)));
    }, () => {
      if (!cancelled) setSnapshot(null);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [open, sessionId, transport]);

  if (!sessionId) return null;
  const filled = view.percent === null ? 0 : Math.min(100, Math.max(0, view.percent));
  const triggerLabel = view.percent === null
    ? '上下文用量'
    : `上下文已用 ${Math.round(view.percent)}%`;

  return (
    <Popover onOpenChange={setOpen} open={open}>
      <div className="agent-context-usage" ref={rootRef}>
        <PopoverTrigger asChild>
          <button
            aria-label={triggerLabel}
            className="agent-context-usage__trigger"
            ref={triggerRef}
            type="button"
          >
            <span aria-hidden="true" className="agent-context-usage__spark">
              <i style={{ width: `${filled}%` }} />
            </span>
            <span className="agent-context-usage__label">
              {view.percent === null ? 'Context' : `${Math.round(view.percent)}%`}
            </span>
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          aria-label="Context Usage"
          className="agent-context-usage__popover"
          collisionBoundary={rootRef.current?.closest<HTMLElement>('.paw-window-body') ?? undefined}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            triggerRef.current?.focus();
          }}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            closeRef.current?.focus();
          }}
          side="top"
          sideOffset={10}
        >
          <header className="agent-context-usage__header">
            <strong>Context Usage</strong>
            <PopoverClose asChild>
              <button aria-label="关闭上下文用量" ref={closeRef} type="button">
                <X size={15} />
              </button>
            </PopoverClose>
          </header>
          <ContextUsageBody loading={loading} view={view} />
        </PopoverContent>
      </div>
    </Popover>
  );
}

function ContextUsageBody({
  loading,
  view,
}: {
  loading: boolean;
  view: ContextUsageView;
}) {
  if (!view.available && loading) {
    return <p className="agent-context-usage__empty">正在读取上下文占用…</p>;
  }
  if (!view.available) {
    return <p className="agent-context-usage__empty">下一轮模型响应后显示精确上下文占用</p>;
  }

  const used = view.tokens ?? 0;
  const dominantId = view.segments.reduce<string | null>((best, segment) => {
    if (!best) return segment.id;
    const current = view.segments.find((item) => item.id === best);
    return (current?.characters ?? 0) >= segment.characters ? best : segment.id;
  }, null);
  const barTotal = Math.max(view.contextWindow, used, 1);
  const characterTotal = Math.max(view.capturedCharacters, 1);

  return (
    <>
      <div className="agent-context-usage__summary">
        <b>{view.percent === null ? '占用未知' : `${Math.round(view.percent)}% Full`}</b>
        <span>
          ~
          {formatContextTokenCount(used)}
          {' / '}
          {formatContextTokenCount(view.contextWindow)}
          {' Tokens'}
        </span>
      </div>
      <div aria-hidden="true" className="agent-context-usage__bar">
        {used > 0 ? <i data-used style={{ width: `${(used / barTotal) * 100}%` }} /> : null}
        {view.freeTokens > 0 ? (
          <i data-free style={{ flex: view.freeTokens / barTotal }} />
        ) : null}
      </div>
      {view.segments.length ? (
        <>
          <p className="agent-context-usage__composition-label">捕获字符构成（非 Token）</p>
          <div aria-hidden="true" className="agent-context-usage__composition">
            {view.segments.map((segment) => (
              <i
                key={segment.id}
                style={{
                  background: segment.color,
                  width: `${Math.max(0.6, (segment.characters / characterTotal) * 100)}%`,
                }}
              />
            ))}
          </div>
          <ul className="agent-context-usage__list" aria-label="上下文分层占用">
            {view.segments.map((segment) => (
              <li data-dominant={segment.id === dominantId || undefined} key={segment.id}>
                <span aria-hidden="true" className="agent-context-usage__swatch" style={{ background: segment.color }} />
                <strong>{segment.label}</strong>
                <span className="agent-context-usage__metric">
                  <b>{formatCharacterCount(segment.characters)} 字符</b>
                  <small>Token 未单独统计</small>
                </span>
              </li>
            ))}
          </ul>
          <p className="agent-context-usage__note">总 Token 仅有整轮统计，不能可靠分摊到各层。</p>
        </>
      ) : (
        <p className="agent-context-usage__note">已有整轮总占用；分层内容尚不可用，Token 未单独统计。</p>
      )}
      {view.compaction ? (
        <p className="agent-context-usage__note" data-compaction={view.compaction.status || undefined}>
          最近压缩
          {view.compaction.count > 0 ? ` · 第 ${view.compaction.count} 次` : ''}
          {view.compaction.tokensBefore !== null ? ` · ${formatContextTokenCount(view.compaction.tokensBefore)}` : ''}
          {view.compaction.tokensAfter !== null ? ` → 约 ${formatContextTokenCount(view.compaction.tokensAfter)}` : ''}
        </p>
      ) : null}
    </>
  );
}

function formatCharacterCount(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(Math.max(0, value));
}
