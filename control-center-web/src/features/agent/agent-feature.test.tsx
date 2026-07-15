import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { StubControlTransport } from '@/test/stub-control-transport';
import type { ControlTransport } from '@/platform/transport';
import { AgentFeature } from './index';
import { previewAgentEvents, previewAgentSnapshot, previewModelCatalog, previewPersonas, previewSessions } from './preview-data';
import { SessionRail } from './sessions/SessionRail';
import { useAgentLiveStore } from './state/live-store';
import { projectStatusPanel } from './status/AgentStatusPanel';
import { AgentTurn } from './timeline/AgentTimeline';
import { sessionItems, type ModelCatalog, type ThinkingLevel } from './types';

vi.mock('react-virtuoso', () => ({
  Virtuoso: ({ data, itemContent }: { data: string[]; itemContent: (index: number, item: string) => ReactNode }) => (
    <div>{data.map((item, index) => <div key={item}>{itemContent(index, item)}</div>)}</div>
  ),
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  for (const session of previewSessions) useAgentLiveStore.getState().clear(session.id);
  useAgentLiveStore.getState().clear('session-history');
});

describe('Agent experience', () => {
  it('makes the full session row clickable', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<TooltipProvider><SessionRail sessions={previewSessions} selectedId="session-preview" loading={false} onSelect={onSelect} onCreate={() => {}} /></TooltipProvider>);
    await user.click(screen.getByRole('button', { name: /记忆整理/ }));
    expect(onSelect).toHaveBeenCalledWith('session-memory');
  });

  it('creates a real Pi-backed conversation branch and restores the selected message as draft', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('button', { name: '创建对话分支' }));
    const dialog = await screen.findByRole('dialog', { name: '从历史消息创建分支' });
    expect(within(dialog).getByText(/原对话保持不变/)).toBeInTheDocument();
    await user.click(await within(dialog).findByRole('radio', { name: /帮我整理权限模式/ }));
    await user.click(within(dialog).getByRole('button', { name: '创建分支' }));

    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.forks.create',
        params: { sessionId: 'session-preview' },
        body: expect.objectContaining({ entryId: 'entry-permissions' }),
      }),
    })));
    expect(await screen.findByRole('textbox', { name: '消息' })).toHaveValue('帮我整理权限模式');
    expect(screen.getByRole('button', { name: /控制中心迁移 · 分支/ })).toHaveAttribute('aria-current', 'true');
  });

  it('keeps delegated runtime sessions out of the user conversation rail', () => {
    const parent = { ...previewSessions[0]!, id: 'session-parent', title: '用户主对话' };
    const child = {
      ...parent,
      id: 'session-child-runtime',
      title: '研究员临时会话',
      sessionKind: 'subagent_runtime',
    };

    expect(sessionItems({ ok: true, items: [parent, child] })).toEqual([parent]);
  });

  it('renders one persona avatar and one activity container per assistant turn without raw payloads', async () => {
    const sessionId = 'session-preview';
    const snapshot = previewAgentSnapshot(sessionId);
    useAgentLiveStore.getState().hydrateSnapshot(sessionId, snapshot);
    const events = previewAgentEvents(sessionId);
    events[1] = { ...events[1]!, payload: { ...events[1]!.payload, rawSecret: '{"token":"do-not-render"}' } };
    useAgentLiveStore.getState().applyEvents(sessionId, events);
    const turnId = `${sessionId}:turn-architecture`;
    render(<TooltipProvider><AgentTurn sessionId={sessionId} turnId={turnId} persona={previewPersonas[0]} onApprovalDecision={() => {}} /></TooltipProvider>);
    expect(screen.getAllByAltText('智鼬·此刻头像')).toHaveLength(1);
    expect(document.querySelectorAll('.agent-activity')).toHaveLength(1);
    expect(document.querySelector('.agent-user-message')).toBeInTheDocument();
    expect(screen.queryByText(/do-not-render/)).not.toBeInTheDocument();
    expect(document.querySelector('.agent-assistant-message')).toHaveTextContent('三条 Lane 已经收束到同一个');
  });

  it('keeps live agent, knowledge-source, and ephemeral subagent status visible without adding child Sessions', async () => {
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: query === '(min-width: 1180px)',
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    const parentSession = { ...previewSessions[0]!, id: 'session-preview', title: '研究主对话' };
    const transport = featureTransport(
      undefined,
      undefined,
      { ok: true, items: [parentSession] },
      undefined,
      subagentListFixture(),
    );
    const user = userEvent.setup();
    renderAgent(transport);

    expect(await screen.findByText('1 个连续对话')).toBeInTheDocument();
    expect(document.querySelectorAll('.agent-session-row')).toHaveLength(1);
    expect(screen.queryByText('研究员临时会话')).not.toBeInTheDocument();

    const statusPanel = await screen.findByLabelText('当前对话状态');
    await waitFor(() => expect(within(statusPanel).getByText('研究员')).toBeInTheDocument());
    expect(within(statusPanel).getByText('规划员')).toBeInTheDocument();
    expect(within(statusPanel).getByText('审阅者')).toBeInTheDocument();
    expect(within(statusPanel).getByText('执行者')).toBeInTheDocument();
    expect(statusPanel.querySelector('.agent-status-subagent[data-state="running"] .agent-status-subagent__state svg')).toBeInTheDocument();
    expect(statusPanel.querySelector('.agent-status-subagent[data-state="queued"] .agent-status-subagent__state svg')).toBeInTheDocument();
    expect(statusPanel.querySelector('.agent-status-subagent[data-state="completed"]')).toBeInTheDocument();
    expect(statusPanel.querySelector('.agent-status-subagent[data-state="failed"]')).toBeInTheDocument();
    expect(statusPanel.querySelector('.agent-status-subagent[data-state="running"] time')).toHaveTextContent(/^\d+(?:分\d{2})?秒$/);
    expect(within(statusPanel).getAllByRole('button', { name: '查看进度' })).toHaveLength(2);
    expect(within(statusPanel).getAllByRole('button', { name: '查看结果' })).toHaveLength(2);

    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.lastSequence).toBeGreaterThan(0));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    act(() => {
      useAgentLiveStore.getState().applyEvents('session-preview', [{
        schemaVersion: 'rag-ime.agent-event.v1',
        eventId: 'knowledge-live-started',
        sessionId: 'session-preview',
        turnId: 'turn-knowledge-live',
        sequence: projection.lastSequence + 1,
        createdAtMs: Date.now(),
        streamKind: 'agent',
        eventType: 'tool_started',
        payload: {
          toolCallId: 'knowledge-live',
          toolId: 'ime_knowledge',
          operation: 'find',
          summary: '正在检索可引用的记忆证据',
          partialResult: {
            items: [
              { fileName: 'memory-design.md', citation: { startLine: 42, endLine: 48 } },
              { fileName: 'agent-runtime.pdf', citation: { page: 7 } },
            ],
          },
        },
        resumeToken: 'knowledge-live-started',
      }]);
    });

    const knowledgeStep = await within(statusPanel).findByText('知识库');
    expect(statusPanel.querySelector('.agent-status-turn[data-state="running"] > svg')).toBeInTheDocument();
    expect(statusPanel.querySelector('.agent-status-tool[data-state="running"] .agent-status-tool__icon svg')).toBeInTheDocument();
    await user.click(knowledgeStep);
    expect(within(statusPanel).getByText('来源 2 · 进行中')).toBeInTheDocument();
    expect(within(statusPanel).getByText('信息来源')).toBeInTheDocument();
    expect(within(statusPanel).getByText('memory-design.md · 42-48 行')).toBeInTheDocument();
    expect(within(statusPanel).getByText('agent-runtime.pdf · 第 7 页')).toBeInTheDocument();
  });

  it('keeps every tool step from the current turn available in the status panel', () => {
    const sessionId = 'session-tool-audit';
    useAgentLiveStore.getState().appendOptimistic(sessionId, {
      clientMessageId: 'tool-audit',
      text: '检查所有步骤',
      nowMs: 1,
    });
    const projection = useAgentLiveStore.getState().projections[sessionId];
    const turnId = projection.turnOrder[0]!;
    useAgentLiveStore.getState().applyEvents(sessionId, Array.from({ length: 12 }, (_, index) => ({
      schemaVersion: 'rag-ime.agent-event.v1' as const,
      eventId: `tool-step-${index}`,
      sessionId,
      turnId,
      sequence: index + 1,
      createdAtMs: index + 2,
      streamKind: 'agent' as const,
      eventType: 'tool_started' as const,
      payload: {
        toolCallId: `tool-call-${index}`,
        toolId: 'ime_knowledge',
        operation: 'search',
        summary: `检索步骤 ${index + 1}`,
      },
      resumeToken: `tool-step-${index}`,
    })));

    expect(projectStatusPanel(useAgentLiveStore.getState().projections[sessionId]).tools).toHaveLength(12);
    useAgentLiveStore.getState().clear(sessionId);
  });

  it('projects the session-local agent plan into the right status panel', () => {
    const sessionId = 'session-plan-panel';
    useAgentLiveStore.getState().appendOptimistic(sessionId, {
      clientMessageId: 'plan-panel',
      text: '按计划执行',
      nowMs: 1,
    });
    const projection = useAgentLiveStore.getState().projections[sessionId];
    const turnId = projection.turnOrder[0]!;
    useAgentLiveStore.getState().applyEvents(sessionId, [{
      schemaVersion: 'rag-ime.agent-event.v1',
      eventId: 'agent-plan-start',
      sessionId,
      turnId,
      sequence: 1,
      createdAtMs: 2,
      streamKind: 'agent',
      eventType: 'tool_started',
      payload: {
        toolCallId: 'agent-plan-call',
        toolId: 'agent_plan',
        operation: 'list',
        summary: '正在读取当前计划',
      },
      resumeToken: 'agent-plan-start',
    }, {
      schemaVersion: 'rag-ime.agent-event.v1',
      eventId: 'agent-plan-result',
      sessionId,
      turnId,
      sequence: 2,
      createdAtMs: 3,
      streamKind: 'agent',
      eventType: 'tool_finished',
      payload: {
        toolCallId: 'agent-plan-call',
        toolId: 'agent_plan',
        operation: 'list',
        summary: '当前计划已读取',
        result: {
          details: {
            result: {
              items: [
                { itemId: 'step-1', title: '核对权限边界', status: 'completed' },
                { itemId: 'step-2', title: '验证原生交互', status: 'in_progress' },
              ],
            },
          },
        },
      },
      resumeToken: 'agent-plan-result',
    }]);

    expect(projectStatusPanel(useAgentLiveStore.getState().projections[sessionId]).tasks).toEqual([
      { id: 'agent-plan:step-1', label: '核对权限边界', status: 'completed' },
      { id: 'agent-plan:step-2', label: '验证原生交互', status: 'running' },
    ]);
    useAgentLiveStore.getState().clear(sessionId);
  });

  it('keeps hydrated legacy history replies beside their user turns', () => {
    const sessionId = 'session-history';
    useAgentLiveStore.getState().hydrate(sessionId, {
      lastSequence: 4,
      resumeToken: `${sessionId}:4`,
      items: [
        historyMessage(sessionId, 'assistant-orphan', 'assistant', '上一段回复'),
        historyMessage(sessionId, 'user-one', 'user', '第一个问题'),
        historyMessage(sessionId, 'assistant-one-a', 'assistant', '第一段回复'),
        historyMessage(sessionId, 'assistant-one-b', 'assistant', '第一段补充'),
        historyMessage(sessionId, 'user-two', 'user', '第二个问题'),
        historyMessage(sessionId, 'user-three', 'user', '第三个问题'),
        historyMessage(sessionId, 'assistant-three', 'assistant', '第三段回复'),
      ],
    });

    const projection = useAgentLiveStore.getState().projections[sessionId];
    expect(projection.turnOrder).toEqual([
      'history:assistant-orphan',
      'history:user-one',
      'history:user-two',
      'history:user-three',
    ]);
    expect(projection.turnsById['history:user-one'].messageIds).toEqual([
      'user-one',
      'assistant-one-a',
      'assistant-one-b',
    ]);
    expect(projection.turnsById['history:user-one'].status).toBe('completed');
    expect(projection.turnsById['history:user-two'].messageIds).toEqual(['user-two']);

    render(
      <TooltipProvider>
        <AgentTurn
          sessionId={sessionId}
          turnId="history:user-three"
          persona={previewPersonas[0]}
          onApprovalDecision={() => {}}
        />
      </TooltipProvider>,
    );
    expect(screen.getByText('第三个问题')).toBeInTheDocument();
    expect(screen.getByText('第三段回复')).toBeInTheDocument();
  });

  it('sends through the allowlisted prompt path', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await user.type(composer, '检查 reducer 边界');
    await user.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(true));
    const prompt = transport.requests.find((call) => call.request.pathId === 'agent.session.prompt');
    expect(prompt?.request.params).toEqual({ sessionId: 'session-preview' });
    expect(prompt?.request.body).toMatchObject({ message: '检查 reducer 边界' });
  });

  it('renders a bordered assistant placeholder immediately while the prompt request is pending', async () => {
    const pendingPrompt = new Promise(() => {});
    const transport = featureTransport(
      previewModelCatalog('session-preview'),
      { ok: true, items: toolCatalog() },
      { ok: true, items: previewSessions },
      () => pendingPrompt,
    );
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });

    fireEvent.change(composer, { target: { value: '立刻显示处理状态' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    const queuedTurn = Object.values(useAgentLiveStore.getState().projections['session-preview'].turnsById)
      .find((turn) => turn.id.startsWith('local-turn:'));
    expect(queuedTurn?.status).toBe('queued');
    const pending = await screen.findByRole('status');
    expect(pending).toHaveClass('agent-assistant-pending');
    expect(pending).toHaveTextContent('思考中');
    expect(pending).toHaveTextContent('0秒');
    expect(pending).toHaveTextContent('消息已收到');
    const assistantTurn = pending.closest('.agent-assistant-turn');
    expect(assistantTurn).not.toBeNull();
    expect(within(assistantTurn as HTMLElement).getByAltText('智鼬·此刻头像')).toBeInTheDocument();
    expect(within(assistantTurn as HTMLElement).getByText('智鼬·此刻')).toBeInTheDocument();
    expect(within(assistantTurn as HTMLElement).getByText('正在处理')).toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(true);
  });

  it('renders a rejected Pi prompt once with a public recovery message', async () => {
    const transport = featureTransport(
      previewModelCatalog('session-preview'),
      { ok: true, items: toolCatalog() },
      { ok: true, items: previewSessions },
      () => { throw new Error('404 Model "gpt-5.6-luna" is not supported by any configured account in this group'); },
    );
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });

    await user.type(composer, '你是谁');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(true));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    const failedTurn = Object.values(projection.turnsById).find((turn) => turn.failure);
    expect(failedTurn?.failure).toBe('当前模型不可用，请切换模型后重试。');
    expect(document.querySelector('.agent-conversation__header [role="alert"]')).not.toBeInTheDocument();
    expect(screen.queryByText(/not supported by any configured account/i)).not.toBeInTheDocument();
  });

  it('retries a failed turn through the real prompt route with the original input', async () => {
    let attempt = 0;
    const transport = featureTransport(
      previewModelCatalog('session-preview'),
      { ok: true, items: toolCatalog() },
      { ok: true, items: previewSessions },
      () => {
        attempt += 1;
        if (attempt === 1) throw new Error('model unavailable');
        return new Promise(() => {});
      },
    );
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await user.type(composer, '重试时保留这句话');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await user.click(await screen.findByRole('button', { name: '重试本轮' }));

    await waitFor(() => expect(transport.requests.filter((call) => call.request.pathId === 'agent.session.prompt')).toHaveLength(2));
    const prompts = transport.requests.filter((call) => call.request.pathId === 'agent.session.prompt');
    expect(prompts[1]?.request.params).toEqual({ sessionId: 'session-preview' });
    expect(prompts[1]?.request.body).toMatchObject({ message: '重试时保留这句话', attachments: [] });
  });

  it('opens the real model picker from a failed turn', async () => {
    const transport = featureTransport(
      previewModelCatalog('session-preview'),
      { ok: true, items: toolCatalog() },
      { ok: true, items: previewSessions },
      () => { throw new Error('model unavailable'); },
    );
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await user.type(composer, '切换模型后继续');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await user.click(await screen.findByRole('button', { name: '切换模型' }));

    expect(await screen.findByText('模型与推理强度')).toBeInTheDocument();
    expect(screen.getByText('GPT-5.4', { selector: 'summary' })).toBeInTheDocument();
  });

  it('unlocks send and retry when projection status is stale working but the latest turn failed', async () => {
    const failedTurnId = 'turn-provider-failed';
    const transport = productionTransport({
      'agent.session.snapshot': {
        lastSequence: 7,
        resumeToken: 'provider-failed:7',
        status: 'working',
        items: [
          {
            ...historyMessage('session-preview', 'provider-user', 'user', '继续处理这个请求'),
            turnId: failedTurnId,
          },
          {
            ...historyMessage('session-preview', 'provider-assistant', 'assistant', ''),
            turnId: failedTurnId,
            status: 'failed',
            blocks: [{
              id: 'provider-assistant:error',
              type: 'error',
              status: 'failed',
              presentationKind: 'error',
              data: { message: '400 Error from provider (Console Go): Upstream request failed' },
            }],
          },
        ],
      },
      'agent.session.prompt': { ok: true },
    });
    const user = userEvent.setup();
    renderAgent(transport);

    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.status).toBe('working'));
    expect(useAgentLiveStore.getState().projections['session-preview']?.turnsById[failedTurnId]?.status).toBe('failed');
    expect(await screen.findByRole('button', { name: '发送' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '停止本轮' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试本轮' })).toBeEnabled();
    expect(screen.getByText('模型服务请求失败，请重试或切换模型。')).toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: '消息' }), '新的输入');
    expect(screen.getByRole('button', { name: '发送' })).toBeEnabled();
  });

  it('submits approval decisions through the real approval route', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.lastSequence).toBeGreaterThan(0));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    const turnId = projection.turnOrder.at(-1) ?? 'turn-approval';
    act(() => {
      useAgentLiveStore.getState().applyEvents('session-preview', [{
        schemaVersion: 'rag-ime.agent-event.v1',
        eventId: 'approval-pending-ui',
        sessionId: 'session-preview',
        turnId,
        sequence: projection.lastSequence + 1,
        createdAtMs: Date.now(),
        streamKind: 'agent',
        eventType: 'approval_required',
        payload: {
          approvalId: 'approval-live-1',
          payloadSha256: 'approval-live-hash',
          summary: '应用这次输入法配置变更',
        },
        resumeToken: 'approval-pending-ui',
      }]);
    });

    await user.click(await screen.findByRole('button', { name: '批准并执行' }));

    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.approval.decide',
        params: { approvalId: 'approval-live-1' },
        body: { decision: 'approve', payloadSha256: 'approval-live-hash' },
      }),
    })));
  });

  it('opens memory review immediately and resumes Pi when the user defers it', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.lastSequence).toBeGreaterThan(0));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    const turnId = projection.turnOrder.at(-1) ?? 'turn-review';
    act(() => {
      useAgentLiveStore.getState().applyEvents('session-preview', [{
        schemaVersion: 'rag-ime.agent-event.v1',
        eventId: 'memory-review-pending-ui',
        sessionId: 'session-preview',
        turnId,
        sequence: projection.lastSequence + 1,
        createdAtMs: Date.now(),
        streamKind: 'agent',
        eventType: 'user_input_required',
        payload: {
          requestId: 'ui-review-1',
          requestKind: 'memory_review',
          runId: 'memory-run-1',
          title: '审阅记忆草案',
        },
        resumeToken: 'memory-review-pending-ui',
      }]);
    });

    expect(await screen.findByRole('dialog')).toHaveTextContent('记忆整理草案');
    expect(await screen.findByText('输入法记忆增量整理')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '稍后审阅' }));

    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.review.resolve',
        params: { sessionId: 'session-preview' },
        body: { runId: 'memory-run-1', decision: 'deferred' },
      }),
    })));
  });

  it('uses the Pi RPC command catalog and supports keyboard and pointer selection', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.commands')).toBe(true));

    await user.click(screen.getByRole('button', { name: '打开命令面板' }));
    expect(screen.getByRole('option', { name: /\/new/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/name/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/model/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/thinking/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/permissions/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/tools/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/status/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/help/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/review.*Pi 扩展/ })).toBeInTheDocument();

    await user.type(composer, '/re');
    expect(screen.getByRole('option', { name: /\/review/ })).toBeInTheDocument();
    expect(screen.queryByText('/memory')).not.toBeInTheDocument();
    await user.keyboard('{Enter}');
    expect(composer).toHaveValue('/review ');

    await user.clear(composer);
    await user.type(composer, '/');
    await user.keyboard('{ArrowDown}{Enter}');
    expect(composer).toHaveValue('/name ');

    await user.clear(composer);
    await user.type(composer, '/skill');
    await user.click(screen.getByRole('option', { name: /\/skill:browser/ }));
    expect(composer).toHaveValue('/skill:browser ');

    await user.clear(composer);
    await user.type(composer, '/');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox', { name: '命令面板' })).not.toBeInTheDocument();

    await user.clear(composer);
    await user.type(composer, '/settings');
    await user.click(screen.getByRole('button', { name: '发送' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('未发送给模型');
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(false);
  });

  it('routes product commands to existing UI and session APIs without prompting the model', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.commands')).toBe(true));

    await user.click(screen.getByRole('button', { name: '打开命令面板' }));
    await user.click(screen.getByRole('option', { name: /\/model/ }));
    expect(await screen.findByText('模型与推理强度')).toBeInTheDocument();
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: '打开命令面板' }));
    await user.click(screen.getByRole('option', { name: /\/permissions/ }));
    expect(await screen.findByText('对话权限')).toBeInTheDocument();
    const permissionPicker = document.querySelector('.agent-picker-popover');
    expect(permissionPicker).not.toBeNull();
    expect(within(permissionPicker as HTMLElement).getByRole('button', { name: /受控助手/ })).toBeInTheDocument();
    expect(within(permissionPicker as HTMLElement).getByRole('button', { name: /只读观察/ })).toBeInTheDocument();
    expect(within(permissionPicker as HTMLElement).getByRole('button', { name: /运行协调/ })).toBeInTheDocument();
    await user.click(within(permissionPicker as HTMLElement).getByRole('button', { name: /只读观察/ }));
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.mode.update',
        params: { sessionId: 'session-preview' },
        body: {
          mode: 'assistant',
          workspaceRoots: ['/Volumes/undo 4t/git/learnA'],
          toolProfileVersion: 'subagent-readonly-v1',
          toolAllowlistMode: 'profile',
        },
      }),
    })));
    expect(await screen.findByRole('button', { name: '对话权限：只读观察' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '打开命令面板' }));
    await user.click(screen.getByRole('option', { name: /\/tools/ }));
    const toolPicker = document.querySelector('.agent-tool-picker');
    expect(toolPicker).not.toBeNull();
    expect(within(toolPicker as HTMLElement).getByText('受控工具')).toBeInTheDocument();
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: '打开命令面板' }));
    await user.click(screen.getByRole('option', { name: /\/name/ }));
    expect(composer).toHaveValue('/name ');
    await user.type(composer, '  新的   对话名称  ');
    await user.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.rename',
        params: { sessionId: 'session-preview' },
        body: { title: '新的 对话名称' },
      }),
    })));
    expect((await screen.findAllByText('新的 对话名称')).length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: '打开命令面板' }));
    await user.click(screen.getByRole('option', { name: /\/help/ }));
    expect(screen.getByText('命令帮助')).toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(false);

    await user.click(screen.getByRole('option', { name: /\/status/ }));
    expect(screen.getByLabelText('当前对话状态')).toHaveAttribute('data-open', 'true');
  });

  it('sends an advertised Pi RPC command through the prompt route', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.commands')).toBe(true));

    await user.type(composer, '/rev');
    await user.keyboard('{Enter}');
    await user.type(composer, '本轮改动');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.prompt',
        body: expect.objectContaining({ message: '/review 本轮改动' }),
      }),
    })));
  });

  it('disables commands from live busy and permission state with visible reasons', async () => {
    const assistantSession = { ...previewSessions[0]!, mode: 'assistant' as const, workspaceRoots: [] };
    const coordinatorOnlyTools = toolCatalog().filter((tool) => tool.id.startsWith('workspace_'));
    const transport = featureTransport(
      undefined,
      { ok: true, items: coordinatorOnlyTools },
      { ok: true, items: [assistantSession] },
    );
    const user = userEvent.setup();
    renderAgent(transport);
    await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.commands')).toBe(true));

    await user.click(screen.getByRole('button', { name: '打开命令面板' }));
    const toolsCommand = screen.getByRole('option', { name: /\/tools/ });
    expect(toolsCommand).toBeDisabled();
    expect(toolsCommand).toHaveAttribute('title', '受控助手没有可用工具');
    await user.click(screen.getByRole('button', { name: '关闭命令面板' }));

    act(() => {
      useAgentLiveStore.getState().appendOptimistic('session-preview', {
        clientMessageId: 'busy-command-state',
        text: '保持处理中',
        attachments: [],
        nowMs: Date.now(),
      });
    });
    await user.click(screen.getByRole('button', { name: '打开命令面板' }));
    const newCommand = screen.getByRole('option', { name: /\/new/ });
    expect(newCommand).toBeDisabled();
    expect(newCommand).toHaveAttribute('title', '当前处理中，仅可查看状态或停止');
    expect(screen.getByRole('option', { name: /\/status/ })).toBeEnabled();
    const stopCommand = screen.getByRole('option', { name: /\/stop/ });
    expect(stopCommand).toBeEnabled();
    await user.click(stopCommand);
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.abort')).toBe(true));
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(false);
  });

  it('accepts a planning handoff as an editable composer draft', async () => {
    const transport = featureTransport();
    renderAgent(transport, `/agent?draft=${encodeURIComponent('请整理今天的真实规划')}`);

    expect(await screen.findByRole('textbox', { name: '消息' })).toHaveValue('请整理今天的真实规划');
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(false);
  });

  it('pastes supported clipboard images into the managed attachment chain', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ });
    const image = new File([new Uint8Array([137, 80, 78, 71])], 'clipboard.png', { type: 'image/png' });

    fireEvent.paste(composer, {
      clipboardData: {
        files: [],
        items: [{ kind: 'file', getAsFile: () => image }],
      },
    });

    await waitFor(() => expect(transport.imagePasteCalls).toHaveLength(1));
    expect(transport.imagePasteCalls[0]).toMatchObject({ sessionId: 'session-preview' });
    expect(await screen.findByText('screen.png')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(true));
    const prompt = transport.requests.find((call) => call.request.pathId === 'agent.session.prompt');
    expect(prompt?.request.body).toMatchObject({ attachments: ['media_fixture_attachment_01'] });
  });

  it('imports a selected image through the native managed attachment picker', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);

    const attachmentButton = await screen.findByRole('button', { name: '添加图片' });
    expect(attachmentButton).toBeVisible();
    expect(attachmentButton).toBeEnabled();
    await user.click(attachmentButton);

    expect(transport.filePickCalls).toEqual([{
      accepts: ['image/png', 'image/jpeg', 'image/gif', 'image/webp'],
      multiple: true,
      purpose: 'attachment',
      sessionId: 'session-preview',
      maxFiles: 8,
    }]);
    expect(await screen.findByText('screen.png')).toBeInTheDocument();
  });

  it('leaves ordinary text paste alone and reports unsupported or oversized image files', async () => {
    const transport = featureTransport();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ });
    expect(fireEvent.paste(composer, { clipboardData: { files: [], getData: () => '普通文本' } })).toBe(true);
    expect(transport.imagePasteCalls).toHaveLength(0);

    const unsupported = new File(['bad'], 'diagram.svg', { type: 'image/svg+xml' });
    expect(fireEvent.paste(composer, { clipboardData: { files: [unsupported] } })).toBe(false);
    expect(await screen.findByRole('alert')).toHaveTextContent('仅支持 PNG、JPEG、GIF 和 WebP');
    expect(transport.imagePasteCalls).toHaveLength(0);

    const oversized = new File(['x'], 'huge.webp', { type: 'image/webp' });
    Object.defineProperty(oversized, 'size', { value: 20 * 1024 * 1024 + 1 });
    fireEvent.paste(composer, { clipboardData: { files: [oversized] } });
    expect(await screen.findByRole('alert')).toHaveTextContent('必须小于 20 MiB');
    expect(transport.imagePasteCalls).toHaveLength(0);
  });

  it('asks the native host to read the system pasteboard when WebKit hides the image File', async () => {
    const transport = featureTransport();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ });
    expect(screen.getByRole('button', { name: '添加图片' })).toBeEnabled();

    expect(fireEvent.paste(composer, {
      clipboardData: {
        files: [],
        items: [{ kind: 'file', type: 'image/png', getAsFile: () => null }],
      },
    })).toBe(false);
    await waitFor(() => expect(transport.imagePasteCalls).toHaveLength(1));
    expect(transport.imagePasteCalls[0]).toEqual({ sessionId: 'session-preview', maxFiles: 8 });
  });

  it('falls back to the native pasteboard when WebKit exposes neither File nor item metadata', async () => {
    const transport = featureTransport();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ });

    expect(fireEvent.paste(composer, {
      clipboardData: { files: [], items: [], getData: () => '' },
    })).toBe(false);

    await waitFor(() => expect(transport.imagePasteCalls).toEqual([
      { sessionId: 'session-preview', maxFiles: 8 },
    ]));
  });

  it('disables image selection and explains paste rejection for a Pi text-only model', async () => {
    const catalog = previewModelCatalog('session-preview');
    catalog.selected = { provider: 'deepseek', id: 'deepseek-v4' };
    const transport = featureTransport(catalog);
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });

    await screen.findByRole('button', { name: /模型：DeepSeek V4/ });
    expect(screen.getByRole('button', { name: '当前模型不支持图片' })).toBeDisabled();

    const image = new File(['png'], 'clipboard.png', { type: 'image/png' });
    expect(fireEvent.paste(composer, { clipboardData: { files: [image] } })).toBe(false);
    expect(await screen.findByRole('alert')).toHaveTextContent('当前模型不支持图片');
    expect(transport.imagePasteCalls).toHaveLength(0);
  });

  it('loads the complete tool catalog and writes an explicit tool intent without faking execution', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const trigger = await screen.findByRole('button', { name: '当前权限可用工具：13 个' });

    await user.click(trigger);
    expect(screen.getByRole('button', { name: /控制中心概览/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /受控命令/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /控制中心概览/ }));

    expect(screen.getByRole('textbox', { name: '消息' })).toHaveValue('请使用“控制中心概览”：');
    expect(screen.queryByText('ime_overview')).not.toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(false);
  });

  it('keeps Sessions and roles usable when the tool catalog is unavailable', async () => {
    const transport = featureTransport(previewModelCatalog('session-preview'), () => {
      throw new Error('tools unavailable');
    });
    renderAgent(transport);

    expect(await screen.findByRole('button', { name: /控制中心迁移/ })).toBeInTheDocument();
    expect(await screen.findByRole('textbox', { name: '消息' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '受控工具目录加载失败' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '受控工具目录加载失败' })).toHaveTextContent('工具 · 未加载');
  });

  it('opens the backend active conversation instead of a newer empty Session', async () => {
    const emptySession = { ...previewSessions[0], id: 'session-empty', title: '刚创建的空对话', messageCount: 0, lastMessagePreview: '' };
    const activeSession = { ...previewSessions[1], id: 'session-active', title: '仍在继续的对话', messageCount: 12, lastMessagePreview: '最近的助手回复' };
    const transport = featureTransport(
      previewModelCatalog('session-active'),
      { ok: true, items: toolCatalog() },
      { ok: true, activeSessionId: activeSession.id, items: [emptySession, activeSession] },
    );
    renderAgent(transport);

    expect(await screen.findByRole('button', { name: /仍在继续的对话/ })).toHaveAttribute('aria-current', 'true');
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.snapshot',
        params: { sessionId: 'session-active' },
      }),
    })));
  });

  it('does not let an empty runtime-active Session hide the most recent conversation', async () => {
    const emptyActive = { ...previewSessions[0], id: 'session-empty-active', title: '空白活动对话', messageCount: 0, lastMessagePreview: '' };
    const meaningful = { ...previewSessions[1], id: 'session-meaningful', title: '继续昨天的对话', messageCount: 6, lastMessagePreview: '已保留回复' };
    const transport = featureTransport(
      previewModelCatalog('session-meaningful'),
      { ok: true, items: toolCatalog() },
      { ok: true, activeSessionId: emptyActive.id, items: [emptyActive, meaningful] },
    );
    renderAgent(transport);

    expect(await screen.findByRole('button', { name: /继续昨天的对话/ })).toHaveAttribute('aria-current', 'true');
  });

  it('keeps persisted conversation visible when the model catalog fails', async () => {
    const transport = productionTransport({
      'agent.session.models': () => { throw new Error('provider probe failed'); },
    });
    renderAgent(transport);

    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.messageOrder).toHaveLength(4));
    expect(useAgentLiveStore.getState().projections['session-preview']?.turnOrder).toHaveLength(2);
    expect(await screen.findByRole('alert')).toHaveTextContent('模型目录暂时不可用，对话记录仍可查看');
  });

  it('keeps persisted conversation visible when the Pi command catalog fails', async () => {
    const transport = productionTransport({
      'agent.session.commands': () => { throw new Error('commands unavailable'); },
    });
    renderAgent(transport);

    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.messageOrder).toHaveLength(4));
    expect(useAgentLiveStore.getState().projections['session-preview']?.turnOrder).toHaveLength(2);
    expect(await screen.findByRole('alert')).toHaveTextContent('Pi 命令暂时不可用，仍可直接发送消息');
  });

  it('rehydrates persisted user and assistant blocks after a page remount', async () => {
    const first = productionTransport();
    const rendered = renderAgent(first);
    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.messageOrder).toHaveLength(4));

    rendered.unmount();
    useAgentLiveStore.getState().clear('session-preview');
    renderAgent(productionTransport());

    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.messageOrder).toHaveLength(4));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    const persistedMessages = Object.values(projection?.messagesById ?? {});
    expect(persistedMessages.some((message) => message.role === 'user'
      && message.blocks.some((block) => String(block.data.text).includes('把迁移进度按真实代码链整理一下')))).toBe(true);
    expect(persistedMessages.some((message) => message.role === 'assistant'
      && message.blocks.some((block) => String(block.data.text).includes('三条 Lane 已经收束到同一个')))).toBe(true);
  });

  it('uses the Pi runtime selection without deriving the Persona from the model name', async () => {
    const transport = featureTransport(lunaModelCatalog());
    const user = userEvent.setup();
    renderAgent(transport);

    expect(await screen.findByRole('button', { name: /模型：GPT-5.6 Luna/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '新建对话' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.sessions.create')).toBe(true));
    const create = transport.requests.find((call) => call.request.pathId === 'agent.sessions.create');
    expect(create?.request.body).toMatchObject({ roleId: 'zhiyou-v1', roleVersion: '1' });
    expect(create?.request.body).not.toHaveProperty('modelProfile');
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.model.select')).toBe(false);
  });

  it('renders Pi-provided Max reasoning and sends max without inventing levels', async () => {
    const transport = featureTransport(lunaModelCatalog());
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('button', { name: /模型：GPT-5.6 Luna/ }));
    const lunaDetails = screen.getByText('GPT-5.6 Luna', { selector: 'summary' }).closest('details');
    expect(lunaDetails).not.toBeNull();
    for (const level of ['关闭', '最小', '低', '中', '高', '极高', 'Max']) {
      expect(within(lunaDetails!).getByRole('button', { name: level })).toBeInTheDocument();
    }
    const max = within(lunaDetails!).getByRole('button', { name: 'Max' });
    await user.click(max);

    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.session.thinking.select'
      && typeof call.request.body === 'object'
      && call.request.body !== null
      && !Array.isArray(call.request.body)
      && call.request.body.level === 'max'
    ))).toBe(true));
  });

  it('does not show Max when the Pi model catalog omits max', async () => {
    const catalog = lunaModelCatalog();
    catalog.providers[0]!.models[1] = modelFixture(
      'gpt-5.6-luna',
      'GPT-5.6 Luna',
      ['off', 'minimal', 'low', 'medium', 'high'],
    );
    const user = userEvent.setup();
    renderAgent(featureTransport(catalog));

    await user.click(await screen.findByRole('button', { name: /模型：GPT-5.6 Luna/ }));
    expect(screen.queryByRole('button', { name: 'Max' })).not.toBeInTheDocument();
  });

  it('uses the real model and thinking selection routes then reloads Pi state', async () => {
    const transport = featureTransport(lunaModelCatalog());
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('button', { name: /模型：GPT-5.6 Luna/ }));
    const codexDetails = screen.getByText('Codex Mini').closest('details');
    expect(codexDetails).not.toBeNull();
    codexDetails!.open = true;
    await user.click(within(codexDetails!).getByRole('button', { name: '中' }));

    await waitFor(() => expect(transport.requests).toEqual(expect.arrayContaining([
      expect.objectContaining({ request: expect.objectContaining({
        pathId: 'agent.session.model.select',
        body: { provider: 'gpt', modelId: 'codex-mini-latest' },
      }) }),
      expect.objectContaining({ request: expect.objectContaining({
        pathId: 'agent.session.thinking.select',
        body: { level: 'medium' },
      }) }),
    ])));
    expect(transport.requests.filter((call) => call.request.pathId === 'agent.session.models')).toHaveLength(2);
  });

  it('starts with the session rail closed on mobile and closes it after selection', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })));
    const user = userEvent.setup();
    renderAgent(featureTransport());
    const feature = document.querySelector('.agent-feature');
    expect(feature).toHaveAttribute('data-rail-open', 'false');

    await user.click(screen.getByRole('button', { name: '展开对话列表' }));
    expect(feature).toHaveAttribute('data-rail-open', 'true');
    await user.click(await screen.findByRole('button', { name: /记忆整理/ }));
    expect(feature).toHaveAttribute('data-rail-open', 'false');
  });

  it('releases the session rail grid column when collapsed on desktop', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })));
    const user = userEvent.setup();
    const { container } = render(
      <MemoryRouter initialEntries={['/agent']}>
        <ControlTransportProvider transport={featureTransport()}>
          <QueryClientProvider client={testQueryClient()}>
            <TooltipProvider>
              <div className="shell-route-stage"><AgentFeature /></div>
            </TooltipProvider>
          </QueryClientProvider>
        </ControlTransportProvider>
      </MemoryRouter>,
    );
    const feature = container.querySelector<HTMLElement>('main.agent-feature');
    expect(feature).toHaveAttribute('data-rail-open', 'true');

    await user.click(screen.getByRole('button', { name: '收起对话列表' }));

    expect(feature).toHaveAttribute('data-rail-open', 'false');
    expect(getComputedStyle(feature!).gridTemplateColumns).toBe('0 minmax(0, 1fr) 0');
  });

  it('selects the Session requested by the roles route handoff', async () => {
    const transport = featureTransport();
    renderAgent(transport, '/agent?session=session-memory');

    expect(await screen.findByRole('button', { name: /记忆整理/ })).toHaveAttribute('aria-current', 'true');
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.snapshot',
        params: { sessionId: 'session-memory' },
      }),
    })));
  });

  it('does not substitute preview Sessions or Personas in the native host', async () => {
    const transport = new StubControlTransport('native', {
      'agent.sessions.list': { ok: true, items: [] },
      'agent.roles.list': { ok: true, items: [] },
      'agent.tools.list': { ok: true, items: [] },
    });
    render(
      <MemoryRouter initialEntries={['/agent']}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={testQueryClient()}>
            <TooltipProvider><AgentFeature /></TooltipProvider>
          </QueryClientProvider>
        </ControlTransportProvider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(transport.requests.map((request) => request.pathId)).toEqual(
      expect.arrayContaining(['agent.sessions.list', 'agent.roles.list']),
    ));
    expect(screen.getByText('0 个连续对话')).toBeInTheDocument();
    expect(screen.queryByText('控制中心迁移')).not.toBeInTheDocument();
    expect(screen.queryByText('记忆整理')).not.toBeInTheDocument();
  });
});

