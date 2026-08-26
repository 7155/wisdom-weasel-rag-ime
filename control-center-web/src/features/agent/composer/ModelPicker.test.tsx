import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ModelCatalog } from '../types';
import { ModelPicker } from './ModelPicker';

afterEach(cleanup);

function catalog(): ModelCatalog {
  return {
    schemaVersion: 'rag-ime.agent-model-catalog.v1',
    ok: true,
    thinkingLevel: 'high',
    selected: {
      provider: 'gpt',
      id: 'gpt-5.6-luna',
      modelId: 'gpt-5.6-luna',
      name: 'GPT-5.6 Luna',
    },
    providers: [
      {
        id: 'gpt',
        displayName: 'OpenAI Codex',
        models: [
          {
            provider: 'gpt',
            id: 'gpt-5.6-luna',
            name: 'GPT-5.6 Luna',
            api: 'responses',
            reasoning: true,
            thinkingLevels: ['off', 'medium', 'high', 'max'],
            supportsImages: true,
            contextWindow: 272_000,
            maxTokens: 64_000,
          },
        ],
      },
      {
        id: 'deepseek',
        displayName: 'DeepSeek',
        models: [
          {
            provider: 'deepseek',
            id: 'deepseek-v4-flash',
            name: 'DeepSeek V4 Flash',
            api: 'chat-completions',
            reasoning: true,
            thinkingLevels: ['off', 'low'],
            supportsImages: false,
            contextWindow: 128_000,
            maxTokens: 32_000,
          },
        ],
      },
    ],
  } as unknown as ModelCatalog;
}

function renderPicker(onChange = vi.fn()) {
  render(
    <ModelPicker
      catalog={catalog()}
      disabled={false}
      pending={false}
      requestOpen={0}
      onChange={onChange}
    />,
  );
  return onChange;
}

describe('compact model and reasoning controls', () => {
  it('keeps model search separate and preserves a legal level when switching models', async () => {
    const onChange = renderPicker();
    const user = userEvent.setup();
    const modelTrigger = screen.getByRole('button', {
      name: '模型：GPT-5.6 Luna · OpenAI Codex',
    });
    expect(screen.getByRole('button', { name: '推理强度：高' })).toBeInTheDocument();

    await user.click(modelTrigger);
    const picker = screen.getByRole('dialog', { name: '选择模型' });
    expect(within(picker).queryByRole('radiogroup')).not.toBeInTheDocument();
    const search = within(picker).getByRole('searchbox', { name: '搜索模型' });
    await waitFor(() => expect(search).toHaveFocus());
    await user.type(search, 'flash');
    expect(within(picker).queryByRole('option', { name: '选择模型 GPT-5.6 Luna' }))
      .not.toBeInTheDocument();
    const flash = within(picker).getByRole('option', { name: '选择模型 DeepSeek V4 Flash' });
    await user.keyboard('{ArrowDown}');
    expect(flash).toHaveFocus();
    await user.keyboard('{Enter}');

    expect(onChange).toHaveBeenCalledWith('deepseek', 'deepseek-v4-flash', 'off');
  });

  it('changes only the current model reasoning level and returns focus on Escape', async () => {
    const onChange = renderPicker();
    const user = userEvent.setup();
    const reasoningTrigger = screen.getByRole('button', { name: '推理强度：高' });
    await user.click(reasoningTrigger);
    const reasoningPicker = screen.getByRole('dialog', { name: '选择推理强度' });
    expect(within(reasoningPicker).queryByRole('option')).not.toBeInTheDocument();
    await waitFor(() => expect(within(reasoningPicker).getByRole('radio', { name: '高' }))
      .toHaveFocus());
    await user.keyboard('{ArrowRight}{Enter}');
    expect(onChange).toHaveBeenCalledWith('gpt', 'gpt-5.6-luna', 'max');

    const modelTrigger = screen.getByRole('button', {
      name: '模型：GPT-5.6 Luna · OpenAI Codex',
    });
    await user.click(modelTrigger);
    expect(screen.getByRole('dialog', { name: '选择模型' })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '选择模型' }))
      .not.toBeInTheDocument());
    expect(modelTrigger).toHaveFocus();
  });

  it('exposes both compact controls with complete names when visible labels collapse', () => {
    renderPicker();
    const controls = screen.getByRole('group', { name: '模型与推理设置' });
    expect(within(controls).getAllByRole('button')).toHaveLength(2);
    expect(within(controls).getByRole('button', { name: /模型：GPT-5\.6 Luna/ }))
      .toHaveClass('agent-composer__picker');
    expect(within(controls).getByRole('button', { name: '推理强度：高' }))
      .toHaveClass('agent-composer__thinking-picker');
  });

  it('opens the requested surface without routing a thinking command through the model list', async () => {
    const { rerender } = render(
      <ModelPicker
        catalog={catalog()}
        disabled={false}
        pending={false}
        requestOpen={0}
        thinkingRequestOpen={0}
        onChange={vi.fn()}
      />,
    );

    rerender(
      <ModelPicker
        catalog={catalog()}
        disabled={false}
        pending={false}
        requestOpen={0}
        thinkingRequestOpen={1}
        onChange={vi.fn()}
      />,
    );

    expect(await screen.findByRole('dialog', { name: '选择推理强度' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '选择模型' })).not.toBeInTheDocument();
  });
});
