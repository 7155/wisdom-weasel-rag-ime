import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport } from '@/test/mock-transport';
import { ContextUsagePopover } from './ContextUsagePopover';

afterEach(() => cleanup());

describe('ContextUsagePopover', () => {
  it('opens the Context Usage dialog from the chat composer meter', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': {
          available: true,
          context: {
            systemPrompt: '<agent-profile>persona</agent-profile>\nbase system\n',
            systemPromptOptions: { contextFiles: [{ path: 'AGENTS.md', content: 'rules body' }] },
            activeTools: ['shell'],
            toolSchemas: [{ name: 'shell', description: 'run shell' }],
            modelCalls: [],
            updatedAtMs: 1,
          },
          telemetry: {
            context: { tokens: 12_000, contextWindow: 200_000, percent: 6 },
            latestCacheHitPercent: null,
            compactionCount: 0,
            updatedAtMs: 1,
          },
        },
      },
    });
    render(
      <ControlTransportProvider transport={transport}>
        <ContextUsagePopover
          sessionId="session-1"
          telemetry={{ tokens: 12_000, contextWindow: 200_000, percent: 6 }}
        />
      </ControlTransportProvider>,
    );

    expect(screen.getByRole('button', { name: '上下文已用 6%' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '上下文已用 6%' }));
    const dialog = await screen.findByRole('dialog', { name: 'Context Usage' });
    expect(within(dialog).getByText('Context Usage')).toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByText(/Full/)).toBeInTheDocument());
    expect(within(dialog).getByLabelText('上下文分层占用')).toBeInTheDocument();
  });
});
