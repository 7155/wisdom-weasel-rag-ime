import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { AgentActivityProjection } from '@/contracts/agent-reducer';
import { StubControlTransport } from '@/test/stub-control-transport';
import { GenericUserInputDialog } from './AgentReviewDialogs';

afterEach(cleanup);

describe('GenericUserInputDialog', () => {
  it('renders every grouped clarification and submits the selected answers once', async () => {
    const transport = inputTransport();
    const user = userEvent.setup();
    renderDialog(transport, inputActivity({
      requestId: 'input:grouped',
      requestKind: 'grouped_questions',
      questions: [
        { id: 'scope', question: '这次先覆盖哪一部分？', options: ['核心流程', '完整流程'] },
        { id: 'review', question: '完成后如何复核？', options: ['伙伴互查', '直接交付'] },
        { id: 'tone', question: '结果说明采用哪种风格？', options: ['简洁', '详细'] },
      ],
    }));

    const submit = screen.getByRole('button', { name: '一起提交' });
    expect(submit).toBeDisabled();
    expect(screen.getByRole('group', { name: '1. 这次先覆盖哪一部分？' })).toBeVisible();
    expect(screen.getByRole('group', { name: '2. 完成后如何复核？' })).toBeVisible();
    expect(screen.getByRole('group', { name: '3. 结果说明采用哪种风格？' })).toBeVisible();

    await user.click(within(screen.getByRole('group', { name: '1. 这次先覆盖哪一部分？' })).getByRole('radio', { name: '完整流程' }));
    await user.click(within(screen.getByRole('group', { name: '2. 完成后如何复核？' })).getByRole('radio', { name: '伙伴互查' }));
    await user.click(within(screen.getByRole('group', { name: '3. 结果说明采用哪种风格？' })).getByRole('radio', { name: '简洁' }));
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => expect(transport.requests).toHaveLength(1));
    expect(transport.requests[0]).toMatchObject({
      pathId: 'agent.session.ui.resolve',
      params: { sessionId: 'session:participant' },
      body: {
        requestId: 'input:grouped',
        value: JSON.stringify({
          answers: {
            scope: '完整流程',
            review: '伙伴互查',
            tone: '简洁',
          },
        }),
        resolutionSource: 'direct_user',
      },
    });
  });

  it('keeps grouped-question cancellation on the existing resolution path', async () => {
    const transport = inputTransport();
    renderDialog(transport, inputActivity({
      requestId: 'input:cancel',
      requestKind: 'grouped_questions',
      questions: [
        { id: 'scope', question: '选择范围', options: ['当前页面', '全部页面'] },
      ],
    }));
    await userEvent.click(screen.getByRole('button', { name: '取消这次提问' }));


    await waitFor(() => expect(transport.requests).toHaveLength(1));
    expect(transport.requests[0]).toMatchObject({
      pathId: 'agent.session.ui.resolve',
      params: { sessionId: 'session:participant' },
      body: {
        requestId: 'input:cancel',
        cancelled: true,
        resolutionSource: 'user_cancelled',
      },
    });
  });

  it('preserves the existing single-select response value', async () => {
    const transport = inputTransport();
    renderDialog(transport, inputActivity({
      requestId: 'input:single',
      requestKind: 'user_input_required',
      method: 'select',
      options: ['继续', '暂缓'],
    }));

    await userEvent.click(screen.getByRole('radio', { name: '继续' }));
    await userEvent.click(screen.getByRole('button', { name: '提交回答' }));

    await waitFor(() => expect(transport.requests).toHaveLength(1));
    expect(transport.requests[0]).toMatchObject({
      body: {
        requestId: 'input:single',
        value: '继续',
        resolutionSource: 'direct_user',
      },
    });
  });
});

function inputTransport(): StubControlTransport {
  return new StubControlTransport('mock', {
    'agent.session.ui.resolve': { ok: true },
  });
}

function renderDialog(transport: StubControlTransport, activity: AgentActivityProjection): void {
  render(
    <ControlTransportProvider transport={transport}>
      <GenericUserInputDialog activity={activity} sessionId="session:participant" onError={() => undefined} />
    </ControlTransportProvider>,
  );
}

function inputActivity(payload: Record<string, unknown>): AgentActivityProjection {
  return {
    id: `activity:${String(payload.requestId)}`,
    turnId: 'turn:participant',
    kind: 'user_input_required',
    status: 'waiting',
    summary: '等待回答',
    payload,
    createdAtMs: 1,
    updatedAtMs: 1,
  };
}