function renderAgent(transport: ControlTransport, initialEntry = '/agent') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={testQueryClient()}>
          <TooltipProvider><AgentFeature /></TooltipProvider>
        </QueryClientProvider>
      </ControlTransportProvider>
    </MemoryRouter>,
  );
}

function testQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function featureTransport(
  modelCatalog: unknown = previewModelCatalog('session-preview'),
  toolRoute: unknown = { ok: true, items: toolCatalog() },
  sessionRoute: unknown = { ok: true, items: previewSessions },
  promptRoute: unknown = { ok: true },
  subagentRoute: unknown = { ok: true, items: [] },
): MockControlTransport {
  return new MockControlTransport({
    pickedFiles: [{
      id: 'media_fixture_attachment_01',
      name: 'screen.png',
      mimeType: 'image/png',
      byteSize: 68,
      sessionId: 'session-preview',
      sha256: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
    }],
    importedFiles: [{
      id: 'media_fixture_attachment_01',
      name: 'screen.png',
      mimeType: 'image/png',
      byteSize: 68,
      sessionId: 'session-preview',
      sha256: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
    }],
    routes: {
      'agent.sessions.list': sessionRoute,
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.tools.list': toolRoute,
      'agent.session.snapshot': previewAgentSnapshot('session-preview'),
      'agent.session.models': modelCatalog,
      'agent.session.commands': commandCatalog(),
      'agent.session.prompt': promptRoute,
      'agent.session.forks.list': {
        schemaVersion: 'rag-ime.agent-session-fork-candidates.v1',
        ok: true,
        sessionId: 'session-preview',
        items: [
          { entryId: 'entry-start', text: '先梳理交互状态' },
          { entryId: 'entry-permissions', text: '帮我整理权限模式' },
        ],
      },
      'agent.session.forks.create': {
        schemaVersion: 'rag-ime.agent-session-fork-create.v1',
        ok: true,
        sourceSessionId: 'session-preview',
        entryId: 'entry-permissions',
        selectedText: '帮我整理权限模式',
        session: {
          ...previewSessions[0],
          schemaVersion: 'rag-ime.agent-session.v1',
          id: 'session-forked',
          title: '控制中心迁移 · 分支',
          createdAtMs: Date.now() - 1_000,
          messageCount: 2,
          updatedAtMs: Date.now(),
        },
      },
      'agent.sessions.create': { ok: true },
      'agent.session.rename': { ok: true },
      'agent.session.compact': { ok: true },
      'agent.session.abort': { ok: true },
      'agent.session.mode.update': { ok: true },
      'agent.session.model.select': { ok: true },
      'agent.session.thinking.select': { ok: true },
      'agent.approval.decide': { ok: true },
      'agent.memoryMaintenance.run': memoryRunFixture(),
      'agent.session.review.resolve': { ok: true },
      'agent.subagents.list': subagentRoute,
      'knowledge.database.draft.edit': { ok: true },
      'knowledge.database.apply.preview': {
        ok: true,
        previewToken: 'preview-token',
        payloadSha256: 'sha256:preview',
        expectedRevision: { runtimeRevision: 1 },
        summary: { items: ['应用已选择的记忆变更'] },
      },
      'knowledge.database.apply': { ok: true },
    },
  });
}

