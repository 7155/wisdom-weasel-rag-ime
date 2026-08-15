import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlConnectionMonitor } from '@/app/control-connection-monitor';
import { ControlTransportProvider } from '@/app/control-transport';
import { ConnectionIndicator, GlobalFeedbackProvider } from '@/components/feedback';
import { MockControlTransport } from '@/test/mock-transport';

afterEach(cleanup);

describe('control connection monitor', () => {
  it('keeps preview transport visibly separate from real local data', async () => {
    renderMonitor(new MockControlTransport());
    expect(await screen.findByRole('status')).toHaveTextContent('演示数据');
  });

  it('publishes a connected state after a real transport capability probe', async () => {
    const transport = new MockControlTransport();
    Object.defineProperty(transport, 'kind', { value: 'http' });
    const capabilities = vi.spyOn(transport, 'capabilities');

    renderMonitor(transport);

    await waitFor(() => expect(capabilities).toHaveBeenCalledOnce());
    expect(screen.getByRole('status')).toHaveTextContent('已连接');
  });

  it('reports a bounded degraded state when the local control service is unavailable', async () => {
    const transport = new MockControlTransport();
    Object.defineProperty(transport, 'kind', { value: 'http' });
    vi.spyOn(transport, 'capabilities').mockRejectedValue(new Error('Failed to fetch secret=abc'));

    renderMonitor(transport);

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('连接受限'));
    expect(screen.getByRole('status')).toHaveAttribute('title', '暂时无法连接本机控制服务');
    expect(screen.getByRole('status')).not.toHaveAttribute('title', expect.stringMatching(/secret|fetch/i));
  });
});

function renderMonitor(transport: MockControlTransport) {
  return render(
    <GlobalFeedbackProvider>
      <ControlTransportProvider transport={transport}>
        <ControlConnectionMonitor />
        <ConnectionIndicator />
      </ControlTransportProvider>
    </GlobalFeedbackProvider>,
  );
}
