import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { AgentActivityProjection } from '@/contracts/agent-reducer';
import { StubControlTransport } from '@/test/stub-control-transport';
import { GenericUserInputCard } from './AgentReviewDialogs';

afterEach(cleanup);

describe('GenericUserInputCard', () => {
  it('renders a recommended rich single choice and keeps custom input exclusive', async () => {
    const transport = inputTransport();
    const user = userEvent.setup();
    renderCard(transport, inputActivity({
      requestId: 'input:recommended',
      requestKind: 'grouped_questions',
      questions: [{
        id: 'delivery',
        header: '交付方式',
        question: '先以哪种形式推进？',
        options: [
          {
            label: '快速草案',
            description: '先给出方向，再逐步补齐。',
            preview: 'draft → review',
          },
          {
            label: '稳定方案',
            description: '稳定优先，适合直接协作。',
            preview: 'plan → verify → ship',
          },
        ],
        recommended: 1,
      }],
    }));

    expect(screen.getByRole('region', { name: '伙伴需要你一起确认几件事' })).toBeVisible();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    const group = screen.getByRole('group', { name: '1. 先以哪种形式推进？' });
    expect(within(group).getByText('交付方式')).toBeVisible();
    expect(within(group).getByText(/先以哪种形式推进？/u)).toBeVisible();
    expect(within(group).getByText('稳定优先，适合直接协作。')).toBeVisible();
    expect(within(group).getByText('plan → verify → ship')).toBeVisible();
    expect(within(group).getByText('推荐')).toBeVisible();

    const recommended = within(group).getByRole('radio', { name: '稳定方案' });
    expect(recommended).toHaveAccessibleDescription(/稳定优先.*plan → verify → ship.*推荐/u);
    const draft = within(group).getByRole('radio', { name: '快速草案' });
    const custom = within(group).getByRole('textbox', { name: '其他' });
    const submit = screen.getByRole('button', { name: '一起提交' });
    expect(submit).toBeDisabled();

    await user.click(recommended);
    expect(recommended).toBeChecked();
    expect(submit).toBeEnabled();

    await user.type(custom, '先做一个可交互样稿');
    expect(recommended).not.toBeChecked();
    expect(custom).toHaveValue('先做一个可交互样稿');
    expect(submit).toBeEnabled();

    await user.click(draft);
    expect(draft).toBeChecked();
    expect(custom).toHaveValue('');
  });

  it('combines multiple selected options with one automatic custom answer', async () => {
    const transport = inputTransport();
    const user = userEvent.setup();
    renderCard(transport, inputActivity({
      requestId: 'input:multi',
      requestKind: 'grouped_questions',
      questions: [{
        id: 'checks',
        header: '复核清单',
        question: '这次需要包含哪些检查？',
        multi: true,
        options: [
          { label: '可访问性', description: '检查键盘与读屏语义。' },
          { label: '响应式', description: '覆盖窄屏与宽屏布局。' },
          { label: '视觉一致性', description: '复用既有设计令牌。' },
        ],
        recommended: 0,
      }],
    }));

    const group = screen.getByRole('group', { name: /这次需要包含哪些检查？/u });
    const accessibility = within(group).getByRole('checkbox', { name: '可访问性' });
    const responsive = within(group).getByRole('checkbox', { name: '响应式' });
    const custom = within(group).getByRole('textbox', { name: '其他' });
    await user.click(accessibility);
    await user.click(responsive);
    await user.type(custom, '补充暗色主题');

    expect(accessibility).toBeChecked();
    expect(responsive).toBeChecked();
    expect(custom).toHaveValue('补充暗色主题');
    await user.click(screen.getByRole('button', { name: '一起提交' }));

    await waitFor(() => expect(transport.requests).toHaveLength(1));
    const body = transport.requests[0]?.body as { value: string };
    expect(JSON.parse(body.value)).toEqual({
      answers: {
        checks: {
          selected: ['可访问性', '响应式'],
          custom: '补充暗色主题',
        },
      },
    });
  });

  it('keeps submit disabled until every question has a non-empty valid answer', async () => {
    const transport = inputTransport();
    const user = userEvent.setup();
    renderCard(transport, inputActivity({
      requestId: 'input:required',
      requestKind: 'grouped_questions',
      questions: [
        {
          id: 'scope',
          question: '覆盖范围是什么？',
          options: [{ label: '当前页面' }, { label: '全部页面' }],
        },
        {
          id: 'notes',
          question: '说明方式是什么？',
          options: [{ label: '简洁' }, { label: '详细' }],
        },
      ],
    }));

    const submit = screen.getByRole('button', { name: '一起提交' });
    expect(submit).toBeDisabled();
    const scope = screen.getByRole('group', { name: /覆盖范围是什么？/u });
    await user.click(within(scope).getByRole('radio', { name: '全部页面' }));
    expect(submit).toBeDisabled();

    const notes = screen.getByRole('group', { name: /说明方式是什么？/u });
    const custom = within(notes).getByRole('textbox', { name: '其他' });
    await user.type(custom, '   ');
    expect(submit).toBeDisabled();
    await user.type(custom, '补充背景');
    expect(submit).toBeEnabled();
  });

  it('keeps grouped-question cancellation on the durable resolution path', async () => {
    const transport = inputTransport();
    renderCard(transport, inputActivity({
      requestId: 'input:cancel',
      requestKind: 'grouped_questions',
      questions: [{
        id: 'scope',
        question: '选择范围',
        options: [{ label: '当前页面' }, { label: '全部页面' }],
      }],
    }));
    await userEvent.click(screen.getByRole('button', { name: '取消这次提问' }));

    await waitFor(() => expect(transport.requests).toHaveLength(1));
    expect(transport.requests[0]?.body).toEqual({
      requestId: 'input:cancel',
      cancelled: true,
      resolutionSource: 'user_cancelled',
    });
    expect(screen.getByRole('region', { name: '伙伴需要你一起确认几件事' })).toBeVisible();
    expect(screen.getByRole('button', { name: '取消这次提问' })).toBeDisabled();
  });

  it('submits the exact canonical grouped answer request body', async () => {
    const transport = inputTransport();
    const user = userEvent.setup();
    renderCard(transport, inputActivity({
      requestId: 'input:exact',
      requestKind: 'grouped_questions',
      questions: [
        {
          id: 'scope',
          question: '这次先覆盖哪一部分？',
          options: [{ label: '核心流程' }, { label: '完整流程' }],
        },
        {
          id: 'evidence',
          question: '还需要什么交付证据？',
          options: [{ label: '运行记录' }, { label: '变更摘要' }],
        },
      ],
    }));

    const scope = screen.getByRole('group', { name: /这次先覆盖哪一部分？/u });
    await user.click(within(scope).getByRole('radio', { name: '完整流程' }));
    const evidence = screen.getByRole('group', { name: /还需要什么交付证据？/u });
    await user.type(within(evidence).getByRole('textbox', { name: '其他' }), '附带截图');
    await user.click(screen.getByRole('button', { name: '一起提交' }));

    await waitFor(() => expect(transport.requests).toHaveLength(1));
    expect(transport.requests[0]?.body).toEqual({
      requestId: 'input:exact',
      value: JSON.stringify({
        answers: {
          scope: { selected: ['完整流程'] },
          evidence: { selected: [], custom: '附带截图' },
        },
      }),
      resolutionSource: 'direct_user',
    });
  });

  it('preserves the existing single-select response value', async () => {
    const transport = inputTransport();
    renderCard(transport, inputActivity({
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

function renderCard(transport: StubControlTransport, activity: AgentActivityProjection): void {
  render(
    <ControlTransportProvider transport={transport}>
      <GenericUserInputCard activity={activity} sessionId="session:participant" onError={() => undefined} />
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
