import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { Button } from '@/components/primitives';
import { useRichHtmlUrl } from '@/features/agent/file-preview/use-rich-html-url';
import { commandLabApp, pendingLabAppCommands, type LabApp, type LabAppCall, type LabAppCommand, type LabAppVersion } from './apps';
import { object, type JsonValue } from './types';
import { projectCommandRejected, projectError } from './api';

const bridge = `<script>(()=>{
  const pending=new Map();
  const request=(kind,fields={})=>new Promise((resolve,reject)=>{
    const requestId=crypto.randomUUID();pending.set(requestId,{resolve,reject});
    parent.postMessage({kind,requestId,...fields},'*');
  });
  window.pawApp=Object.freeze({mode:'paw',
    invoke:(actionId,input={})=>request('paw.lab-app.invoke',{actionId,input}),
    history:()=>request('paw.lab-app.history')});
  addEventListener('message',e=>{
    if(e.source!==parent||e.data?.kind!=='paw.lab-app.result')return;
    const p=pending.get(e.data.requestId);if(!p)return;pending.delete(e.data.requestId);
    if(e.data.ok)p.resolve(e.data.result);
    else p.reject(Object.assign(new Error(e.data.message||'应用调用未完成'),{state:e.data.state,requestId:e.data.requestId}));
  });
})();</script>`;
const policy = `<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'">`;

