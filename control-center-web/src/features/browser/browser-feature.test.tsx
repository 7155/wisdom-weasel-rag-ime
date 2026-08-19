import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { BrowserFeature } from '.';

afterEach(cleanup);

describe('BrowserFeature', () => {
  it('shows the paired page as visual and structured context', async () => {
    const transport = renderBrowser();

    expect(await screen.findByRole('heading', { name: '浏览器', level: 1 })).toBeInTheDocument();
    expect(await screen.findByText('1 个浏览器在线')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Agent Runtime 文档', level: 2 })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '浏览器页面截图：Agent Runtime 文档' })).toHaveAttribute(
      'src',
      'blob:browser-snap-docs',
    );
    expect(screen.getByLabelText('结构化页面快照')).toHaveTextContent('[0:e1] button "运行测试"');
    expect(transport.requests.some((call) => call.request.pathId.startsWith('memory.'))).toBe(false);
  });

  it('changes co-drive mode and resolves a pending site permission', async () => {
    const user = userEvent.setup();
    const transport = renderBrowser();

    await screen.findByText('1 个浏览器在线');
    await user.click(screen.getByRole('radio', { name: '协同操作' }));
    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'browser.mode.update'
      && typeof call.request.body === 'object'
      && call.request.body !== null
      && !Array.isArray(call.request.body)
      && call.request.body.mode === 'codrive'
    ))).toBe(true));
    expect(await screen.findByText('切换浏览器操作方式已确认')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: /权限/ }));
    expect(await screen.findByText('https://research.example.com')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '仅本次' }));
    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'browser.permission.decide'
      && call.request.params?.promptId === 'bperm-research'
      && typeof call.request.body === 'object'
      && call.request.body !== null
      && !Array.isArray(call.request.body)
      && call.request.body.decision === 'allow_once'
    ))).toBe(true));
    expect(await screen.findByText('允许一次已确认')).toBeInTheDocument();
  });

  it('keeps a site permission actionable while browser status is still loading', async () => {
    const user = userEvent.setup();
    renderBrowser({ pendingStatus: true, permissionOrigin: 'https://pi.dev' });

    await user.click(await screen.findByRole('tab', { name: /权限 1/ }));
    expect(await screen.findByText('https://pi.dev')).toBeInTheDocument();
    expect(screen.getByText('浏览器状态正在恢复，权限请求仍可处理。')).toBeInTheDocument();
  });

  it('shows accepted-but-unconfirmed receipts and keeps pairing credentials guarded', async () => {
    const user = userEvent.setup();
    renderBrowser();

    await screen.findByText('1 个浏览器在线');
    await user.click(screen.getByRole('button', { name: '获取截图' }));
    expect(await screen.findByText('获取截图请求已送达，等待确认')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '停止' }));
    expect(await screen.findByText('停止浏览器请求已送达，等待确认')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: /连接/ }));
    const credential = await screen.findByLabelText('配对码');
    expect(credential).toHaveAttribute('type', 'password');
    expect(credential).toHaveAccessibleDescription(/只复制给正在配对的本机插件/);
    expect(screen.getByText('高级连接详情')).toBeInTheDocument();
    expect(screen.queryByText('桥接地址')).not.toBeInTheDocument();
    await user.click(screen.getByText('高级连接详情'));
    expect(screen.getByText('本机连接地址')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '更换配对码' }));
    expect(await screen.findByText('更换配对码请求已送达，等待确认')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '启动托管浏览器' }));
    expect(await screen.findByText('启动托管浏览器请求已送达，等待确认')).toBeInTheDocument();
  });

  it('turns a rejected browser action into a public failure receipt', async () => {
    const user = userEvent.setup();
    renderBrowser({ failCommand: true });

    await screen.findByText('1 个浏览器在线');
    await user.click(screen.getByRole('button', { name: '获取截图' }));

    expect(await screen.findByText('获取截图失败')).toBeInTheDocument();
    expect(screen.getByText('请求未完成；当前页面状态没有改变。请刷新状态后重试。')).toBeInTheDocument();
  });

  it('keeps browser status visible when tabs fail and retries only the tab list', async () => {
    const user = userEvent.setup();
    const transport = renderBrowser({ failOnce: ['tabs'] });

    expect(await screen.findByText('1 个浏览器在线')).toBeInTheDocument();
    expect(await screen.findByText('标签页暂时未同步')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Agent Runtime 文档', level: 2 })).toBeInTheDocument();
    const requestsBeforeRetry = requestCount(transport, 'browser.tabs');

    await user.click(screen.getByRole('button', { name: '重新加载标签页' }));

    await waitFor(() => expect(requestCount(transport, 'browser.tabs')).toBeGreaterThan(requestsBeforeRetry));
    await waitFor(() => expect(screen.queryByText('标签页暂时未同步')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: /Agent Runtime 文档/ })).toBeInTheDocument();
  });

  it('recovers snapshot, permission, and trace queries in place without false empty states', async () => {
    const user = userEvent.setup();
    renderBrowser({ failOnce: ['snapshot', 'permissions', 'traces'] });

    expect(await screen.findByText('页面快照未更新')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Agent Runtime 文档', level: 2 })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '重新加载页面快照' }));
    await waitFor(() => expect(screen.queryByText('页面快照未更新')).not.toBeInTheDocument());

    await user.click(screen.getByRole('tab', { name: /权限/ }));
    expect(await screen.findByText('权限请求未同步')).toBeInTheDocument();
    expect(screen.queryByText('没有待处理权限')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '重新加载权限请求' }));
    expect(await screen.findByText('https://research.example.com')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('权限请求未同步')).not.toBeInTheDocument());

    await user.click(screen.getByRole('tab', { name: /轨迹/ }));
    expect(await screen.findByText('执行轨迹未同步')).toBeInTheDocument();
    expect(screen.queryByText('暂无执行轨迹')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '重新加载执行轨迹' }));
    expect(await screen.findByText('暂无执行轨迹')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('执行轨迹未同步')).not.toBeInTheDocument());
  });

  it('recovers pairing locally and includes pairing in the page refresh', async () => {
    const user = userEvent.setup();
    const transport = renderBrowser({ failOnce: ['pairing'] });

    await screen.findByText('1 个浏览器在线');
    await user.click(screen.getByRole('tab', { name: /连接/ }));
    expect(await screen.findByText('配对信息未同步')).toBeInTheDocument();
    expect(screen.queryByText('配对码已生成')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '重新加载配对信息' }));
    expect(await screen.findByText('配对码已生成')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('配对信息未同步')).not.toBeInTheDocument());

    const pairingRequestsBeforeRefresh = requestCount(transport, 'browser.pairing');
    await user.click(screen.getByRole('button', { name: '刷新浏览器状态' }));
    await waitFor(() => expect(requestCount(transport, 'browser.pairing')).toBeGreaterThan(pairingRequestsBeforeRefresh));
  });
});