function subagentListFixture() {
  const now = Date.now();
  const run = (
    id: string,
    templateId: 'researcher' | 'planner' | 'worker' | 'reviewer',
    state: 'queued' | 'running' | 'completed' | 'failed',
    task: string,
  ) => ({
    schemaVersion: 'rag-ime.agent-subagent-run.v1',
    id,
    batchId: 'batch-status-panel',
    childSessionId: `session-child-${id}`,
    templateId,
    templateVersion: '1',
    ordinal: 0,
    task,
    state,
    budget: { maxTurns: 10, maxToolCalls: 18, maxTotalTokens: 32_000, maxDurationMs: 300_000, maxOutputChars: 24_000 },
    usage: { turnCount: state === 'completed' ? 4 : 1, toolCount: state === 'completed' ? 3 : 0, totalTokens: state === 'completed' ? 2_400 : 320 },
    result: state === 'completed' ? { summary: '证据已经交回主对话。' } : {},
    error: state === 'failed' ? 'public failure' : '',
    createdAtMs: now - 20_000,
    startedAtMs: state === 'queued' ? null : now - 14_000,
    updatedAtMs: now,
    completedAtMs: state === 'completed' || state === 'failed' ? now : null,
  });
  const runs = [
    run('run-research', 'researcher', 'running', '核对记忆设计与来源'),
    run('run-plan', 'planner', 'queued', '整理实现顺序'),
    run('run-review', 'reviewer', 'completed', '审阅公开结果'),
    run('run-work', 'worker', 'failed', '验证受控执行路径'),
  ];
  return {
    ok: true,
    items: [{
      schemaVersion: 'rag-ime.agent-subagent-batch.v1',
      id: 'batch-status-panel',
      parentSessionId: 'session-preview',
      parentRunId: 'run-parent',
      contextMode: 'fresh',
      state: 'running',
      depth: 0,
      maxDepth: 2,
      abortRequested: false,
      createdAtMs: now - 20_000,
      updatedAtMs: now,
      completedAtMs: null,
      runs,
    }],
  };
}

