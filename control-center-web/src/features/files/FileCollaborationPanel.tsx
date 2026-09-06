import { ChevronDown, RefreshCw } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useControlTransport } from '@/app/control-transport';
import type { AgentProjectionState } from '@/contracts/agent-reducer';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';
import { collectFileCollaboration, fileToolAccess, readFileActivity, type CollaborationLink, type FileCollaboration, type FileSessionCandidate, type FileToolAccess } from './file-collaboration';
import './file-collaboration.css';

export interface FileCollaborationPanelProps { sessionId: string; path: string; fileName?: string; children?: ReactNode }
export function FileCollaborationPanel(props: FileCollaborationPanelProps) {
  // The prior document's cache and pending request can never become the next
  // document's presence. Closing the panel also unmounts its Tool inspector.
  return <FileCollaborationDocument key={`${props.sessionId}:${props.path}`} {...props} />;
}

function FileCollaborationDocument({ sessionId, path, fileName, children }: FileCollaborationPanelProps) {
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const [expanded, setExpanded] = useState(false);
  const [data, setData] = useState<FileCollaboration>();
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [revision, setRevision] = useState(0);
  const [roomDetailLimit, setRoomDetailLimit] = useState(3);
  const [selectedSessionId, setSelectedSessionId] = useState('');

  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    let active = true;
    setState('loading');
    void collectFileCollaboration(transport, { sessionId, path }, { signal: controller.signal, roomDetailLimit }).then((value) => {
      if (!active) return;
      setData((previous) => {
        if (!previous || !value.issues.length) return value;
        const missing = previous.relations.filter((row) => !value.relations.some((next) => next.id === row.id && next.kind === row.kind));
        const retainedSessionIds = new Set(missing.flatMap((row) => row.links.filter((item) => item.kind === 'session').map((item) => item.id)));
        return {
          ...value,
          relations: [...value.relations, ...missing.map((row) => ({ ...row, stale: true }))],
          candidates: [...value.candidates, ...previous.candidates.filter((item) => retainedSessionIds.has(item.sessionId) && !value.candidates.some((next) => next.sessionId === item.sessionId))
            .map((item) => ({ ...item, reason: '上次关联的 Session', workspaceRoots: [] }))].slice(0, 12),
        };
      });
      setState('ready');
    }).catch(() => {
      if (active) setState('failed');
    });
    return () => { active = false; controller.abort(); };
  }, [expanded, path, revision, roomDetailLimit, sessionId, transport]);

  const candidate = data?.candidates.find((item) => item.sessionId === selectedSessionId) ?? data?.candidates[0];
  const coverage = data?.coverage;
  return <section className="paw-files-collaboration" aria-label={fileName ? `${fileName} 协作与访问` : '协作与访问'}>
    <button className="paw-files-collaboration__toggle" type="button" aria-label="协作与访问" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      <span><strong>协作与访问</strong><small>关联的 Room、Session 与文件操作</small></span>
      <ChevronDown size={16} aria-hidden="true" className={expanded ? 'is-expanded' : undefined} />
    </button>
    {expanded ? <div className="paw-files-collaboration__body">
      <div className="paw-files-collaboration__toolbar">
        <p className="paw-files-collaboration__note">文档责任与产物登记指向关联任务；工具回执说明实际访问。</p>
        <button type="button" disabled={state === 'loading'} onClick={() => setRevision((value) => value + 1)} aria-label="刷新文档关联"><RefreshCw size={14} aria-hidden="true" />刷新关联</button>
      </div>
      {state === 'loading' ? <p role="status">正在查找文档关联…</p> : null}
      {state === 'failed' ? <p role="status">文档关联暂时读不到，可刷新重试。{data ? '下方保留上次读到的登记。' : ''}</p> : null}
      {data ? <>
        {data.issues.length ? <p role="status" className="paw-files-collaboration__note">{data.issues.join('；')}。可以刷新重试；已返回的关联仍可打开。</p> : null}
        <section aria-label="文档责任与产物" className="paw-files-collaboration__group">
          <h3>文档责任与产物</h3>
          {data.relations.length ? <ul className="paw-files-collaboration__list">
            {data.relations.map((row) => <li key={`${row.kind}:${row.id}`}>
              <strong>{row.title}</strong>
              <p className="paw-files-collaboration__note">{row.stale ? '上次读到的关联 · 本次未能重新确认' : row.detail}</p>
              <div className="paw-files-collaboration__links">{row.links.map((item) => <EntityButton key={`${item.kind}:${item.id}`} item={item} />)}</div>
            </li>)}
          </ul> : <p>已读取的登记中尚未找到此文件。可继续核对 Room，或查看下方 Session 的实际访问。</p>}
        </section>
        <section aria-label="Session 文件访问" className="paw-files-collaboration__group">
          <h3>Session 文件访问</h3>
          <label className="paw-files-collaboration__chooser">核对 Session
            <select value={candidate?.sessionId ?? ''} onChange={(event) => setSelectedSessionId(event.target.value)} aria-label="核对访问的 Session">
              {data.candidates.map((item) => <option value={item.sessionId} key={item.sessionId}>{item.title} · {item.reason}</option>)}
            </select>
          </label>
          {candidate ? <FileAccessInspector key={`${candidate.sessionId}:${candidate.workspaceRoots.join('|')}`} candidate={candidate} path={path} /> : <p>Session 候选暂未读到，可刷新关联目录。</p>}
        </section>
        <details className="paw-files-collaboration__workspace">
          <summary>同一工作区 · {data.workspace.length} 个 Room / Session</summary>
          <p className="paw-files-collaboration__note">这些记录的工作区覆盖此文件。仅凭工作区绑定，无法确认它们访问过这份文件。</p>
          <div className="paw-files-collaboration__links">{data.workspace.map((item) => <EntityButton key={`${item.kind}:${item.id}`} item={item} />)}</div>
        </details>
        {coverage ? <p className="paw-files-collaboration__note">本次目录：{coverage.sessions === null ? 'Session 目录未读到' : `${coverage.sessions} 段 Session`}、{coverage.rooms === null ? 'Room 目录未读到' : `${coverage.rooms} 个 Room`}、{coverage.documents === null ? '文档登记未读到' : `${coverage.documents} 份文档登记`}；{coverage.rooms !== null ? <>核对 {coverage.checkedRooms}/{coverage.relevantRooms} 个相关 Room。</> : null}{data.limited ? '结果仅覆盖本次已读取的范围。' : ''}</p> : null}
        <div className="paw-files-collaboration__links">
          {coverage && roomDetailLimit < coverage.relevantRooms ? <button type="button" disabled={state === 'loading'} onClick={() => setRoomDetailLimit((value) => value + 3)}>继续查找 Room 关联</button> : null}
          {data.limited || data.issues.length ? <><button type="button" onClick={() => openPawOsRoute(desktop, '/rooms')}>打开 Room 列表</button><button type="button" onClick={() => openPawOsRoute(desktop, '/agent')}>打开 Session 列表</button></> : null}
        </div>
      </> : null}
      {children}
    </div> : null}
  </section>;
}