type BrowserQueryFailure = 'pairing' | 'permissions' | 'snapshot' | 'tabs' | 'traces';

function renderBrowser({
  failCommand = false,
  failOnce = [],
  pendingStatus = false,
  permissionOrigin = 'https://research.example.com',
}: {
  failCommand?: boolean;
  failOnce?: BrowserQueryFailure[];
  pendingStatus?: boolean;
  permissionOrigin?: string;
} = {}) {
  const now = Date.now();
  const pendingFailures = new Set(failOnce);
  const queryResponse = async <Value,>(name: BrowserQueryFailure, value: Value): Promise<Value> => {
    if (pendingFailures.delete(name)) throw new Error(`${name} unavailable`);
    return value;
  };
  const snapshot = {
    ok: true,
    schemaVersion: 'rag-ime.browser-control.v1',
    snapshotId: 'snap-docs',
    deviceId: 'chrome-user',
    tabId: 17,
    url: 'https://docs.example.com/runtime',
    title: 'Agent Runtime 文档',
    summary: '1 个 Frame · 2 个可交互元素',
    markdown: '# Agent Runtime 文档\nURL: https://docs.example.com/runtime\n- [0:e1] button "运行测试"',
    interactiveCount: 2,
    hasScreenshot: true,
    createdAtMs: now,
  };
  const transport = new MockControlTransport({
    browserSnapshotImageUrl: (snapshotId) => `blob:browser-${snapshotId}`,
    routes: {
      'browser.status': pendingStatus ? async () => new Promise(() => undefined) : {
        ok: true,
        mode: 'observe',
        clients: [{
          deviceId: 'chrome-user',
          displayName: '我的 Chrome',
          connected: true,
          activeTabId: 17,
        }],
        latestSnapshot: snapshot,
        managedBrowser: {
          running: false,
          profilePath: '/tmp/browser-profile',
        },
      },
      'browser.pairing': async () => queryResponse('pairing', {
        ok: true,
        pairingToken: 'pairing-secret',
        tokenFingerprint: 'abcd1234',
        extensionPath: '/Applications/RagIme/BrowserCopilot/extension',
        bridgeUrl: 'http://127.0.0.1:8766',
      }),
      'browser.tabs': async () => queryResponse('tabs', {
        ok: true,
        items: [{
          deviceId: 'chrome-user',
          tabId: 17,
          title: 'Agent Runtime 文档',
          url: 'https://docs.example.com/runtime',
          active: true,
        }],
      }),
      'browser.snapshot.latest': async () => queryResponse('snapshot', snapshot),
      'browser.permissions': async () => queryResponse('permissions', {
        ok: true,
        items: [{
          promptId: 'bperm-research',
          origin: permissionOrigin,
          reason: '首次进入调研站点',
          action: 'domain_transition',
          status: 'pending',
          createdAtMs: now,
        }],
      }),
      'browser.traces': async () => queryResponse('traces', { ok: true, items: [] }),
      'browser.mode.update': { ok: true, mode: 'codrive' },
      'browser.permission.decide': {
        ok: true,
        promptId: 'bperm-research',
        decision: 'allow_once',
      },
      'browser.command': failCommand
        ? async () => {
          throw new Error('bridge failed for https://secret.example.test');
        }
        : { ok: true },
      'browser.stop': { ok: true },
      'browser.pairing.rotate': { ok: true },
      'browser.managed.start': { ok: true },
      'browser.managed.stop': { ok: true },
    },
  });
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <TooltipProvider delayDuration={0}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <BrowserFeature />
        </QueryClientProvider>
      </ControlTransportProvider>
    </TooltipProvider>,
  );
  return transport;
}

function requestCount(transport: MockControlTransport, pathId: string): number {
  return transport.requests.filter((call) => call.request.pathId === pathId).length;
}