function memoryRunFixture() {
  return {
    ok: true,
    run: {
      runId: 'memory-run-1',
      status: 'draft',
      summary: '输入法记忆增量整理',
      diffCount: 2,
      pendingDiffCount: 2,
      changes: [
        { diffId: 1, operationLabel: '更新主题书', status: 'pending', selected: true, title: '输入法 Agent 交互', detail: '记录审阅状态机决策', sourceCount: 3 },
        { diffId: 2, operationLabel: '归档重复内容', status: 'pending', selected: true, title: '旧的重复记录', detail: '仅保留来源引用', sourceCount: 2 },
      ],
    },
  };
}

function productionTransport(
  overrides: Partial<Record<string, unknown>> = {},
): StubControlTransport {
  return new StubControlTransport('native', {
    'agent.sessions.list': { ok: true, activeSessionId: 'session-preview', items: previewSessions },
    'agent.roles.list': { ok: true, items: previewPersonas },
    'agent.tools.list': { ok: true, items: toolCatalog() },
    'agent.session.snapshot': previewAgentSnapshot('session-preview'),
    'agent.session.models': previewModelCatalog('session-preview'),
    'agent.session.commands': commandCatalog(),
    ...overrides,
  } as ConstructorParameters<typeof StubControlTransport>[1]);
}