export function LabAppPreview({ app, version, calls, onActivity }: { app: LabApp; version: LabAppVersion; calls: LabAppCall[]; onActivity: () => void }) {
  const transport = useControlTransport(); const frame = useRef<HTMLIFrameElement>(null);
  const inFlight = useRef(new Set<string>()); const delivered = useRef(new Set<string>());
  const requestCalls = useRef(new Map<string, string>());
  const [error, setError] = useState('');
  const [pending, setPending] = useState<LabAppCommand[]>(() => pendingLabAppCommands(transport, app.appId)
    .filter((command) => command.action === 'invoke' ? command.input.version === version.version : ['cancel', 'resume'].includes(command.action)));
  const html = useMemo(() => `<!doctype html>${policy}${bridge}${version.html}`, [version.html]);
  const previewUrl = useRichHtmlUrl(html);
  const send = useCallback(async (command: LabAppCommand, requestId?: string) => {
    setError('');
    try {
      const receipt = await commandLabApp(transport, command);
      setPending((items) => items.filter((item) => item.clientRequestId !== command.clientRequestId));
      if (receipt.call && requestId) requestCalls.current.set(receipt.call.callId, requestId);
      onActivity();
    } catch (reason) {
      const definite = projectCommandRejected(reason);
      setPending((items) => [...items.filter((item) => item.clientRequestId !== command.clientRequestId), ...(definite ? [] : [command])]);
      const message = projectError(reason, '应用请求暂未确认，已保留原输入。'); setError(message);
      if (definite && requestId) frame.current?.contentWindow?.postMessage({ kind: 'paw.lab-app.result', requestId, ok: false, state: 'rejected', message }, '*');
      if (definite) onActivity();
    }
  }, [transport, onActivity]);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow) return;
      const data = object(event.data);
      if (typeof data.requestId !== 'string' || !/^[a-f0-9-]{36}$/u.test(data.requestId)) return;
      if (data.kind === 'paw.lab-app.history') {
        const result = calls.filter((call) => call.appId === app.appId)
          .sort((left, right) => right.createdAtMs - left.createdAtMs).slice(0, 20)
          .map((call) => ({ requestId: call.callId, version: call.version, actionId: call.actionId,
            input: call.input, state: call.state, result: call.result, message: call.error,
            createdAtMs: call.createdAtMs, updatedAtMs: call.updatedAtMs }));
        frame.current?.contentWindow?.postMessage({ kind: 'paw.lab-app.result', requestId: data.requestId, ok: true, result }, '*');
        return;
      }
      let inputSize: number;
      try { inputSize = JSON.stringify(data.input ?? {}).length; } catch { return; }
      if (data.kind !== 'paw.lab-app.invoke'
          || typeof data.actionId !== 'string' || !version.spec.actions.some((action) => action.id === data.actionId)
          || inputSize > 32_000 || inFlight.current.has(data.requestId)) return;
      inFlight.current.add(data.requestId);
      void send({ action: 'invoke', appId: app.appId, expectedRevision: app.revision,
        clientRequestId: `app-ui:${app.appId}:${data.requestId}`,
        input: { version: version.version, actionId: data.actionId, values: object(data.input) as Record<string, JsonValue> } }, data.requestId);
    };
    window.addEventListener('message', receive); return () => window.removeEventListener('message', receive);
  }, [app.appId, app.revision, version.spec.actions, version.version, calls, send]);
  useEffect(() => {
    for (const call of calls) {
      const requestId = requestCalls.current.get(call.callId);
      if (!requestId || delivered.current.has(call.callId) || !['completed', 'failed', 'cancelled'].includes(call.state)) continue;
      frame.current?.contentWindow?.postMessage({ kind: 'paw.lab-app.result', requestId, ok: call.state === 'completed', state: call.state, result: call.result, message: call.error }, '*');
      delivered.current.add(call.callId);
    }
  }, [calls]);
  const active = calls.filter((call) => call.appId === app.appId && ['queued', 'running', 'interrupted'].includes(call.state));
  return <div className="lab-app-preview">
    {error || pending.length ? <div className="lab-project-error" role="alert"><p>{error || '有尚未确认的应用操作，已保留原请求。'}</p>{pending.map((command) => <Button key={command.clientRequestId} onClick={() => void send(command, command.action === 'invoke' ? command.clientRequestId.split(':').at(-1) : undefined)}>核对原操作</Button>)}</div> : null}
    {active.length ? <div className="lab-app-preview__activity" role="status">{active.map((call) => <span key={call.callId}>
      <small>应用 v{call.version}</small>
      {call.state === 'interrupted' ? '调用中断，保留原请求' : call.cancelRequested ? '正在停止…' : '应用正在处理…'}
      {call.state === 'interrupted' && !call.cancelRequested ? <Button size="small" onClick={() => void send({ action: 'resume', appId: app.appId, expectedRevision: app.revision, clientRequestId: `app-resume:${crypto.randomUUID()}`, input: { callId: call.callId } })}>恢复原调用</Button> : null}
      <Button size="small" disabled={call.cancelRequested && call.state !== 'interrupted'} onClick={() => void send({ action: 'cancel', appId: app.appId, expectedRevision: app.revision, clientRequestId: `app-cancel:${crypto.randomUUID()}`, input: { callId: call.callId } })}>{call.cancelRequested && call.state === 'interrupted' ? '重试停止' : '停止'}</Button>
    </span>)}</div> : null}
    <iframe ref={frame} title={`${version.spec.title} · 应用预览`} sandbox="allow-scripts" referrerPolicy="no-referrer" src={previewUrl} />
    {calls.length ? <details className="lab-app-preview__receipts"><summary>实际调用记录 · {calls.length}</summary>{calls.map((call) => <article key={call.callId}>
      <strong>{version.spec.actions.find((action) => action.id === call.actionId)?.title ?? call.actionId} · {call.state === 'completed' ? '已完成' : call.state === 'failed' ? '失败' : call.state === 'cancelled' ? '已停止' : call.state === 'interrupted' ? '中断' : '处理中'}</strong>
      <small>应用 v{call.version} · {call.sessionId || '等待 Runtime 接纳'}</small>
      {call.result.text ? <pre>{call.result.text}</pre> : call.error ? <p>{call.error}</p> : null}
      {call.result.usage && Object.keys(call.result.usage).length ? <small>实际用量：{JSON.stringify(call.result.usage)}</small> : null}
    </article>)}</details> : null}
  </div>;
}
