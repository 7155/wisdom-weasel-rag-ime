import { FileText, FolderOpen, LoaderCircle } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { MarkdownPreview } from '@/features/agent/file-preview/MarkdownPreview';
import '@/features/agent/file-preview/file-preview.css';
import type { SessionSummary } from '@/features/agent/types';
import type { WayfinderWorkItem, WayfinderWorkProject } from './wayfinder-work-projection';
import './paw-project-documents.css';

type Entry = { path: string; name: string; kind: 'file' | 'directory' };
type Root = { path: string; sessionId: string };
export type PawProjectDocumentsProps = {
  project: WayfinderWorkProject;
  sessions: readonly SessionSummary[];
  onOpenFile: (path: string, sessionId: string) => void;
  onOpenWork: (item: WayfinderWorkItem) => void;
};

/** Read through an existing project Session; visual folder assignment grants no file access. */
export function PawProjectDocuments({ project, sessions, onOpenFile, onOpenWork }: PawProjectDocumentsProps) {
  const roots = useMemo(() => project.workspaceRoots.flatMap((path): Root[] => {
    if (!path.startsWith('/')) return [];
    const direct = project.items.find((item) => item.kind === 'session' && item.workspaceRoots.includes(path)
      && sessions.some((session) => session.id === item.id && session.workspaceRoots?.includes(path)));
    const roomIds = new Set(project.items.filter((item) => item.kind === 'room').map((item) => item.id));
    const participant = sessions.find((session) => session.workspaceRoots?.includes(path)
      && session.roomParticipant?.status !== 'removed' && roomIds.has(session.roomParticipant?.roomId ?? ''));
    const sessionId = direct?.id ?? participant?.id;
    return sessionId ? [{ path, sessionId }] : [];
  }), [project, sessions]);
  const [chosenRoot, setChosenRoot] = useState('');
  const selected = roots.find((root) => root.path === chosenRoot) ?? roots[0];
  return <section className="paw-project-documents" aria-label="文档列表与预览">
    {selected ? <div className="paw-project-documents__header"><button onClick={() => onOpenFile(selected.path, selected.sessionId)} type="button">在 Files 中打开</button></div> : null}
    {!selected ? <div className="paw-project-documents__empty">
      <FolderOpen aria-hidden="true" size={24} />
      <strong>{project.workspaceRoots.length ? '暂时无法浏览这个工作区' : '尚未绑定工作区'}</strong>
      <p>{project.workspaceRoots.length ? '打开项目对话，检查工作区目录后再查看文档。' : '打开对话后选择工作区，这里就会显示目录中的文档。'}</p>
      {project.items.map((item) => <button key={item.key} onClick={() => onOpenWork(item)} type="button">打开 {item.title || '对话'}</button>)}
    </div> : <>
      {roots.length > 1 ? <label className="paw-project-documents__roots">工作区
        <select value={selected.path} onChange={(event) => setChosenRoot(event.target.value)}>{roots.map((root) => <option key={root.path} value={root.path}>{root.path}</option>)}</select>
      </label> : null}
      <DocumentBrowser key={`${project.id}:${selected.sessionId}:${selected.path}`} root={selected} onOpenFile={onOpenFile} />
    </>}
  </section>;
}

