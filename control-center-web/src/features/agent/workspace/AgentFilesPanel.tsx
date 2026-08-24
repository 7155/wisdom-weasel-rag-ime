import {
  ChevronRight,
  File,
  FileCode2,
  FileDiff,
  FileImage,
  FileJson2,
  FileText,
  Folder,
  FolderOpen,
  LoaderCircle,
  PanelRightClose,
  RefreshCw,
  Settings2,
  TriangleAlert,
} from 'lucide-react';
import {
  forwardRef,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { useControlTransport } from '@/app/control-transport';
import { IconButton } from '@/components/primitives';
import { WorkspaceFilePreviewDialog } from './WorkspaceFilePreviewDialog';

interface AgentFilesPanelProps {
  sessionId: string;
  workspaceRoots: string[];
  open: boolean;
  modal?: boolean;
  onClose: () => void;
  onManageRoots: () => void;
}

interface WorkspaceEntry {
  path: string;
  name: string;
  kind: 'directory' | 'file' | 'symlink';
  byteSize?: number;
}

export const AgentFilesPanel = forwardRef<HTMLElement, AgentFilesPanelProps>(function AgentFilesPanel({
  sessionId,
  workspaceRoots,
  open,
  modal = false,
  onClose,
  onManageRoots,
}, ref) {
  const transport = useControlTransport();
  const cacheRef = useRef(new Map<string, WorkspaceEntry[]>());
  const loadingRef = useRef(new Set<string>());
  const errorsRef = useRef(new Map<string, string>());
  const generationRef = useRef(0);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [selectedFile, setSelectedFile] = useState<WorkspaceEntry>();
  const [revision, setRevision] = useState(0);
  const roots = useMemo(() => workspaceRoots
    .map((path) => path.trim())
    .filter((path, index, values) => path.startsWith('/') && values.indexOf(path) === index), [workspaceRoots]);
  const rootsKey = roots.join('\u0000');

  const redraw = useCallback(() => setRevision((value) => value + 1), []);
  const loadChildren = useCallback(async (path: string, force = false) => {
    if (!sessionId || loadingRef.current.has(path)) return;
    if (!force && cacheRef.current.has(path)) return;
    const generation = generationRef.current;
    loadingRef.current.add(path);
    errorsRef.current.delete(path);
    redraw();
    try {
      const response = await transport.request({
        pathId: 'agent.session.workspace.list',
        params: { sessionId },
        query: { path, depth: 1, limit: 240 },
      });
      if (generation !== generationRef.current) return;
      cacheRef.current.set(path, workspaceEntries(response));
    } catch (error) {
      if (generation !== generationRef.current) return;
      errorsRef.current.set(path, publicError(error));
    } finally {
      if (generation === generationRef.current) {
        loadingRef.current.delete(path);
        redraw();
      }
    }
  }, [redraw, sessionId, transport]);

  useEffect(() => {
    generationRef.current += 1;
    cacheRef.current.clear();
    loadingRef.current.clear();
    errorsRef.current.clear();
    setExpanded(new Set(roots));
    setSelectedFile(undefined);
    setRevision((value) => value + 1);
  }, [rootsKey, sessionId]);

  useEffect(() => {
    if (!open) return;
    for (const root of roots) void loadChildren(root);
  }, [loadChildren, open, rootsKey]);

  function toggleDirectory(path: string): void {
    const willExpand = !expanded.has(path);
    setExpanded((current) => {
      const next = new Set(current);
      if (willExpand) next.add(path);
      else next.delete(path);
      return next;
    });
    if (willExpand) void loadChildren(path);
  }

  function refresh(): void {
    cacheRef.current.clear();
    errorsRef.current.clear();
    for (const path of expanded) void loadChildren(path, true);
    for (const root of roots) void loadChildren(root, true);
    redraw();
  }

  function renderChildren(parentPath: string, depth: number): ReactNode {
    const isLoading = loadingRef.current.has(parentPath);
    const error = errorsRef.current.get(parentPath);
    const items = cacheRef.current.get(parentPath);
    if (isLoading && !items) {
      return <div className="agent-files-panel__state" role="status"><LoaderCircle size={14} />正在读取目录…</div>;
    }
    if (error && !items) {
      return (
        <div className="agent-files-panel__state" role="alert">
          <TriangleAlert size={14} />
          <span>{error}</span>
          <button type="button" onClick={() => void loadChildren(parentPath, true)}>重试</button>
        </div>
      );
    }
    if (!items?.length) return <div className="agent-files-panel__state">空目录</div>;
    return (
      <ul role="group">
        {items.map((item) => {
          const directory = item.kind === 'directory';
          const isExpanded = directory && expanded.has(item.path);
          const style = { '--agent-file-depth': depth } as CSSProperties;
          return (
            <li key={item.path} role="treeitem" aria-expanded={directory ? isExpanded : undefined}>
              {directory ? (
                <button
                  className="agent-files-panel__row"
                  style={style}
                  type="button"
                  title={item.path}
                  aria-label={`${isExpanded ? '收起' : '展开'}目录 ${item.name}`}
                  onClick={() => toggleDirectory(item.path)}
                >
                  <ChevronRight className="agent-files-panel__chevron" size={13} data-open={isExpanded || undefined} />
                  {isExpanded ? <FolderOpen size={15} /> : <Folder size={15} />}
                  <span>{item.name}</span>
                </button>
              ) : (
                <button
                  className="agent-files-panel__row"
                  style={style}
                  type="button"
                  title={`预览 ${item.path}`}
                  aria-label={`预览文件 ${item.name}`}
                  onClick={() => setSelectedFile(item)}
                >
                  <span className="agent-files-panel__file-indent" />
                  {fileIcon(item.name)}
                  <span>{item.name}</span>
                  {typeof item.byteSize === 'number' ? <small>{formatBytes(item.byteSize)}</small> : null}
                </button>
              )}
              {directory && isExpanded ? renderChildren(item.path, depth + 1) : null}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <>
      <aside
        ref={ref}
        id="agent-files-panel"
        className="agent-files-panel"
        data-open={open}
        aria-label="当前对话文件目录"
        aria-hidden={!open || undefined}
        inert={!open ? true : undefined}
        role={modal ? 'dialog' : 'complementary'}
        aria-modal={modal || undefined}
      >
        <header>
          <span><strong>文件目录</strong><small>{roots.length ? `${roots.length} 个工作区` : '未选择工作区'}</small></span>
          <div className="agent-files-panel__actions">
            <IconButton label="刷新文件目录" icon={<RefreshCw size={16} />} onClick={refresh} disabled={!roots.length} tooltip />
            <IconButton label="管理工作区目录" icon={<Settings2 size={16} />} onClick={onManageRoots} tooltip />
            <IconButton data-drawer-autofocus label="收起文件目录" icon={<PanelRightClose size={17} />} onClick={onClose} tooltip />
          </div>
        </header>
        <div className="agent-files-panel__body" data-revision={revision}>
          {roots.length ? (
            <nav aria-label="工作区文件">
              <ul role="tree">
                {roots.map((root) => {
                  const isExpanded = expanded.has(root);
                  return (
                    <li className="agent-files-panel__root" key={root} role="treeitem" aria-expanded={isExpanded}>
                      <button
                        className="agent-files-panel__root-toggle"
                        type="button"
                        title={root}
                        aria-expanded={isExpanded}
                        aria-label={`${isExpanded ? '收起' : '展开'}工作区 ${pathName(root)}`}
                        onClick={() => toggleDirectory(root)}
                      >
                        <ChevronRight className="agent-files-panel__chevron" size={14} data-open={isExpanded || undefined} />
                        {isExpanded ? <FolderOpen size={16} /> : <Folder size={16} />}
                        <span><strong>{pathName(root)}</strong><small>{root}</small></span>
                      </button>
                      {isExpanded ? renderChildren(root, 1) : null}
                    </li>
                  );
                })}
              </ul>
            </nav>
          ) : (
            <p className="agent-files-panel__empty" role="status">
              <span>当前没有文件；选择工作区目录后即可浏览。</span>
              <button type="button" onClick={onManageRoots}>选择目录</button>
            </p>
          )}
        </div>
      </aside>
      <WorkspaceFilePreviewDialog
        sessionId={sessionId}
        path={selectedFile?.path ?? ''}
        byteSize={selectedFile?.byteSize}
        open={Boolean(selectedFile)}
        onOpenChange={(next) => { if (!next) setSelectedFile(undefined); }}
      />
    </>
  );
});

function workspaceEntries(value: unknown): WorkspaceEntry[] {
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error('目录服务返回了无法识别的数据。');
  return value.items.flatMap((item) => {
    if (!isRecord(item)) return [];
    const path = typeof item.path === 'string' ? item.path.trim() : '';
    const name = typeof item.name === 'string' ? item.name.trim() : '';
    const kind = item.kind;
    if (!path.startsWith('/') || !name || !['directory', 'file', 'symlink'].includes(String(kind))) return [];
    return [{
      path,
      name,
      kind: kind as WorkspaceEntry['kind'],
      ...(typeof item.byteSize === 'number' && Number.isFinite(item.byteSize) ? { byteSize: item.byteSize } : {}),
    }];
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function pathName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) ?? path;
}

function formatBytes(value: number): string {
  if (value < 1_024) return `${value} B`;
  if (value < 1_048_576) return `${Math.max(1, Math.round(value / 1_024))} KB`;
  return `${Math.max(1, Math.round(value / 1_048_576))} MB`;
}

function fileIcon(name: string): ReactNode {
  const extension = name.split('.').at(-1)?.toLowerCase() ?? '';
  if (['diff', 'patch'].includes(extension)) return <FileDiff aria-hidden="true" size={15} />;
  if (['gif', 'heic', 'jpeg', 'jpg', 'png', 'svg', 'webp'].includes(extension)) return <FileImage aria-hidden="true" size={15} />;
  if (['json', 'jsonl'].includes(extension)) return <FileJson2 aria-hidden="true" size={15} />;
  if (['md', 'mdx', 'markdown', 'txt'].includes(extension)) return <FileText aria-hidden="true" size={15} />;
  if (['c', 'cc', 'cpp', 'css', 'go', 'h', 'hpp', 'html', 'java', 'js', 'jsx', 'kt', 'py', 'rs', 'sh', 'sql', 'swift', 'toml', 'ts', 'tsx', 'vue', 'xml', 'yaml', 'yml', 'zsh'].includes(extension)) {
    return <FileCode2 aria-hidden="true" size={15} />;
  }
  return <File aria-hidden="true" size={15} />;
}

function publicError(error: unknown): string {
  return error instanceof Error && error.message.trim() ? error.message : '目录读取失败。';
}
