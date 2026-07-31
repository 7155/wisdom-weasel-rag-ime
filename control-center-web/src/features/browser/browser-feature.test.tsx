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

  it('shows accepted-but-unconfirmed receipts and keeps pairing credentials guarded', async () => {
    const user = userEvent.setup();
    renderBrowser();

    await screen.findByText('1 个浏览器在线');
    await user.click(screen.getByRole('button', { name: '获取截图' }));
    expect(await screen.findByText('获取截图请求已送达，等待确认')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '停止' }));
    expect(await screen.findByText('停止浏览器请求已送达，等待确认')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: /连接/ }));
    const credential = await screen.findByLabelText('配对凭据');
    expect(credential).toHaveAttribute('type', 'password');
    expect(credential).toHaveAccessibleDescription(/只复制给你正在配对的本机插件/);

    await user.click(screen.getByRole('button', { name: '轮换配对凭据' }));
    expect(await screen.findByText('轮换配对凭据请求已送达，等待确认')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '启动托管浏览器' }));
    expect(await screen.findByText('启动托管浏览器请求已送达，等待确认')).toBeInTheDocument();
  });

  it('turns a rejected browser action into a public failure receipt', async () => {
    const user = userEvent.setup();
    renderBrowser(true);

    await screen.findByText('1 个浏览器在线');
    await user.click(screen.getByRole('button', { name: '获取截图' }));

    expect(await screen.findByText('获取截图失败')).toBeInTheDocument();
    expect(screen.getByText('请求未完成；当前页面状态没有改变。请刷新状态后重试。')).toBeInTheDocument();
  });
});

function renderBrowser(failCommand = false) {
  const now = Date.now();
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
      'browser.status': {
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
      'browser.pairing': {
        ok: true,
        pairingToken: 'pairing-secret',
        tokenFingerprint: 'abcd1234',
        extensionPath: '/Applications/RagIme/BrowserCopilot/extension',
        bridgeUrl: 'http://127.0.0.1:8766',
      },
      'browser.tabs': {
        ok: true,
        items: [{
          deviceId: 'chrome-user',
          tabId: 17,
          title: 'Agent Runtime 文档',
          url: 'https://docs.example.com/runtime',
          active: true,
        }],
      },
      'browser.snapshot.latest': snapshot,
      'browser.permissions': {
        ok: true,
        items: [{
          promptId: 'bperm-research',
          origin: 'https://research.example.com',
          reason: '首次进入调研站点',
          action: 'domain_transition',
          status: 'pending',
          createdAtMs: now,
        }],
      },
      'browser.traces': { ok: true, items: [] },
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
