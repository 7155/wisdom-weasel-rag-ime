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

function renderApprovals(transport = createPreviewTransport()) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ControlTransportProvider transport={transport}>
        <TooltipProvider>
          <MemoryRouter><ApprovalsFeature /></MemoryRouter>
        </TooltipProvider>
      </ControlTransportProvider>
    </QueryClientProvider>,
  );
  return transport;
}

describe('ApprovalsFeature', () => {
  it('tells the truth about the queue and mirrors the selected request in the decision panel', async () => {
    const user = userEvent.setup();
    renderApprovals();

    expect(await screen.findByRole('heading', { name: '审批中心', level: 1 })).toBeInTheDocument();

    const pulse = screen.getByRole('region', { name: '审批现状' });
    expect(within(pulse).getByText('2 项操作在等你决定')).toBeVisible();
    expect(within(pulse).getByText(/1 项高风险需要二次确认/)).toBeVisible();
    expect(within(pulse).getByText(/1 项将在 5 分钟内过期/)).toBeVisible();

    const queue = screen.getByRole('list', { name: '审批项目' });
    const releaseRow = within(queue).getByRole('button', { name: /构建并安装 Control Center 开发版本/ });
    expect(releaseRow).toHaveAttribute('aria-current', 'true');

    const panel = screen.getByRole('region', { name: '审批详情' });
    expect(within(panel).getByRole('heading', { level: 3, name: '构建并安装 Control Center 开发版本' })).toBeInTheDocument();
    expect(within(panel).getByText('控制中心迁移')).toBeVisible();

    await user.click(within(queue).getByRole('button', { name: /允许 Room 伙伴使用 Session 子 Agent 模板/ }));
    expect(within(panel).getByRole('heading', { level: 3, name: '允许 Room 伙伴使用 Session 子 Agent 模板' })).toBeInTheDocument();
    expect(within(queue).getByRole('button', { name: /允许 Room 伙伴使用 Session 子 Agent 模板/ })).toHaveAttribute('aria-current', 'true');
    expect(releaseRow).not.toHaveAttribute('aria-current');
  });

  it('keeps secret preview fields hidden and the R3 decision bound to the exact payload hash', async () => {
    const user = userEvent.setup();
    const transport = renderApprovals();

    expect(await screen.findByRole('heading', { name: '审批中心', level: 1 })).toBeInTheDocument();
    const panel = screen.getByRole('region', { name: '审批详情' });
    await within(panel).findByRole('heading', { level: 3, name: '构建并安装 Control Center 开发版本' });

    const listRequest = transport.requests.find((call) => call.request.pathId === 'agent.approvals.list');
    expect(listRequest?.request.query).toEqual({ limit: 500 });

    // Facts stay readable but never leak secret-named fields.
    expect(within(panel).getByText('恢复方式')).toBeInTheDocument();
    expect(within(panel).getByText('保留当前安装包，可按安装回执恢复')).toBeInTheDocument();
    expect(within(panel).getByText('已隐藏')).toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE_APPROVAL_TOKEN/)).not.toBeInTheDocument();

    await user.click(within(panel).getByText('完整预览'));
    expect(within(panel).getByText('以下完整预览与本次审批哈希绑定')).toBeInTheDocument();
    expect(within(panel).getByText('a'.repeat(64))).toBeInTheDocument();
    expect(within(panel).getByText(/"rollback": "保留当前安装包，可按安装回执恢复"/)).toBeInTheDocument();
    expect(within(panel).getByText(/"apiToken": "已隐藏"/)).toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE_APPROVAL_TOKEN/)).not.toBeInTheDocument();

    const previewDetails = within(panel).getByText('完整预览').closest('details');
    await user.click(within(panel).getByText('完整预览'));
    expect(within(panel).getByText('完整预览').closest('summary')).toHaveAttribute('aria-expanded', 'false');
    expect(previewDetails?.querySelector('.approvals-preview__reveal')).toHaveAttribute('aria-hidden', 'true');
    await waitFor(() => expect(previewDetails).not.toHaveAttribute('open'));
    expect(within(panel).queryByText(/"rollback": "保留当前安装包，可按安装回执恢复"/)).not.toBeInTheDocument();

    await user.click(within(panel).getByRole('button', { name: '批准' }));
    expect(within(panel).getByText('确认批准 R3 高风险操作？')).toBeVisible();
    await user.click(within(panel).getByRole('button', { name: '确认批准' }));

    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.approval.decide'
      && call.request.params?.approvalId === 'approval:preview-release'
      && (call.request.body as Record<string, unknown> | undefined)?.payloadSha256 === 'a'.repeat(64)
    ))).toBe(true));

    // The decided request leaves the pending queue; the desk moves on to the
    // next waiting item instead of leaving an empty panel.
    const queue = screen.getByRole('list', { name: '审批项目' });
    await waitFor(() => expect(within(queue).queryByRole('button', { name: /构建并安装 Control Center 开发版本/ })).not.toBeInTheDocument());
    expect(within(panel).getByRole('heading', { level: 3, name: '允许 Room 伙伴使用 Session 子 Agent 模板' })).toBeInTheDocument();

    // The fact record stays readable under 已处理 but offers no second decision.
    await user.click(screen.getByRole('radio', { name: '已处理' }));
    expect(await within(queue).findByRole('button', { name: /构建并安装 Control Center 开发版本/ })).toBeInTheDocument();
    expect(within(panel).getByRole('heading', { level: 3, name: '构建并安装 Control Center 开发版本' })).toBeInTheDocument();
    expect(within(panel).getAllByText('已批准待执行').length).toBeGreaterThan(0);
    expect(within(panel).queryByRole('button', { name: '批准' })).not.toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: '拒绝' })).not.toBeInTheDocument();
  });
});
