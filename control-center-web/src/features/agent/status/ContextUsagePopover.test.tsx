import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport } from '@/test/mock-transport';
import { ContextUsagePopover } from './ContextUsagePopover';
import contextUsageCss from './ContextUsagePopover.css?raw';

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
            compactionCount: 2,
            latestCompaction: {
              reason: 'threshold',
              status: 'completed',
              tokensBefore: 128_000,
              estimatedTokensAfter: 29_000,
              updatedAtMs: 1,
            },
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
    expect(within(dialog).getByText('系统提示词')).toBeInTheDocument();
    expect(within(dialog).getAllByText('Token 未单独统计').length).toBeGreaterThan(0);
    expect(within(dialog).getByText(/总 Token 仅有整轮统计/)).toBeInTheDocument();
    expect(within(dialog).getByText(/128K → 约 29K/)).toBeInTheDocument();
  });

  it('moves focus into the dialog and restores it to the trigger after keyboard or button close', async () => {
    const user = userEvent.setup();
    render(
      <ContextUsagePopover
        sessionId="session-focus"
        telemetry={{ tokens: 4_000, contextWindow: 100_000, percent: 4 }}
      />,
    );
    const trigger = screen.getByRole('button', { name: '上下文已用 4%' });

    trigger.focus();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('button', { name: '关闭上下文用量' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    const close = await screen.findByRole('button', { name: '关闭上下文用量' });
    await user.click(close);
    expect(trigger).toHaveFocus();
  });

  it('sizes the portalled panel from Radix collision space and compacts its trigger in narrow composer containers', () => {
    expect(contextUsageCss).toContain('--radix-popover-content-available-width');
    expect(contextUsageCss).toMatch(/@container paw-composer-toolbar \(max-width: 360px\)/);
    expect(contextUsageCss).toMatch(/\.agent-context-usage__label\s*\{[^}]*clip-path:\s*inset\(50%\)/s);
  });
});
