import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { TooltipProvider } from '@/components/primitives';
import { ApprovalsFeature } from '.';

afterEach(cleanup);

describe('ApprovalsFeature', () => {
  it('shows a cross-Session approval queue and keeps R3 confirmation bound to the exact payload', async () => {
    const user = userEvent.setup();
    const transport = createPreviewTransport();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <TooltipProvider>
            <MemoryRouter><ApprovalsFeature /></MemoryRouter>
          </TooltipProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole('heading', { name: '审批中心', level: 1 })).toBeInTheDocument();
    const summary = await screen.findByText('构建并安装 Control Center 开发版本');
    const card = summary.closest('li');
    expect(card).not.toBeNull();
    expect(within(card!).getByText('R3')).toBeVisible();
    expect(within(card!).getByText('控制中心迁移')).toBeVisible();
    expect(within(card!).queryByText('保留当前安装包，可按安装回执恢复')).not.toBeInTheDocument();

    await user.click(within(card!).getByText('完整预览'));
    expect(within(card!).getByText('以下完整预览与本次审批哈希绑定')).toBeInTheDocument();
    expect(within(card!).getByText(/"rollback": "保留当前安装包，可按安装回执恢复"/)).toBeInTheDocument();
    expect(within(card!).getByText(/"apiToken": "已隐藏"/)).toBeInTheDocument();
    expect(within(card!).queryByText(/PRIVATE_APPROVAL_TOKEN/)).not.toBeInTheDocument();
    expect(within(card!).getByText('a'.repeat(64))).toBeInTheDocument();

    const previewDetails = within(card!).getByText('完整预览').closest('details');
    await user.click(within(card!).getByText('完整预览'));
    expect(within(card!).getByText('完整预览').closest('summary')).toHaveAttribute('aria-expanded', 'false');
    expect(previewDetails).toHaveAttribute('open');
    expect(previewDetails?.querySelector('.approvals-preview__reveal')).toHaveAttribute('aria-hidden', 'true');
    expect(within(card!).getByText(/"rollback": "保留当前安装包，可按安装回执恢复"/)).toBeInTheDocument();
    await waitFor(() => expect(previewDetails).not.toHaveAttribute('open'));
    expect(within(card!).queryByText(/"rollback": "保留当前安装包，可按安装回执恢复"/)).not.toBeInTheDocument();

    const listRequest = transport.requests.find((call) => call.request.pathId === 'agent.approvals.list');
    expect(listRequest?.request.query).toEqual({ limit: 500 });

    await user.click(within(card!).getByRole('button', { name: '批准' }));
    expect(within(card!).getByText('确认批准 R3 高风险操作？')).toBeVisible();
    await user.click(within(card!).getByRole('button', { name: '确认批准' }));

    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.approval.decide'
      && call.request.params?.approvalId === 'approval:preview-release'
      && (call.request.body as Record<string, unknown> | undefined)?.payloadSha256 === 'a'.repeat(64)
    ))).toBe(true));
    await waitFor(() => expect(screen.queryByText('构建并安装 Control Center 开发版本')).not.toBeInTheDocument());
    await user.click(screen.getByRole('radio', { name: '已处理' }));
    expect(await screen.findByText('构建并安装 Control Center 开发版本')).toBeVisible();
    expect(screen.getByText('已批准待执行')).toBeVisible();
  });
});
