import {
  Archive,
  ArchiveRestore,
  ChevronDown,
  ChevronRight,
  Folder,
  MessageSquarePlus,
  LoaderCircle,
  MoreHorizontal,
  PanelsTopLeft,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import { forwardRef, useEffect, useMemo, useState, type ReactNode } from 'react';
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
  error?: string;
  open?: boolean;
  modal?: boolean;
  blocked?: boolean;
  showArchived?: boolean;
  onSelect: (sessionId: string) => void;
  onCreate: () => void;
  onShowArchivedChange?: (value: boolean) => void;
  onArchive?: (sessionId: string, archived: boolean) => void;
  onDelete?: (sessionId: string) => void | Promise<void>;
  onOpenWindow?: (session: SessionSummary) => void;
  onRetry?: () => void;
  onClose?: () => void;
}>(function SessionRail({
  sessions,
  selectedId,
  loading,
  error = '',
  open = true,
  modal = false,
  blocked = false,
  showArchived = false,
  onSelect,
  onCreate,
  onShowArchivedChange,
  onArchive,
  onDelete,
  onOpenWindow,
  onRetry,
  onClose,
}, ref) {
  const [query, setQuery] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<SessionSummary>();
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const [collapsedRoots, setCollapsedRoots] = useState<ReadonlySet<string>>(new Set());
  const visibleSessions = useMemo(
    () => sessions.filter((session) => !session.roomParticipant),
    [sessions],
  );
  const groups = useMemo(() => projectGroups(visibleSessions, query), [query, visibleSessions]);
  const projectCount = new Set(visibleSessions.map((session) => primaryRoot(session)).filter(Boolean)).size;
  const selectedRoot = useMemo(
    () => primaryRoot(visibleSessions.find((session) => session.id === selectedId)),
    [selectedId, visibleSessions],
  );
  useEffect(() => {
    setCollapsedRoots((current) => {
      if (!current.has(selectedRoot)) return current;
      const next = new Set(current);
      next.delete(selectedRoot);
      return next;
    });
  }, [selectedId, selectedRoot]);

  function toggleProject(root: string): void {
    setCollapsedRoots((current) => {
      const next = new Set(current);
      if (next.has(root)) next.delete(root);
      else next.add(root);
      return next;
    });
  }

  return (
    <aside
      ref={ref}
      className="agent-session-rail"
      aria-label="对话与项目"
      aria-hidden={!open || blocked || undefined}
      aria-modal={modal || undefined}
      inert={!open || blocked ? true : undefined}
      role={modal ? 'dialog' : undefined}
      tabIndex={-1}
    >
      <header>
        <div><strong>对话</strong><small>{visibleSessions.length} 段对话 · {projectCount} 个项目</small></div>
        <span className="agent-session-rail__actions">
          <IconButton label="新建对话" icon={<MessageSquarePlus size={17} />} onClick={onCreate} tooltip />
          <Menu>
            <MenuTrigger asChild>
              <IconButton label="对话列表选项" icon={<MoreHorizontal size={17} />} tooltip />
            </MenuTrigger>
            <MenuContent align="end">
              <MenuCheckboxItem checked={showArchived} onCheckedChange={(checked) => onShowArchivedChange?.(checked === true)}>
                显示已归档对话
              </MenuCheckboxItem>
            </MenuContent>
          </Menu>
          {onClose ? <IconButton className="agent-session-rail__close" label="关闭对话列表" icon={<X size={17} />} onClick={onClose} /> : null}
        </span>
      </header>
      <label className="agent-session-search">
        <Search size={14} aria-hidden="true" />
        <input aria-label="搜索对话或项目" data-drawer-autofocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索对话或项目" />
      </label>
      <div className="agent-session-list" aria-busy={loading || undefined}>
        {loading && visibleSessions.length === 0 ? (
          <SessionRailState
            icon={<LoaderCircle className="ui-spin" size={18} />}
            message="正在读取这台设备上的对话"
            role="status"
            title="正在加载"
          />
        ) : null}
        {error ? (
          <SessionRailState
            action={onRetry ? <Button size="small" onClick={onRetry}>重新读取</Button> : null}
            message={error}
            role="alert"
            title="对话列表暂时不可用"
          />
        ) : null}
        {!loading && !error && visibleSessions.length === 0 ? (
          <SessionRailState
            action={<Button size="small" onClick={onCreate}>新建第一段对话</Button>}
            message={showArchived ? '当前没有可显示的对话。' : '新建一段对话开始工作；历史归档不会混入当前列表。'}
            title="还没有对话"
          />
        ) : null}
        {!loading && !error && visibleSessions.length > 0 && groups.length === 0 ? (
          <SessionRailState
            action={<Button size="small" variant="quiet" onClick={() => setQuery('')}>清除搜索</Button>}
            message="换一个关键词，或清除搜索查看全部对话。"
            title="没有匹配的对话"
          />
        ) : null}
        {groups.map((group, groupIndex) => {
          const collapsed = collapsedRoots.has(group.root);
          const groupId = `agent-session-project-${groupIndex}`;
          return (
            <section className="agent-session-project" key={group.root || 'unassigned'} data-selected={group.sessions.some((session) => session.id === selectedId) || undefined}>
              <button
                type="button"
                className="agent-session-project__toggle"
                aria-controls={groupId}
                aria-expanded={!collapsed}
                onClick={() => toggleProject(group.root)}
                title={group.root || '这些对话没有关联工作目录'}
              >
                {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                <Folder size={15} />
                <strong>{group.label}</strong>
                <small>{group.sessions.length}</small>
              </button>
              <div className="agent-session-project__sessions" hidden={collapsed} id={groupId}>
                {group.sessions.map((session, sessionIndex) => {
                  const titleId = `agent-session-title-${groupIndex}-${sessionIndex}`;
                  const previewId = `${titleId}-preview`;
                  const timeId = `${titleId}-time`;
                  const preview = session.lastMessagePreview || `${session.messageCount ?? 0} 条消息`;
                  const updated = relativeTime(session.updatedAtMs);
                  const updatedDate = new Date(session.updatedAtMs);
                  const archived = session.status === 'archived';
                  return (
                    <div className="agent-session-row-shell" data-selected={selectedId === session.id || undefined} key={session.id}>
                      <button
                        type="button"
                        className="agent-session-row"
                        aria-current={selectedId === session.id ? 'true' : undefined}
                        aria-labelledby={titleId}
                        aria-describedby={`${previewId} ${timeId}`}
                        onClick={() => onSelect(session.id)}
                        title={`${session.title} · ${updated}`}
                      >
                        <span className="agent-session-row__status" data-status={session.status} aria-hidden="true" />
                        <span className="agent-session-row__copy">
                          <span className="agent-session-row__heading">
                            <strong id={titleId}>{session.title}</strong>
                            <time id={timeId} dateTime={updatedDate.toISOString()} title={updatedDate.toLocaleString()}>
                              {updated}
                            </time>
                          </span>
                          <small id={previewId} title={session.lastMessagePreview || undefined}>{preview}</small>
                        </span>
                      </button>
                      {!session.roomParticipant ? (
                        <Menu>
                          <MenuTrigger asChild>
                            <IconButton
                              className="agent-session-row__menu"
                              label={`更多“${session.title}”操作`}
                              icon={<MoreHorizontal size={16} />}
                              size="small"
                              title={`更多“${session.title}”操作`}
                            />
                          </MenuTrigger>
                          <MenuContent align="end" aria-label={`${session.title} 对话操作`}>
                            {onOpenWindow ? (
                              <MenuItem aria-describedby={titleId} onSelect={() => onOpenWindow(session)}>
                                <PanelsTopLeft size={15} />
                                独立窗口
                              </MenuItem>
                            ) : null}
                            {onArchive ? (
                              <>
                                {onOpenWindow ? <MenuSeparator /> : null}
                                <MenuItem
                                  aria-describedby={titleId}
                                  onSelect={() => onArchive(session.id, !archived)}
                                >
                                  {archived ? <ArchiveRestore size={15} /> : <Archive size={15} />}
                                  {archived ? '恢复对话' : '归档对话'}
                                </MenuItem>
                                <MenuSeparator />
                              </>
                            ) : null}
                            <MenuItem className="agent-session-row__delete" aria-describedby={titleId} onSelect={() => {
                              setDeleteError('');
                              setDeleteTarget(session);
                            }}>
                              <Trash2 size={15} />
                              删除对话
                            </MenuItem>
                          </MenuContent>
                        </Menu>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => {
        if (!open && !deleting) {
          setDeleteError('');
          setDeleteTarget(undefined);
        }
      }}>
        <DialogContent className="agent-session-delete-dialog">
          <DialogHeader>
            <DialogTitle>删除“{deleteTarget?.title ?? '对话'}”</DialogTitle>
            <DialogDescription>将删除这段对话及其本地附件。暂时不想看到它，可以先归档。</DialogDescription>
          </DialogHeader>
          {deleteError ? <p className="agent-session-delete-dialog__error" role="alert">{deleteError}</p> : null}
          <DialogFooter>
            <Button variant="quiet" disabled={deleting} onClick={() => {
              setDeleteError('');
              setDeleteTarget(undefined);
            }}>取消</Button>
            <Button variant="danger" loading={deleting} leadingIcon={<Trash2 size={15} />} onClick={async () => {
              if (!deleteTarget) return;
              setDeleting(true);
              setDeleteError('');
              try {
                await onDelete?.(deleteTarget.id);
                setDeleteTarget(undefined);
              } catch (error) {
                setDeleteError(error instanceof Error && error.message.trim()
                  ? error.message
                  : '删除未完成，请检查连接后重试。对话仍保留在列表中。');
              } finally {
                setDeleting(false);
              }
            }}>删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  );
});

function SessionRailState({
  action,
  icon,
  message,
  role,
  title,
}: {
  action?: ReactNode;
  icon?: ReactNode;
  message: string;
  role?: 'alert' | 'status';
  title: string;
}) {
  return (
    <div className="agent-session-list__state" role={role}>
      {icon ? <span aria-hidden="true">{icon}</span> : null}
      <strong>{title}</strong>
      <small>{message}</small>
      {action ? <div>{action}</div> : null}
    </div>
  );
}

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

function primaryRoot(session: SessionSummary | undefined): string {
  return session?.workspaceRoots?.[0]?.trim() ?? '';
}

function pathName(path: string): string {
  const segments = path.split('/').filter(Boolean);
  const leaf = segments.at(-1) ?? path;
  if (['workspace', 'project', 'repo', 'repository'].includes(leaf.toLowerCase()) && segments.length > 1) {
    return `${segments.at(-2)} / ${leaf}`;
  }
  return leaf;
}

function relativeTime(value: number): string {
  const delta = Math.max(0, Date.now() - value);
  if (delta < 60_000) return '刚刚';
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} 分`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} 小时`;
  return `${Math.floor(delta / 86_400_000)} 天`;
}
