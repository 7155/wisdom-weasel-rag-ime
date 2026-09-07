import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport } from '@/test/mock-transport';
import { currentPawApps, pawApp, pawAppForPath } from '@/paw-os/runtime/app-registry';
import { pawExtensionApps, registerLabExtensionApps } from '@/paw-os/extensions/registry';
import { LabAppDelivery } from './LabAppDelivery';
import { LabAppPreview } from './LabAppPreview';
import type { LabApp, LabAppCall, LabAppVersion } from './apps';
import type { ControlRequest } from '@/platform/transport';

const firstId = 'extension:lab-11111111111111111111111111111111';
const secondId = 'extension:lab-22222222222222222222222222222222';
const app = (appId = firstId): LabApp => ({ appId, projectId: 'project-1', title: '售后助手', description: '按当前规则工作', revision: 1, latestVersion: 1, activeVersion: null, createdAtMs: 1, updatedAtMs: 1 });
const version = (appId = firstId): LabAppVersion => ({ appId, version: 1, contentHash: 'a'.repeat(64), html: '<h1>应用界面</h1>', fileCount: 3, byteSize: 1000, createdAtMs: 1,
  sourceFiles: [{ path: 'SKILL.md', byteSize: 100, sha256: 'a'.repeat(64) }], spec: { title: '售后助手', description: '按当前规则工作', html: 'index.html', skill: 'SKILL.md', context: ['rules.md'],
    model: { provider: 'test', model: 'test-model', thinkingLevel: 'medium' }, actions: [{ id: 'answer', title: '处理问题', prompt: '按规则回答', inputSchema: { type: 'object' } }] } });
const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); sessionStorage.clear(); registerLabExtensionApps({ ok: true, items: [] }); vi.restoreAllMocks(); });
function mount(transport: MockControlTransport, body = <LabAppDelivery projectId="project-1" />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client);
  return render(<QueryClientProvider client={client}><ControlTransportProvider transport={transport}>{body}</ControlTransportProvider></QueryClientProvider>);
}
const read = (current: LabApp, item = version()) => ({ ok: true, items: [current], app: current, version: item, versions: [item], calls: [] });

