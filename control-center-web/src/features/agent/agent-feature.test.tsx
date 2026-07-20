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
import { resolveConversationEntryId } from './sessions/ConversationForkDialog';
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
    expect(screen.getByText('learnA')).toBeInTheDocument();
    expect(screen.getByText('未指定项目')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /记忆整理/ }));
    expect(onSelect).toHaveBeenCalledWith('session-memory');
  });

  it('offers archive, delete confirmation, and archived visibility controls per task', async () => {
    const onArchive = vi.fn();
    const onDelete = vi.fn();
    const onShowArchivedChange = vi.fn();
    const user = userEvent.setup();
    const { container } = render(
      <TooltipProvider>
        <SessionRail
          sessions={previewSessions}
          selectedId="session-preview"
          loading={false}
          onSelect={() => {}}
          onCreate={() => {}}
          onArchive={onArchive}
          onDelete={onDelete}
          onShowArchivedChange={onShowArchivedChange}
        />
      </TooltipProvider>,
    );
    const targetRow = [...container.querySelectorAll('.agent-session-row-shell')]
      .find((row) => row.textContent?.includes('记忆整理'));
    expect(targetRow).toBeDefined();

    await user.click(within(targetRow as HTMLElement).getByRole('button', { name: '更多任务操作' }));
    await user.click(await screen.findByRole('menuitem', { name: '归档任务' }));
    expect(onArchive).toHaveBeenCalledWith('session-memory', true);

    await user.click(within(targetRow as HTMLElement).getByRole('button', { name: '更多任务操作' }));
    await user.click(await screen.findByRole('menuitem', { name: '删除任务' }));
    const dialog = await screen.findByRole('dialog', { name: /删除“记忆整理”/ });
    await user.click(within(dialog).getByRole('button', { name: '删除' }));
    expect(onDelete).toHaveBeenCalledWith('session-memory');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /删除“记忆整理”/ })).not.toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: '任务列表选项' }));
    await user.click(await screen.findByRole('menuitemcheckbox', { name: '显示已归档任务' }));
    expect(onShowArchivedChange).toHaveBeenCalledWith(true);
  });

  it('keeps the delete confirmation open and shows the backend error when deletion fails', async () => {
    const onDelete = vi.fn().mockRejectedValue(new Error('DELETE requires application/json'));
    const user = userEvent.setup();
    const { container } = render(
      <TooltipProvider>
        <SessionRail
          sessions={previewSessions}
          selectedId="session-preview"
          loading={false}
          onSelect={() => {}}
          onCreate={() => {}}
          onDelete={onDelete}
        />
      </TooltipProvider>,
    );
    const targetRow = [...container.querySelectorAll('.agent-session-row-shell')]
      .find((row) => row.textContent?.includes('记忆整理'));

    await user.click(within(targetRow as HTMLElement).getByRole('button', { name: '更多任务操作' }));
    await user.click(await screen.findByRole('menuitem', { name: '删除任务' }));
    const dialog = await screen.findByRole('dialog', { name: /删除“记忆整理”/ });
    await user.click(within(dialog).getByRole('button', { name: '删除' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('DELETE requires application/json');
    expect(dialog).toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByRole('button', { name: '删除' })).not.toBeDisabled());
  });

  it('resolves projected message ids to real Pi transcript entry ids', () => {
    expect(resolveConversationEntryId({
      items: [{
        entryId: 'pi-jsonl-entry-42',
        role: 'user',
        text: '修改之前的问题',
        createdAtMs: 1_234,
      }],
    }, [{
      entryId: 'projected-message-id',
      role: 'user',
      text: '修改之前的问题',
      createdAtMs: 1_234,
    }], 'projected-message-id')).toBe('pi-jsonl-entry-42');
  });

  it('renders a right-edge conversation navigator with turn previews', async () => {
    renderAgent(featureTransport());
    const navigator = await screen.findByRole('navigation', { name: '快速跳转对话' });
    const markers = within(navigator).getAllByRole('button');
    expect(markers.length).toBeGreaterThan(1);
    expect(markers[0]).toHaveTextContent('第 1 轮');
    expect(navigator).toHaveTextContent('读取输入法工具书');
    expect(navigator).toHaveTextContent('智鼬');
  });

  it('creates a real Pi-backed conversation branch and restores the selected message as draft', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);

    const branchButton = await screen.findByRole('button', { name: '查看对话路径与分支' }, { timeout: 5_000 });
    await waitFor(() => expect(branchButton).toBeEnabled());
    await user.click(branchButton);
    const dialog = await screen.findByRole('dialog', { name: '对话路径' });
    expect(within(dialog).getByText(/所有公开消息都可跳转和创建分支/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/private deep-search evidence/)).not.toBeInTheDocument();
    await user.click(await within(dialog).findByRole('radio', { name: /读取输入法工具书，并把结果作为可展开卡片保留/ }));
    await user.click(within(dialog).getByRole('button', { name: '创建分支' }));

    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.forks.create',
        params: { sessionId: 'session-preview' },
        body: expect.objectContaining({ entryId: 'session-preview:user-media' }),
      }),
    })));
    expect(await screen.findByRole('textbox', { name: '消息' })).toHaveValue('读取输入法工具书，并把结果作为可展开卡片保留。');
    expect(screen.getByRole('button', { name: /控制中心迁移 · 分支/ })).toHaveAttribute('aria-current', 'true');
  });

  it('creates a branch directly from the selected user message', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);

    const actions = await screen.findAllByRole('button', { name: '从这条消息创建分支' }, { timeout: 5_000 });
    const action = actions.find((item) => (
      item.closest('.agent-user-message-shell')?.getAttribute('data-agent-message-id')
        === 'session-preview:user-media'
    ));
    expect(action).toBeDefined();
    await user.click(action!);
    const dialog = await screen.findByRole('dialog', { name: '对话路径' });
    const create = within(dialog).getByRole('button', { name: '创建分支' });
    await waitFor(() => expect(create).toBeEnabled());
    await user.click(create);

    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.forks.create',
        params: { sessionId: 'session-preview' },
        body: expect.objectContaining({ entryId: 'session-preview:user-media' }),
      }),
    })));
    expect(await screen.findByRole('textbox', { name: '消息' })).toHaveValue('读取输入法工具书，并把结果作为可展开卡片保留。');
  });

  it('rewinds the same conversation when double Escape edits the previous user message', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(screen.getAllByRole('button', { name: '修改这条消息' }).length).toBeGreaterThan(0));

    composer.focus();
    await user.keyboard('{Escape}{Escape}');
    expect(await screen.findByText('正在修改这条消息')).toBeInTheDocument();
    expect(composer).toHaveValue('读取输入法工具书，并把结果作为可展开卡片保留。');
    await user.clear(composer);
    await user.type(composer, '改成更准确的问题');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.rewrite',
        params: { sessionId: 'session-preview' },
        body: expect.objectContaining({
          entryId: 'session-preview:user-media',
          message: '改成更准确的问题',
        }),
      }),
    })));
    expect(screen.queryByRole('button', { name: '打开命令面板' })).not.toBeInTheDocument();
  });

  it('creates a branch after an assistant message and keeps the new composer empty', async () => {
    const forkCreate = (request: { body?: unknown }) => {
      const body = request.body as { entryId?: string };
      return {
        schemaVersion: 'rag-ime.agent-session-fork-create.v1',
        ok: true,
        sourceSessionId: 'session-preview',
        entryId: body.entryId ?? '',
        selectedText: '',
        session: {
          ...previewSessions[0],
          schemaVersion: 'rag-ime.agent-session.v1',
          id: 'session-forked-assistant',
          title: '回答之后 · 分支',
          createdAtMs: Date.now() - 1_000,
          messageCount: 4,
          updatedAtMs: Date.now(),
        },
      };
    };
    const transport = featureTransport(
      undefined, undefined, undefined, undefined, undefined, undefined,
      undefined, undefined, undefined, forkCreate,
    );
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('button', { name: '查看对话路径与分支' }));
    const dialog = await screen.findByRole('dialog', { name: '对话路径' });
    const assistant = await within(dialog).findByRole('radio', { name: /已完成。正文展示工具书内容/ });
    await user.click(assistant);
    expect(within(assistant).getByText('可跳转 · 可分支')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '跳到节点' })).toBeEnabled();
    expect(within(dialog).getByRole('button', { name: '创建分支' })).toBeEnabled();
    await user.click(within(dialog).getByRole('button', { name: '创建分支' }));

    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.forks.create',
        params: { sessionId: 'session-preview' },
        body: expect.objectContaining({ entryId: 'session-preview:assistant-media' }),
      }),
    })));
    expect(await screen.findByRole('textbox', { name: '消息' })).toHaveValue('');
  });

  it('lists every conversation node and jumps back to an assistant message', async () => {
    const user = userEvent.setup();
    renderAgent(featureTransport());

    await user.click(await screen.findByRole('button', { name: '查看对话路径与分支' }));
    const dialog = await screen.findByRole('dialog', { name: '对话路径' });
    await user.click(within(dialog).getByRole('radio', { name: /已完成。正文展示工具书内容/ }));
    await user.click(within(dialog).getByRole('button', { name: '跳到节点' }));

    await waitFor(() => expect(document.querySelector(
      '[data-agent-message-id="session-preview:assistant-media"][data-history-target="true"]',
    )).not.toBeNull());
    expect(screen.queryByRole('dialog', { name: '对话路径' })).not.toBeInTheDocument();
  });

  it('exposes native fork capability without waiting for slower session catalogs', async () => {
    let resolveTools!: (value: unknown) => void;
    const slowTools = new Promise<unknown>((resolve) => { resolveTools = resolve; });
    renderAgent(featureTransport(undefined, () => slowTools));

    const branchButton = await screen.findByRole('button', { name: '查看对话路径与分支' });
    await waitFor(() => expect(branchButton).toBeEnabled());
    resolveTools({ ok: true, items: toolCatalog() });
  });

  it('does not offer branches when the active Pi protocol declares them unsupported', async () => {
    const transport = featureTransport(
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      {
        schemaVersion: 'rag-ime.agent-runtime.v1',
        enabled: true,
        managed: true,
        status: 'ready',
        piVersion: '0.80.7',
        idleTimeoutSeconds: 600,
        capabilities: { conversationFork: false },
      },
    );
    renderAgent(transport);

    const navigator = await screen.findByRole('button', { name: '查看对话路径与分支' });
    await waitFor(() => expect(navigator).toBeEnabled());
    fireEvent.click(navigator);
    expect(await screen.findByText('当前运行时未提供分支能力，历史节点仍可直接跳转。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '创建分支' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '从这条消息创建分支' })).not.toBeInTheDocument();
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
    const turnId = `${sessionId}:turn-media`;
    render(<TooltipProvider><AgentTurn sessionId={sessionId} turnId={turnId} persona={previewPersonas[0]} onApprovalDecision={() => {}} /></TooltipProvider>);
    expect(screen.getAllByAltText('智鼬·未来头像')).toHaveLength(1);
    expect(document.querySelectorAll('.agent-activity')).toHaveLength(1);
    expect(document.querySelector('.agent-user-message')).toBeInTheDocument();
    expect(screen.queryByText(/do-not-render/)).not.toBeInTheDocument();
    expect(document.querySelector('.agent-assistant-message')).toHaveTextContent('正文展示工具书内容');
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

    expect(await screen.findByText('1 个任务 · 1 个项目')).toBeInTheDocument();
    expect(document.querySelectorAll('.agent-session-row')).toHaveLength(1);
    expect(screen.queryByText('研究员临时会话')).not.toBeInTheDocument();

    const statusPanel = await screen.findByLabelText('当前对话状态');
    await waitFor(() => expect(within(statusPanel).getByText('研究员')).toBeInTheDocument());
    const planPanel = await within(statusPanel).findByRole('region', { name: '会话执行计划' });
    expect(planPanel).toHaveTextContent('第 2 / 3 步 · 1 项已完成');
    expect(within(statusPanel).getByText('执行中 · 1/3')).toBeInTheDocument();
    expect(document.querySelector('.agent-timeline .agent-plan-card')).not.toBeInTheDocument();
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
    expect(within(statusPanel).getByText('ime_knowledge')).toBeInTheDocument();
    expect(within(statusPanel).getByText('find')).toBeInTheDocument();
    expect(within(statusPanel).getByText('0 个字段')).toBeInTheDocument();
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
    expect(prompt?.request.body).not.toHaveProperty('delivery');
  });

  it('queues native steer and follow-up messages on the active turn', async () => {
    const busySnapshot = {
      ...previewAgentSnapshot('session-preview'),
      status: 'working',
      messageQueue: { steering: [], followUp: [] },
    };
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);

    const composer = await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(
      useAgentLiveStore.getState().projections['session-preview']?.messageOrder.length,
    ).toBeGreaterThan(0));
    act(() => useAgentLiveStore.getState().hydrateSnapshot('session-preview', busySnapshot));
    await screen.findByRole('radiogroup', { name: '消息投递方式' });
    await user.type(composer, '先停止继续搜索，直接核对实现');
    await user.click(screen.getByRole('button', { name: '干预当前执行' }));

    await user.click(screen.getByRole('radio', { name: '接续' }));
    await user.type(composer, '完成后再整理测试结果');
    await user.click(screen.getByRole('button', { name: '当前执行完成后接续' }));

    await waitFor(() => expect(
      transport.requests.filter((call) => call.request.pathId === 'agent.session.prompt'),
    ).toHaveLength(2));
    const prompts = transport.requests.filter((call) => call.request.pathId === 'agent.session.prompt');
    expect(prompts[0]?.request.body).toMatchObject({
      message: '先停止继续搜索，直接核对实现',
      delivery: 'steer',
    });
    expect(prompts[1]?.request.body).toMatchObject({
      message: '完成后再整理测试结果',
      delivery: 'followUp',
    });
    expect(screen.getByText('干预当前执行')).toBeInTheDocument();
    expect(screen.getByText('完成后接续')).toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.abort')).toBe(false);
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

  it('reports a native route version mismatch instead of blaming the model', async () => {
    const transport = featureTransport(
      previewModelCatalog('session-preview'),
      { ok: true, items: toolCatalog() },
      { ok: true, items: previewSessions },
      () => { throw new Error('Unexpected request body field: delivery'); },
    );
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });

    await user.type(composer, '检查原生路由版本');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(true));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    const failedTurn = Object.values(projection.turnsById).find((turn) => turn.failure);
    expect(failedTurn?.failure).toBe('控制中心组件版本不一致，请更新并重新打开控制中心。');
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
          riskLevel: 'R2',
          preview: {
            title: '确认输入法配置变更',
            summary: '关闭模糊音并重新部署输入方案',
            changes: [
              { label: '模糊音', before: '开启', after: '关闭' },
              { label: '输入方案', before: '', after: '小鹤双拼' },
            ],
          },
        },
        resumeToken: 'approval-pending-ui',
      }]);
    });

    expect(await screen.findByRole('heading', { name: '确认输入法配置变更' })).toBeInTheDocument();
    expect(screen.getByText('模糊音')).toBeInTheDocument();
    expect(screen.getByText('开启')).toBeInTheDocument();
    expect(screen.getByText('关闭')).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: '批准并执行' }));

    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.approval.decide',
        params: { approvalId: 'approval-live-1' },
        body: { decision: 'approve', payloadSha256: 'approval-live-hash' },
      }),
    })));
  });

  it('opens the existing approval review from a failed tool receipt and uses its bound route', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    const view = renderAgent(transport);
    await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.lastSequence).toBeGreaterThan(0));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    const turnId = projection.turnOrder.at(-1) ?? 'turn-tool-approval';
    act(() => {
      useAgentLiveStore.getState().applyEvents('session-preview', [{
        schemaVersion: 'rag-ime.agent-event.v1',
        eventId: 'tool-approval-failed-ui',
        sessionId: 'session-preview',
        turnId,
        sequence: projection.lastSequence + 1,
        createdAtMs: Date.now(),
        streamKind: 'agent',
        eventType: 'tool_finished',
        payload: {
          toolCallId: 'tool-approval-failed-ui',
          toolName: 'ime_input',
          isError: true,
          approvalId: 'approval-from-tool-1',
          payloadSha256: 'd'.repeat(64),
          preview: {
            title: '确认失败工具的受控操作',
            summary: '应用输入法设置',
            changes: [{ label: '候选数', before: '5', after: '7' }],
          },
          result: {
            details: {
              ok: false,
              operation: 'apply_settings',
              result: { error: '该操作需要本机审批后继续。' },
            },
          },
        },
        resumeToken: 'tool-approval-failed-ui',
      }]);
    });

    const activity = [...view.container.querySelectorAll<HTMLElement>('.agent-activity--inline')]
      .find((item) => item.textContent?.includes('该操作需要本机审批后继续'));
    expect(activity).toBeDefined();
    fireEvent.click(activity!.querySelector('summary')!);
    const failedRow = [...activity!.querySelectorAll<HTMLDetailsElement>('.agent-activity-row')]
      .find((row) => row.textContent?.includes('该操作需要本机审批后继续'));
    expect(failedRow).toBeDefined();
    fireEvent.click(failedRow!.querySelector('summary')!);
    await user.click(within(failedRow!).getByRole('button', { name: '去审批' }));

    const dialog = await screen.findByRole('dialog', { name: '确认失败工具的受控操作' });
    expect(within(dialog).getByText('候选数')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: '批准并执行' }));
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.approval.decide',
        params: { approvalId: 'approval-from-tool-1' },
        body: { decision: 'approve', payloadSha256: 'd'.repeat(64) },
      }),
    })));
  });

  it('opens the real permission picker from a permission-denied tool receipt', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    const view = renderAgent(transport);
    await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.lastSequence).toBeGreaterThan(0));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    const turnId = projection.turnOrder.at(-1) ?? 'turn-tool-permission';
    act(() => {
      useAgentLiveStore.getState().applyEvents('session-preview', [{
        schemaVersion: 'rag-ime.agent-event.v1',
        eventId: 'tool-permission-failed-ui',
        sessionId: 'session-preview',
        turnId,
        sequence: projection.lastSequence + 1,
        createdAtMs: Date.now(),
        streamKind: 'agent',
        eventType: 'tool_finished',
        payload: {
          toolCallId: 'tool-permission-failed-ui',
          toolName: 'workspace_shell',
          isError: true,
          result: { details: { ok: false, result: { error: '工作区不在授权目录内，当前权限不足。' } } },
        },
        resumeToken: 'tool-permission-failed-ui',
      }]);
    });

    const activity = [...view.container.querySelectorAll<HTMLElement>('.agent-activity--inline')]
      .find((item) => item.textContent?.includes('工作区不在授权目录内'));
    expect(activity).toBeDefined();
    fireEvent.click(activity!.querySelector('summary')!);
    const failedRow = [...activity!.querySelectorAll<HTMLDetailsElement>('.agent-activity-row')]
      .find((row) => row.textContent?.includes('工作区不在授权目录内'));
    expect(failedRow).toBeDefined();
    fireEvent.click(failedRow!.querySelector('summary')!);
    await user.click(within(failedRow!).getByRole('button', { name: '请求权限' }));

    expect(await screen.findByText('对话权限')).toBeInTheDocument();
    const picker = document.querySelector('.agent-picker-popover');
    expect(picker).not.toBeNull();
    expect(within(picker as HTMLElement).getByRole('radio', { name: /受控助手/ })).toBeInTheDocument();
  });

  it('restores a pending approval dialog directly from the session snapshot', async () => {
    const snapshot = previewAgentSnapshot('session-preview');
    const transport = productionTransport({
      'agent.session.snapshot': {
        ...snapshot,
        status: 'busy',
        liveEvents: [{
          schemaVersion: 'rag-ime.agent-event.v1',
          eventId: 'session-preview:snapshot:approval-snapshot-1',
          sessionId: 'session-preview',
          turnId: 'approval:approval-snapshot-1',
          sequence: 12,
          createdAtMs: Date.now(),
          eventType: 'approval_required',
          payload: {
            approvalId: 'approval-snapshot-1',
            payloadSha256: 'c'.repeat(64),
            summary: '恢复后继续审批',
            preview: { title: '恢复待审批操作', changes: [] },
          },
          resumeToken: 'session-preview:snapshot:approval-snapshot-1',
        }],
      },
    });
    renderAgent(transport);

    expect(await screen.findByRole('dialog', { name: '恢复待审批操作' })).toBeInTheDocument();
    expect(useAgentLiveStore.getState().projections['session-preview']?.status).toBe('waiting');
  });

  it('keeps approval failures visible inside the forced review dialog', async () => {
    const transport = featureTransport(
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      async () => { throw new Error('审批已过期，请重新发起操作'); },
    );
    const user = userEvent.setup();
    renderAgent(transport);
    await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.lastSequence).toBeGreaterThan(0));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    const turnId = projection.turnOrder.at(-1) ?? 'turn-approval-error';
    act(() => {
      useAgentLiveStore.getState().applyEvents('session-preview', [{
        schemaVersion: 'rag-ime.agent-event.v1',
        eventId: 'approval-pending-error-ui',
        sessionId: 'session-preview',
        turnId,
        sequence: projection.lastSequence + 1,
        createdAtMs: Date.now(),
        streamKind: 'agent',
        eventType: 'approval_required',
        payload: {
          approvalId: 'approval-live-error',
          payloadSha256: 'approval-live-error-hash',
          summary: '应用设置',
          preview: { title: '确认应用设置', changes: [{ label: '候选数', before: '5', after: '7' }] },
        },
        resumeToken: 'approval-pending-error-ui',
      }]);
    });

    await user.click(await screen.findByRole('button', { name: '批准并执行' }));

    const dialog = await screen.findByRole('dialog', { name: '确认应用设置' });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('审批已过期，请重新发起操作');
    expect(within(dialog).getByRole('button', { name: '批准并执行' })).toBeEnabled();
  });

  it('keeps the turn busy while abort is only acknowledged and prevents repeated stop clicks', async () => {
    let resolveAbort!: (value: unknown) => void;
    const abortPending = new Promise((resolve) => { resolveAbort = resolve; });
    const transport = featureTransport(
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      () => abortPending,
    );
    const user = userEvent.setup();
    renderAgent(transport);
    await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.lastSequence).toBeGreaterThan(0));
    act(() => {
      useAgentLiveStore.getState().appendOptimistic('session-preview', {
        clientMessageId: 'stop-in-flight',
        text: '停止这轮',
        nowMs: Date.now(),
      });
    });

    await user.click(await screen.findByRole('button', { name: '停止本轮' }));

    const stopping = await screen.findByRole('button', { name: '正在停止本轮' });
    expect(stopping).toBeDisabled();
    expect(stopping).toHaveAttribute('aria-busy', 'true');
    expect(useAgentLiveStore.getState().projections['session-preview']?.status).toBe('busy');
    expect(transport.requests.filter(({ request }) => request.pathId === 'agent.session.abort')).toHaveLength(1);
    resolveAbort({ ok: true });
  });

  it('recovers a stale client-side busy turn from the idle snapshot returned after abort ACK', async () => {
    let snapshotCalls = 0;
    const transport = featureTransport(
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      () => {
        snapshotCalls += 1;
        if (snapshotCalls === 1) return previewAgentSnapshot('session-preview');
        return {
          schemaVersion: 'rag-ime.agent-message-list.v1',
          ok: true,
          sessionId: 'session-preview',
          items: [],
          liveEvents: [],
          status: 'idle',
          lastSequence: 99,
          resumeToken: 'session-preview:99',
        };
      },
    );
    const user = userEvent.setup();
    renderAgent(transport);
    await screen.findByRole('textbox', { name: '消息' });
    await waitFor(() => expect(snapshotCalls).toBe(1));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    act(() => {
      useAgentLiveStore.getState().applyEvents('session-preview', [
        {
          schemaVersion: 'rag-ime.agent-event.v1',
          eventId: 'stale-busy-before-stop',
          sessionId: 'session-preview',
          turnId: 'turn-stale-stop',
          sequence: projection.lastSequence + 1,
          createdAtMs: Date.now(),
          streamKind: 'agent',
          eventType: 'status_changed',
          payload: { status: 'busy' },
          resumeToken: `session-preview:${projection.lastSequence + 1}`,
        },
        {
          schemaVersion: 'rag-ime.agent-event.v1',
          eventId: 'stale-delta-before-stop',
          sessionId: 'session-preview',
          turnId: 'turn-stale-stop',
          sequence: projection.lastSequence + 2,
          createdAtMs: Date.now(),
          streamKind: 'agent',
          eventType: 'text_delta',
          payload: { delta: 'partial' },
          resumeToken: `session-preview:${projection.lastSequence + 2}`,
        },
      ]);
    });

    await user.click(await screen.findByRole('button', { name: '停止本轮' }));

    await waitFor(() => expect(snapshotCalls).toBe(2));
    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.status).toBe('idle'));
    expect(screen.queryByRole('button', { name: '正在停止本轮' })).not.toBeInTheDocument();
  });

  it('treats an open Pi transcript as quiescent instead of showing a permanent stop action', async () => {
    const snapshot = {
      ...previewAgentSnapshot('session-preview'),
      status: 'active',
    };
    const transport = featureTransport(
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      snapshot,
    );

    renderAgent(transport);

    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-preview']?.turnsById['session-preview:turn-media']?.status).toBe('completed'));
    expect(document.querySelector('.agent-assistant-message')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '停止本轮' })).not.toBeInTheDocument();
    expect(screen.queryByText('思考中')).not.toBeInTheDocument();
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

    await user.type(composer, '/');
    expect(screen.getByRole('option', { name: /\/new/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/resume/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/name/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/model/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/thinking/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/permissions/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/tools/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/session/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/status/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/settings/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/hotkeys/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/help/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /\/review.*Pi 扩展/ })).toBeInTheDocument();

    await user.clear(composer);
    await user.type(composer, '/rev');
    expect(screen.getByRole('option', { name: /\/review/ })).toBeInTheDocument();
    expect(screen.queryByText('/memory')).not.toBeInTheDocument();
    await user.keyboard('{Enter}');
    expect(composer).toHaveValue('/review ');

    await user.clear(composer);
    await user.type(composer, '/n');
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
    await user.type(composer, '/not-a-real-command');
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
    expect(transport.requests
      .filter((call) => call.request.pathId === 'agent.tools.list')
      .every((call) => call.request.query?.sessionId === 'session-preview')).toBe(true);

    const openCommandPalette = async () => {
      await user.clear(composer);
      await user.type(composer, '/');
    };

    await openCommandPalette();
    await user.click(screen.getByRole('option', { name: /\/model/ }));
    expect(await screen.findByText('模型与推理强度')).toBeInTheDocument();
    await user.keyboard('{Escape}');

    await openCommandPalette();
    await user.click(screen.getByRole('option', { name: /\/permissions/ }));
    expect(await screen.findByText('对话权限')).toBeInTheDocument();
    const permissionPicker = document.querySelector('.agent-picker-popover');
    expect(permissionPicker).not.toBeNull();
    expect(within(permissionPicker as HTMLElement).getByRole('radio', { name: /受控助手/ })).toBeInTheDocument();
    expect(within(permissionPicker as HTMLElement).getByRole('radio', { name: /只读观察/ })).toBeInTheDocument();
    expect(within(permissionPicker as HTMLElement).getByRole('radio', { name: /完全信任/ })).toBeInTheDocument();
    const readonlyPermission = within(permissionPicker as HTMLElement).getByRole('radio', { name: /只读观察/ });
    const coordinatorPermission = within(permissionPicker as HTMLElement).getByRole('radio', { name: /运行协调/ });
    expect(coordinatorPermission).toHaveAttribute('aria-checked', 'true');
    readonlyPermission.focus();
    await user.keyboard(' ');
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.mode.update',
        params: { sessionId: 'session-preview' },
        body: {
          mode: 'assistant',
          workspaceRoots: [],
          toolProfileVersion: 'subagent-readonly-v1',
          toolAllowlistMode: 'profile',
        },
      }),
    })));
    expect(await screen.findByRole('button', { name: '对话权限：只读观察' })).toBeInTheDocument();

    await openCommandPalette();
    await user.click(screen.getByRole('option', { name: /\/tools/ }));
    const toolPicker = document.querySelector('.agent-tool-picker');
    expect(toolPicker).not.toBeNull();
    expect(within(toolPicker as HTMLElement).getByText('受控工具')).toBeInTheDocument();
    await user.keyboard('{Escape}');

    await openCommandPalette();
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

    await openCommandPalette();
    await user.click(screen.getByRole('option', { name: /\/help/ }));
    expect(screen.getByText('命令帮助')).toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(false);

    await user.click(screen.getByRole('option', { name: /\/status/ }));
    expect(screen.getByLabelText('当前对话状态')).toHaveAttribute('data-open', 'true');

    await openCommandPalette();
    await user.click(screen.getByRole('option', { name: /\/settings/ }));
    expect(window.location.hash).toBe('#/configuration');
  });

  it('persists Pi and Codex Skill source switches through the current session settings route', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);

    const contextButton = await screen.findByRole('button', { name: '项目指令：已加载' });
    await user.click(contextButton);
    await user.click(screen.getByRole('switch', { name: '加载 Pi Skills' }));
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.mode.update',
        params: { sessionId: 'session-preview' },
        body: expect.objectContaining({ piSkillsEnabled: true }),
      }),
    })));

    const codexSwitch = screen.getByRole('switch', { name: '加载 Codex Skills' });
    await waitFor(() => expect(codexSwitch).toBeEnabled());
    await user.click(codexSwitch);
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.mode.update',
        params: { sessionId: 'session-preview' },
        body: expect.objectContaining({ codexSkillsEnabled: true }),
      }),
    })));
  });

  it('requires a native workspace choice before enabling coordinator mode', async () => {
    const assistantSession = {
      ...previewSessions[0]!,
      mode: 'assistant' as const,
      workspaceRoots: [],
      toolProfileVersion: 'control-center-v1',
    };
    const transport = featureTransport(
      undefined,
      undefined,
      { ok: true, items: [assistantSession] },
    );
    const pickFiles = vi.spyOn(transport, 'pickFiles').mockResolvedValue([{
      id: 'workspace-directory-1',
      name: 'learnA',
      mimeType: 'application/octet-stream',
      byteSize: 0,
      path: '/Volumes/undo 4t/git/learnA',
    }]);
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('button', { name: '对话权限：受控助手' }));
    const permissionPicker = document.querySelector('.agent-picker-popover');
    expect(permissionPicker).not.toBeNull();
    await user.click(within(permissionPicker as HTMLElement).getByRole('radio', { name: /运行协调/ }));

    await waitFor(() => expect(pickFiles).toHaveBeenCalledWith({
      purpose: 'workspace-root',
      selection: 'directory',
      multiple: true,
      maxFiles: 4,
    }));
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.mode.update',
        body: expect.objectContaining({
          mode: 'coordinator',
          workspaceRoots: ['/Volumes/undo 4t/git/learnA'],
          toolAllowlistMode: 'profile',
        }),
      }),
    })));
    expect(await screen.findByRole('button', { name: '对话权限：运行协调' })).toBeInTheDocument();
  });

  it('requires an explicit native confirmation before enabling complete trust', async () => {
    const assistantSession = {
      ...previewSessions[0]!,
      mode: 'assistant' as const,
      workspaceRoots: [],
      toolProfileVersion: 'control-center-v1',
    };
    const transport = featureTransport(
      undefined,
      undefined,
      { ok: true, items: [assistantSession] },
    );
    const pickFiles = vi.spyOn(transport, 'pickFiles').mockResolvedValue([{
      id: 'workspace-directory-danger',
      name: 'learnA',
      mimeType: 'application/octet-stream',
      byteSize: 0,
      path: '/Volumes/undo 4t/git/learnA',
    }]);
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole('button', { name: '对话权限：受控助手' }));
    const permissionPicker = document.querySelector('.agent-picker-popover');
    expect(permissionPicker).not.toBeNull();
    await user.click(within(permissionPicker as HTMLElement).getByRole('radio', { name: /完全信任/ }));

    const dialog = await screen.findByRole('dialog', { name: '启用完全信任？' });
    const confirm = within(dialog).getByRole('button', { name: '启用完全信任' });
    expect(confirm).toBeDisabled();
    await user.click(within(dialog).getByRole('checkbox', { name: '我确认让此对话自动批准全部受控写操作' }));
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() => expect(pickFiles).toHaveBeenCalledWith({
      purpose: 'workspace-root',
      selection: 'directory',
      multiple: true,
      maxFiles: 4,
    }));
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.mode.update',
        params: { sessionId: 'session-preview' },
        body: {
          mode: 'coordinator',
          workspaceRoots: ['/Volumes/undo 4t/git/learnA'],
          toolProfileVersion: 'control-center-auto-approve-v1',
          toolAllowlistMode: 'profile',
          dangerousModeConfirmation: 'AUTO_APPROVE_ALL',
        },
      }),
    })));
    expect(await screen.findByRole('button', { name: '对话权限：完全信任' })).toBeInTheDocument();
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

    const composer = screen.getByRole('textbox', { name: '消息' });
    await user.type(composer, '/');
    const toolsCommand = screen.getByRole('option', { name: /\/tools/ });
    expect(toolsCommand).toBeDisabled();
    expect(toolsCommand).toHaveAttribute('title', '受控助手没有可用工具');
    await user.keyboard('{Escape}');

    act(() => {
      useAgentLiveStore.getState().appendOptimistic('session-preview', {
        clientMessageId: 'busy-command-state',
        text: '保持处理中',
        attachments: [],
        nowMs: Date.now(),
      });
    });
    await user.clear(composer);
    await user.type(composer, '/');
    const newCommand = screen.getByRole('option', { name: /\/new/ });
    expect(newCommand).toBeDisabled();
    expect(newCommand).toHaveAttribute('title', '当前处理中，仅可切换对话、查看状态或停止');
    expect(screen.getByRole('option', { name: /\/resume/ })).toBeEnabled();
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
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ }, { timeout: 5_000 });
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

    await screen.findByRole('button', { name: /模型：GPT-5\.4/ }, { timeout: 5_000 });
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
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ }, { timeout: 5_000 });
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
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ }, { timeout: 5_000 });
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
    await screen.findByRole('button', { name: /模型：GPT-5\.4/ }, { timeout: 5_000 });

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
    catalog.thinkingLevel = 'off';
    const transport = featureTransport(catalog);
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });

    const modelPicker = await screen.findByRole('button', {
      name: '模型：DeepSeek V4，思考强度：不启用推理',
    });
    expect(modelPicker).toHaveTextContent('DeepSeek V4 · 不启用推理');
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
    const trigger = await screen.findByRole(
      'button',
      { name: '当前权限可用工具：13 个' },
      { timeout: 5_000 },
    );

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
    const unavailableTools = await screen.findByRole('button', { name: '受控工具目录加载失败' });
    expect(unavailableTools).toBeDisabled();
    expect(unavailableTools).toHaveTextContent('工具 · 未加载');
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

    expect(await screen.findByRole(
      'button',
      { name: /模型：GPT-5.6 Luna/ },
      { timeout: 5_000 },
    )).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '新建任务' }));
    const dialog = await screen.findByRole('dialog', { name: '新建任务' });
    expect(within(dialog).getByRole('radio', { name: /learnA/ })).toBeChecked();
    await user.click(within(dialog).getByRole('button', { name: '创建任务' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.sessions.create')).toBe(true));
    const create = transport.requests.find((call) => call.request.pathId === 'agent.sessions.create');
    expect(create?.request.body).toMatchObject({
      roleId: 'vcp-v1',
      roleVersion: '1',
      mode: 'coordinator',
      workspaceRoots: ['/Volumes/undo 4t/git/learnA'],
    });
    expect(create?.request.body).not.toHaveProperty('modelProfile');
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.model.select')).toBe(false);
  });

  it('renders Pi-provided Max reasoning and sends max without inventing levels', async () => {
    const transport = featureTransport(lunaModelCatalog());
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole(
      'button',
      { name: /模型：GPT-5.6 Luna/ },
      { timeout: 5_000 },
    ));
    const lunaDetails = screen.getByText('GPT-5.6 Luna', { selector: 'summary' }).closest('details');
    expect(lunaDetails).not.toBeNull();
    for (const level of ['不启用推理', '最小', '低', '中', '高', '极高', 'Max']) {
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

    await user.click(await screen.findByRole(
      'button',
      { name: /模型：GPT-5.6 Luna/ },
      { timeout: 5_000 },
    ));
    expect(screen.queryByRole('button', { name: 'Max' })).not.toBeInTheDocument();
  });

  it('uses the real model and thinking selection routes then reloads Pi state', async () => {
    const transport = featureTransport(lunaModelCatalog());
    const user = userEvent.setup();
    renderAgent(transport);

    await user.click(await screen.findByRole(
      'button',
      { name: /模型：GPT-5.6 Luna/ },
      { timeout: 5_000 },
    ));
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

  it('reloads the model catalog when Pi publishes a session configuration change', async () => {
    let modelCatalogCalls = 0;
    const transport = featureTransport(() => {
      modelCatalogCalls += 1;
      return lunaModelCatalog();
    });
    renderAgent(transport);

    await waitFor(() => expect(modelCatalogCalls).toBe(1));
    await waitFor(() => expect(transport.activeSubscriptionCount()).toBe(1));
    const projection = useAgentLiveStore.getState().projections['session-preview'];
    const sequence = projection.lastSequence + 1;
    act(() => {
      transport.emit('agent.session.events', {
        schemaVersion: 'rag-ime.agent-event.v1',
        eventId: 'event-model-refresh',
        sessionId: 'session-preview',
        turnId: '',
        sequence,
        createdAtMs: Date.now(),
        streamKind: 'agent',
        eventType: 'session_configuration_changed',
        payload: { kind: 'model' },
        resumeToken: `session-preview:${sequence}`,
      });
    });

    await waitFor(() => expect(modelCatalogCalls).toBe(2));
  });

  it('treats the mobile session rail as a focus-managed drawer', async () => {
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: query.includes('max-width: 760px') || query.includes('max-width: 1100px'),
    })));
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    const user = userEvent.setup();
    renderAgent(featureTransport());
    const feature = () => document.querySelector('.agent-feature');
    expect(feature()).toHaveAttribute('data-rail-open', 'false');

    const toggle = await screen.findByRole('button', { name: '展开任务列表' });
    await user.click(toggle);
    expect(feature()).toHaveAttribute('data-rail-open', 'true');
    const rail = screen.getByRole('dialog', { name: '任务与项目' });
    const conversation = document.querySelector('.agent-conversation');
    expect(rail).toHaveAttribute('aria-modal', 'true');
    expect(conversation).toHaveAttribute('inert');
    expect(conversation).toHaveAttribute('aria-hidden', 'true');
    await waitFor(() => expect(screen.getByPlaceholderText('搜索任务或项目')).toHaveFocus());

    const sessionRows = rail.querySelectorAll<HTMLButtonElement>('.agent-session-row');
    const lastSession = sessionRows.item(sessionRows.length - 1);
    const lastSessionMenu = lastSession.parentElement?.querySelector<HTMLButtonElement>('.agent-session-row__menu');
    expect(lastSessionMenu).not.toBeNull();
    lastSession.focus();
    await user.tab();
    expect(lastSessionMenu).toHaveFocus();
    await user.tab();
    expect(within(rail).getByRole('button', { name: '新建任务' })).toHaveFocus();
    await user.tab({ shift: true });
    expect(lastSessionMenu).toHaveFocus();
    await user.tab({ shift: true });
    expect(lastSession).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(feature()).toHaveAttribute('data-rail-open', 'false');
    expect(conversation).not.toHaveAttribute('inert');
    expect(conversation).not.toHaveAttribute('aria-hidden');
    await waitFor(() => expect(toggle).toHaveFocus());

    await user.click(toggle);
    expect(document.querySelector('.agent-rail-backdrop')).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: /记忆整理/ }));
    expect(feature()).toHaveAttribute('data-rail-open', 'false');
  });

  it('treats the responsive status panel as a focus-managed dialog', async () => {
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: query.includes('max-width: 1100px'),
    })));
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    const user = userEvent.setup();
    renderAgent(featureTransport());

    const toggle = await screen.findByRole('button', { name: '展开状态面板' });
    await user.click(toggle);
    const panel = screen.getByRole('dialog', { name: '当前对话状态' });
    const conversation = document.querySelector('.agent-conversation');
    const rail = document.querySelector('.agent-session-rail');
    expect(panel).toHaveAttribute('aria-modal', 'true');
    expect(conversation).toHaveAttribute('inert');
    expect(rail).toHaveAttribute('inert');
    await waitFor(() => expect(within(panel).getByRole('button', { name: '收起状态面板' })).toHaveFocus());

    await user.tab({ shift: true });
    expect(panel).toContainElement(document.activeElement as HTMLElement);
    expect(conversation).not.toContainElement(document.activeElement as HTMLElement);

    await user.keyboard('{Escape}');
    expect(panel).toHaveAttribute('aria-hidden', 'true');
    expect(conversation).not.toHaveAttribute('inert');
    expect(rail).not.toHaveAttribute('inert');
    await waitFor(() => expect(toggle).toHaveFocus());
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
    const feature = () => container.querySelector<HTMLElement>('main.agent-feature');
    expect(feature()).toHaveAttribute('data-rail-open', 'true');
    const composer = await screen.findByRole('textbox', { name: '消息' });
    expect(composer).toBeVisible();

    await user.click(screen.getByRole('button', { name: '收起任务列表' }));

    expect(feature()).toHaveAttribute('data-rail-open', 'false');
    expect(getComputedStyle(feature()!).gridTemplateColumns).toBe('0 minmax(0, 1fr) 0');
    expect(screen.getByRole('textbox', { name: '消息' })).toBe(composer);
    expect(composer).toBeVisible();
    expect(composer.closest('.agent-composer-wrap')).toBeInTheDocument();
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
    expect(screen.getByText('0 个任务 · 0 个项目')).toBeInTheDocument();
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
  approvalRoute: unknown = { ok: true },
  abortRoute: unknown = { ok: true },
  runtimeRoute: unknown = {
    schemaVersion: 'rag-ime.agent-runtime.v1',
    enabled: true,
    managed: true,
    status: 'ready',
    driverId: 'managed-pi',
    runtimeKind: 'pi_rpc',
    runtimeVersion: 'preview',
    piVersion: '0.80.7',
    idleTimeoutSeconds: 600,
    activeSessionId: null,
    lastError: '',
    capabilities: { conversationFork: true, conversationRewrite: true },
  },
  snapshotRoute: unknown = previewAgentSnapshot('session-preview'),
  forkCreateRoute: unknown = {
    schemaVersion: 'rag-ime.agent-session-fork-create.v1',
    ok: true,
    sourceSessionId: 'session-preview',
    entryId: 'session-preview:user-media',
    selectedText: '读取输入法工具书，并把结果作为可展开卡片保留。',
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
      'agent.runtime.get': runtimeRoute,
      'agent.session.snapshot': snapshotRoute,
      'agent.session.workflow.get': workflowRouteFixture(),
      'agent.session.plan.mutate': workflowRouteFixture(),
      'agent.session.goal.mutate': workflowRouteFixture(),
      'agent.session.models': modelCatalog,
      'agent.session.commands': commandCatalog(),
      'agent.session.prompt': promptRoute,
      'agent.session.rewrite': { ok: true },
      'agent.session.forks.list': {
        schemaVersion: 'rag-ime.agent-session-fork-candidates.v1',
        ok: true,
        sessionId: 'session-preview',
        items: [
          { entryId: 'session-preview:user-architecture', text: '把迁移进度按真实代码链整理一下，别把工具日志当回答。', role: 'user', createdAtMs: 0 },
          { entryId: 'session-preview:assistant-architecture', text: '三条 Lane 已经收束到同一个可执行计划。', role: 'assistant', createdAtMs: 0 },
          { entryId: 'session-preview:user-media', text: '读取输入法工具书，并把结果作为可展开卡片保留。', role: 'user', createdAtMs: 0 },
          { entryId: 'session-preview:assistant-media', text: '已完成。正文展示工具书内容，精确接口与参数继续留在右侧运行状态中。', role: 'assistant', createdAtMs: 0 },
          { entryId: 'internal-context', text: '<rag-ime-deep-search-context>private deep-search evidence</rag-ime-deep-search-context>', role: 'user', createdAtMs: 0 },
        ],
      },
      'agent.session.forks.create': forkCreateRoute,
      'agent.sessions.create': { ok: true },
      'agent.session.rename': { ok: true },
      'agent.session.compact': { ok: true },
      'agent.session.abort': abortRoute,
      'agent.session.mode.update': { ok: true },
      'agent.session.model.select': { ok: true },
      'agent.session.thinking.select': { ok: true },
      'agent.approval.decide': approvalRoute,
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

function workflowRouteFixture() {
  return {
    schemaVersion: 'rag-ime.agent-workflow-state.v1',
    ok: true,
    sessionId: 'session-preview',
    plan: {
      schemaVersion: 'rag-ime.agent-plan.v2',
      id: 'plan:preview',
      sessionId: 'session-preview',
      revision: 4,
      title: '控制中心迁移',
      status: 'executing',
      actor: 'agent',
      note: '',
      updatedAtMs: Date.now(),
      editable: false,
      actApproved: true,
      items: [
        { id: 'plan:item:1', title: '核对现状', status: 'completed', position: 1, sequence: 1, updatedAtMs: Date.now() },
        { id: 'plan:item:2', title: '接入前端', status: 'in_progress', position: 2, sequence: 2, updatedAtMs: Date.now() },
        { id: 'plan:item:3', title: '运行验收', status: 'pending', position: 3, sequence: 3, updatedAtMs: Date.now() },
      ],
      counts: { total: 3, pending: 1, inProgress: 1, completed: 1 },
    },
    goal: {
      schemaVersion: 'rag-ime.agent-goal.v1',
      sessionId: 'session-preview',
      configured: false,
      goalId: '',
      revision: 0,
      objective: '',
      status: 'cleared',
      budget: { tokenLimit: null, timeLimitMs: null },
      usage: { tokens: 0, elapsedMs: 0 },
      remaining: { tokens: null, timeMs: null },
      budgetExceeded: false,
      completionAudit: null,
      updatedAtMs: 0,
    },
    actGate: { allowed: true, reason: 'approved', message: 'Plan 已批准，可以执行。' },
  };
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
