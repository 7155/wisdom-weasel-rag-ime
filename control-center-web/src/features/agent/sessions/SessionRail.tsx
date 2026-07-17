import { Archive, ArchiveRestore, Folder, MessageSquarePlus, MoreHorizontal, Search, Trash2, X } from 'lucide-react';
import { forwardRef, useMemo, useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  IconButton,
  Menu,
  MenuCheckboxItem,
  MenuContent,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
} from '@/components/primitives';
import type { SessionSummary } from '../types';

export const SessionRail = forwardRef<HTMLElement, {
  sessions: SessionSummary[];
  selectedId: string;
  loading: boolean;
  open?: boolean;
  modal?: boolean;
  blocked?: boolean;
  showArchived?: boolean;
  onSelect: (sessionId: string) => void;
  onCreate: () => void;
  onShowArchivedChange?: (value: boolean) => void;
  onArchive?: (sessionId: string, archived: boolean) => void;
  onDelete?: (sessionId: string) => void;
  onClose?: () => void;
}>(function SessionRail({
  sessions,
  selectedId,
  loading,
  open = true,
  modal = false,
  blocked = false,
  showArchived = false,
  onSelect,
  onCreate,
  onShowArchivedChange,
  onArchive,
  onDelete,
  onClose,
}, ref) {
  const [query, setQuery] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<SessionSummary>();
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
          <Menu>
            <MenuTrigger asChild>
              <IconButton label="任务列表选项" icon={<MoreHorizontal size={17} />} tooltip />
            </MenuTrigger>
            <MenuContent align="end">
              <MenuCheckboxItem checked={showArchived} onCheckedChange={(checked) => onShowArchivedChange?.(checked === true)}>
                显示已归档任务
              </MenuCheckboxItem>
            </MenuContent>
          </Menu>
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
              <div className="agent-session-row-shell" data-selected={selectedId === session.id || undefined} key={session.id}>
                <button
                  type="button"
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
                <Menu>
                  <MenuTrigger asChild>
                    <IconButton className="agent-session-row__menu" label="更多任务操作" icon={<MoreHorizontal size={16} />} size="small" title={session.title} />
                  </MenuTrigger>
                  <MenuContent align="end">
                    <MenuItem onSelect={() => onArchive?.(session.id, session.status !== 'archived')}>
                      {session.status === 'archived' ? <ArchiveRestore size={15} /> : <Archive size={15} />}
                      {session.status === 'archived' ? '恢复任务' : '归档任务'}
                    </MenuItem>
                    <MenuSeparator />
                    <MenuItem className="agent-session-row__delete" onSelect={() => setDeleteTarget(session)}>
                      <Trash2 size={15} />
                      删除任务
                    </MenuItem>
                  </MenuContent>
                </Menu>
              </div>
            ))}
          </section>
        ))}
      </div>
      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open) setDeleteTarget(undefined); }}>
        <DialogContent className="agent-session-delete-dialog">
          <DialogHeader>
            <DialogTitle>删除“{deleteTarget?.title ?? '任务'}”</DialogTitle>
            <DialogDescription>将删除这条对话及其本地附件。需要暂时隐藏时，请改用归档。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="quiet" onClick={() => setDeleteTarget(undefined)}>取消</Button>
            <Button variant="danger" leadingIcon={<Trash2 size={15} />} onClick={() => {
              if (deleteTarget) onDelete?.(deleteTarget.id);
              setDeleteTarget(undefined);
            }}>删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
