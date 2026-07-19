import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import type { UiAgentBlock, UiAgentMessage } from '@/contracts/ui-events';
import { agentEventFixture } from '@/test/fixtures/events';
import { useAgentLiveStore } from '../state/live-store';
import {
  AgentTurn,
  agentScrollSeekConfiguration,
  interleavedTurnEntries,
} from './AgentTimeline';
import { AgentPlanCard } from './AgentPlanCard';
import {
  AgentBlock,
  AgentBlocks,
  MarkdownBody,
  partitionStreamingMarkdown,
  partitionStreamingMarkdownFragments,
} from './BlockRenderer';
import { agentRendererPolicy, TRUSTED_AGENT_RENDERERS } from './renderer-registry';

afterEach(() => {
  cleanup();
  useAgentLiveStore.getState().clear('session-failed-snapshot');
  useAgentLiveStore.getState().clear('session-1');
});

describe('Agent chat rendering', () => {
  it('renders the session plan as a compact live checklist', () => {
    const { container, rerender } = render(
      <AgentPlanCard plan={{
        revision: 3,
        items: [
          { id: 'step-1', title: '核对上下文链路', status: 'completed', sequence: 1, updatedAtMs: 1 },
          { id: 'step-2', title: '实现执行清单', status: 'in_progress', sequence: 2, updatedAtMs: 2 },
          { id: 'step-3', title: '运行真实验收', status: 'pending', sequence: 3, updatedAtMs: 3 },
        ],
        counts: { total: 3, pending: 1, inProgress: 1, completed: 1 },
      }} />,
    );

    expect(screen.getByRole('region', { name: '会话执行计划' })).toHaveTextContent('第 2 / 3 步 · 1 项已完成');
    expect(container.querySelectorAll('li[data-state="completed"]')).toHaveLength(1);
    expect(container.querySelectorAll('li[data-state="in_progress"]')).toHaveLength(1);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '33');

    rerender(<AgentPlanCard plan={{
      revision: 4,
      items: [
        { id: 'step-1', title: '核对上下文链路', status: 'completed', sequence: 1, updatedAtMs: 1 },
        { id: 'step-2', title: '实现执行清单', status: 'completed', sequence: 4, updatedAtMs: 4 },
        { id: 'step-3', title: '运行真实验收', status: 'completed', sequence: 5, updatedAtMs: 5 },
      ],
      counts: { total: 3, pending: 0, inProgress: 0, completed: 3 },
    }} />);
    expect(screen.getByRole('region', { name: '会话执行计划' })).toHaveTextContent('3 / 3 项已完成');
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
  });

  it('uses authoritative event sequence before message clock drift', () => {
    const before = { ...assistantMessage('session-1', 'turn-1', '调用前', 120), timelineSequence: 8 };
    const after = { ...assistantMessage('session-1', 'turn-1', '调用后', 80), id: 'turn-1:assistant:segment:10', timelineSequence: 10 };
    const activity = {
      id: 'same-time-tool',
      turnId: 'turn-1',
      kind: 'tool_finished',
      status: 'completed' as const,
      summary: '工具完成',
      payload: { toolName: 'ime_overview' },
      createdAtMs: 100,
      updatedAtMs: 100,
      timelineSequence: 9,
    };

    const entries = interleavedTurnEntries([after, before], [activity]);

    expect(entries.map((entry) => entry.kind)).toEqual(['message', 'activity-group', 'message']);
    expect(entries[0].kind === 'message' ? entries[0].message.blocks[0]?.data.text : '').toBe('调用前');
    expect(entries[2].kind === 'message' ? entries[2].message.blocks[0]?.data.text : '').toBe('调用后');
  });

  it('renders assistant text and tool results in their real event order', () => {
    const sessionId = 'session-1';
    const turnId = 'turn-1';
    useAgentLiveStore.getState().hydrateSnapshot(sessionId, {
      messages: [userMessage(sessionId, turnId)],
      liveEvents: [],
      lastSequence: 0,
      resumeToken: '',
      status: 'idle',
    });
    useAgentLiveStore.getState().applyEvents(sessionId, [
      agentEventFixture(1, 'text_delta', { delta: '我先读取运行状态。', replaceBlock: true }),
      agentEventFixture(2, 'message_completed', {
        message: assistantMessage(sessionId, turnId, '我先读取运行状态。', 10),
      }),
      agentEventFixture(3, 'tool_started', {
        toolCallId: 'call-interleaved-overview',
        toolName: 'ime_overview',
      }),
      agentEventFixture(4, 'tool_finished', {
        toolCallId: 'call-interleaved-overview',
        toolName: 'ime_overview',
        result: { details: { ok: true, operation: 'status', result: { summary: '运行状态正常' } } },
      }),
      agentEventFixture(5, 'text_delta', { delta: '读取完成，当前运行正常。', replaceBlock: true }),
      agentEventFixture(6, 'message_completed', {
        message: assistantMessage(sessionId, turnId, '读取完成，当前运行正常。', 50),
      }),
      agentEventFixture(7, 'turn_completed', { status: 'completed' }),
    ]);

    const { container } = render(
      <AgentTurn sessionId={sessionId} turnId={turnId} onApprovalDecision={() => {}} />,
    );

    const entries = [...container.querySelectorAll<HTMLElement>('[data-timeline-kind]')];
    expect(entries.map((entry) => entry.dataset.timelineKind)).toEqual(['message', 'activity', 'message']);
    expect(entries[0]).toHaveTextContent('我先读取运行状态。');
    expect(entries[1]).toHaveTextContent('运行状态正常');
    expect(entries[2]).toHaveTextContent('读取完成，当前运行正常。');
    expect(entries[0]).not.toHaveTextContent('读取完成');
  });

  it('renders headings, lists, GFM tables, inline code, and fenced code blocks', () => {
    const markdown = [
      '## 验收结论',
      '',
      '正文包含 `ControlTransport`。',
      '',
      '- 保留消息顺序',
      '- 展示结构化结果',
      '',
      '| 项目 | 状态 |',
      '| --- | --- |',
      '| Markdown | 通过 |',
      '| GFM 表格 | 通过 |',
      '',
      '```ts',
      'const ready = true;',
      '```',
      '',
      '```',
      'plain fenced block',
      '```',
      '',
      '```jsonl',
      '{"type":"message","id":"entry-1"}',
      '{"type":"tool_result","ok":true}',
      '```',
    ].join('\n');

    const { container } = render(<TooltipProvider><MarkdownBody text={markdown} /></TooltipProvider>);

    expect(screen.getByRole('heading', { level: 2, name: '验收结论' })).toBeInTheDocument();
    const list = screen.getByRole('list');
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    const table = screen.getByRole('table');
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['项目', '状态']);
    expect(within(table).getByText('GFM 表格')).toBeInTheDocument();
    expect(screen.getByText('ControlTransport').tagName).toBe('CODE');
    expect(container.querySelector('pre[data-language="ts"]')).toHaveTextContent('const ready = true;');
    expect(container.querySelector('pre[data-language="text"]')).toHaveTextContent('plain fenced block');
    const jsonl = container.querySelector('pre[data-language="jsonl"]');
    expect(jsonl).toHaveTextContent('{"type":"message","id":"entry-1"}');
    expect(jsonl?.querySelector('code')).toHaveClass('agent-code-block__content');
    expect(container.querySelectorAll('.agent-code-block')).toHaveLength(3);
  });

  it('anchors the streaming cursor inside the final Markdown text container', () => {
    const blocks: UiAgentBlock[] = [{
      id: 'streaming-text',
      type: 'text',
      status: 'running',
      presentationKind: 'markdown',
      data: { text: '- 保留 `Markdown`\n- 光标紧贴最后一项' },
    }];
    const { container } = render(
      <div className="agent-assistant-message" data-status="streaming">
        <AgentBlocks blocks={blocks} streaming />
        <span aria-label="正在生成" className="agent-streaming-cursor" />
      </div>,
    );

    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).not.toHaveAttribute('data-stream-tail');
    expect(items[1]).toHaveAttribute('data-stream-tail', 'true');
    expect(within(items[0]!).getByText('Markdown').tagName).toBe('CODE');
    expect(items[1]!.querySelector('.agent-streaming-cursor--inline')).toBeInTheDocument();
    expect(container.querySelector('.agent-blocks')).toHaveAttribute('data-has-stream-tail', 'true');
    expect(screen.getByLabelText('正在生成')).toBe(container.querySelector('.agent-blocks')?.nextElementSibling);
  });

  it('moves completed top-level sections out of the active Markdown window', () => {
    const source = [
      '开场说明已经稳定。',
      '',
      '## 已完成阶段',
      '',
      '这一阶段也已经稳定。',
      '',
      '## 正在生成',
      '',
      '当前尾部',
    ].join('\n');

    expect(partitionStreamingMarkdown(source)).toEqual({
      stable: [
        '开场说明已经稳定。',
        '',
        '## 已完成阶段',
        '',
        '这一阶段也已经稳定。',
        '',
        '## 正在生成',
        '',
        '',
      ].join('\n'),
      active: '当前尾部',
    });
  });

  it('does not treat headings inside a fenced block as streaming section boundaries', () => {
    const source = [
      '稳定说明。',
      '',
      '```md',
      '',
      '# 这是代码，不是新章节',
      '```',
    ].join('\n');

    expect(partitionStreamingMarkdown(source)).toEqual({
      stable: '稳定说明。\n\n',
      active: ['```md', '', '# 这是代码，不是新章节', '```'].join('\n'),
    });
  });

  it('keeps earlier streaming Markdown fragments immutable as new paragraphs arrive', () => {
    const first = partitionStreamingMarkdownFragments('第一段。\n\n第二段还在生成');
    const second = partitionStreamingMarkdownFragments('第一段。\n\n第二段完成。\n\n第三段还在生成');

    expect(first).toEqual({
      stableFragments: ['第一段。\n\n'],
      active: '第二段还在生成',
    });
    expect(second).toEqual({
      stableFragments: ['第一段。\n\n', '第二段完成。\n\n'],
      active: '第三段还在生成',
    });
    expect(second.stableFragments[0]).toBe(first.stableFragments[0]);
  });

  it('only renders explicitly trusted non-executable block policies', () => {
    expect(agentRendererPolicy('text')).toMatchObject({
      streaming: 'incremental',
      executableContent: false,
    });
    expect(agentRendererPolicy('image')).toMatchObject({
      isolation: 'managed-receipt',
      executableContent: false,
    });
    expect(agentRendererPolicy('html')).toBeUndefined();
    expect(agentRendererPolicy('script')).toBeUndefined();
    expect(Object.values(TRUSTED_AGENT_RENDERERS).every((item) => !item.executableContent)).toBe(true);
  });

  it('uses measured tombstones only while the user scrolls quickly', () => {
    expect(agentScrollSeekConfiguration.enter(901)).toBe(true);
    expect(agentScrollSeekConfiguration.enter(300)).toBe(false);
    expect(agentScrollSeekConfiguration.exit(119)).toBe(true);
    expect(agentScrollSeekConfiguration.exit(500)).toBe(false);
  });

  it('removes stale segment cursors while a turn is waiting for confirmation', () => {
    const sessionId = 'session-1';
    const turnId = 'turn-1';
    useAgentLiveStore.getState().hydrateSnapshot(sessionId, {
      messages: [userMessage(sessionId, turnId)],
      liveEvents: [],
      lastSequence: 0,
      resumeToken: '',
      status: 'responding',
    });
    useAgentLiveStore.getState().applyEvents(sessionId, [
      agentEventFixture(1, 'text_delta', {
        messageId: 'turn-1:assistant:segment:1',
        blockId: 'turn-1:assistant:segment:1:text',
        delta: '先盘点记忆库。',
        replaceBlock: true,
      }),
      agentEventFixture(2, 'text_delta', {
        messageId: 'turn-1:assistant:segment:2',
        blockId: 'turn-1:assistant:segment:2:text',
        delta: '草案已生成，等待确认。',
        replaceBlock: true,
      }),
      agentEventFixture(3, 'user_input_required', {
        requestId: 'memory-review-1',
        requestKind: 'memory_review',
        title: '审阅记忆草案',
      }),
    ]);

    const { container } = render(
      <AgentTurn sessionId={sessionId} turnId={turnId} onApprovalDecision={() => {}} />,
    );

    expect(container.querySelector('.agent-turn')).toHaveAttribute('data-turn-status', 'waiting');
    expect(container.querySelectorAll('.agent-assistant-message')).toHaveLength(2);
    expect(container.querySelector('.agent-streaming-cursor')).not.toBeInTheDocument();
  });

  it('renders only a same-origin managed image receipt and ignores src/url fallbacks', () => {
    const managedReceipt = '/api/agent/media/media-123/content?sessionId=session-123';
    const { container, rerender } = render(
      <AgentBlock block={imageBlock({
        receiptUrl: managedReceipt,
        src: 'https://example.com/untrusted.png',
        alt: '受控图片',
      })} />,
    );

    const image = screen.getByRole('img', { name: '受控图片' });
    expect(image).toHaveAttribute('src', managedReceipt);
    expect(container.querySelector('.agent-media-block img')).toBe(image);

    rerender(<AgentBlock block={imageBlock({ src: managedReceipt, alt: '伪造回执' })} />);
    expect(screen.queryByRole('img', { name: '伪造回执' })).not.toBeInTheDocument();
    expect(screen.getByText('图片回执不可用')).toBeInTheDocument();

    rerender(<AgentBlock block={imageBlock({ receiptUrl: 'https://example.com/remote.png', alt: '远程回执' })} />);
    expect(screen.queryByRole('img', { name: '远程回执' })).not.toBeInTheDocument();

    rerender(<AgentBlock block={imageBlock({ receiptUrl: '/companions/RagImeCompanionDone.png', alt: '静态资产' })} />);
    expect(screen.queryByRole('img', { name: '静态资产' })).not.toBeInTheDocument();
  });

  it('keeps remote Markdown images blocked', () => {
    const { container } = render(
      <MarkdownBody text="远程图片：![外部图片](https://example.com/not-allowed.png)" />,
    );

    expect(container.querySelector('.agent-markdown img')).not.toBeInTheDocument();
    expect(screen.getByText('外部图片')).toHaveClass('agent-markdown__blocked-media');
  });

  it('shows one public failure notice without repeating the raw provider error', () => {
    const sessionId = 'session-failed-snapshot';
    const turnId = 'turn-failed-snapshot';
    useAgentLiveStore.getState().hydrateSnapshot(sessionId, {
      messages: [userMessage(sessionId, turnId), failedAssistantMessage(sessionId, turnId)],
      liveEvents: [],
      lastSequence: 7,
      resumeToken: `${sessionId}:7`,
      status: 'responding',
    });

    const projection = useAgentLiveStore.getState().projections[sessionId];
    expect(projection.turnsById[turnId]?.status).toBe('failed');

    const { container } = render(
      <AgentTurn
        sessionId={sessionId}
        turnId={turnId}
        onApprovalDecision={() => {}}
      />,
    );

    expect(screen.getByText('本轮失败')).toBeInTheDocument();
    expect(screen.queryByText('正在响应')).not.toBeInTheDocument();
    expect(container.querySelector('.agent-turn')).toHaveAttribute('data-turn-status', 'failed');
    expect(container.querySelectorAll('.agent-user-message')).toHaveLength(1);
    expect(screen.getAllByText('请检查失败状态')).toHaveLength(1);
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getByRole('alert')).toHaveTextContent('当前模型不可用，请切换模型后重试');
    expect(screen.queryByText(/not supported by any configured account/i)).not.toBeInTheDocument();
    expect(container.querySelectorAll('.agent-inline-notice[data-tone="danger"]')).toHaveLength(0);
  });
});

