import {
  ArrowDown,
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardCopy,
  Copy,
  File,
  FileCode2,
  FileImage,
  FileJson2,
  FileSymlink,
  FileText,
  Folder,
  FolderOpen,
  FolderTree,
  LoaderCircle,
  RefreshCw,
  ScanSearch,
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
import { EvidenceEchoUsage } from '@/features/evidence-echo/EvidenceEchoUsage';
import { PawWindowChromePortal, usePawWindowChromeTarget } from '@/paw-os/shell/PawWindowChrome';
import { writeClipboardText } from '@/platform/clipboard';
import { SvgFilePreview } from './SvgFilePreview';
import './paw-os-files-app.css';

interface WorkspaceEntry {
  path: string;
  name: string;
  kind: 'directory' | 'file' | 'symlink';
  byteSize?: number;
}

interface WorkspaceListing {
  items: WorkspaceEntry[];
  /** The directory holds more entries than the bounded list request returned. */
  limited: boolean;
}

interface WorkspacePreview {
  path: string;
  content: string;
  /** Total file size reported by the read route, in UTF-8 bytes. */
  byteSize: number;
  /** Bytes loaded so far from offset 0 — the read route's nextOffset. */
  loadedBytes: number;
  /** More bytes remain beyond loadedBytes. */
  truncated: boolean;
}

interface VisibleTreeNode {
  path: string;
  parentPath: string | null;
  kind: 'root' | WorkspaceEntry['kind'];
}

interface PathCrumb {
  label: string;
  path: string;
  kind: 'root' | 'directory';
}

/** One bounded read request — the transport caps workspace reads at 64 KB. */
const PREVIEW_CHUNK_BYTES = 65_536;
/** Honest in-App reading window; longer files belong to Terminal/Agent tools. */
const PREVIEW_MAX_BYTES = 524_288;
/** Bounded filter projection so one broad query cannot flood the pane. */
const FILTER_MATCH_LIMIT = 120;

/** Recognition families drive glyphs and hue chips; unknown extensions stay
    a neutral document instead of pretending to be classified. */
const FILE_FAMILY: Record<string, string> = {
  c: 'code', cc: 'code', cjs: 'code', cpp: 'code', cs: 'code', css: 'code', go: 'code', h: 'code',
  htm: 'code', html: 'code', java: 'code', js: 'code', jsx: 'code', kt: 'code', mjs: 'code',
  php: 'code', py: 'code', rb: 'code', rs: 'code', scss: 'code', sh: 'code', sql: 'code',
  swift: 'code', ts: 'code', tsx: 'code', vue: 'code', zsh: 'code',
  markdown: 'doc', md: 'doc', mdx: 'doc', rst: 'doc', rtf: 'doc', txt: 'doc',
  csv: 'data', env: 'data', ini: 'data', json: 'data', jsonl: 'data', lock: 'data',
  plist: 'data', toml: 'data', tsv: 'data', xml: 'data', yaml: 'data', yml: 'data',
  avif: 'media', bmp: 'media', gif: 'media', heic: 'media', ico: 'media', jpeg: 'media',
  jpg: 'media', mp3: 'media', mp4: 'media', png: 'media', svg: 'media', webp: 'media',
  diff: 'diff', patch: 'diff',
};

export function PawOsFilesApp({ initialRoute = '' }: { initialRoute?: string } = {}) {
  const transport = useControlTransport();
  const windowChromeTarget = usePawWindowChromeTarget();
  const requested = useMemo(() => requestedWorkspaceFile(initialRoute), [initialRoute]);
  const generationRef = useRef(0);
  const directoryGenerationRef = useRef(0);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState('');
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionError, setSessionError] = useState('');
  const [entries, setEntries] = useState<Record<string, WorkspaceListing>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [pathErrors, setPathErrors] = useState<Record<string, string>>({});
  const [selectedFile, setSelectedFile] = useState<WorkspaceEntry | null>(null);
  const [preview, setPreview] = useState<WorkspacePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [previewMoreLoading, setPreviewMoreLoading] = useState(false);
  const [previewMoreError, setPreviewMoreError] = useState('');
  const [treeFocusPath, setTreeFocusPath] = useState('');
  const [filterQuery, setFilterQuery] = useState('');
  const [copiedAction, setCopiedAction] = useState<'' | 'path' | 'content'>('');
  const [copyError, setCopyError] = useState('');
  const treeItemRefs = useRef(new Map<string, HTMLButtonElement>());
  const treeRef = useRef<HTMLElement | null>(null);
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const backButtonRef = useRef<HTMLButtonElement | null>(null);
  // Whether this App currently holds keyboard focus. A focusout that names no
  // new target means the focused element was hidden, not that someone moved
  // away, so the flag survives exactly the case the layout swap creates.
  const holdsFocusRef = useRef(false);
  const pendingFocusPathRef = useRef('');
  const typeaheadRef = useRef({ text: '', at: 0 });
  const selectedSession = sessions.find((session) => session.id === selectedSessionId) ?? null;
  const roots = useMemo(() => authorizedRoots(selectedSession), [selectedSession]);
  const visibleTreeNodes = useMemo(
    () => flattenVisibleTree(roots, entries, expanded),
    [entries, expanded, roots],
  );
  const visibleEntryCount = useMemo(() => {
    const paths = new Set<string>();
    for (const listing of Object.values(entries)) {
      for (const entry of listing.items) paths.add(entry.path);
    }
    return paths.size;
  }, [entries]);
  // The filter only sees directories that have already been read; the result
  // meta states that coverage truthfully instead of implying a full-disk find.
  const normalizedFilter = filterQuery.trim().toLocaleLowerCase();
  const filterMatches = useMemo(() => {
    if (!normalizedFilter) return [];
    const seen = new Set<string>();
    const matches: WorkspaceEntry[] = [];
    for (const listing of Object.values(entries)) {
      for (const entry of listing.items) {
        if (seen.has(entry.path) || !entry.name.toLocaleLowerCase().includes(normalizedFilter)) continue;
        seen.add(entry.path);
        matches.push(entry);
      }
    }
    return matches.sort((first, second) => first.path.localeCompare(second.path, undefined, { numeric: true, sensitivity: 'base' }));
  }, [entries, normalizedFilter]);
  const shownMatches = filterMatches.slice(0, FILTER_MATCH_LIMIT);
  const filterActive = Boolean(normalizedFilter);
  const previewIsBinary = preview ? isProbablyBinary(preview.content) : false;
  const previewCapped = Boolean(preview?.truncated && preview.loadedBytes >= PREVIEW_MAX_BYTES);
  const selectedCrumbs = useMemo(
    () => (selectedFile ? pathCrumbs(selectedFile.path, roots) : []),
    [roots, selectedFile],
  );
  const previewReady = Boolean(preview && !previewLoading && !previewError);
  // Loaded-line readout: honest for exactly the bytes on screen, never a
  // whole-file claim while the read window is still partial.
  const previewLineCount = useMemo(() => {
    if (!preview?.content || previewIsBinary) return 0;
    const lines = preview.content.split('\n').length;
    return preview.content.endsWith('\n') ? lines - 1 : lines;
  }, [preview?.content, previewIsBinary]);
  const previewRenderer = previewReady && preview ? rendererLabel(preview) : '';
  const directoriesRead = Object.keys(entries).length;

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
        // 深链指名的那段 Session 先于活跃 Session：它才是这个文件的授权来源。
        if (requested.sessionId && next.some((session) => session.id === requested.sessionId && authorizedRoots(session).length)) {
          return requested.sessionId;
        }
        if (next.some((session) => session.id === activeId && authorizedRoots(session).length)) return activeId;
        return next.find((session) => authorizedRoots(session).length)?.id ?? next[0]?.id ?? '';
      });
    } catch (error) {
      setSessionError(publicError(error, 'Session 列表读取失败。'));
    } finally {
      setSessionsLoading(false);
    }
  }, [requested.sessionId, transport]);

  const loadDirectory = useCallback(async (path: string, force = false) => {
    if (!selectedSessionId || (!force && (loadingPaths.has(path) || entries[path]))) return;
    const requestGeneration = directoryGenerationRef.current;
    const requestSessionId = selectedSessionId;
    setLoadingPaths((current) => new Set(current).add(path));
    setPathErrors((current) => omitKey(current, path));
    try {
      const response = await transport.request({
        pathId: 'agent.session.workspace.list',
        params: { sessionId: requestSessionId },
        query: { path, depth: 1, limit: 240 },
      });
      if (requestGeneration !== directoryGenerationRef.current) return;
      setEntries((current) => ({ ...current, [path]: workspaceListing(response) }));
    } catch (error) {
      if (requestGeneration !== directoryGenerationRef.current) return;
      setPathErrors((current) => ({ ...current, [path]: publicError(error, '目录读取失败。') }));
    } finally {
      if (requestGeneration === directoryGenerationRef.current) {
        setLoadingPaths((current) => {
          const next = new Set(current);
          next.delete(path);
          return next;
        });
      }
    }
  }, [entries, loadingPaths, selectedSessionId, transport]);

  useEffect(() => { void loadSessions(); }, [loadSessions]);

  useEffect(() => {
    generationRef.current += 1;
    directoryGenerationRef.current += 1;
    setEntries({});
    setLoadingPaths(new Set());
    setPathErrors({});
    setExpanded(new Set(roots));
    setSelectedFile(null);
    setPreview(null);
    setPreviewError('');
    setPreviewMoreError('');
    setFilterQuery('');
    for (const root of roots) void loadDirectory(root, true);
    // Directory state is intentionally reset whenever Session authority changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSessionId, roots.join('\u0000')]);

  /* 正向证据链落点：路由指名的那个文件在这段 Session 的授权工作区里时，展开
     它的目录链并直接打开它。只走一次——之后这扇窗属于翻看它的人。 */
  const openedRequestRef = useRef('');
  useEffect(() => {
    const path = resolveRequestedWorkspacePath(requested.path, roots);
    if (!path || !selectedSessionId || !roots.length) return;
    const chain = ancestorDirectories(path, roots);
    if (!chain.length) return;
    const request = `${selectedSessionId}\u0000${path}`;
    if (openedRequestRef.current === request) return;
    openedRequestRef.current = request;
    setExpanded((current) => new Set([...current, ...chain]));
    for (const directory of chain) if (!roots.includes(directory)) void loadDirectory(directory, true);
    if (roots.includes(path)) {
      // 深链指名的是一个工作区根目录（项目桌面的“在 Files 中打开”走这里）。
      // 目录不是文件，不进入读取链：展开它、把目录树焦点交给它，预览面板
      // 保持空态，由翻看的人自己选文件。
      setSelectedFile(null);
      setPreview(null);
      setPreviewError('');
      pendingFocusPathRef.current = path;
      return;
    }
    setSelectedFile({ path, name: pathName(path), kind: 'file' });
    // loadDirectory changes identity with every listing; the one-shot guard,
    // not the dependency list, is what keeps this from re-opening the file.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requested.path, roots.join('\u0000'), selectedSessionId]);

  useEffect(() => {
    setTreeFocusPath((current) => {
      if (visibleTreeNodes.some((node) => node.path === current)) return current;
      if (selectedFile && visibleTreeNodes.some((node) => node.path === selectedFile.path)) return selectedFile.path;
      return visibleTreeNodes[0]?.path ?? '';
    });
  }, [selectedFile, visibleTreeNodes]);

  // The App opens as rail + reader with the rail as the working object: once
  // the first listing lands, keyboard focus starts on the tree so ↑/↓/→/Enter
  // work immediately. One shot only, and never stolen from another window or
  // from a field the person is already typing in.
  const initialTreeFocusDone = useRef(false);
  useEffect(() => {
    if (initialTreeFocusDone.current || !visibleTreeNodes.length) return;
    initialTreeFocusDone.current = true;
    const active = document.activeElement;
    if (active instanceof HTMLElement) {
      const ownShell = treeRef.current?.closest('.paw-window-shell') ?? null;
      const activeShell = active.closest('.paw-window-shell');
      if (activeShell && activeShell !== ownShell) return;
      if (active.matches('input, textarea, select, [contenteditable="true"]')) return;
    }
    const node = treeItemRefs.current.get(visibleTreeNodes[0]?.path ?? '');
    if (!node || window.getComputedStyle(node).display === 'none') return;
    setTreeFocusPath(visibleTreeNodes[0]?.path ?? '');
    node.focus();
  }, [visibleTreeNodes]);

  const loadPreview = useCallback(async (file: WorkspaceEntry) => {
    if (!selectedSessionId) return;
    const generation = ++generationRef.current;
    setPreviewLoading(true);
    setPreviewError('');
    setPreviewMoreError('');
    setCopiedAction('');
    setCopyError('');
    try {
      const response = await transport.request({
        pathId: 'agent.session.workspace.read',
        params: { sessionId: selectedSessionId },
        query: { path: file.path, offset: 0, limit: PREVIEW_CHUNK_BYTES },
      });
      if (generation !== generationRef.current) return;
      const chunk = workspaceFileChunk(response, file.path);
      setPreview({
        path: file.path,
        content: chunk.content,
        byteSize: chunk.byteSize,
        loadedBytes: chunk.nextOffset,
        truncated: chunk.truncated,
      });
    } catch (error) {
      if (generation === generationRef.current) {
        setPreview(null);
        setPreviewError(publicError(error, '文件读取失败。'));
      }
    } finally {
      if (generation === generationRef.current) setPreviewLoading(false);
    }
  }, [selectedSessionId, transport]);

  const loadMorePreview = useCallback(async () => {
    const current = preview;
    if (!selectedSessionId || !current || !current.truncated || previewLoading || previewMoreLoading) return;
    if (current.loadedBytes >= PREVIEW_MAX_BYTES) return;
    const generation = generationRef.current;
    setPreviewMoreLoading(true);
    setPreviewMoreError('');
    try {
      const response = await transport.request({
        pathId: 'agent.session.workspace.read',
        params: { sessionId: selectedSessionId },
        query: { path: current.path, offset: current.loadedBytes, limit: PREVIEW_CHUNK_BYTES },
      });
      if (generation !== generationRef.current) return;
      const chunk = workspaceFileChunk(response, current.path);
      setPreview((existing) => existing && existing.path === current.path
        ? {
          ...existing,
          content: existing.content + chunk.content,
          byteSize: chunk.byteSize || existing.byteSize,
          loadedBytes: chunk.nextOffset,
          truncated: chunk.truncated,
        }
        : existing);
    } catch (error) {
      if (generation === generationRef.current) setPreviewMoreError(publicError(error, '继续读取失败。'));
    } finally {
      if (generation === generationRef.current) setPreviewMoreLoading(false);
    }
  }, [preview, previewLoading, previewMoreLoading, selectedSessionId, transport]);

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
    pendingFocusPathRef.current = selectedFile.path;
    setSelectedFile(null);
  }

  /** Expand a directory's ancestor chain and hand tree focus to it. In the
      narrow reader layout the tree is hidden, so revealing also returns to
      the list; the wide layout keeps the open file beside the located row. */
  function revealInTree(path: string): void {
    setExpanded((current) => {
      const next = new Set(current);
      for (const ancestor of ancestorDirectories(path, roots)) next.add(ancestor);
      next.add(path);
      return next;
    });
    void loadDirectory(path);
    pendingFocusPathRef.current = path;
    if (treeHidden()) setSelectedFile(null);
  }

  function openFilterMatch(entry: WorkspaceEntry): void {
    if (entry.kind !== 'directory') {
      setSelectedFile(entry);
      return;
    }
    revealInTree(entry.path);
    setFilterQuery('');
  }

  async function copyPreviewText(action: 'path' | 'content'): Promise<void> {
    if (!selectedFile) return;
    const value = action === 'path' ? selectedFile.path : preview?.content ?? '';
    if (!value) return;
    setCopyError('');
    try {
      await writeClipboardText(value);
      setCopiedAction(action);
      window.setTimeout(() => setCopiedAction((current) => current === action ? '' : current), 1_500);
    } catch {
      setCopiedAction('');
      setCopyError(action === 'path'
        ? '无法访问剪贴板，文件路径没有复制。'
        : '无法访问剪贴板，文件内容没有复制。');
    }
  }

  // When the narrow layout swaps the tree for the reader, focus travels with
  // the content; going back restores focus to the row that opened the file.
  useEffect(() => {
    if (selectedFile && treeHidden()) backButtonRef.current?.focus();
  }, [selectedFile]);

  // A window drag-resize can cross the single-pane breakpoint while a file is
  // open. The rail is hidden by CSS, which strands whatever it held outside
  // the focus order; this hands focus to the return path instead, so changing
  // the window size never costs the person their place. Focus is only ever
  // reclaimed from this App's own hidden rail, never from another window.
  useEffect(() => {
    if (!selectedFile) return;
    const repairStrandedRailFocus = (): void => {
      const rail = treeRef.current;
      if (!rail || !holdsFocusRef.current || !treeHidden()) return;
      const active = document.activeElement;
      const stranded = active === document.body || (active instanceof HTMLElement && rail.contains(active));
      if (stranded) backButtonRef.current?.focus();
    };
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(repairStrandedRailFocus) : null;
    if (observer && workspaceRef.current) observer.observe(workspaceRef.current);
    window.addEventListener('resize', repairStrandedRailFocus);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', repairStrandedRailFocus);
    };
  }, [selectedFile]);

  useEffect(() => {
    const path = pendingFocusPathRef.current;
    if (!path) return;
    if (selectedFile && treeHidden()) {
      pendingFocusPathRef.current = '';
      return;
    }
    const node = treeItemRefs.current.get(path);
    if (!node) return;
    pendingFocusPathRef.current = '';
    setTreeFocusPath(path);
    node.focus();
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
    const listing = entries[parent];
    if (loadingPaths.has(parent) && !listing) return <TreeState loading>正在读取目录…</TreeState>;
    if (pathErrors[parent] && !listing) {
      return <TreeState error={pathErrors[parent]} onRetry={() => void loadDirectory(parent, true)} />;
    }
    if (!listing?.items.length) return <TreeState>空目录</TreeState>;
    return (
      <>
        <ul role="group">
          {listing.items.map((entry) => {
            const directory = entry.kind === 'directory';
            const symlink = entry.kind === 'symlink';
            const open = directory && expanded.has(entry.path);
            const childListing = directory ? entries[entry.path] : undefined;
            return (
              <li key={entry.path} role="none">
                <button
                  aria-expanded={directory ? open : undefined}
                  aria-label={directory ? `${open ? '收起' : '展开'}目录 ${entry.name}` : symlink ? `打开符号链接 ${entry.name}` : `打开文件 ${entry.name}`}
                  aria-level={depth + 1}
                  aria-selected={!directory ? entry.path === selectedFile?.path : undefined}
                  className="paw-files-tree__row"
                  data-family={entryFamily(entry)}
                  data-kind={directory ? 'directory' : symlink ? 'symlink' : undefined}
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
                  {directory
                    ? <ChevronRight className="paw-files-tree__disclosure" data-open={open || undefined} size={13} />
                    : <i aria-hidden="true" className="paw-files-tree__disclosure" />}
                  <i aria-hidden="true" className="paw-files-tree__glyph">
                    {directory ? (open ? <FolderOpen size={14} /> : <Folder size={14} />) : symlink ? <FileSymlink size={14} /> : fileGlyph(entry.name)}
                  </i>
                  <span className="paw-files-tree__label"><span>{directory ? entry.name : entryLabel(entry.name)}</span></span>
                  {directory && childListing
                    ? <small>{childListing.items.length}{childListing.limited ? '+' : ''} 项</small>
                    : !directory && entry.byteSize !== undefined
                      ? <small>{formatBytes(entry.byteSize)}</small>
                      : null}
                </button>
                {directory && open ? renderChildren(entry.path, depth + 1) : null}
              </li>
            );
          })}
        </ul>
        {listing.limited ? (
          <div className="paw-files-tree__limit" role="note" style={{ '--paw-files-depth': depth } as CSSProperties}>
            目录条目已达显示上限，仅列出前 {listing.items.length} 项。
          </div>
        ) : null}
      </>
    );
  }

  const filesTools = (
    <div className="paw-files-app__toolbar" data-window-chrome={windowChromeTarget ? true : undefined}>
      <label className="paw-files-scope">
        <FolderTree aria-hidden="true" size={13} />
        <span className="sr-only">Session</span>
        <select
          aria-label="选择文件所属 Session"
          disabled={sessionsLoading || !sessions.length}
          onChange={(event) => setSelectedSessionId(event.target.value)}
          value={selectedSessionId}
        >
          {sessions.map((session) => (
            <option key={session.id} title={session.title} value={session.id}>
              {session.title}{authorizedRoots(session).length ? '' : ' · 无工作区'}
            </option>
          ))}
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
        {filterActive ? <span aria-hidden="true" className="paw-files-filter__count">{filterMatches.length}</span> : null}
      </label>
      <button aria-busy={loadingPaths.size ? true : undefined} aria-label="刷新文件" className="paw-files-refresh" disabled={!selectedSessionId || loadingPaths.size > 0} onClick={refresh} type="button"><RefreshCw className={loadingPaths.size ? 'ui-spin' : undefined} size={14} /><span>刷新</span></button>
    </div>
  );

  return (
    <>
      {windowChromeTarget ? <PawWindowChromePortal>{filesTools}</PawWindowChromePortal> : null}
      <section
        className="paw-files-app"
        onBlur={(event) => {
          if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) holdsFocusRef.current = false;
        }}
        onFocus={() => { holdsFocusRef.current = true; }}
      >
        <h1 className="paw-files-app__title">Session 文件</h1>
        {windowChromeTarget ? null : filesTools}
        {sessionError ? <div className="paw-native-app__error" role="alert"><TriangleAlert size={16} />{sessionError}<button onClick={() => void loadSessions()} type="button">重试</button></div> : null}
        <div className="paw-files-app__workspace" data-file-open={selectedFile ? true : undefined} ref={workspaceRef}>
        <aside className="paw-files-tree" aria-label="Session 授权工作区" ref={treeRef}>
          {roots.length ? (
            <header className="paw-files-tree__head">
              <strong>目录</strong>
              {loadingPaths.size ? (
                <span className="paw-files-tree__head-scan">
                  <LoaderCircle aria-hidden="true" className="ui-spin" size={11} />
                  正在读取 {loadingPaths.size} 个目录
                </span>
              ) : (
                <span className="paw-files-tree__head-count">{directoriesRead} 目录 · {visibleEntryCount} 项</span>
              )}
            </header>
          ) : null}
          <div className="paw-files-tree__scroll">
            {sessionsLoading ? <TreeState loading>正在读取 Session…</TreeState> : null}
            {!sessionsLoading && !sessionError && !sessions.length ? <TreeState>还没有可浏览的 Session。</TreeState> : null}
            {!sessionsLoading && sessions.length > 0 && !roots.length ? <TreeState>这个 Session 还没有绑定工作区。</TreeState> : null}
            {roots.length && filterActive ? (
              <div className="paw-files-filter-results">
                <p aria-live="polite" className="paw-files-filter-results__meta">
                  在已加载的 {visibleEntryCount} 项中匹配 {filterMatches.length} 项
                  {filterMatches.length > shownMatches.length ? `，仅显示前 ${shownMatches.length} 项` : ''}
                </p>
                {shownMatches.length ? (
                  <ul aria-label="筛选结果">
                    {shownMatches.map((entry) => {
                      const directory = entry.kind === 'directory';
                      const symlink = entry.kind === 'symlink';
                      return (
                        <li key={entry.path}>
                          <button
                            aria-label={directory ? `在目录树中展开 ${entry.name}` : `打开文件 ${entry.name}`}
                            className="paw-files-tree__row"
                            data-family={entryFamily(entry)}
                            data-kind={directory ? 'directory' : symlink ? 'symlink' : undefined}
                            data-selected={!directory && entry.path === selectedFile?.path || undefined}
                            onClick={() => openFilterMatch(entry)}
                            onFocus={() => setTreeFocusPath(entry.path)}
                            ref={(node) => {
                              if (node) treeItemRefs.current.set(entry.path, node);
                              else treeItemRefs.current.delete(entry.path);
                            }}
                            title={entry.path}
                            type="button"
                          >
                            <i aria-hidden="true" className="paw-files-tree__disclosure" />
                            <i aria-hidden="true" className="paw-files-tree__glyph">
                              {directory ? <Folder size={14} /> : symlink ? <FileSymlink size={14} /> : fileGlyph(entry.name)}
                            </i>
                            <span className="paw-files-tree__label"><span>{highlightMatch(entry.name, normalizedFilter)}</span></span>
                            <small>{rootRelativeParent(entry.path, roots)}</small>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                ) : <TreeState>没有匹配已加载的条目。</TreeState>}
              </div>
            ) : null}
            {roots.length && !filterActive ? (
              <nav aria-label="项目文件"><ul aria-label="项目文件" role="tree">
                {roots.map((root) => {
                  const rootListing = entries[root];
                  return (
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
                        <ChevronRight className="paw-files-tree__disclosure" data-open={expanded.has(root) || undefined} size={14} />
                        <i aria-hidden="true" className="paw-files-tree__root-glyph">
                          {expanded.has(root) ? <FolderOpen size={15} /> : <Folder size={15} />}
                        </i>
                        <span className="paw-files-tree__root-id"><strong>{pathName(root)}</strong><small>{root}</small></span>
                        {rootListing ? <span aria-hidden="true" className="paw-files-tree__root-count">{rootListing.items.length}{rootListing.limited ? '+' : ''}</span> : null}
                      </button>
                      {expanded.has(root) ? renderChildren(root, 1) : null}
                    </li>
                  );
                })}
              </ul></nav>
            ) : null}
          </div>
        </aside>
        <section aria-label="文件预览" className="paw-files-preview" onKeyDown={(event) => { if (event.key === 'Escape' && treeHidden()) goBackToTree(); }} role="region">
          {!selectedFile ? (
            <div className="paw-files-preview__empty">
              <div aria-hidden="true" className="paw-files-preview__empty-art">
                <i />
                <i />
                <span><ScanSearch size={17} /></span>
              </div>
              <strong>选择要检查的文件</strong>
              <span>从目录树打开一个文件，在这里阅读代码、Markdown、diff、SVG 或网页。</span>
              <span className="paw-files-preview__empty-keys">
                <span><kbd>↑</kbd><kbd>↓</kbd><span>移动</span></span>
                <span><kbd>→</kbd><span>展开目录</span></span>
                <span><kbd>Enter</kbd><span>打开</span></span>
              </span>
            </div>
          ) : (
            <>
              <header key={`header:${selectedFile.path}`}>
                <button aria-label="返回文件列表" className="paw-files-preview__back" onClick={goBackToTree} ref={backButtonRef} title="返回文件列表（Esc）" type="button"><ChevronLeft size={15} /><span>返回</span></button>
                <span aria-hidden="true" className="paw-files-preview__badge" data-family={entryFamily(selectedFile)}>
                  {fileExtension(selectedFile.name)
                    ? fileExtension(selectedFile.name).slice(0, 4).toUpperCase()
                    : selectedFile.kind === 'symlink' ? <FileSymlink size={15} /> : <File size={15} />}
                </span>
                <div className="paw-files-preview__id">
                  <h2 title={pathName(selectedFile.path)}>{pathName(selectedFile.path)}</h2>
                  <small className="paw-files-crumbs" title={selectedFile.path}>
                    {selectedCrumbs.length ? selectedCrumbs.map((crumb) => (
                      <button
                        aria-label={`在目录树中定位 ${crumb.label}`}
                        className="paw-files-crumbs__segment"
                        data-root={crumb.kind === 'root' || undefined}
                        key={crumb.path}
                        onClick={() => revealInTree(crumb.path)}
                        title={crumb.path}
                        type="button"
                      >
                        {crumb.label}
                      </button>
                    )) : <span className="paw-files-crumbs__plain">{selectedFile.path}</span>}
                    <span className="paw-files-crumbs__meta">
                      {previewRenderer
                        ? <b className="paw-files-renderer" data-family={entryFamily(selectedFile)}>{previewRenderer}</b>
                        : <span>{fileExtension(selectedFile.name).toUpperCase() || '文件'}</span>}
                      {selectedFile.byteSize !== undefined ? <span>{formatBytes(selectedFile.byteSize)}</span> : null}
                      {previewReady && previewLineCount > 0
                        ? <span>{preview?.truncated ? `已载 ${previewLineCount} 行` : `${previewLineCount} 行`}</span>
                        : null}
                    </span>
                  </small>
                </div>
                <div className="paw-files-preview__actions">
                  <button
                    aria-label={copiedAction === 'content' ? '已复制文件内容' : '复制文件内容'}
                    className="paw-files-preview__action"
                    data-copied={copiedAction === 'content' || undefined}
                    disabled={!copyableContent(preview, previewLoading, previewError)}
                    onClick={() => void copyPreviewText('content')}
                    title={copyContentTitle(preview, previewLoading, previewError, copiedAction === 'content')}
                    type="button"
                  >
                    {copiedAction === 'content' ? <Check size={14} /> : <ClipboardCopy size={14} />}
                  </button>
                  <button
                    aria-label={copiedAction === 'path' ? '已复制文件路径' : '复制文件路径'}
                    className="paw-files-preview__action"
                    data-copied={copiedAction === 'path' || undefined}
                    onClick={() => void copyPreviewText('path')}
                    title={copiedAction === 'path' ? '已复制完整路径' : '复制完整路径'}
                    type="button"
                  >
                    {copiedAction === 'path' ? <Check size={14} /> : <Copy size={14} />}
                  </button>
                </div>
              </header>
              {copyError ? (
                <div className="paw-files-preview__copy-error" role="alert">
                  <TriangleAlert aria-hidden="true" size={14} />
                  <span>{copyError}</span>
                </div>
              ) : null}
              <div className="paw-files-preview__body" key={`body:${selectedFile.path}`}>
                {previewLoading ? (
                  <div className="paw-files-preview__state paw-files-preview__state--loading" role="status">
                    <span className="paw-files-preview__state-line"><LoaderCircle className="ui-spin" size={16} />正在读取文件…</span>
                    <span aria-hidden="true" className="paw-files-skeleton paw-files-skeleton--reader"><i /><i /><i /><i /><i /><i /></span>
                  </div>
                ) : null}
                {previewError ? <div className="paw-files-preview__state" role="alert"><TriangleAlert size={18} /><span>{previewError}</span><button onClick={() => void loadPreview(selectedFile)} type="button">重试</button></div> : null}
                {!previewLoading && !previewError && preview ? renderPreview(preview) : null}
              </div>
              {preview && !previewLoading && !previewError && preview.truncated && !previewIsBinary ? (
                <footer className="paw-files-preview__more">
                  <div className="paw-files-preview__range">
                    <span className="paw-files-preview__range-readout">
                      <span>已显示前 {formatBytes(preview.loadedBytes)} · 共 {formatBytes(preview.byteSize)}</span>
                      <em aria-hidden="true">{honestShare(preview)}%</em>
                    </span>
                    <span
                      aria-label={`已读取 ${formatBytes(preview.loadedBytes)}，共 ${formatBytes(preview.byteSize)}`}
                      aria-valuemax={100}
                      aria-valuemin={0}
                      aria-valuenow={honestShare(preview)}
                      className="paw-files-preview__meter"
                      data-busy={previewMoreLoading || undefined}
                      role="progressbar"
                      style={meterStyle(preview)}
                    >
                      <i />
                      {capMarkerShare(preview) ? <b aria-hidden="true" title={`${formatBytes(PREVIEW_MAX_BYTES)} 预览上限`} /> : null}
                    </span>
                  </div>
                  {previewMoreError ? <em role="alert">{previewMoreError}</em> : null}
                  {previewCapped ? (
                    <em>已达 {formatBytes(PREVIEW_MAX_BYTES)} 预览上限，更长内容请用 Terminal 或 Agent 工具查看。</em>
                  ) : (
                    <button aria-busy={previewMoreLoading || undefined} disabled={previewMoreLoading} onClick={() => void loadMorePreview()} type="button">
                      {previewMoreLoading ? <LoaderCircle className="ui-spin" size={13} /> : <ArrowDown size={13} />}
                      <span>继续读取 {formatBytes(Math.min(PREVIEW_CHUNK_BYTES, Math.max(1, preview.byteSize - preview.loadedBytes)))}</span>
                    </button>
                  )}
                </footer>
              ) : null}
              <EvidenceEchoUsage appId="files" entityId={selectedFile.path} entityLabel={selectedFile.name} />
            </>
          )}
        </section>
        </div>
        <footer className="paw-files-statusbar" aria-live="polite">
          <span>已加载 {visibleEntryCount} 项</span>
          {filterActive ? <><i aria-hidden="true" /><span>匹配 {filterMatches.length} 项</span></> : null}
          {selectedFile ? <><i aria-hidden="true" /><span className="paw-files-statusbar__selection" title={`${selectedFile.path}${selectedFile.byteSize !== undefined ? ` · ${formatBytes(selectedFile.byteSize)}` : ''}`}>已选 {selectedFile.name}{selectedFile.byteSize !== undefined ? ` · ${formatBytes(selectedFile.byteSize)}` : ''}</span></> : null}
          <span className="paw-files-statusbar__root" data-live={roots.length ? true : undefined} title={roots.join('\n') || undefined}>{roots.length ? `${roots.length} 个授权工作区` : '没有授权工作区'}</span>
        </footer>
      </section>
    </>
  );
}

function TreeState({ children, error, loading, onRetry }: { children?: ReactNode; error?: string; loading?: boolean; onRetry?: () => void }) {
  return (
    <div className="paw-files-tree__state" data-error={error ? true : undefined} role={error ? 'alert' : loading ? 'status' : undefined}>
      <span className="paw-files-tree__state-line">
        {loading ? <LoaderCircle className="ui-spin" size={14} /> : error ? <TriangleAlert size={14} /> : null}
        <span>{error ?? children}</span>
        {onRetry ? <button onClick={onRetry} type="button">重试</button> : null}
      </span>
      {loading ? <span aria-hidden="true" className="paw-files-skeleton paw-files-skeleton--tree"><i /><i /><i /></span> : null}
    </div>
  );
}

function renderPreview(file: WorkspacePreview): ReactNode {
  const name = pathName(file.path);
  const extension = fileExtension(name);
  if (!file.content && !file.truncated) {
    return (
      <div className="paw-files-preview__state paw-files-preview__state--empty" role="status">
        <i aria-hidden="true" className="paw-files-preview__state-mark"><File size={17} /></i>
        <span>这个文件是空的。</span>
      </div>
    );
  }
  if (isProbablyBinary(file.content)) {
    return (
      <div className="paw-files-preview__state paw-files-preview__state--binary" role="status">
        <i aria-hidden="true" className="paw-files-preview__state-mark"><FileImage size={17} /></i>
        <span>二进制文件不能作为文本预览。</span>
        <small>可从上方复制完整路径，用 Terminal 或 Agent 工具检查原始内容。</small>
      </div>
    );
  }
  if (extension === 'svg' && !file.truncated) return <SvgFilePreview content={file.content} fileName={name} />;
  if (['md', 'mdx', 'markdown'].includes(extension)) return <MarkdownPreview content={file.content} />;
  if (['html', 'htm'].includes(extension)) return <RichHtmlPreview content={file.content} title={name} />;
  if (['diff', 'patch'].includes(extension)) return <DiffPreview content={file.content} fileName={name} />;
  return <CodePreview content={file.content} fileName={name} language={fileLanguage(name)} />;
}

function highlightMatch(name: string, query: string): ReactNode {
  const index = name.toLocaleLowerCase().indexOf(query);
  if (index < 0 || !query) return name;
  return (
    <>
      {name.slice(0, index)}
      <mark>{name.slice(index, index + query.length)}</mark>
      {name.slice(index + query.length)}
    </>
  );
}

/** `/files?session=…&path=…` — 正向证据链把一个具体文件交给这扇窗。 */
function requestedWorkspaceFile(initialRoute: string): { sessionId: string; path: string } {
  const query = new URLSearchParams(initialRoute.split('?', 2)[1] ?? '');
  const path = (query.get('path') ?? '').trim();
  return {
    sessionId: (query.get('session') ?? '').trim().slice(0, 200),
    path: path.slice(0, 1_000),
  };
}

/** Markdown in a Session usually names files relative to its workspace. The
 * workspace route still uses an absolute path internally so directory listing
 * and reads keep one canonical identity. A root-name prefix remains supported
 * for the common `repository/src/file.ts` form. */
function resolveRequestedWorkspacePath(path: string, roots: string[]): string {
  const normalized = path.trim();
  if (!normalized) return '';
  if (normalized.startsWith('/')) return normalized;
  const relative = normalized.replace(/^\.\//u, '');
  if (!relative || relative.split('/').some((segment) => !segment || segment === '..')) return '';
  const namedRoot = roots.find((root) => (
    relative === pathName(root) || relative.startsWith(`${pathName(root)}/`)
  ));
  if (namedRoot) {
    const suffix = relative.slice(pathName(namedRoot).length).replace(/^\//u, '');
    return suffix ? `${namedRoot}/${suffix}` : namedRoot;
  }
  const root = roots[0];
  return root ? `${root}/${relative}` : '';
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

/** Root-relative crumb chain for the reader header: the workspace root first,
    then every intermediate directory. The file's own name stays in the h2. */
function pathCrumbs(path: string, roots: string[]): PathCrumb[] {
  const root = roots.find((candidate) => path === candidate || path.startsWith(`${candidate}/`));
  if (!root) return [];
  const crumbs: PathCrumb[] = [{ label: pathName(root), path: root, kind: 'root' }];
  const segments = path.slice(root.length).split('/').filter(Boolean);
  segments.pop();
  let current = root;
  for (const segment of segments) {
    current = `${current}/${segment}`;
    crumbs.push({ label: segment, path: current, kind: 'directory' });
  }
  return crumbs;
}

function rootRelativeParent(path: string, roots: string[]): string {
  const root = roots.find((candidate) => path.startsWith(`${candidate}/`));
  const parent = path.split('/').slice(0, -1).join('/');
  if (!root) return parent || '/';
  const relative = parent.slice(root.length).replace(/^\//, '');
  return relative ? `${pathName(root)}/${relative}` : pathName(root);
}

function copyableContent(preview: WorkspacePreview | null, loading: boolean, error: string): boolean {
  if (!preview || loading || error) return false;
  return preview.content !== '' && !isProbablyBinary(preview.content);
}

function copyContentTitle(preview: WorkspacePreview | null, loading: boolean, error: string, copied: boolean): string {
  if (copied) return '已复制文件内容';
  if (loading || error || !preview) return '内容尚未读取';
  if (preview.content === '') return '文件没有文本内容';
  if (isProbablyBinary(preview.content)) return '二进制内容不能复制为文本';
  return preview.truncated ? `复制已加载的前 ${formatBytes(preview.loadedBytes)} 内容` : '复制文件内容';
}

function workspaceListing(value: unknown): WorkspaceListing {
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error('目录服务返回了无法识别的数据。');
  const items = value.items.flatMap((item): WorkspaceEntry[] => {
    if (!isRecord(item)) return [];
    const path = typeof item.path === 'string' ? item.path.trim() : '';
    const name = typeof item.name === 'string' ? item.name.trim() : '';
    const kind = String(item.kind);
    if (!path.startsWith('/') || !name || !['directory', 'file', 'symlink'].includes(kind)) return [];
    return [{ path, name, kind: kind as WorkspaceEntry['kind'], ...(typeof item.byteSize === 'number' ? { byteSize: item.byteSize } : {}) }];
  });
  return { items: sortedEntries(items), limited: value.truncated === true };
}

function workspaceFileChunk(value: unknown, path: string): { content: string; byteSize: number; nextOffset: number; truncated: boolean } {
  if (!isRecord(value) || value.path !== path || typeof value.content !== 'string') throw new Error('文件服务返回了无法识别的数据。');
  const byteSize = typeof value.byteSize === 'number' ? value.byteSize : 0;
  const offset = typeof value.offset === 'number' ? value.offset : 0;
  const nextOffset = typeof value.nextOffset === 'number'
    ? value.nextOffset
    : offset + new TextEncoder().encode(value.content).length;
  return { content: value.content, byteSize, nextOffset, truncated: value.truncated === true };
}

function entryFamily(entry: Pick<WorkspaceEntry, 'kind' | 'name'>): string | undefined {
  if (entry.kind === 'symlink') return 'symlink';
  if (entry.kind === 'directory') return undefined;
  return FILE_FAMILY[fileExtension(entry.name)] ?? 'plain';
}

function fileGlyph(name: string, size = 14): ReactNode {
  switch (FILE_FAMILY[fileExtension(name)]) {
    case 'code':
    case 'diff':
      return <FileCode2 size={size} />;
    case 'doc':
      return <FileText size={size} />;
    case 'data':
      return <FileJson2 size={size} />;
    case 'media':
      return <FileImage size={size} />;
    default:
      return <File size={size} />;
  }
}

function fileLanguage(name: string): string {
  const extension = fileExtension(name);
  return ({ js: 'javascript', jsx: 'jsx', json: 'json', md: 'markdown', py: 'python', sh: 'shellscript', svg: 'xml', ts: 'typescript', tsx: 'tsx', yaml: 'yaml', yml: 'yaml' } as Record<string, string>)[extension] ?? (extension || 'text');
}

/** Honest loaded share for the bounded-read meter; floored so a partial file
    never rounds up to a full bar. */
function loadedShare(preview: WorkspacePreview): number {
  if (preview.byteSize <= 0) return 0;
  return Math.max(2, Math.min(100, Math.floor((preview.loadedBytes / preview.byteSize) * 100)));
}

/** Numeric readout share: plain floored percentage without the visual floor,
    so the printed number never claims more than the bytes on screen. */
function honestShare(preview: WorkspacePreview): number {
  if (preview.byteSize <= 0) return 0;
  return Math.min(100, Math.floor((preview.loadedBytes / preview.byteSize) * 100));
}

/** One gauge tick per 64 KB read request. Ticks disappear when the file is so
    large they would blur into noise (below a 4% pitch). */
function chunkTickShare(preview: WorkspacePreview): number {
  if (preview.byteSize <= 0) return 0;
  const share = (PREVIEW_CHUNK_BYTES / preview.byteSize) * 100;
  return share >= 4 && share < 100 ? share : 0;
}

/** Position of the 512 KB in-App reading cap on the gauge scale; zero when
    the whole file fits inside the cap and no marker is needed. */
function capMarkerShare(preview: WorkspacePreview): number {
  if (preview.byteSize <= PREVIEW_MAX_BYTES) return 0;
  return Math.min(98, (PREVIEW_MAX_BYTES / preview.byteSize) * 100);
}

function meterStyle(preview: WorkspacePreview): CSSProperties {
  const tick = chunkTickShare(preview);
  const cap = capMarkerShare(preview);
  return {
    '--paw-files-loaded': `${loadedShare(preview)}%`,
    ...(tick ? { '--paw-files-tick': `${tick}%` } : {}),
    ...(cap ? { '--paw-files-cap': `${cap}%` } : {}),
  } as CSSProperties;
}

/** Which renderer is actually on screen — the reader names its own lens. */
function rendererLabel(preview: WorkspacePreview): string {
  if (!preview.content && !preview.truncated) return '空文件';
  if (isProbablyBinary(preview.content)) return '二进制';
  const extension = fileExtension(pathName(preview.path));
  if (extension === 'svg' && !preview.truncated) return 'SVG';
  if (['md', 'mdx', 'markdown'].includes(extension)) return 'Markdown';
  if (['html', 'htm'].includes(extension)) return '网页';
  if (['diff', 'patch'].includes(extension)) return 'Diff';
  return FILE_FAMILY[extension] === 'code' ? '代码' : '纯文本';
}

/** File names read base-first: the extension keeps its own quieter span so a
    column of names scans by stem. Dotfiles stay whole. */
function entryLabel(name: string): ReactNode {
  const dot = name.lastIndexOf('.');
  if (dot <= 0 || dot === name.length - 1) return name;
  return <>{name.slice(0, dot)}<i aria-hidden="true">{name.slice(dot)}</i></>;
}

function flattenVisibleTree(roots: string[], entries: Record<string, WorkspaceListing>, expanded: Set<string>): VisibleTreeNode[] {
  const nodes: VisibleTreeNode[] = [];
  const appendChildren = (parentPath: string) => {
    for (const entry of entries[parentPath]?.items ?? []) {
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
