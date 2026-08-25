import { X } from 'lucide-react';
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useOptionalControlTransport } from '@/app/control-transport';
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
  const panelId = useId();
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

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node) || !rootRef.current?.contains(target)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  if (!sessionId) return null;
  const filled = view.percent === null ? 0 : Math.min(100, Math.max(0, view.percent));
  const triggerLabel = view.percent === null
    ? '上下文用量'
    : `上下文已用 ${Math.round(view.percent)}%`;

  return (
    <div className="agent-context-usage" ref={rootRef}>
      <button
        aria-controls={open ? panelId : undefined}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={triggerLabel}
        className="agent-context-usage__trigger"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span aria-hidden="true" className="agent-context-usage__spark">
          <i style={{ width: `${filled}%` }} />
        </span>
        <span>{view.percent === null ? 'Context' : `${Math.round(view.percent)}%`}</span>
      </button>
      {open ? (
        <div
          aria-label="Context Usage"
          className="agent-context-usage__popover"
          id={panelId}
          onKeyDown={(event: ReactKeyboardEvent) => {
            if (event.key === 'Escape') {
              event.stopPropagation();
              setOpen(false);
            }
          }}
          role="dialog"
        >
          <header className="agent-context-usage__header">
            <strong>Context Usage</strong>
            <button aria-label="关闭上下文用量" onClick={() => setOpen(false)} type="button">
              <X size={15} />
            </button>
          </header>
          <ContextUsageBody loading={loading} view={view} />
        </div>
      ) : null}
    </div>
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

  const used = view.tokens ?? view.segments.reduce((sum, segment) => sum + segment.tokens, 0);
  const dominantId = view.segments.reduce<string | null>((best, segment) => {
    if (!best) return segment.id;
    const current = view.segments.find((item) => item.id === best);
    return (current?.tokens ?? 0) >= segment.tokens ? best : segment.id;
  }, null);
  const barTotal = Math.max(view.contextWindow, used);

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
        {view.segments.map((segment) => (
          <i
            key={segment.id}
            style={{
              background: segment.color,
              width: `${Math.max(0.6, (segment.tokens / barTotal) * 100)}%`,
            }}
            title={`${segment.label}: ${formatContextTokenCount(segment.tokens)}`}
          />
        ))}
        {view.freeTokens > 0 ? (
          <i data-free style={{ flex: view.freeTokens / barTotal }} />
        ) : null}
      </div>
      {view.segments.length ? (
        <ul className="agent-context-usage__list" aria-label="上下文分层占用">
          {view.segments.map((segment) => (
            <li data-dominant={segment.id === dominantId || undefined} key={segment.id}>
              <span aria-hidden="true" className="agent-context-usage__swatch" style={{ background: segment.color }} />
              <strong>{segment.label}</strong>
              <b>{formatContextTokenCount(segment.tokens)}</b>
            </li>
          ))}
        </ul>
      ) : (
        <p className="agent-context-usage__note">已有总占用，分层明细需调试上下文快照</p>
      )}
    </>
  );
}
