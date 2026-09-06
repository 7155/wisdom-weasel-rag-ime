import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it } from 'vitest';
import { MockControlTransport } from '@/test/mock-transport';
import type { ControlRequest } from '@/platform/transport';
import { PromptSettingsPanel } from './PromptSettingsPanel';

afterEach(cleanup);

function setup({ conflict = false, policy = true } = {}) {
  let revision = 3;
  let pendingConflict = conflict;
  let prompts = { systemInstructions: '', compactionInstructions: '保留文档引用与未落盘进度。' };
  const writes: ControlRequest[] = [];
  const snapshot = () => ({
    ok: true, configuration: { revision, configuration: { prompts, skillRouting: { ordinary: ['alignment-and-decision'] } } },
    ...(policy ? { promptPolicy: { schemaVersion: 'rag-ime.agent-prompt-policy.v1', appliesTo: 'new_sessions', maxCharacters: 8000,
      defaults: { systemInstructions: '', compactionInstructions: '保留文档引用与未落盘进度。' }, builtInSystemPrompt: '内置规则：按证据验收。', compactionOwner: 'pi' } } : {}),
  });
  const transport = new MockControlTransport({ routes: {
    'agent.configuration.get': snapshot,
    'agent.configuration.update': (request: ControlRequest) => {
      writes.push(request);
      if (pendingConflict) {
        pendingConflict = false;
        revision += 1;
        prompts = { ...prompts, systemInstructions: '另处已保存的规则' };
        throw new Error('agent configuration revision changed');
      }
      const body = request.body as { expectedRevision: number; changes: Record<string, string> };
      expect(body.expectedRevision).toBe(revision);
      for (const [key, value] of Object.entries(body.changes)) {
        if (key === 'prompts.systemInstructions') prompts = { ...prompts, systemInstructions: value };
        else if (key === 'prompts.compactionInstructions') prompts = { ...prompts, compactionInstructions: value };
        else throw new Error('Unrelated configuration changed');
      }
      revision += 1;
      return snapshot();
    },
  } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><PromptSettingsPanel routeIds={['agent.configuration.get', 'agent.configuration.update']} transport={transport} /></QueryClientProvider>);
  return { writes };
}

it('shows server-owned defaults and saves only changed prompt fields', async () => {
  const user = userEvent.setup();
  const { writes } = setup();
  await user.type(await screen.findByLabelText('系统补充指令'), '请先给结论。');
  await user.click(screen.getByRole('button', { name: '保存提示词' }));
  expect(await screen.findByText('提示词已保存')).toBeInTheDocument();
  expect(writes).toHaveLength(1);
  expect(writes[0]?.body).toMatchObject({ expectedRevision: 3, changes: { 'prompts.systemInstructions': '请先给结论。' } });
  expect(screen.getByLabelText('压缩补充指令')).toHaveValue('保留文档引用与未落盘进度。');
  await user.click(screen.getByText('查看内置系统规则'));
  expect(screen.getByText('内置规则：按证据验收。')).toBeInTheDocument();
});

it('preserves the draft when a concurrent save fails', async () => {
  const user = userEvent.setup();
  const { writes } = setup({ conflict: true });
  await user.type(await screen.findByLabelText('系统补充指令'), '保留这个草稿');
  await user.click(screen.getByRole('button', { name: '保存提示词' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('草稿已保留');
  expect(screen.getByLabelText('系统补充指令')).toHaveValue('保留这个草稿');
  expect(writes).toHaveLength(1);
  await user.click(screen.getByRole('button', { name: '重新读取当前版本' }));
  await user.click(await screen.findByText('比较当前已保存内容'));
  expect(screen.getByText('另处已保存的规则')).toBeVisible();
  expect(screen.getByLabelText('系统补充指令')).toHaveValue('保留这个草稿');
  await user.click(screen.getByRole('button', { name: '按最新版本保存草稿' }));
  expect(await screen.findByText('提示词已保存')).toBeInTheDocument();
  expect(writes[1]?.body).toMatchObject({ expectedRevision: 4, changes: { 'prompts.systemInstructions': '保留这个草稿' } });
});

it('restores the draft from server defaults without automatically saving', async () => {
  const user = userEvent.setup();
  const { writes } = setup();
  const input = await screen.findByLabelText('压缩补充指令');
  await user.clear(input);
  await user.type(input, '自定义规则');
  await user.click(screen.getByRole('button', { name: '恢复默认草稿' }));
  expect(input).toHaveValue('保留文档引用与未落盘进度。');
  expect(writes).toHaveLength(0);
});

it('does not invent editable settings when an older backend has no prompt policy', async () => {
  setup({ policy: false });
  await waitFor(() => expect(screen.getByText('当前版本尚未提供提示词设置')).toBeInTheDocument());
  expect(screen.queryByRole('button', { name: '保存提示词' })).not.toBeInTheDocument();
});
