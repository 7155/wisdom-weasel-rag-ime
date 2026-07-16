import { MessageSquarePlus, Search, X } from 'lucide-react';
import { forwardRef, useMemo, useState } from 'react';
import { IconButton } from '@/components/primitives';
import type { SessionSummary } from '../types';

export const SessionRail = forwardRef<HTMLElement, {
  sessions: SessionSummary[];
  selectedId: string;
  loading: boolean;
  open?: boolean;
  modal?: boolean;
  blocked?: boolean;
  onSelect: (sessionId: string) => void;
  onCreate: () => void;
  onClose?: () => void;
}>(function SessionRail({
  sessions,
  selectedId,
  loading,
  open = true,
  modal = false,
  blocked = false,
  onSelect,
  onCreate,
  onClose,
}, ref) {
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => sessions.filter((session) => {
    const value = `${session.title} ${session.lastMessagePreview ?? ''}`.toLowerCase();
    return value.includes(query.trim().toLowerCase());
  }), [query, sessions]);
  return (
    <aside
      ref={ref}
      className="agent-session-rail"
      aria-label="连续对话"
      aria-hidden={!open || blocked || undefined}
      aria-modal={modal || undefined}
      inert={!open || blocked ? true : undefined}
      role={modal ? 'dialog' : undefined}
      tabIndex={-1}
    >
      <header>
        <div><strong>对话</strong><small>{sessions.length} 个连续对话</small></div>
        <span className="agent-session-rail__actions">
          <IconButton label="新建对话" icon={<MessageSquarePlus size={17} />} onClick={onCreate} tooltip />
          {onClose ? <IconButton className="agent-session-rail__close" label="关闭对话列表" icon={<X size={17} />} onClick={onClose} /> : null}
        </span>
      </header>
      <label className="agent-session-search">
        <Search size={14} aria-hidden="true" />
        <input data-drawer-autofocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索对话" />
      </label>
      <div className="agent-session-list" aria-busy={loading || undefined}>
        {filtered.map((session) => (
          <button
            type="button"
            key={session.id}
            className="agent-session-row"
            aria-current={selectedId === session.id ? 'true' : undefined}
            onClick={() => onSelect(session.id)}
          >
            <span className="agent-session-row__status" data-status={session.status} aria-hidden="true" />
            <span className="agent-session-row__copy">
              <strong>{session.title}</strong>
              <small>{session.lastMessagePreview || `${session.messageCount ?? 0} 条消息`}</small>
            </span>
            <time>{relativeTime(session.updatedAtMs)}</time>
          </button>
        ))}
      </div>
    </aside>
  );
});

function relativeTime(value: number): string {
  const delta = Math.max(0, Date.now() - value);
  if (delta < 60_000) return '刚刚';
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} 分`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} 小时`;
  return `${Math.floor(delta / 86_400_000)} 天`;
}
