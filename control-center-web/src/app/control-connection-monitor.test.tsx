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
    vi.spyOn(transport, 'capabilities').mockRejectedValue(new Error('control service unavailable'));

    renderMonitor(transport);

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('连接受限'));
    expect(screen.getByRole('status')).toHaveAttribute('title', 'control service unavailable');
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
