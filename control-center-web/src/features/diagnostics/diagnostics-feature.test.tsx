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
    renderFeature(new MockControlTransport({ routes }));

    expect(await screen.findByText('语音定稿')).toBeInTheDocument();
    expect(screen.getByText('语音代理安装版本过旧，缺少完整定稿能力')).toBeInTheDocument();
    expect(screen.getByText('安装一致性')).toBeInTheDocument();
    expect(screen.getByText('voice was installed from another product commit')).toBeInTheDocument();
    expect(screen.queryByText('已返回运行信息')).not.toBeInTheDocument();
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
    await user.click(within(workflow).getByRole('button', { name: '查看影响' }));
    expect(await within(workflow).findByText('不会自动授予或撤销任何权限。')).toBeInTheDocument();
    await user.click(within(workflow).getByRole('button', { name: '确认这些更改' }));
    await user.click(within(workflow).getByRole('checkbox'));
    await user.click(within(workflow).getByRole('button', { name: '确认执行' }));

    expect(await within(workflow).findByText('这次更改已安全记录')).toBeInTheDocument();
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
    await user.click(within(workflow).getByRole('button', { name: '查看影响' }));
    await user.click(await within(workflow).findByRole('button', { name: '确认这些更改' }));
    await user.click(within(workflow).getByRole('checkbox'));
    await user.click(within(workflow).getByRole('button', { name: '确认执行' }));

    expect(await within(workflow).findByText('这次更改已安全记录')).toBeInTheDocument();
    expect(externalAction).not.toHaveBeenCalled();
    expect(transport.requests.some((item) => item.request.pathId === 'diagnostics.action.job')).toBe(true);
  });

  it('exposes every migrated repair and fails closed for external actions without the native bridge', async () => {
    renderFeature(runtimeTransport({ terminalStatus: 'succeeded', native: false }));

    expect(await screen.findByText('请在已安装的应用中操作')).toBeInTheDocument();
    const actionList = document.querySelector('.diagnostics-action-list');
    expect(actionList).not.toBeNull();
    expect(actionList?.querySelectorAll('.mgmt-workflow')).toHaveLength(6);

    for (const title of [
      '重新连接输入法',
      '重启后台服务',
      '重启本机模型',
      '重新部署输入法配置',
      '打开辅助功能设置',
      '暂停智能候选',
    ]) {
      expect(await screen.findByText(title)).toBeInTheDocument();
    }
    const accessibility = await workflowFor('打开辅助功能设置');
    expect(within(accessibility).queryByRole('button', { name: '当前不可用' })).not.toBeInTheDocument();
    const pause = await workflowFor('暂停智能候选');
    expect(within(pause).getByRole('button', { name: '查看影响' })).toBeEnabled();
  });

  it('offers a fresh preview after a terminal job failure', async () => {
    const user = userEvent.setup();
    renderFeature(runtimeTransport({ terminalStatus: 'failed' }));
    const workflow = await workflowFor('暂停智能候选');

    await user.click(within(workflow).getByRole('button', { name: '查看影响' }));
    await user.click(await within(workflow).findByRole('button', { name: '确认这些更改' }));
    await user.click(within(workflow).getByRole('checkbox'));
    await user.click(within(workflow).getByRole('button', { name: '确认执行' }));

    expect(await within(workflow).findByText('修复任务失败')).toBeInTheDocument();
    expect(within(workflow).getByRole('button', { name: '重新查看影响' })).toBeEnabled();
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
});

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
  const heading = await screen.findByText(title);
  const workflow = heading.closest<HTMLElement>('.mgmt-workflow');
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