describe('Lab application delivery', () => {
  it('preserves the conversation while opening a declared workspace and denies its messages the App bridge', async () => {
    const current = app(); const item = version();
    item.spec.externalWorkspace = { title: '空间工作台', url: 'http://127.0.0.1:5173/' };
    const received: unknown[] = [];
    const transport = new MockControlTransport({ routes: { 'agent.eval-lab.apps.command': ({ body }: ControlRequest) => { received.push(body); return {}; } } });
    mount(transport, <LabAppPreview app={current} version={item} calls={[]} onActivity={() => undefined} />);
    const conversation = screen.getByTitle('售后助手 · 应用预览');
    expect(screen.queryByTitle('空间工作台')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '空间工作台' }));
    const workspace = screen.getByTitle('空间工作台') as HTMLIFrameElement;
    expect(workspace).toHaveAttribute('src', 'http://127.0.0.1:5173/');
    expect(workspace).toHaveAttribute('sandbox', expect.stringContaining('allow-same-origin'));
    expect(conversation).toHaveAttribute('hidden');
    await act(async () => { window.dispatchEvent(new MessageEvent('message', { source: workspace.contentWindow!, data: {
      kind: 'paw.lab-app.invoke', requestId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', actionId: 'answer', input: { question: 'foreign frame' },
    } })); });
    expect(received).toEqual([]);
    fireEvent.click(screen.getByRole('button', { name: '资料问答' }));
    expect(screen.getByTitle('售后助手 · 应用预览')).toBe(conversation);
    expect(conversation).not.toHaveAttribute('hidden');
    expect(workspace).toHaveAttribute('hidden');
  });

  it('mounts both split panes immediately and retains the conversation across mobile view selection', () => {
    const item = version(); item.spec.externalWorkspace = { title: '地图与故事', url: 'http://127.0.0.1:5173/embedded', presentation: 'split' };
    mount(new MockControlTransport(), <LabAppPreview app={app()} version={item} calls={[]} onActivity={() => undefined} />);
    const conversation = screen.getByTitle('售后助手 · 应用预览');
    const workspace = screen.getByTitle('地图与故事');
    expect(conversation).not.toHaveAttribute('hidden'); expect(workspace).not.toHaveAttribute('hidden');
    fireEvent.click(screen.getByRole('button', { name: '地图与故事' }));
    expect(screen.getByTitle('售后助手 · 应用预览')).toBe(conversation);
    expect(screen.getByTitle('地图与故事')).toBe(workspace);
  });

  it('does not embed the current control origin as an external workspace', () => {
    const item = version(secondId); item.spec.externalWorkspace = { title: '另一个工作台', url: window.location.origin + '/control' };
    mount(new MockControlTransport(), <LabAppPreview app={app(secondId)} version={item} calls={[]} onActivity={() => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: '另一个工作台' }));
    expect(screen.getByRole('alert')).toHaveTextContent('不能嵌入当前控制服务');
    expect(screen.queryByTitle('另一个工作台')).not.toBeInTheDocument();
  });

  it('opens the newly prepared version after the catalog refresh without falling back to its old selection', async () => {
    let current = app();
    const transport = new MockControlTransport({ routes: { 'agent.eval-lab.apps.get': ({ query }: ControlRequest) => {
      const chosen = { ...version(), version: Number(query?.version ?? current.latestVersion) };
      return { ...read(current, chosen), versions: [ { ...version(), version: 2 }, version() ] };
    } } });
    const prepare = vi.fn(async () => { current = { ...current, latestVersion: 2, revision: 2 }; return true; });
    mount(transport, <LabAppDelivery projectId="project-1" onPrepare={prepare} />);
    await screen.findByRole('button', { name: '添加至 PAW' });
    fireEvent.click(screen.getByText('从执行目录准备应用'));
    fireEvent.change(screen.getByRole('textbox', { name: '应用源目录' }), { target: { value: 'knowledge-app' } });
    fireEvent.click(screen.getByRole('button', { name: '准备应用版本' }));
    await waitFor(() => expect(screen.getByRole('combobox', { name: '应用版本' })).toHaveValue('2'));
    expect(prepare).toHaveBeenCalledWith('knowledge-app', firstId);
  });

  it('keeps a prepared version separate from activation and replays an unknown activation exactly', async () => {
    let current = app(); const received: unknown[] = [];
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.apps.get': () => read(current),
      'agent.eval-lab.apps.command': ({ body }: ControlRequest) => { received.push(body); current = { ...current, activeVersion: 1, revision: 2 }; if (received.length === 1) throw new TypeError('Connection lost'); return { ok: true, app: current, clientRequestId: (body as Record<string, unknown>).clientRequestId, replayed: true }; },
    } });
    mount(transport);
    fireEvent.click(await screen.findByRole('button', { name: '添加至 PAW' }));
    fireEvent.click(await screen.findByRole('button', { name: '核对原操作' }));
    expect(await screen.findByRole('button', { name: '已添加至 PAW' })).toBeDisabled();
    expect(received).toHaveLength(2); expect(received[1]).toEqual(received[0]);
    expect(screen.getByRole('button', { name: '打开 App' })).toBeVisible();
  });

  it('accepts declared actions only from its own opaque iframe and binds the frozen version', async () => {
    const received: Record<string, unknown>[] = [];
    const transport = new MockControlTransport({ routes: { 'agent.eval-lab.apps.command': ({ body }: ControlRequest) => { const command = body as Record<string, unknown>; received.push(command); return { ok: true, app: app(), call: { callId: 'call-1' }, clientRequestId: command.clientRequestId, replayed: false }; } } });
    mount(transport, <LabAppPreview app={app()} version={version()} calls={[]} onActivity={() => undefined} />);
    const frame = screen.getByTitle('售后助手 · 应用预览') as HTMLIFrameElement;
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts allow-popups allow-popups-to-escape-sandbox'); expect(frame.getAttribute('srcdoc')).toBeNull();
    expect(frame.getAttribute('src')).toMatch(/^\/__paw_html_preview#/u);
    expect(atob(frame.getAttribute('src')!.split('#')[1]!.replaceAll('-', '+').replaceAll('_', '/'))).toContain("connect-src 'none'");
    const data = { kind: 'paw.lab-app.invoke', actionId: 'answer', requestId: '11111111-1111-1111-1111-111111111111', input: { question: '第七天可以退吗？' } };
    fireEvent(window, new MessageEvent('message', { source: window, data }));
    fireEvent(window, new MessageEvent('message', { source: frame.contentWindow, data: { ...data, actionId: 'undeclared' } }));
    expect(received).toHaveLength(0);
    fireEvent(window, new MessageEvent('message', { source: frame.contentWindow, data }));
    fireEvent(window, new MessageEvent('message', { source: frame.contentWindow, data }));
    await waitFor(() => expect(received).toHaveLength(1));
    expect(received[0]).toMatchObject({ action: 'invoke', appId: firstId, expectedRevision: 1, input: { version: 1, actionId: 'answer', values: data.input } });
  });

  it('retains actual calls and offers recovery without inventing completed output', () => {
    const transport = new MockControlTransport({ routes: {} });
    const call: LabAppCall = { callId: 'call-1', appId: firstId, version: 1, actionId: 'answer', input: {}, state: 'interrupted', sessionId: 'session-1', result: {}, error: '连接中断', cancelRequested: false, createdAtMs: 1, updatedAtMs: 2 };
    mount(transport, <LabAppPreview app={app()} version={version()} calls={[call]} onActivity={() => undefined} />);
    expect(screen.getByRole('button', { name: '恢复原调用' })).toBeVisible();
    expect(screen.queryByText('已完成')).not.toBeInTheDocument();
  });

  it('delivers progress to the original frame without remounting or resolving before settlement', async () => {
    const onActivity = vi.fn(); let update!: (calls: LabAppCall[]) => void;
    const transport = new MockControlTransport({ routes: { 'agent.eval-lab.apps.command': ({ body }: ControlRequest) => ({ ok: true, app: app(), call: { callId: 'call-1' }, clientRequestId: (body as Record<string, unknown>).clientRequestId, replayed: false }) } });
    function Surface() {
      const [calls, setCalls] = useState<LabAppCall[]>([]); update = setCalls;
      return <LabAppPreview app={app()} version={version()} calls={calls} onActivity={onActivity} />;
    }
    mount(transport, <Surface />);
    const frame = screen.getByTitle('售后助手 · 应用预览') as HTMLIFrameElement;
    const notify = vi.spyOn(frame.contentWindow!, 'postMessage'); const src = frame.src;
    const requestId = '11111111-1111-1111-1111-111111111111';
    fireEvent(window, new MessageEvent('message', { source: frame.contentWindow, data: { kind: 'paw.lab-app.invoke', actionId: 'answer', requestId, input: { question: 'original' } } }));
    await waitFor(() => expect(onActivity).toHaveBeenCalledTimes(1));
    const call: LabAppCall = { callId: 'call-1', appId: firstId, version: 1, actionId: 'answer', input: {}, state: 'running', sessionId: 'session-1', result: {}, error: '', cancelRequested: false, createdAtMs: 1, updatedAtMs: 2,
      progress: { stage: 'thinking', sources: [{ title: 'Actual source' }] } };
    act(() => update([call]));
    expect(notify).toHaveBeenCalledWith({ kind: 'paw.lab-app.progress', requestId, progress: call.progress }, '*');
    expect(notify.mock.calls.some(([message]) => message.kind === 'paw.lab-app.result')).toBe(false);
    expect(screen.getByTitle('售后助手 · 应用预览')).toBe(frame); expect(frame.src).toBe(src);
    act(() => update([{ ...call, state: 'completed', progress: { ...call.progress, stage: 'completed' }, result: { text: 'Settled answer' } }]));
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ kind: 'paw.lab-app.result', requestId, ok: true, result: { text: 'Settled answer' } }), '*');
  });

  it('keeps an older active version controllable while a newer version is displayed', async () => {
    const received: Record<string, unknown>[] = [];
    const transport = new MockControlTransport({ routes: { 'agent.eval-lab.apps.command': ({ body }: ControlRequest) => {
      const command = body as Record<string, unknown>; received.push(command);
      return { ok: true, app: app(), clientRequestId: command.clientRequestId, replayed: false };
    } } });
    const oldCall: LabAppCall = { callId: 'older-running-call', appId: firstId, version: 1, actionId: 'answer', input: {},
      state: 'running', sessionId: 'session-1', result: {}, error: '', cancelRequested: false, createdAtMs: 1, updatedAtMs: 2 };
    mount(transport, <LabAppPreview app={app()} version={{ ...version(), version: 2 }}
      calls={[oldCall, { ...oldCall, appId: secondId, callId: 'foreign-running-call' }]} onActivity={() => undefined} />);
    expect(screen.getByRole('status')).toHaveTextContent('应用 v1');
    fireEvent.click(screen.getByRole('button', { name: '停止' }));
    await waitFor(() => expect(received).toHaveLength(1));
    expect(received[0]).toMatchObject({ action: 'cancel', appId: firstId, input: { callId: 'older-running-call' } });
  });

  it('binds embedded stop to its own admitted call and keeps the original promise pending until settlement', async () => {
    const commands: Record<string, unknown>[] = []; let update!: (calls: LabAppCall[]) => void;
    const transport = new MockControlTransport({ routes: { 'agent.eval-lab.apps.command': ({ body }: ControlRequest) => {
      const command = body as Record<string, unknown>; commands.push(command);
      return { ok: true, app: app(), call: { callId: 'call-1' }, clientRequestId: command.clientRequestId, replayed: false };
    } } });
    const onActivity = vi.fn();
    function Surface() {
      const [calls, setCalls] = useState<LabAppCall[]>([]); update = setCalls;
      return <LabAppPreview app={app()} version={version()} calls={calls} onActivity={onActivity} />;
    }
    mount(transport, <Surface />);
    const frame = screen.getByTitle('售后助手 · 应用预览') as HTMLIFrameElement;
    const notify = vi.spyOn(frame.contentWindow!, 'postMessage');
    const requestId = '11111111-1111-1111-1111-111111111111';
    const send = (kind: string, source: Window | null = frame.contentWindow, id = requestId) => fireEvent(window,
      new MessageEvent('message', { source, data: { kind, requestId: id, actionId: 'answer', input: { question: 'original' } } }));
    send('paw.lab-app.invoke');
    await waitFor(() => expect(commands).toHaveLength(1));
    const call: LabAppCall = { callId: 'call-1', appId: firstId, version: 1, actionId: 'answer', input: {},
      state: 'running', sessionId: 'session-1', result: {}, error: '', cancelRequested: false, createdAtMs: 1, updatedAtMs: 2 };
    act(() => update([call]));
    send('paw.lab-app.cancel', window); send('paw.lab-app.cancel', frame.contentWindow, '22222222-2222-2222-2222-222222222222');
    expect(commands).toHaveLength(1);
    send('paw.lab-app.cancel'); send('paw.lab-app.cancel');
    await waitFor(() => expect(commands).toHaveLength(2));
    expect(commands[1]).toMatchObject({ action: 'cancel', appId: firstId, input: { callId: 'call-1' } });
    expect(notify.mock.calls.some(([message]) => message.kind === 'paw.lab-app.result')).toBe(false);
    act(() => update([{ ...call, state: 'cancelled', cancelRequested: true, error: '已停止' }]));
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ kind: 'paw.lab-app.result', requestId, state: 'cancelled', ok: false }), '*');
  });

  it('restores only this application history through its own frame without submitting a call', () => {
    const transport = new MockControlTransport({ routes: {} });
    const calls: LabAppCall[] = Array.from({ length: 25 }, (_, index) => ({ callId: `call-${index}`, appId: firstId,
      version: index < 10 ? 1 : 2, actionId: 'answer', input: { question: `原问题 ${index}` }, state: 'completed',
      sessionId: `session-${index}`, result: { text: `原结果 ${index}` }, error: '', cancelRequested: false,
      createdAtMs: index + 1, updatedAtMs: index + 2 }));
    calls.push({ ...calls[0]!, callId: 'foreign-call', appId: secondId, createdAtMs: 99 });
    mount(transport, <LabAppPreview app={app()} version={version()} calls={calls} onActivity={() => undefined} />);
    const frame = screen.getByTitle('售后助手 · 应用预览') as HTMLIFrameElement;
    const notify = vi.spyOn(frame.contentWindow!, 'postMessage');
    const data = { kind: 'paw.lab-app.history', requestId: '11111111-1111-1111-1111-111111111111' };
    fireEvent(window, new MessageEvent('message', { source: window, data }));
    expect(notify).not.toHaveBeenCalled();
    fireEvent(window, new MessageEvent('message', { source: frame.contentWindow, data }));
    expect(notify).toHaveBeenCalledTimes(1);
    const reply = notify.mock.calls[0]![0];
    expect(reply).toMatchObject({ kind: 'paw.lab-app.result', requestId: data.requestId, ok: true });
    expect(reply.result).toHaveLength(20);
    expect(reply.result[0]).toMatchObject({ requestId: 'call-24', version: 2, input: { question: '原问题 24' }, result: { text: '原结果 24' }, createdAtMs: 25 });
    expect(reply.result.some((row: { requestId: string }) => row.requestId === 'foreign-call')).toBe(false);
    expect(transport.requests).toHaveLength(0);
  });

  it('restores an uncertain paid request after remount and reconciles its original identity', async () => {
    const received: unknown[] = [];
    const transport = new MockControlTransport({ routes: { 'agent.eval-lab.apps.command': ({ body }: ControlRequest) => {
      received.push(body); if (received.length === 1) throw new TypeError('Failed to fetch');
      return { ok: true, app: app(), clientRequestId: (body as Record<string, unknown>).clientRequestId, replayed: true };
    } } });
    const first = mount(transport, <LabAppPreview app={app()} version={version()} calls={[]} onActivity={() => undefined} />);
    const frame = screen.getByTitle('售后助手 · 应用预览') as HTMLIFrameElement;
    fireEvent(window, new MessageEvent('message', { source: frame.contentWindow, data: {
      kind: 'paw.lab-app.invoke', requestId: '11111111-1111-1111-1111-111111111111', actionId: 'answer', input: { question: '保留这次问题' },
    } }));
    await screen.findByRole('button', { name: '核对原操作' });
    expect(screen.getByText('应用请求暂未确认，已保留原输入。')).toBeVisible(); first.unmount();
    mount(transport, <LabAppPreview app={app()} version={version()} calls={[]} onActivity={() => undefined} />);
    expect(received).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: '核对原操作' }));
    await waitFor(() => expect(received).toHaveLength(2)); expect(received[1]).toEqual(received[0]);
  });

  it('returns a definite input rejection to the iframe instead of leaving it waiting forever', async () => {
    const transport = new MockControlTransport({ routes: { 'agent.eval-lab.apps.command': () => {
      throw Object.assign(new Error('请填写问题'), { status: 422 });
    } } });
    mount(transport, <LabAppPreview app={app()} version={version()} calls={[]} onActivity={() => undefined} />);
    const frame = screen.getByTitle('售后助手 · 应用预览') as HTMLIFrameElement;
    const notify = vi.spyOn(frame.contentWindow!, 'postMessage');
    fireEvent(window, new MessageEvent('message', { source: frame.contentWindow, data: {
      kind: 'paw.lab-app.invoke', requestId: '11111111-1111-1111-1111-111111111111', actionId: 'answer', input: {},
    } }));
    await screen.findByText('请填写问题');
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ kind: 'paw.lab-app.result', ok: false, message: '请填写问题' }), '*');
    expect(screen.queryByRole('button', { name: '核对原操作' })).not.toBeInTheDocument();
  });

  it('registers two different server-activated identities without rebuilding the desktop', () => {
    const row = (appId: string, label: string) => ({ ...app(appId), activeVersion: 1, installation: {
      schemaVersion: 'pawos.lab-app.v1', id: appId, version: '0.1.0', label, shortLabel: label, tagline: '项目自己的界面', route: `/extensions/${appId.slice('extension:'.length)}`,
      presentation: 'workspace', accent: 'green', icon: { symbol: 'assistant', background: '#22876A' }, packageId: appId,
      bindingSha256: 'a'.repeat(64), skillRef: 'SKILL.md', skillSha256: 'b'.repeat(64), verticalSuiteId: 'project-1', verticalSuiteRevision: '1',
      hosting: { kind: 'lab-html', appId, projectId: 'project-1', version: 1 },
    } });
    const branded = row(secondId, '发布检查器');
    branded.installation.accent = 'blue';
    branded.installation.icon = { symbol: 'analytics', background: '#215d74' };
    const ids = registerLabExtensionApps({ ok: true, items: [row(firstId, '售后助手'), branded] });
    expect([...ids]).toEqual([firstId, secondId]); expect(pawApp(firstId).label).toBe('售后助手'); expect(pawApp(secondId).label).toBe('发布检查器');
    expect(pawAppForPath(`/extensions/${secondId.slice('extension:'.length)}`)?.id).toBe(secondId);
    expect(currentPawApps().some((item) => item.id === secondId)).toBe(true);
    expect(pawExtensionApps.find((item) => item.id === secondId)?.icon).toEqual(branded.installation.icon);
    registerLabExtensionApps({ ok: true, items: [row(secondId, '发布检查器')] });
    expect(pawExtensionApps.some((item) => item.id === firstId)).toBe(false);
  });
});