function DocumentBrowser({ root, onOpenFile }: { root: Root; onOpenFile: PawProjectDocumentsProps['onOpenFile'] }) {
  const transport = useControlTransport();
  const [trail, setTrail] = useState<Entry[]>([{ path: root.path, name: leaf(root.path), kind: 'directory' }]);
  const directory = trail[trail.length - 1]!;
  const [listing, setListing] = useState<{ path: string; entries: Entry[]; truncated: boolean } | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<Entry | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setError(''); setListing(null); setSelected(null);
    void transport.request({ pathId: 'agent.session.workspace.list', params: { sessionId: root.sessionId },
      query: { path: directory.path, depth: 1, limit: 240 }, signal: controller.signal }).then((value) => {
      if (controller.signal.aborted) return;
      if (!record(value) || !Array.isArray(value.items)) throw new Error('invalid listing');
      setListing({ path: directory.path, entries: documentEntries(value.items, directory.path, trail.length === 1), truncated: value.truncated === true });
    }).catch(() => { if (!controller.signal.aborted) setError('文档目录暂时无法读取，请重试。'); });
    return () => controller.abort();
  }, [directory.path, retry, root.sessionId, trail.length, transport]);
  const visibleListing = listing?.path === directory.path ? listing : null;
  return <>
    <nav className="paw-project-documents__breadcrumbs" aria-label="文档路径">
      {trail.map((entry, index) => <button key={entry.path} title={entry.path} aria-current={index === trail.length - 1 ? 'page' : undefined}
        onClick={() => { setSelected(null); setTrail((current) => current.slice(0, index + 1)); }} type="button">{entry.name}</button>)}
    </nav>
    <div className="paw-project-documents__body">
      <div className="paw-project-documents__list">
        {error ? <div role="alert"><p>{error}</p><button onClick={() => setRetry((value) => value + 1)} type="button">重试目录</button></div>
          : !visibleListing ? <p role="status"><LoaderCircle aria-hidden="true" size={14} /> 正在读取目录…</p>
            : <>
              {!visibleListing.entries.length ? <p>这个目录暂时没有可查看的文档。</p> : <ul aria-label="文档与目录">{visibleListing.entries.map((entry) => <li key={entry.path}>
                <button className="paw-project-documents__entry" aria-label={entry.kind === 'directory' ? `打开目录 ${entry.name}` : entry.name} aria-pressed={entry.kind === 'file' ? selected?.path === entry.path : undefined}
                  onClick={() => { if (entry.kind === 'directory') { setSelected(null); setTrail((current) => [...current, entry]); } else setSelected(entry); }} type="button">
                  {entry.kind === 'directory' ? <FolderOpen aria-hidden="true" size={15} /> : <FileText aria-hidden="true" size={15} />}
                  <span>{entry.name}</span>{entry.kind === 'directory' ? <small>目录</small> : null}
                </button>
              </li>)}</ul>}
              {visibleListing.truncated ? <p className="paw-project-documents__note">目录条目较多，当前仅显示已读取的部分。可在 Files 中继续浏览。</p> : null}
            </>}
      </div>
      <div className="paw-project-documents__preview" role="region" aria-label="文档预览">
        {selected ? <DocumentPreview key={selected.path} entry={selected} sessionId={root.sessionId} onOpenFile={onOpenFile} />
          : <p className="paw-project-documents__hint">选择文档，在这里阅读。</p>}
      </div>
    </div>
  </>;
}

function DocumentPreview({ entry, sessionId, onOpenFile }: { entry: Entry; sessionId: string; onOpenFile: PawProjectDocumentsProps['onOpenFile'] }) {
  const transport = useControlTransport();
  const [preview, setPreview] = useState<{ content: string; truncated: boolean } | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setPreview(null); setError('');
    void transport.request({ pathId: 'agent.session.workspace.read', params: { sessionId },
      query: { path: entry.path, offset: 0, limit: 65_536 }, signal: controller.signal }).then((value) => {
      if (controller.signal.aborted) return;
      if (!record(value) || value.path !== entry.path || typeof value.content !== 'string') throw new Error('invalid document');
      setPreview({ content: value.content, truncated: value.truncated === true });
    }).catch(() => { if (!controller.signal.aborted) setError('这份文档暂时无法读取，请重试。'); });
    return () => controller.abort();
  }, [entry.path, retry, sessionId, transport]);
  return <>
    <header className="paw-project-documents__file-header"><strong>{entry.name}</strong><button onClick={() => onOpenFile(entry.path, sessionId)} type="button">在 Files 中阅读</button></header>
    {error ? <div role="alert"><p>{error}</p><button onClick={() => setRetry((value) => value + 1)} type="button">重试文档</button></div>
      : !preview ? <p role="status">正在读取文档…</p> : <>
        {preview.truncated ? <p className="paw-project-documents__note">当前显示文档的前 64 KB，可在 Files 中继续阅读。</p> : null}
        {/\.(md|markdown|mdx)$/iu.test(entry.name) ? <MarkdownPreview content={preview.content} /> : <pre className="paw-project-documents__text">{preview.content}</pre>}
      </>}
  </>;
}

function documentEntries(items: unknown[], directory: string, atRoot: boolean): Entry[] {
  const parent = directory.replace(/\/+$/u, '');
  return items.flatMap((value): Entry[] => {
    if (!record(value) || typeof value.path !== 'string' || typeof value.name !== 'string') return [];
    const { path, name, kind } = value;
    // Navigate only direct entries actually returned for this directory.
    if (!name || name === '.' || name === '..' || name.includes('/') || path !== `${parent}/${name}`) return [];
    if (kind === 'directory' && (!atRoot || /^(docs?|documentation)$/iu.test(name))) return [{ path, name, kind }];
    if (kind === 'file' && /\.(md|markdown|mdx|txt|rst)$/iu.test(name)) return [{ path, name, kind }];
    return [];
  }).sort((a, b) => Number(b.kind === 'directory') - Number(a.kind === 'directory') || a.name.localeCompare(b.name));
}
function leaf(path: string): string { return path.split('/').filter(Boolean).pop() ?? path; }
function record(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