function imageBlock(data: Record<string, unknown>): UiAgentBlock {
  return {
    id: 'image-block',
    type: 'image',
    status: 'completed',
    presentationKind: 'image',
    data,
  };
}

function failedAssistantMessage(sessionId: string, turnId: string): UiAgentMessage {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id: 'failed-assistant-message',
    sessionId,
    turnId,
    role: 'assistant',
    status: 'failed',
    blocks: [{
      id: 'failed-assistant-error',
      type: 'error',
      status: 'failed',
      presentationKind: 'error',
      data: { message: '404 Model "gpt-5.6-luna" is not supported by any configured account in this group' },
    }],
    attachments: [],
    citations: [],
    createdAtMs: 1,
    completedAtMs: 2,
  };
}

function userMessage(sessionId: string, turnId: string): UiAgentMessage {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id: 'failed-turn-user-message',
    sessionId,
    turnId,
    role: 'user',
    status: 'completed',
    blocks: [{
      id: 'failed-turn-user-text',
      type: 'text',
      status: 'completed',
      presentationKind: 'markdown',
      data: { text: '请检查失败状态' },
    }],
    attachments: [],
    citations: [],
    createdAtMs: 0,
    completedAtMs: 1,
  };
}

function assistantMessage(sessionId: string, turnId: string, value: string, createdAtMs: number): UiAgentMessage {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id: `${turnId}:assistant`,
    sessionId,
    turnId,
    role: 'assistant',
    status: 'completed',
    blocks: [{
      id: `${turnId}:assistant:text`,
      type: 'text',
      status: 'completed',
      presentationKind: 'markdown',
      data: { text: value },
    }],
    attachments: [],
    citations: [],
    createdAtMs,
    completedAtMs: createdAtMs,
  };
}
