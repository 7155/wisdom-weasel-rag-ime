import { Button } from '@/components/primitives';
import { useEffect, useState } from 'react';
import type { PawExtensionAppProps } from '@/paw-os/extensions/types';
import { useLabApps } from './apps';
import { LabAppPreview } from './LabAppPreview';
import { projectError } from './api';
import './lab-project-workbench.css';

export default function LabAppHost({ manifest }: PawExtensionAppProps) {
  const hosting = manifest.hosting; const [activeVersion, setActiveVersion] = useState(hosting?.version);
  const query = useLabApps(hosting?.projectId ?? '', manifest.id, activeVersion);
  const app = query.data?.app; const version = query.data?.version;
  useEffect(() => { if (app?.activeVersion && activeVersion === undefined) setActiveVersion(app.activeVersion); }, [app?.activeVersion, activeVersion]);
  if (query.isError) return <div className="lab-project-error" role="alert"><p>{projectError(query.error)}</p><Button onClick={() => void query.refetch()}>重新读取应用</Button></div>;
  if (!app || !version) return <p className="lab-project-loading" role="status">正在打开 {manifest.label}…</p>;
  if (!app.activeVersion) return <div className="lab-project-empty"><h2>此应用已停用</h2><p>应用版本与调用记录保留在 Lab 中。</p></div>;
  return <section className="lab-app-host" aria-label={version.spec.title}>
    {app.activeVersion !== version.version ? <div className="lab-project-notice" role="status"><p>v{app.activeVersion} 已启用；当前仍显示 v{version.version}，保留你的输入和调用。</p><Button onClick={() => setActiveVersion(app.activeVersion!)}>载入已启用版本</Button></div> : null}
    <LabAppPreview key={version.version} app={app} version={version} calls={query.data?.calls ?? []} onActivity={() => void query.refetch()} />
  </section>;
}