function commandCatalog() {
  return {
    schemaVersion: 'rag-ime.agent-command-catalog.v1',
    ok: true,
    sessionId: 'session-preview',
    runtimeAvailable: true,
    items: [
      { name: 'review', invocation: '/review', description: '审阅当前改动', source: 'extension' },
      { name: 'plan', invocation: '/plan', description: '运行规划模板', source: 'prompt' },
      { name: 'skill:browser', invocation: '/skill:browser', description: '调用浏览器技能', source: 'skill' },
    ],
  };
}

function lunaModelCatalog(): ModelCatalog {
  return {
    schemaVersion: 'rag-ime.agent-model-catalog.v1',
    ok: true,
    sessionId: 'session-preview',
    selected: { provider: 'gpt', id: 'gpt-5.6-luna', modelId: 'codex-mini-latest', name: 'GPT-5.6 Luna' },
    thinkingLevel: 'medium',
    providers: [{
      id: 'gpt',
      displayName: 'GPT',
      models: [
        modelFixture('codex-mini-latest', 'Codex Mini'),
        modelFixture('gpt-5.6-luna', 'GPT-5.6 Luna', ['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']),
      ],
    }],
  };
}

function modelFixture(id: string, name: string, thinkingLevels: ThinkingLevel[] = ['off', 'medium']) {
  return { provider: 'gpt', id, name, api: 'responses', reasoning: true, thinkingLevels: thinkingLevels as [ThinkingLevel, ...ThinkingLevel[]], supportsImages: true, contextWindow: 100_000, maxTokens: 32_000 };
}

