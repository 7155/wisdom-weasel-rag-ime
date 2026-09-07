import { Download, ExternalLink, PackageCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { Button, Field, Input } from '@/components/primitives';
import { PAW_EXTENSION_INSTALLATION_CHANGED_EVENT } from '@/paw-os/extensions/installation';
import { commandLabApp, downloadLabApp, pendingLabAppCommands, useLabApps, type LabAppCommand } from './apps';
import { LabAppPreview } from './LabAppPreview';
import { projectCommandRejected, projectError } from './api';

export function LabAppDelivery({ projectId, preparing = false, onPrepare }: { projectId: string; preparing?: boolean; onPrepare?: (directory: string, appId?: string) => Promise<boolean> }) {
  const transport = useControlTransport(); const catalog = useLabApps(projectId); const [selectedId, setSelectedId] = useState('');
  const appId = selectedId || catalog.data?.items[0]?.appId || ''; const [selectedVersion, setSelectedVersion] = useState<number>();
  const requestedVersion = selectedVersion ?? catalog.data?.items.find((item) => item.appId === appId)?.latestVersion;
  const query = useLabApps(projectId, appId, requestedVersion); const app = query.data?.app; const version = query.data?.version;
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [pending, setPending] = useState<LabAppCommand>();
  const [directory, setDirectory] = useState('app');
  useEffect(() => { setPending(pendingLabAppCommands(transport, appId).find((command) => ['activate', 'deactivate'].includes(command.action))); }, [transport, appId]);
  useEffect(() => { if (requestedVersion && selectedVersion === undefined) setSelectedVersion(requestedVersion); }, [requestedVersion, selectedVersion]);
  const act = async (command: LabAppCommand) => {
    setBusy(true); setError('');
    try {
      await commandLabApp(transport, command); setPending(undefined); await Promise.all([query.refetch(), catalog.refetch()]);
      window.dispatchEvent(new Event(PAW_EXTENSION_INSTALLATION_CHANGED_EVENT));
    } catch (reason) {
      const definite = projectCommandRejected(reason); setPending(definite ? undefined : command); setError(projectError(reason));
      if (definite) void Promise.all([query.refetch(), catalog.refetch()]);
    }
    finally { setBusy(false); }
  };
  const download = async (target: 'paw' | 'standalone') => {
    if (!app || !version) return; setBusy(true); setError('');
    try { await downloadLabApp(transport, app.appId, version.version, target); }
    catch (reason) { setError(projectError(reason)); }
    finally { setBusy(false); }
  };
  return <section className="lab-app-delivery" aria-label="项目应用交付">
    <header><div><small>应用交付</small><h2>{version?.spec.title ?? app?.title ?? '把成果变成可用的应用'}</h2></div>
      {app && version ? <select aria-label="应用版本" value={version.version} onChange={(event) => setSelectedVersion(Number(event.target.value))}>
        {query.data?.versions?.map((item) => <option key={item.version} value={item.version}>v{item.version}{app.activeVersion === item.version ? ' · PAW 当前版本' : ''}</option>)}
      </select> : null}</header>
    {catalog.isError || query.isError ? <p className="lab-project-error" role="alert">{projectError(catalog.error ?? query.error)}</p> : null}
    {error || pending ? <div className="lab-project-error" role="alert"><p>{error || '应用操作尚未确认，已保留原请求。'}</p>{pending ? <Button onClick={() => void act(pending)} disabled={busy}>核对原操作</Button> : null}</div> : null}
    {onPrepare ? <details className="lab-app-delivery__sources"><summary>从执行目录准备应用</summary>
      <form onSubmit={(event) => { event.preventDefault(); void (async () => {
        if (await onPrepare(directory, appId || undefined)) {
          const [fresh] = await Promise.all([catalog.refetch(), query.refetch()]);
          const prepared = appId ? fresh.data?.items.find((item) => item.appId === appId) : fresh.data?.items[0];
          if (prepared) { setSelectedId(prepared.appId); setSelectedVersion(prepared.latestVersion); }
        }
      })(); }}><p>填写项目执行目录中的应用子目录，里面应有 app.json、界面和方法文件。准备后可试用并导出；已有应用会增加一个版本。</p>
        <Field label="应用源目录" htmlFor="lab-app-source-directory"><Input id="lab-app-source-directory" value={directory} onChange={(event) => setDirectory(event.target.value)} required /></Field>
        <Button type="submit" disabled={busy || preparing || !directory.trim()}>准备应用版本</Button>
      </form></details> : null}
    {catalog.data?.items.length ? <nav aria-label="项目应用">{catalog.data.items.map((item) => <button key={item.appId} aria-current={item.appId === appId ? 'page' : undefined} onClick={() => { setSelectedId(item.appId); setSelectedVersion(undefined); }}>{item.title}</button>)}</nav> : null}
    {!catalog.isPending && !catalog.isError && !catalog.data?.items.length ? <div className="lab-project-empty"><PackageCheck size={28} /><h3>还没有准备好的应用版本</h3><p>让项目 Agent 在执行目录中实现应用并准备版本。界面、方法和输入由项目决定；准备完成后，就可以在这里试用和导出。</p></div>
      : app && version ? <><div className="lab-app-delivery__toolbar">
        <span>{version.fileCount} 份冻结源文件 · {(version.byteSize / 1024).toFixed(1)} KB · {version.spec.model.model}</span>
        <Button disabled={busy || app.activeVersion === version.version} onClick={() => void act({ action: 'activate', appId, expectedRevision: app.revision, clientRequestId: `app-activate:${crypto.randomUUID()}`, input: { version: version.version } })}><PackageCheck size={15} />{app.activeVersion === version.version ? '已添加至 PAW' : app.activeVersion ? '将此版本用于 PAW' : '添加至 PAW'}</Button>
        {app.activeVersion === version.version ? <Button onClick={() => { window.location.hash = `/extensions/${appId.slice('extension:'.length)}`; }}><ExternalLink size={15} />打开 App</Button> : null}
        <Button disabled={busy} onClick={() => void download('standalone')}><Download size={15} />下载独立 App</Button>
        <Button disabled={busy} onClick={() => void download('paw')}><Download size={15} />下载 PAW 应用包</Button>
      </div>{version.spec.knowledge ? <p className="lab-app-delivery__boundary">随包冻结 {version.spec.knowledge.documentCount.toLocaleString()} 篇文档、{version.spec.knowledge.chunkCount.toLocaleString()} 个切片。关键词检索 Top {version.spec.knowledge.profile.topK}，每次最多提供 {version.spec.knowledge.profile.contextChars.toLocaleString()} 字符证据。查找来源无需模型；生成回答会产生真实调用。</p> : null}
      {version.spec.externalWorkspace ? <p className="lab-app-delivery__boundary">连接工作台：{version.spec.externalWorkspace.title}。工作台服务需要单独启动，未随包复制；资料问答不会自动执行工作台任务。</p> : null}
      <p className="lab-app-delivery__boundary">PAW 使用此版本的方法和已配置模型。独立 App 使用 Python 标准库运行；生成回答需要在目标环境配置兼容的模型服务，应用包不携带登录凭据。</p>
      <LabAppPreview key={`${appId}:${version.version}`} app={app} version={version} calls={query.data?.calls ?? []} onActivity={() => void query.refetch()} />
      <details className="lab-app-delivery__sources"><summary>版本内容与来源</summary><p>源内容指纹：{version.contentHash}</p><ul>{version.sourceFiles.map((file) => <li key={file.path}>{file.path} · {file.byteSize} bytes</li>)}</ul>
        {app.activeVersion ? <Button size="small" disabled={busy} onClick={() => void act({ action: 'deactivate', appId, expectedRevision: app.revision, clientRequestId: `app-disable:${crypto.randomUUID()}`, input: {} })}>从 PAW 停用，保留版本和记录</Button> : null}</details></>
        : <p role="status">正在读取应用版本…</p>}
  </section>;
}
