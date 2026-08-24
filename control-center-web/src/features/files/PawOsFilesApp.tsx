import {
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardCopy,
  Copy,
  File,
  FileCode2,
  FileSymlink,
  Folder,
  FolderOpen,
  LoaderCircle,
  RefreshCw,
  Search,
  TriangleAlert,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { CodePreview } from '@/features/agent/file-preview/CodePreview';
import { DiffPreview } from '@/features/agent/file-preview/DiffPreview';
import { MarkdownPreview } from '@/features/agent/file-preview/MarkdownPreview';
import { RichHtmlPreview } from '@/features/agent/file-preview/RichHtmlPreview';
import '@/features/agent/file-preview/file-preview.css';
import { sessionItems, type SessionSummary } from '@/features/agent/types';
import { PawWindowChromePortal, usePawWindowChromeTarget } from '@/paw-os/shell/PawWindowChrome';
import { writeClipboardText } from '@/platform/clipboard';
import './paw-os-files-app.css';

interface WorkspaceEntry {
  path: string;
  name: string;
  kind: 'directory' | 'file' | 'symlink';
  byteSize?: number;
}

interface WorkspaceFile {
  path: string;
  content: string;
  byteSize: number;
  truncated: boolean;
}

interface VisibleTreeNode {
  path: string;
  parentPath: string | null;
  kind: 'root' | WorkspaceEntry['kind'];
}

export function PawOsFilesApp() {
  const transport = useControlTransport();
  const windowChromeTarget = usePawWindowChromeTarget();
  const generationRef = useRef(0);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState('');
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionError, setSessionError] = useState('');
  const [entries, setEntries] = useState<Record<string, WorkspaceEntry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [pathErrors, setPathErrors] = useState<Record<string, string>>({});
  const [selectedFile, setSelectedFile] = useState<WorkspaceEntry | null>(null);
  const [preview, setPreview] = useState<WorkspaceFile | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [treeFocusPath, setTreeFocusPath] = useState('');
  const [copiedPathFor, setCopiedPathFor] = useState('');
  const [copiedContentFor, setCopiedContentFor] = useState('');
  const [filterQuery, setFilterQuery] = useState('');
  const treeItemRefs = useRef(new Map<string, HTMLButtonElement>());
  const treeRef = useRef<HTMLElement | null>(null);
  const backButtonRef = useRef<HTMLButtonElement | null>(null);
  const returnFocusPathRef = useRef('');
  const typeaheadRef = useRef({ text: '', at: 0 });
  const selectedSession = sessions.find((session) => session.id === selectedSessionId) ?? null;
  const roots = useMemo(() => authorizedRoots(selectedSession), [selectedSession]);
  const visibleTreeNodes = useMemo(
    () => flattenVisibleTree(roots, entries, expanded),
    [entries, expanded, roots],
  );
  const visibleEntryCount = useMemo(() => {
    const paths = new Set<string>();
    for (const children of Object.values(entries)) {
      for (const entry of children) paths.add(entry.path);
    }
    return paths.size;
  }, [entries]);

  // The filter only sees directories that have already been read; the result
  // meta states that coverage truthfully instead of implying a full-disk find.
  const filterMatches = useMemo(() => {
    const query = filterQuery.trim().toLocaleLowerCase();
    if (!query) return null;
    const matches: WorkspaceEntry[] = [];
    for (const children of Object.values(entries)) {
      for (const entry of children) {
        if (entry.name.toLocaleLowerCase().includes(query)) matches.push(entry);
      }
    }
    return matches.sort((first, second) => first.path.localeCompare(second.path, undefined, { numeric: true, sensitivity: 'base' }));
  }, [entries, filterQuery]);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    setSessionError('');
    try {
      const response = await transport.request({
        pathId: 'agent.sessions.list',
        query: { limit: 100, includeArchived: false },
      });
      const next = sessionItems(response);
      setSessions(next);
      const activeId = isRecord(response) && typeof response.activeSessionId === 'string'
        ? response.activeSessionId
        : '';
      setSelectedSessionId((current) => {
        if (next.some((session) => session.id === current && authorizedRoots(session).length)) return current;
        if (next.some((session) => session.id === activeId && authorizedRoots(session).length)) return activeId;
        return next.find((session) => authorizedRoots(session).length)?.id ?? next[0]?.id ?? '';
      });
    } catch (error) {
      setSessionError(publicError(error, 'Session 列表读取失败。'));
    } finally {
      setSessionsLoading(false);
    }
  }, [transport]);

  const loadDirectory = useCallback(async (path: string, force = false) => {
    if (!selectedSessionId || loadingPaths.has(path) || (!force && entries[path])) return;
    setLoadingPaths((current) => new Set(current).add(path));
    setPathErrors((current) => omitKey(current, path));
    try {
      const response = await transport.request({
        pathId: 'agent.session.workspace.list',
        params: { sessionId: selectedSessionId },
        query: { path, depth: 1, limit: 240 },
      });
      setEntries((current) => ({ ...current, [path]: sortedEntries(workspaceEntries(response)) }));
    } catch (error) {
      setPathErrors((current) => ({ ...current, [path]: publicError(error, '目录读取失败。') }));
    } finally {
      setLoadingPaths((current) => {
        const next = new Set(current);
        next.delete(path);
        return next;
      });
    }
  }, [entries, loadingPaths, selectedSessionId, transport]);

  useEffect(() => { void loadSessions(); }, [loadSessions]);

  useEffect(() => {
    generationRef.current += 1;
    setEntries({});
    setPathErrors({});
    setExpanded(new Set(roots));
    setSelectedFile(null);
    setPreview(null);
    setFilterQuery('');
    for (const root of roots) void loadDirectory(root);
    // Directory state is intentionally reset whenever Session authority changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSessionId, roots.join('\u0000')]);

  useEffect(() => {
    setTreeFocusPath((current) => {
      if (visibleTreeNodes.some((node) => node.path === current)) return current;
      if (selectedFile && visibleTreeNodes.some((node) => node.path === selectedFile.path)) return selectedFile.path;
      return visibleTreeNodes[0]?.path ?? '';
    });
  }, [selectedFile, visibleTreeNodes]);

  const loadPreview = useCallback(async (file: WorkspaceEntry) => {
    if (!selectedSessionId) return;
    const generation = ++generationRef.current;
    setPreviewLoading(true);
    setPreviewError('');
    try {
      const response = await transport.request({
        pathId: 'agent.session.workspace.read',
        params: { sessionId: selectedSessionId },
        query: { path: file.path, offset: 0, limit: 65_536 },
      });
      if (generation === generationRef.current) setPreview(workspaceFile(response, file.path));
    } catch (error) {
      if (generation === generationRef.current) {
        setPreview(null);
        setPreviewError(publicError(error, '文件读取失败。'));
      }
    } finally {
      if (generation === generationRef.current) setPreviewLoading(false);
    }
  }, [selectedSessionId, transport]);

  useEffect(() => {
    if (!selectedFile) return;
    void loadPreview(selectedFile);
  }, [loadPreview, selectedFile]);

  function toggleDirectory(path: string): void {
    const willExpand = !expanded.has(path);
    setExpanded((current) => {
      const next = new Set(current);
      if (willExpand) next.add(path);
      else next.delete(path);
      return next;
    });
    if (willExpand) void loadDirectory(path);
  }

  function refresh(): void {
    const pathsToRefresh = new Set([...roots, ...expanded]);
    setEntries({});
    for (const path of pathsToRefresh) void loadDirectory(path, true);
  }

  function focusTreeItem(path: string): void {
    setTreeFocusPath(path);
    treeItemRefs.current.get(path)?.focus();
  }

  function treeHidden(): boolean {
    const tree = treeRef.current;
    return Boolean(tree && window.getComputedStyle(tree).display === 'none');
  }

  function goBackToTree(): void {
    if (!selectedFile) return;
    returnFocusPathRef.current = selectedFile.path;
    setSelectedFile(null);
  }

  async function copySelectedPath(): Promise<void> {
    if (!selectedFile) return;
    try {
      await writeClipboardText(selectedFile.path);
      setCopiedPathFor(selectedFile.path);
      window.setTimeout(() => setCopiedPathFor((current) => current === selectedFile.path ? '' : current), 1_500);
    } catch {
      // The full path remains available through the row/header title when the
      // clipboard is denied; the inspection flow is never blocked by copy.
    }
  }

  async function copySelectedContent(): Promise<void> {
    if (!selectedFile || !preview) return;
    try {
      await writeClipboardText(preview.content);
      setCopiedContentFor(selectedFile.path);
      window.setTimeout(() => setCopiedContentFor((current) => current === selectedFile.path ? '' : current), 1_500);
    } catch {
      // The reader keeps the content on screen when the clipboard is denied.
    }
  }

  function openFilterMatch(entry: WorkspaceEntry): void {
    if (entry.kind !== 'directory') {
      setSelectedFile(entry);
      return;
    }
    setExpanded((current) => {
      const next = new Set(current);
      for (const ancestor of ancestorDirectories(entry.path, roots)) next.add(ancestor);
      next.add(entry.path);
      return next;
    });
    void loadDirectory(entry.path);
    setFilterQuery('');
    returnFocusPathRef.current = entry.path;
  }

  // When the narrow layout swaps the tree for the reader, focus travels with
  // the content; going back restores focus to the row that opened the file.
  useEffect(() => {
    if (selectedFile && treeHidden()) backButtonRef.current?.focus();
  }, [selectedFile]);

  useEffect(() => {
    if (selectedFile) return;
    const path = returnFocusPathRef.current;
    if (!path) return;
    returnFocusPathRef.current = '';
    focusTreeItem(path);
  });

  function onTreeKeyDown(event: KeyboardEvent<HTMLButtonElement>, path: string): void {
    const index = visibleTreeNodes.findIndex((node) => node.path === path);
    const node = visibleTreeNodes[index];
    if (!node) return;

    if (event.key.length === 1 && event.key !== ' ' && !event.metaKey && !event.ctrlKey && !event.altKey) {
      const now = Date.now();
      const buffer = now - typeaheadRef.current.at < 700 ? typeaheadRef.current.text + event.key : event.key;
      typeaheadRef.current = { text: buffer, at: now };
      const query = (/^(.)\1+$/.test(buffer) ? buffer.charAt(0) : buffer).toLowerCase();
      const ordered = [...visibleTreeNodes.slice(index + 1), ...visibleTreeNodes.slice(0, index + 1)];
      const match = ordered.find((candidate) => pathName(candidate.path).toLowerCase().startsWith(query));
      if (match) {
        event.preventDefault();
        focusTreeItem(match.path);
      }
      return;
    }

    let nextPath = '';

    if (event.key === 'ArrowDown') nextPath = visibleTreeNodes[Math.min(index + 1, visibleTreeNodes.length - 1)]?.path ?? '';
    if (event.key === 'ArrowUp') nextPath = visibleTreeNodes[Math.max(index - 1, 0)]?.path ?? '';
    if (event.key === 'Home') nextPath = visibleTreeNodes[0]?.path ?? '';
    if (event.key === 'End') nextPath = visibleTreeNodes.at(-1)?.path ?? '';
    if (event.key === 'ArrowRight' && (node.kind === 'root' || node.kind === 'directory')) {
      if (!expanded.has(path)) toggleDirectory(path);
      else nextPath = visibleTreeNodes.find((candidate) => candidate.parentPath === path)?.path ?? '';
    }
    if (event.key === 'ArrowLeft') {
      if ((node.kind === 'root' || node.kind === 'directory') && expanded.has(path)) toggleDirectory(path);
      else nextPath = node.parentPath ?? '';
    }
    if (!nextPath && !['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    if (!nextPath && !((node.kind === 'root' || node.kind === 'directory') && ['ArrowLeft', 'ArrowRight'].includes(event.key))) return;
    event.preventDefault();
    if (nextPath) focusTreeItem(nextPath);
  }

  function renderChildren(parent: string, depth: number): ReactNode {
    if (loadingPaths.has(parent) && !entries[parent]) return <TreeState loading>正在读取目录…</TreeState>;
    if (pathErrors[parent] && !entries[parent]) {
      return <TreeState error={pathErrors[parent]} onRetry={() => void loadDirectory(parent, true)} />;
    }
    if (!entries[parent]?.length) return <TreeState>空目录</TreeState>;
    return (
      <ul role="group">
        {entries[parent].map((entry) => {
          const directory = entry.kind === 'directory';
          const symlink = entry.kind === 'symlink';
          const open = directory && expanded.has(entry.path);
          return (
            <li key={entry.path} role="none">
              <button
                aria-expanded={directory ? open : undefined}
                aria-label={directory ? `${open ? '收起' : '展开'}目录 ${entry.name}` : symlink ? `打开符号链接 ${entry.name}` : `打开文件 ${entry.name}`}
                aria-level={depth + 1}
                aria-selected={!directory ? entry.path === selectedFile?.path : undefined}
                className="paw-files-tree__row"
                data-ext={directory ? undefined : fileExtension(entry.name) || undefined}
                data-kind={symlink ? 'symlink' : undefined}
                data-selected={!directory && entry.path === selectedFile?.path || undefined}
                onClick={() => directory ? toggleDirectory(entry.path) : setSelectedFile(entry)}
                onFocus={() => setTreeFocusPath(entry.path)}
                onKeyDown={(event) => onTreeKeyDown(event, entry.path)}
                ref={(node) => {
                  if (node) treeItemRefs.current.set(entry.path, node);
                  else treeItemRefs.current.delete(entry.path);
                }}
                role="treeitem"
                style={{ '--paw-files-depth': depth } as CSSProperties}
                tabIndex={treeFocusPath === entry.path ? 0 : -1}
                title={entry.path}
                type="button"
              >
                {directory ? <ChevronRight data-open={open || undefined} size={14} /> : <span />}
                {directory ? (open ? <FolderOpen size={16} /> : <Folder size={16} />) : symlink ? <FileSymlink size={16} /> : fileIcon(entry.name)}
                <span>{entry.name}</span>
                {entry.byteSize !== undefined ? <small>{formatBytes(entry.byteSize)}</small> : null}
              </button>
              {directory && open ? renderChildren(entry.path, depth + 1) : null}
            </li>
          );
        })}
      </ul>
    );
  }

  const filesTools = (
    <div className="paw-files-app__toolbar" data-window-chrome={windowChromeTarget ? true : undefined}>
      <label>
        <span className="sr-only">Session</span>
        <select
          aria-label="选择文件所属 Session"
          disabled={sessionsLoading || !sessions.length}
          onChange={(event) => setSelectedSessionId(event.target.value)}
          value={selectedSessionId}
        >
          {sessions.map((session) => <option key={session.id} title={session.title} value={session.id}>{session.title}</option>)}
        </select>
      </label>
      <label className="paw-files-filter">
        <Search aria-hidden="true" size={13} />
        <input
          aria-label="筛选已加载的文件"
          disabled={!roots.length}
          onChange={(event) => setFilterQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setFilterQuery('');
          }}
          placeholder="筛选已加载的文件"
          spellCheck={false}
          type="search"
          value={filterQuery}
        />
      </label>
      <button aria-busy={loadingPaths.size ? true : undefined} aria-label="刷新文件" disabled={!selectedSessionId || loadingPaths.size > 0} onClick={refresh} type="button"><RefreshCw className={loadingPaths.size ? 'ui-spin' : undefined} size={15} /><span>刷新</span></button>
    </div>
  );

  return (
    <>
      {windowChromeTarget ? <PawWindowChromePortal>{filesTools}</PawWindowChromePortal> : null}
      <section className="paw-files-app" data-session-error={sessionError ? true : undefined} data-tools-in-window-chrome={windowChromeTarget ? true : undefined}>
        <h1 className="paw-files-app__title">Session 文件</h1>
        {windowChromeTarget ? null : filesTools}
        {sessionError ? <div className="paw-native-app__error" role="alert"><TriangleAlert size={16} />{sessionError}<button onClick={() => void loadSessions()} type="button">重试</button></div> : null}
        <div className="paw-files-app__workspace" data-file-open={selectedFile ? true : undefined}>
        <aside className="paw-files-tree" aria-label="Session 授权工作区" ref={treeRef}>
          {sessionsLoading ? <TreeState loading>正在读取 Session…</TreeState> : null}
          {!sessionsLoading && !sessionError && !sessions.length ? <TreeState>还没有可浏览的 Session。</TreeState> : null}
          {!sessionsLoading && sessions.length > 0 && !roots.length ? <TreeState>这个 Session 还没有绑定工作区。</TreeState> : null}
          {roots.length && filterMatches ? (
            <div className="paw-files-filter-results">
              <p aria-live="polite" className="paw-files-filter-results__meta">在已加载的 {visibleEntryCount} 项中匹配 {filterMatches.length} 项</p>
              {filterMatches.length ? (
                <ul aria-label="筛选结果">
                  {filterMatches.map((entry) => {
                    const directory = entry.kind === 'directory';
                    const symlink = entry.kind === 'symlink';
                    return (
                      <li key={entry.path}>
                        <button
                          aria-label={directory ? `在目录树中展开 ${entry.name}` : `打开文件 ${entry.name}`}
                          className="paw-files-tree__row"
                          data-ext={directory ? undefined : fileExtension(entry.name) || undefined}
                          data-kind={symlink ? 'symlink' : undefined}
                          data-selected={!directory && entry.path === selectedFile?.path || undefined}
                          onClick={() => openFilterMatch(entry)}
                          title={entry.path}
                          type="button"
                        >
                          <span />
                          {directory ? <Folder size={16} /> : symlink ? <FileSymlink size={16} /> : fileIcon(entry.name)}
                          <span>{entry.name}</span>
                          <small>{rootRelativeParent(entry.path, roots)}</small>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : <TreeState>没有匹配已加载的条目。</TreeState>}
            </div>
          ) : null}
          {roots.length && !filterMatches ? (
            <nav aria-label="项目文件"><ul aria-label="项目文件" role="tree">
              {roots.map((root) => (
                <li className="paw-files-tree__root" key={root} role="none">
                  <button
                    aria-expanded={expanded.has(root)}
                    aria-label={`${expanded.has(root) ? '收起' : '展开'}工作区 ${pathName(root)}，路径 ${root}`}
                    aria-level={1}
                    className="paw-files-tree__root-button"
                    onClick={() => toggleDirectory(root)}
                    onFocus={() => setTreeFocusPath(root)}
                    onKeyDown={(event) => onTreeKeyDown(event, root)}
                    ref={(node) => {
                      if (node) treeItemRefs.current.set(root, node);
                      else treeItemRefs.current.delete(root);
                    }}
                    role="treeitem"
                    tabIndex={treeFocusPath === root ? 0 : -1}
                    title={root}
                    type="button"
                  >
                    <ChevronRight data-open={expanded.has(root) || undefined} size={14} />
                    {expanded.has(root) ? <FolderOpen size={17} /> : <Folder size={17} />}
                    <span><strong>{pathName(root)}</strong><small>{root}</small></span>
                  </button>
                  {expanded.has(root) ? renderChildren(root, 1) : null}
                </li>
              ))}
            </ul></nav>
          ) : null}
        </aside>
        <main className="paw-files-preview" onKeyDown={(event) => { if (event.key === 'Escape' && treeHidden()) goBackToTree(); }}>
          {!selectedFile ? (
            <div className="paw-files-preview__empty">
              <FileCode2 size={30} />
              <strong>选择文件</strong>
              <span>从目录树选择一个文件，在这里阅读代码、Markdown、diff 或网页。</span>
            </div>
          ) : (
            <>
              <header key={`header:${selectedFile.path}`}>
                <button aria-label="返回文件列表" className="paw-files-preview__back" onClick={goBackToTree} ref={backButtonRef} type="button"><ChevronLeft size={15} /></button>
                <div>
                  <h2 title={pathName(selectedFile.path)}>{pathName(selectedFile.path)}</h2>
                  <small title={selectedFile.path}>{fileExtension(selectedFile.name).toUpperCase() || '文件'}{selectedFile.byteSize !== undefined ? ` · ${formatBytes(selectedFile.byteSize)}` : ''} · {selectedFile.path}</small>
                </div>
                <button
                  aria-label={copiedPathFor === selectedFile.path ? '已复制文件路径' : '复制文件路径'}
                  className="paw-files-preview__copy"
                  data-copied={copiedPathFor === selectedFile.path || undefined}
                  onClick={() => void copySelectedPath()}
                  title={copiedPathFor === selectedFile.path ? '已复制完整路径' : '复制完整路径'}
                  type="button"
                >
                  {copiedPathFor === selectedFile.path ? <Check size={14} /> : <Copy size={14} />}
                </button>
                <button
                  aria-label={copiedContentFor === selectedFile.path ? '已复制文件内容' : '复制文件内容'}
                  className="paw-files-preview__copy"
                  data-copied={copiedContentFor === selectedFile.path || undefined}
                  disabled={!copyableContent(preview, previewLoading, previewError)}
                  onClick={() => void copySelectedContent()}
                  title={copyContentTitle(preview, previewLoading, previewError, copiedContentFor === selectedFile.path)}
                  type="button"
                >
                  {copiedContentFor === selectedFile.path ? <Check size={14} /> : <ClipboardCopy size={14} />}
                </button>
                {preview?.truncated ? <em>前 64 KB</em> : null}
              </header>
              <div className="paw-files-preview__body" key={`body:${selectedFile.path}`}>
                {previewLoading ? <div className="paw-files-preview__state" role="status"><LoaderCircle className="ui-spin" size={18} />正在读取文件…</div> : null}
                {previewError ? <div className="paw-files-preview__state" role="alert"><TriangleAlert size={18} /><span>{previewError}</span><button onClick={() => void loadPreview(selectedFile)} type="button">重试</button></div> : null}
                {!previewLoading && !previewError && preview ? renderPreview(preview) : null}
              </div>
            </>
          )}
        </main>
        </div>
        <footer className="paw-files-statusbar" aria-live="polite">
          <span>已加载 {visibleEntryCount} 项</span>
          {selectedFile ? <><i aria-hidden="true" /><span className="paw-files-statusbar__selection" title={`${selectedFile.path}${selectedFile.byteSize !== undefined ? ` · ${formatBytes(selectedFile.byteSize)}` : ''}`}>已选 {selectedFile.name}{selectedFile.byteSize !== undefined ? ` · ${formatBytes(selectedFile.byteSize)}` : ''}</span></> : null}
          <span className="paw-files-statusbar__root" title={roots.join('\n') || undefined}>{roots.length ? `${roots.length} 个授权工作区` : '没有授权工作区'}</span>
        </footer>
      </section>
    </>
  );
}

function TreeState({ children, error, loading, onRetry }: { children?: ReactNode; error?: string; loading?: boolean; onRetry?: () => void }) {
  return <div className="paw-files-tree__state" role={error ? 'alert' : loading ? 'status' : undefined}>{loading ? <LoaderCircle className="ui-spin" size={14} /> : error ? <TriangleAlert size={14} /> : null}<span>{error ?? children}</span>{onRetry ? <button onClick={onRetry} type="button">重试</button> : null}</div>;
}

function renderPreview(file: WorkspaceFile): ReactNode {
  const name = pathName(file.path);
  const extension = fileExtension(name);
  if (!file.content && !file.truncated) return <div className="paw-files-preview__state paw-files-preview__state--empty" role="status"><File size={18} /><span>这个文件是空的。</span></div>;
  if (isProbablyBinary(file.content)) return <div className="paw-files-preview__state paw-files-preview__state--binary" role="status"><File size={18} /><span>二进制文件不能作为文本预览。</span></div>;
  if (['md', 'mdx', 'markdown'].includes(extension)) return <MarkdownPreview content={file.content} />;
  if (['html', 'htm'].includes(extension)) return <RichHtmlPreview content={file.content} title={name} />;
  if (['diff', 'patch'].includes(extension)) return <DiffPreview content={file.content} fileName={name} />;
  return <CodePreview content={file.content} fileName={name} language={fileLanguage(name)} />;
}

function authorizedRoots(session: SessionSummary | null): string[] {
  return (session?.workspaceRoots ?? []).filter((path, index, roots) => path.startsWith('/') && roots.indexOf(path) === index);
}

// Directory listings arrive in service order; Files presents them the way a
// file browser reads: directories first, then names in natural order.
function sortedEntries(items: WorkspaceEntry[]): WorkspaceEntry[] {
  return [...items].sort((first, second) => {
    const firstRank = first.kind === 'directory' ? 0 : 1;
    const secondRank = second.kind === 'directory' ? 0 : 1;
    if (firstRank !== secondRank) return firstRank - secondRank;
    return first.name.localeCompare(second.name, undefined, { numeric: true, sensitivity: 'base' });
  });
}

function ancestorDirectories(path: string, roots: string[]): string[] {
  const root = roots.find((candidate) => path === candidate || path.startsWith(`${candidate}/`));
  if (!root) return [];
  const chain = [root];
  const segments = path.slice(root.length).split('/').filter(Boolean);
  segments.pop();
  let current = root;
  for (const segment of segments) {
    current = `${current}/${segment}`;
    chain.push(current);
  }
  return chain;
}

function rootRelativeParent(path: string, roots: string[]): string {
  const root = roots.find((candidate) => path.startsWith(`${candidate}/`));
  const parent = path.split('/').slice(0, -1).join('/');
  if (!root) return parent || '/';
  const relative = parent.slice(root.length).replace(/^\//, '');
  return relative ? `${pathName(root)}/${relative}` : pathName(root);
}

function copyableContent(preview: WorkspaceFile | null, loading: boolean, error: string): boolean {
  if (!preview || loading || error) return false;
  return preview.content !== '' && !isProbablyBinary(preview.content);
}

function copyContentTitle(preview: WorkspaceFile | null, loading: boolean, error: string, copied: boolean): string {
  if (copied) return '已复制文件内容';
  if (loading || error || !preview) return '内容尚未读取';
  if (preview.content === '') return '文件没有文本内容';
  if (isProbablyBinary(preview.content)) return '二进制内容不能复制为文本';
  return preview.truncated ? '复制已加载的前 64 KB 内容' : '复制文件内容';
}

function workspaceEntries(value: unknown): WorkspaceEntry[] {
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error('目录服务返回了无法识别的数据。');
  return value.items.flatMap((item) => {
    if (!isRecord(item)) return [];
    const path = typeof item.path === 'string' ? item.path.trim() : '';
    const name = typeof item.name === 'string' ? item.name.trim() : '';
    const kind = String(item.kind);
    if (!path.startsWith('/') || !name || !['directory', 'file', 'symlink'].includes(kind)) return [];
    return [{ path, name, kind: kind as WorkspaceEntry['kind'], ...(typeof item.byteSize === 'number' ? { byteSize: item.byteSize } : {}) }];
  });
}

function workspaceFile(value: unknown, path: string): WorkspaceFile {
  if (!isRecord(value) || value.path !== path || typeof value.content !== 'string') throw new Error('文件服务返回了无法识别的数据。');
  return { path, content: value.content, byteSize: typeof value.byteSize === 'number' ? value.byteSize : 0, truncated: value.truncated === true };
}

function fileIcon(name: string): ReactNode {
  return ['c', 'css', 'go', 'html', 'js', 'json', 'md', 'py', 'rs', 'sh', 'swift', 'ts', 'tsx', 'yaml', 'yml'].includes(fileExtension(name)) ? <FileCode2 size={16} /> : <File size={16} />;
}

function fileLanguage(name: string): string {
  const extension = fileExtension(name);
  return ({ js: 'javascript', jsx: 'jsx', json: 'json', md: 'markdown', py: 'python', sh: 'shellscript', ts: 'typescript', tsx: 'tsx', yaml: 'yaml', yml: 'yaml' } as Record<string, string>)[extension] ?? (extension || 'text');
}

function flattenVisibleTree(roots: string[], entries: Record<string, WorkspaceEntry[]>, expanded: Set<string>): VisibleTreeNode[] {
  const nodes: VisibleTreeNode[] = [];
  const appendChildren = (parentPath: string) => {
    for (const entry of entries[parentPath] ?? []) {
      nodes.push({ path: entry.path, parentPath, kind: entry.kind });
      if (entry.kind === 'directory' && expanded.has(entry.path)) appendChildren(entry.path);
    }
  };
  for (const root of roots) {
    nodes.push({ path: root, parentPath: null, kind: 'root' });
    if (expanded.has(root)) appendChildren(root);
  }
  return nodes;
}

function isProbablyBinary(content: string): boolean {
  if (content.includes('\u0000')) return true;
  const sample = content.slice(0, 4_096);
  if (!sample) return false;
  let controlCharacters = 0;
  for (const character of sample) {
    const code = character.charCodeAt(0);
    if (code < 32 && code !== 9 && code !== 10 && code !== 13) controlCharacters += 1;
  }
  return controlCharacters > Math.max(2, sample.length * 0.02);
}

function fileExtension(value: string): string { return value.split('.').at(-1)?.toLowerCase() ?? ''; }
function pathName(value: string): string { return value.split('/').filter(Boolean).at(-1) ?? value; }
function formatBytes(value: number): string { return value < 1_024 ? `${value} B` : value < 1_048_576 ? `${Math.max(1, Math.round(value / 1_024))} KB` : `${Math.max(1, Math.round(value / 1_048_576))} MB`; }
function omitKey<Value>(record: Record<string, Value>, key: string): Record<string, Value> { const next = { ...record }; delete next[key]; return next; }
function isRecord(value: unknown): value is Record<string, unknown> { return Boolean(value) && typeof value === 'object' && !Array.isArray(value); }
function publicError(error: unknown, fallback: string): string { return error instanceof Error && error.message.trim() ? error.message : fallback; }
