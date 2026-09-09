import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import { PawOsAppSurfaceProvider } from '@/features/paw-os/surface-context';
import { TraceDiagnosticReportDocument } from './report-document';

afterEach(cleanup);

describe('Trace report Evidence dialog lifecycle', () => {
  it.each(['打开原对象', '打开 Trace'])('releases the Evidence modal before navigating with %s and leaves focus in the destination', async (action) => {
    const user = userEvent.setup();
    const modalAtNavigation: boolean[] = [];
    let destination: HTMLElement;
    const navigate = vi.fn(() => {
      modalAtNavigation.push(Boolean(document.querySelector('[role="dialog"], .ui-dialog__overlay')));
      destination.focus();
    });
    render(<><input aria-label="目标窗口输入" /><TraceDiagnosticReportDocument onOpenDiagnosticSession={() => undefined} onOpenTarget={navigate} onOpenTrace={navigate} report={fixture()} /></>);
    destination = screen.getByRole('textbox', { name: '目标窗口输入' });
    const opener = screen.getByRole('button', { name: '查看证据 evidence:source' });
    await user.click(opener);
    const dialog = await screen.findByRole('dialog', { name: 'Evidence 详情' });
    await user.click(within(dialog).getByRole('button', { name: action }));

    await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
    expect(modalAtNavigation).toEqual([false]);
    expect(screen.queryByRole('dialog', { name: 'Evidence 详情' })).not.toBeInTheDocument();
    await waitFor(() => expect(destination).toHaveFocus());
    expect(opener).not.toHaveFocus();
    expect(navigate).toHaveBeenCalledWith(action === '打开 Trace' ? 'trace:source' : fixture().targets[0]);
  });

  it('dismisses the portal when its owning PAW window becomes inactive and keeps it closed on return', async () => {
    const user = userEvent.setup();
    const report = fixture();
    const content = (active: boolean) => <PawOsAppSurfaceProvider active={active} appId="trace-agent" height={900} width={1200} windowId="trace-window"><TraceDiagnosticReportDocument onOpenDiagnosticSession={() => undefined} onOpenTarget={() => undefined} report={report} /></PawOsAppSurfaceProvider>;
    const view = render(content(true));
    await user.click(screen.getByRole('button', { name: '查看证据 evidence:source' }));
    expect(await screen.findByRole('dialog', { name: 'Evidence 详情' })).toBeVisible();
    view.rerender(content(false));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Evidence 详情' })).not.toBeInTheDocument());
    expect(document.querySelector('.ui-dialog__overlay')).toBeNull();
    view.rerender(content(true));
    expect(screen.queryByRole('dialog', { name: 'Evidence 详情' })).not.toBeInTheDocument();
  });

  it.each(['Escape', '关闭'])('still restores focus to the Evidence opener after ordinary %s dismissal', async (action) => {
    const user = userEvent.setup();
    render(<TraceDiagnosticReportDocument onOpenDiagnosticSession={() => undefined} onOpenTarget={() => undefined} report={fixture()} />);
    const opener = screen.getByRole('button', { name: '查看证据 evidence:source' });
    await user.click(opener);
    const dialog = await screen.findByRole('dialog', { name: 'Evidence 详情' });
    if (action === 'Escape') await user.keyboard('{Escape}');
    else await user.click(within(dialog).getByRole('button', { name: '关闭' }));
    await waitFor(() => expect(opener).toHaveFocus());
    expect(screen.queryByRole('dialog', { name: 'Evidence 详情' })).not.toBeInTheDocument();
  });
});

function fixture(): TraceDiagnosticReportV1 {
  return {
    schemaVersion: 'rag-ime.trace-diagnostic-report.v1', reportId: `trace-report:${'f'.repeat(32)}`, revision: 1, status: 'completed', title: 'Evidence 导航验收', diagnosticSessionId: 'agent:diagnostic', targets: [{ targetKey: 'session:source', kind: 'session', id: 'source', title: '来源对话', traceIds: ['trace:source'], sourceAvailable: true }], traceIds: ['trace:source'], inspectionSha256: 'a'.repeat(64), failureReason: '', createdAtMs: 100, updatedAtMs: 200,
    inspection: { evidence: [{ evidenceId: 'evidence:source', sourceRef: 'trace:source:span:read', sourceKind: 'trace_span', targetKey: 'session:source', summary: '读取来源文件', status: 'completed', traceId: 'trace:source' }] },
    result: { findings: [{ findingId: 'finding:source', observation: '需要核对原对象', hypothesis: '回跳应属于来源窗口', conclusion: '关闭详情后打开来源', candidateRepair: '保留报告身份', verification: '检查导航与焦点', evidenceIds: ['evidence:source'], dimensionId: 'tool_runtime', severity: 'high', confidence: 'medium' }] },
  };
}