function EntityButton({ item }: { item: CollaborationLink }) {
  const desktop = usePawOsDesktop();
  const kind = item.kind === 'session' ? 'Session' : 'Room';
  return <button type="button" onClick={() => openPawOsRoute(desktop, item.route)} aria-label={item.kind === 'document' ? '打开工作文档' : `打开 ${kind} ${item.title}`}>
    {item.kind === 'document' ? item.title : <><span className="paw-files-collaboration__kind">{kind}</span>{item.title}</>}
  </button>;
}

function FileAccessInspector({ candidate, path }: { candidate: FileSessionCandidate; path: string }) {
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const [projection, setProjection] = useState<AgentProjectionState>();
  const previous = useRef<AgentProjectionState | undefined>(undefined);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [revision, setRevision] = useState(0);
  const [checkedAtMs, setCheckedAtMs] = useState(0);
  const [visible, setVisible] = useState(document.visibilityState !== 'hidden');
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  useEffect(() => {
    if (!visible) return;
    let active = true;
    const controller = new AbortController();
    setState('loading');
    void readFileActivity(transport, candidate, { signal: controller.signal, previous: previous.current }).then((value) => {
      if (!active) return;
      previous.current = value;
      setProjection(value);
      setCheckedAtMs(Date.now());
      setState('ready');
    }).catch(() => {
      if (active) setState('failed');
    });
    return () => { active = false; controller.abort(); };
  }, [candidate.sessionId, revision, transport, visible]);

  const access = projection ? fileToolAccess(projection, path, candidate.workspaceRoots) : undefined;
  const fresh = state === 'ready' && visible;
  const current = fresh ? access?.rows.filter((row) => row.state === 'running') ?? [] : [];
  const history = access?.rows.filter((row) => !fresh || row.state !== 'running') ?? [];
  // Only the one selected Session is refreshed, only while Runtime is busy.
  // A failed read stops automatic retries and removes all current-state claims.
  useEffect(() => {
    if (!fresh || !projection || !['busy', 'working', 'responding', 'analyzing'].includes(projection.status)) return;
    const timer = window.setTimeout(() => setRevision((value) => value + 1), 8_000);
    return () => window.clearTimeout(timer);
  }, [fresh, projection]);

  return <div className="paw-files-collaboration__access">
    <div className="paw-files-collaboration__toolbar">
      <button type="button" onClick={() => openPawOsRoute(desktop, `/agent?${new URLSearchParams({ session: candidate.sessionId })}`)}>打开 Session 核对</button>
      <button type="button" aria-label={state === 'failed' ? '重试访问记录' : '刷新访问记录'} disabled={state === 'loading'} onClick={() => setRevision((value) => value + 1)}><RefreshCw size={14} aria-hidden="true" />{state === 'failed' ? '重试' : '刷新访问'}</button>
    </div>
    {state === 'loading' ? <p role="status">正在读取访问记录…</p> : null}
    {state === 'failed' ? <p role="status">当前状态未知，访问记录暂时读不到。{projection ? '保留上次读到的操作回执。' : ''}请重试。</p> : null}
    {current.length ? <section aria-label="当前精确操作">
      <h4>当前精确操作</h4>
      <ul className="paw-files-collaboration__operations">{current.map((row) => <li key={row.id} data-current="true"><strong>{accessLabel(row, true)}</strong><span>目标路径与此文件完全一致</span></li>)}</ul>
    </section> : null}
    {history.length ? <section aria-label="已发生的访问">
      <h4>已发生的访问</h4>
      <ul className="paw-files-collaboration__operations">{history.map((row) => <li key={row.id}><strong>{accessLabel(row, false)}</strong><time dateTime={new Date(row.atMs).toISOString()}>{timeLabel(row.atMs)}</time></li>)}</ul>
    </section> : null}
    {fresh && !current.length ? <p className="paw-files-collaboration__note">这次读取未发现对此文件的进行中工具操作。{!history.length ? '最近工具记录中也没有完整路径匹配的访问。' : ''}</p> : null}
    {access?.unresolvedTargetCount ? <p className="paw-files-collaboration__note">{access.unresolvedTargetCount} 条工具记录未提供完整目标位置，未计入此文件。可打开 Session 核对原始记录。</p> : null}
    {checkedAtMs ? <p className="paw-files-collaboration__note">{fresh ? '检查于' : '上次读取'} {timeLabel(checkedAtMs)} · 只读取所选 Session 的最近工具记录。</p> : null}
  </div>;
}

function accessLabel(row: FileToolAccess, current: boolean): string {
  const operation = { read: '读取', write: '写入', edit: '修改', patch: '补丁修改' }[row.operation];
  return row.state === 'running' && current ? `正在${operation}` : row.state === 'completed' ? `已${operation}` : row.state === 'not_executed' ? `${operation}未执行` : row.state === 'failed' ? `${operation}失败` : `${operation}尝试`;
}
function timeLabel(atMs: number): string { return new Date(atMs).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
