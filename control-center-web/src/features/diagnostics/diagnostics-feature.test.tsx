import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { DiagnosticsFeature } from './index';

const routes = {
  'diagnostics.runtime': { ok: true, components: { sidecar: { ok: true, status: 'ready' } } },
  'diagnostics.predictor': { ok: true, predictor: { status: 'ready', providerName: 'local-mlx' } },
  'diagnostics.models': { ok: true, schemaVersion: 'rag-ime.models-status.v3' },
  'input.source.get': { ok: true, typingReady: false, readinessState: 'not_selected' },
} as const;

afterEach(cleanup);

describe('DiagnosticsFeature native actions', () => {
  it('runs the allowlisted accessibility action and renders the native receipt', async () => {
    const user = userEvent.setup();
    const externalAction = vi.fn(async (request) => ({
      receiptId: request.receiptId,
      action: request.action,
      accepted: true,
      completed: true,
      exitCode: 0,
    }));
    renderFeature(new MockControlTransport({ routes, externalAction }));

    await user.click(await screen.findByRole('button', { name: '预览操作' }));
    expect(screen.getByText('仅打开系统设置，不自动修改权限。')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '继续确认' }));
    await user.click(screen.getByRole('button', { name: '打开系统设置' }));

    expect(await screen.findByText('macOS 辅助功能设置已打开。')).toBeInTheDocument();
    expect(externalAction).toHaveBeenCalledWith(expect.objectContaining({
      action: 'open_accessibility_settings',
      payloadSha256: expect.stringMatching(/^[a-f0-9]{64}$/),
      commandSha256: expect.stringMatching(/^[a-f0-9]{64}$/),
    }));
    expect(screen.getByRole('button', { name: '撤销' })).toBeDisabled();
    expect(screen.queryByText('重启 Sidecar')).not.toBeInTheDocument();
  });

  it('fails closed without the native action capability', async () => {
    renderFeature(new MockControlTransport({ routes }));

    expect(await screen.findByText('当前应用无法直接打开辅助功能设置，请从 macOS 系统设置中进入。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '查看示例' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '当前不可用' })).not.toBeInTheDocument();
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

    await user.click(await screen.findByRole('button', { name: '复制诊断' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const report = String(writeText.mock.calls[0]?.[0] ?? '');
    expect(report).not.toMatch(/schemaVersion|pathId|runtimeRevision|payloadSha|sha256:|\/Models\/private/);
    expect(report).toContain('"model": "已隐藏"');
  });
});

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
