import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import './index';

describe('portable Agent controls', () => {
  let handle: ReturnType<typeof window.pawAgentUI.mount> | undefined;
  afterEach(() => { act(() => handle?.destroy()); document.body.replaceChildren(); });
  it('keeps Luna Max, uses readable errors, and checks uncertain work instead of issuing a retry', async () => {
    const selection = { provider: 'openai-codex', model: 'gpt-5.6-luna', thinkingLevel: 'max' };
    const controls = document.createElement('div'), recovery = document.createElement('div');
    document.body.append(controls, recovery);
    window.pawApp = { models: async () => ({ selected: selection, catalog: { providers: [{ id: selection.provider,
      models: [{ id: selection.model, name: 'Luna', thinkingLevels: ['low', 'high', 'max'] }] }] } }) };
    const retry = vi.fn(), check = vi.fn();
    await act(async () => { handle = window.pawAgentUI.mount({ controls, recovery, onRetry: retry, onCheck: check }); await handle.ready; });
    expect(handle?.selection()).toEqual(selection);
    expect(screen.getByRole('button', { name: /模型与推理：Luna.*最高/u })).toBeEnabled();
    act(() => handle?.failure({ state: 'failed', message: 'APP_API_BASE_URL missing' }));
    expect(screen.getByRole('alert')).toHaveTextContent('模型连接配置不完整');
    expect(screen.queryByText(/APP_API_BASE_URL/u)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重试本轮' })); expect(retry).toHaveBeenCalledTimes(1);
    act(() => handle?.failure({ state: 'unconfirmed', message: 'connection lost' }));
    expect(screen.queryByRole('button', { name: '重试本轮' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '核对原调用' })); expect(check).toHaveBeenCalledTimes(1);
    expect(retry).toHaveBeenCalledTimes(1);
    act(() => handle?.setBusy(true));
    await waitFor(() => expect(screen.getByRole('button', { name: '核对原调用' })).toBeDisabled());
  });
});