function toolCatalog() {
  const tools = [
    ['ime_overview', '控制中心概览', 'overview'],
    ['ime_input', '输入法', 'input'],
    ['ime_voice', '语音输入', 'voice'],
    ['ime_planning', '规划与任务', 'planning'],
    ['ime_memory', '记忆与工具书', 'memory'],
    ['ime_knowledge', '知识检索', 'knowledge'],
    ['ime_models', '模型', 'models'],
    ['ime_runtime', '诊断与运行时', 'runtime'],
    ['ime_configuration', '历史与配置', 'configuration'],
    ['ime_agents', '多 Agent 协作', 'agents'],
    ['workspace_list', '工作区浏览', 'workspace'],
    ['workspace_read', '工作区读取', 'workspace'],
    ['workspace_shell', '受控命令', 'workspace'],
  ] as const;
  return tools.map(([id, displayName, category]) => ({
    schemaVersion: 'rag-ime.control-tool-manifest.v1',
    id,
    domain: category,
    displayName,
    description: `${displayName}真实能力`,
    category,
    riskLevel: id === 'workspace_shell' ? 'R2' : 'R0',
    operationRisks: { status: id === 'workspace_shell' ? 'R2' : 'R0' },
    sessionModes: id.startsWith('workspace_') ? ['coordinator'] : ['assistant', 'coordinator'],
    operations: ['status'],
    resultPresentation: 'tool_result',
    availability: 'online',
    version: '1',
  }));
}

function historyMessage(
  sessionId: string,
  id: string,
  role: 'user' | 'assistant',
  text: string,
) {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id,
    sessionId,
    turnId: 'history',
    role,
    status: 'completed',
    blocks: [{
      id: `${id}:text`,
      type: 'text',
      status: 'completed',
      presentationKind: 'markdown',
      data: { text },
    }],
    attachments: [],
    citations: [],
    createdAtMs: 100,
    completedAtMs: 101,
  };
}
