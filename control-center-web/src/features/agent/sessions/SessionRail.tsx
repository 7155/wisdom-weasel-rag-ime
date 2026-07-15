import { MessageSquarePlus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { IconButton } from '@/components/primitives';
import type { SessionSummary } from '../types';

export function SessionRail({
  sessions,
  selectedId,
  loading,
  onSelect,
  onCreate,
}: {
  sessions: SessionSummary[];
  selectedId: string;
  loading: boolean;
  onSelect: (sessionId: string) => void;
  onCreate: () => void;
}) {
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => sessions.filter((session) => {
    const value = `${session.title} ${session.lastMessagePreview ?? ''}`.toLowerCase();
    return value.includes(query.trim().toLowerCase());
  }), [query, sessions]);
  return (
    <aside className="agent-session-rail" aria-label="连续对话">
      <header>
        <div><strong>对话</strong><small>{sessions.length} 个连续对话</small></div>
        <IconButton label="新建对话" icon={<MessageSquarePlus size={17} />} onClick={onCreate} tooltip />
      </header>
      <label className="agent-session-search">
        <Search size={14} aria-hidden="true" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索对话" />
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
}

function relativeTime(value: number): string {
  const delta = Math.max(0, Date.now() - value);
  if (delta < 60_000) return '刚刚';
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} 分`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} 小时`;
  return `${Math.floor(delta / 86_400_000)} 天`;
}
