import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport, type MockControlTransportOptions } from '@/test/mock-transport';
import { DiagnosticsFeature } from './index';

const payloadSha256 = `sha256:${'a'.repeat(64)}`;
const commandSha256 = `sha256:${'b'.repeat(64)}`;
const routes = {
  'diagnostics.runtime': {
    ok: true,
    runtimeRevision: 7,
    runtimeConfig: { postCommit: { enabled: true } },
    components: {
      sidecar: { ok: true, status: 'ready', detail: '运行中' },
      voiceRecognition: {
        ok: false,
        status: 'error',
        detail: '语音代理安装版本过旧，缺少完整定稿能力',
      },
      deployment: {
        ok: false,
        status: 'error',
        detail: 'voice was installed from another product commit',
      },
    },
  },
  'diagnostics.predictor': { ok: true, predictor: { status: 'ready', providerName: 'local-mlx' } },
  'diagnostics.models': { ok: true, schemaVersion: 'rag-ime.models-status.v3' },
  'input.source.get': { ok: true, typingReady: false, readinessState: 'not_selected' },
} as const;

afterEach(cleanup);

describe('DiagnosticsFeature runtime actions', () => {
  it('keeps backend failure reasons visible and names voice components', async () => {
    const user = userEvent.setup();
    renderFeature(new MockControlTransport({ routes }));

    expect(await screen.findByText('实时转写')).toBeInTheDocument();
    expect(screen.getByText('已安装的语音输入组件版本较旧，暂不支持完整转写。')).toBeInTheDocument();
    expect(screen.getByText('安装状态')).toBeInTheDocument();
    expect(screen.getByText('已安装的语音组件与当前版本不一致。')).toBeInTheDocument();
    expect(screen.queryByText('voice was installed from another product commit')).not.toBeInTheDocument();
    expect(screen.queryByText('已返回运行信息')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '等待前台验证' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新检查' })).toBeInTheDocument();

    const service = screen.getByText('实时转写').closest('details');
    expect(service).toHaveClass('diagnostics-service');
    expect(service).not.toHaveAttribute('open');
    expect(within(service as HTMLElement).queryByText('建议处理')).not.toBeInTheDocument();

    await user.click(within(service as HTMLElement).getByText('实时转写'));
    expect(service).toHaveAttribute('open');
    expect(within(service as HTMLElement).getByText('建议处理')).toBeInTheDocument();
    expect(within(service as HTMLElement).getByText('先更新或重新部署受管输入法，再到真实应用中复测语音输入。')).toBeInTheDocument();

    await user.click(within(service as HTMLElement).getByText('脱敏技术记录'));
    expect(within(service as HTMLElement).getByText(/"component": "实时转写"/)).toBeInTheDocument();
    expect(within(service as HTMLElement).queryByText(/voice was installed/i)).not.toBeInTheDocument();

    await user.click(within(service as HTMLElement).getByText('实时转写'));
    expect(within(service as HTMLElement).getByText('实时转写').closest('summary')).toHaveAttribute('aria-expanded', 'false');
    expect(service).toHaveAttribute('open');
    expect(service?.querySelector('.diagnostics-disclosure__reveal')).toHaveAttribute('aria-hidden', 'true');
    expect(within(service as HTMLElement).getByText('建议处理')).toBeInTheDocument();
    await waitFor(() => expect(service).not.toHaveAttribute('open'));
    expect(within(service as HTMLElement).queryByText('建议处理')).not.toBeInTheDocument();
  });

  it('keeps candidate source, install, connection, production, and foreground render evidence separate', async () => {
    renderFeature(new MockControlTransport({
      routes: {
        ...routes,
        'diagnostics.runtime': {
          ok: true,
          runtimeRevision: 7,
          runtimeConfig: { postCommit: { enabled: true } },
          components: {
            assistantCandidateDelivery: {
              ok: false,
              status: 'unavailable',
              detail: '候选已生成，但尚无近期前台显示凭证',
              metadata: {
                stages: {
                  sourcePresent: { ok: true, detail: '候选框源码存在' },
                  installedProvenance: { ok: true, detail: '已安装版本与当前源码一致' },
                  sidecarConnected: { ok: true, detail: 'Sidecar 已响应' },
                  candidateProduced: { ok: true, detail: '最近真实请求已生成候选' },
                  foregroundRendered: { ok: false, detail: '前台 trace 没有近期显示事件' },
                },
              },
            },
          },
        },
      },
    }));

    expect(await screen.findByRole('heading', { name: '智能候选检查' })).toBeInTheDocument();
    expect(screen.getByText('输入法功能已准备')).toBeInTheDocument();
    expect(screen.getByText('已安装输入法版本')).toBeInTheDocument();
    expect(screen.getByText('本机补全服务已连接')).toBeInTheDocument();
    expect(screen.getByText('候选已生成')).toBeInTheDocument();
    expect(screen.getByText('候选已显示')).toBeInTheDocument();
    expect(screen.getByText('等待检查或实际输入验证')).toBeInTheDocument();
    expect(screen.queryByText('前台 trace 没有近期显示事件')).not.toBeInTheDocument();
    expect(screen.getByText('本机服务正常不代表候选已经显示。请依次检查输入法、已安装组件、本机补全服务、候选生成和前台显示。')).toBeInTheDocument();
  });

  it('runs the server-bound accessibility workflow and renders the terminal receipt', async () => {
    const user = userEvent.setup();
    const externalAction = vi.fn(async (request) => ({
      receiptId: request.receiptId,
      action: request.action,
      accepted: true,
      completed: true,
      exitCode: 0,
    }));
    const transport = runtimeTransport({ externalAction, terminalStatus: 'external-supervisor-required' });
    renderFeature(transport);

    const workflow = await workflowFor('打开辅助功能设置');
    expect(workflow).toHaveAttribute('data-confirmation', 'direct');
    await user.click(within(workflow).getByRole('button', { name: '打开辅助功能设置' }));

    expect(await within(workflow).findByText('已保存')).toBeInTheDocument();
    expect(externalAction).toHaveBeenCalledWith({
      action: 'open_accessibility_settings',
      receiptId: 'runtime-job-1',
      payloadSha256: 'a'.repeat(64),
      commandSha256: 'b'.repeat(64),
    });
    const previewCall = transport.requests.find((item) => item.request.pathId === 'diagnostics.action.preview');
    const startCall = transport.requests.find((item) => item.request.pathId === 'diagnostics.action.start');
    expect(previewCall?.request.body).toEqual({ action: 'open_accessibility_settings', expectedRuntimeRevision: 7 });
    expect(startCall?.request.body).toEqual(expect.objectContaining({
      action: 'open_accessibility_settings',
      expectedRuntimeRevision: 7,
      previewToken: 'preview-token',
      payloadSha256,
      commandSha256,
      confirmText: 'apply',
    }));
  });

  it('polls a backend-only pause job without invoking the native bridge', async () => {
    const user = userEvent.setup();
    const externalAction = vi.fn();
    const transport = runtimeTransport({ externalAction, terminalStatus: 'succeeded' });
    renderFeature(transport);

    const workflow = await workflowFor('暂停智能候选');
    expect(workflow).toHaveAttribute('data-confirmation', 'direct');
    await user.click(within(workflow).getByRole('button', { name: '暂停智能候选' }));

    expect(await within(workflow).findByText('已保存')).toBeInTheDocument();
    expect(externalAction).not.toHaveBeenCalled();
    expect(transport.requests.some((item) => item.request.pathId === 'diagnostics.action.job')).toBe(true);
  });

  it('keeps browser-preview repairs compact while still exposing every real action and its impact', async () => {
    renderFeature(runtimeTransport({ terminalStatus: 'succeeded', native: false }));

    expect(await screen.findByText('请在已安装的应用中操作')).toBeInTheDocument();
    expect(screen.queryByText(/固定白名单/)).not.toBeInTheDocument();
    const actionList = document.querySelector('.diagnostics-action-list');
    expect(actionList).toBeNull();
    const actionSummary = document.querySelector('.diagnostics-action-summary');
    expect(actionSummary?.querySelectorAll('li')).toHaveLength(6);

    for (const title of [
      '重新连接输入法',
      '重新连接本机补全服务',
      '应用并重启本机模型',
      '重新部署受管输入法',
      '打开辅助功能设置',
      '暂停智能候选',
    ]) {
      expect(await screen.findByText(title)).toBeInTheDocument();
    }
    expect(screen.getByText('需要确认')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '暂停智能候选' })).not.toBeInTheDocument();
  });

  it('offers a fresh preview after a terminal job failure', async () => {
    const user = userEvent.setup();
    renderFeature(runtimeTransport({ externalAction: vi.fn(), terminalStatus: 'failed' }));
    const workflow = await workflowFor('暂停智能候选');

    await user.click(within(workflow).getByRole('button', { name: '暂停智能候选' }));

    expect(await within(workflow).findByText('修复任务失败')).toBeInTheDocument();
    expect(within(workflow).getByRole('button', { name: '返回' })).toBeEnabled();
  });

  it('keeps preview-binding failures out of the user-facing repair feedback', async () => {
    const user = userEvent.setup();
    renderFeature(new MockControlTransport({
      externalAction: vi.fn(),
      routes: {
        ...routes,
        'diagnostics.action.preview': {
          ok: true,
          action: 'stop_ai',
          commandSha256: 'sha256:not-a-real-binding',
          previewToken: 'PRIVATE_PREVIEW_TOKEN',
          payloadSha256,
          requiredConfirm: 'apply',
        },
      },
    }));
    const workflow = await workflowFor('暂停智能候选');

    await user.click(within(workflow).getByRole('button', { name: '暂停智能候选' }));

    expect(await within(workflow).findByText('无法确认这项本机操作，请重新检查后再试。')).toBeInTheDocument();
    expect(within(workflow).queryByText(/PRIVATE_PREVIEW_TOKEN|绑定/)).not.toBeInTheDocument();
  });

  it('marks managed input-method redeployment as the only dangerous browser-preview repair', async () => {
    renderFeature(runtimeTransport({ native: false, terminalStatus: 'succeeded' }));

    expect(await screen.findByText('重新部署受管输入法')).toBeInTheDocument();
    const summary = document.querySelector('.diagnostics-action-summary');
    expect(summary).not.toBeNull();
    expect(within(summary as HTMLElement).getByText('需要确认')).toBeInTheDocument();
  });

  it('copies a support snapshot without internal contract metadata or local paths', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn(async (_value: string) => undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    renderFeature(new MockControlTransport({
      routes: {
        ...routes,
        'diagnostics.predictor': {
          ok: true,
          schemaVersion: 'rag-ime.predictor-status.v1',
          predictor: { model: '/Models/private/model.bin', payloadSha256: 'sha256:secret' },
        },
        'diagnostics.models': { ok: true, pathId: 'diagnostics.models', runtimeRevision: 9 },
      },
    }));

    await user.click(await screen.findByRole('button', { name: '复制排查报告' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const report = String(writeText.mock.calls[0]?.[0] ?? '');
    expect(report).not.toMatch(/schemaVersion|pathId|runtimeRevision|payloadSha|sha256:|\/Models\/private/);
    expect(report).toContain('"model": "已隐藏"');
  });

  it('does not disguise a capability read failure as an unavailable desktop action', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes });
    const capabilities = vi.spyOn(transport, 'capabilities')
      .mockRejectedValueOnce(new Error('native bridge timed out'))
      .mockResolvedValue({
        schemaVersion: 'rag-ime.control-frontend-capabilities.v1',
        transport: 'mock',
        routeIds: [],
        features: {},
        native: {
          pickFiles: false,
          managedAgentImageImport: false,
          revealPath: false,
          approvedExternalActions: false,
          keychain: false,
          tcc: false,
        },
      });
    renderFeature(transport);

    expect(await screen.findByText('无法确认本机操作能力')).toBeInTheDocument();
    expect(screen.queryByText('请在已安装的应用中操作')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '重新检查操作能力' }));

    await waitFor(() => expect(screen.queryByText('无法确认本机操作能力')).not.toBeInTheDocument());
    expect(capabilities).toHaveBeenCalledTimes(2);
  });

  it('keeps report export disabled until every core diagnostic source is ready', async () => {
    const runtime = deferred<typeof routes['diagnostics.runtime']>();
    const transport = new MockControlTransport({
      routes: { ...routes, 'diagnostics.runtime': () => runtime.promise },
    });
    renderFeature(transport);

    const copyButton = screen.getByRole('button', { name: '复制排查报告' });
    expect(copyButton).toBeDisabled();

    runtime.resolve(routes['diagnostics.runtime']);

    await waitFor(() => expect(copyButton).toBeEnabled());
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function runtimeTransport({
  externalAction,
  native = true,
  terminalStatus,
}: {
  externalAction?: MockControlTransportOptions['externalAction'];
  native?: boolean;
  terminalStatus: 'succeeded' | 'failed' | 'external-supervisor-required';
}) {
  let action = 'open_accessibility_settings';
  return new MockControlTransport({
    routes: {
      ...routes,
      'diagnostics.action.preview': (request: ControlRequest) => {
        action = String((request.body as Record<string, unknown>).action);
        return {
          ok: true,
          pathId: 'diagnostics.action.start',
          action,
          commandSha256,
          payloadSha256,
          previewToken: 'preview-token',
          expectedRevision: { runtimeRevision: 7 },
          expiresAtMs: Date.now() + 60_000,
          requiredConfirm: 'apply',
          externalSupervisorRequired: !['stop_ai', 'resume_ai'].includes(action),
          summary: {
            title: action === 'open_accessibility_settings' ? '打开辅助功能设置' : '确认运行操作',
            items: action === 'open_accessibility_settings'
              ? ['打开 macOS 辅助功能页面。', '不会自动授予或撤销任何权限。']
              : ['只执行已预览的运行操作。'],
            risk: 'R1',
          },
        };
      },
      'diagnostics.action.start': {
        ok: true,
        receiptId: 'work-receipt-1',
        pathId: 'diagnostics.action.start',
        payloadSha256,
        appliedAtMs: Date.now(),
        rollbackAvailable: false,
        rollbackToken: '',
        result: { jobId: 'runtime-job-1' },
      },
      'diagnostics.action.job': () => ({
        ok: true,
        job: {
          jobId: 'runtime-job-1',
          action,
          status: terminalStatus,
          error: terminalStatus === 'failed' ? '修复任务失败' : '',
          result: terminalStatus === 'external-supervisor-required'
            ? {
              externalAction: {
                action,
                receiptId: 'runtime-job-1',
                payloadSha256,
                commandSha256,
              },
            }
            : {},
        },
      }),
    },
    ...(native && externalAction ? { externalAction } : {}),
  });
}

async function workflowFor(title: string): Promise<HTMLElement> {
  const workflow = (await screen.findAllByText(title))
    .map((element) => element.closest<HTMLElement>('.mgmt-workflow'))
    .find((candidate): candidate is HTMLElement => Boolean(candidate));
  if (!workflow) throw new Error(`workflow not found for ${title}`);
  return workflow;
}

function renderFeature(transport: MockControlTransport) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <TooltipProvider delayDuration={0}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <DiagnosticsFeature />
        </QueryClientProvider>
      </ControlTransportProvider>
    </TooltipProvider>,
  );
}
