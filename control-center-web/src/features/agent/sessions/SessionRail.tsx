import { Folder, MessageSquarePlus, Search, X } from 'lucide-react';
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
  const groups = useMemo(() => projectGroups(sessions, query), [query, sessions]);
  const projectCount = new Set(sessions.map((session) => primaryRoot(session)).filter(Boolean)).size;
  return (
    <aside
      ref={ref}
      className="agent-session-rail"
      aria-label="任务与项目"
      aria-hidden={!open || blocked || undefined}
      aria-modal={modal || undefined}
      inert={!open || blocked ? true : undefined}
      role={modal ? 'dialog' : undefined}
      tabIndex={-1}
    >
      <header>
        <div><strong>任务</strong><small>{sessions.length} 个任务 · {projectCount} 个项目</small></div>
        <span className="agent-session-rail__actions">
          <IconButton label="新建任务" icon={<MessageSquarePlus size={17} />} onClick={onCreate} tooltip />
          {onClose ? <IconButton className="agent-session-rail__close" label="关闭任务列表" icon={<X size={17} />} onClick={onClose} /> : null}
        </span>
      </header>
      <label className="agent-session-search">
        <Search size={14} aria-hidden="true" />
        <input data-drawer-autofocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务或项目" />
      </label>
      <div className="agent-session-list" aria-busy={loading || undefined}>
        {groups.map((group) => (
          <section className="agent-session-project" key={group.root || 'unassigned'} data-selected={group.sessions.some((session) => session.id === selectedId) || undefined}>
            <header title={group.root || '旧任务尚未指定项目路径'}>
              <Folder size={15} />
              <strong>{group.label}</strong>
              <small>{group.sessions.length}</small>
            </header>
            {group.sessions.map((session) => (
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
          </section>
        ))}
      </div>
    </aside>
  );
});

function projectGroups(sessions: SessionSummary[], query: string): Array<{ root: string; label: string; sessions: SessionSummary[] }> {
  const needle = query.trim().toLowerCase();
  const groups = new Map<string, SessionSummary[]>();
  for (const session of sessions) {
    const root = primaryRoot(session);
    const haystack = `${session.title} ${session.lastMessagePreview ?? ''} ${root}`.toLowerCase();
    if (needle && !haystack.includes(needle)) continue;
    groups.set(root, [...(groups.get(root) ?? []), session]);
  }
  return [...groups].map(([root, items]) => ({
    root,
    label: root ? pathName(root) : '未指定项目',
    sessions: items,
  }));
}

function primaryRoot(session: SessionSummary): string {
  return session.workspaceRoots?.[0]?.trim() ?? '';
}

function pathName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) ?? path;
}

function relativeTime(value: number): string {
  const delta = Math.max(0, Date.now() - value);
  if (delta < 60_000) return '刚刚';
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} 分`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} 小时`;
  return `${Math.floor(delta / 86_400_000)} 天`;
}
