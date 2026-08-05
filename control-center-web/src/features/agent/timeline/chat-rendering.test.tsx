import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { UiAgentBlock, UiAgentMessage } from '@/contracts/ui-events';
import { agentEventFixture } from '@/test/fixtures/events';
import { StubControlTransport } from '@/test/stub-control-transport';
import { useAgentLiveStore } from '../state/live-store';
import {
  AgentTurn,
  agentScrollSeekConfiguration,
  interleavedTurnEntries,
} from './AgentTimeline';
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

  it('uses authoritative event sequence before message clock drift', () => {
    const before = { ...assistantMessage('session-1', 'turn-1', '调用前', 120), timelineSequence: 8 };
    const after = { ...assistantMessage('session-1', 'turn-1', '调用后', 80), id: 'turn-1:assistant:segment:10', timelineSequence: 10 };
    const activity = {
      id: 'same-time-tool',
      turnId: 'turn-1',
      kind: 'tool_finished',
      status: 'completed' as const,
      summary: '工具完成',
      payload: { toolName: 'overview' },
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
        toolName: 'overview',
      }),
      agentEventFixture(4, 'tool_finished', {
        toolCallId: 'call-interleaved-overview',
        toolName: 'overview',
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

  it('renders a terminal provider failure once with one recovery action set', () => {
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
      agentEventFixture(1, 'turn_failed', {
        error: '400 Error from provider (Console Go): Upstream request failed',
      }),
    ]);

    const { container } = render(
      <AgentTurn
        sessionId={sessionId}
        turnId={turnId}
        modelSelectionAvailable
        onApprovalDecision={() => {}}
        onRetryTurn={() => true}
        onSwitchModel={() => {}}
      />,
    );

    expect(screen.getAllByText('本轮未完成')).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: '重试本轮' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: '切换模型' })).toHaveLength(1);
    expect(container.querySelectorAll('[data-timeline-kind="activity"]')).toHaveLength(0);
    expect(container).not.toHaveTextContent('操作记录');
  });

  it('aggregates Provider usage once after the whole Tool Loop settles', () => {
    const sessionId = 'session-1';
    const turnId = 'turn-1';
    useAgentLiveStore.getState().hydrateSnapshot(sessionId, {
      messages: [userMessage(sessionId, turnId)],
      liveEvents: [],
      lastSequence: 0,
      resumeToken: '',
      status: 'idle',
    });
    const first = {
      ...assistantMessage(sessionId, turnId, '先检查工具。', 10),
      id: 'turn-1:assistant:provider:1',
      provider: 'openai-codex',
      model: 'gpt-5.6-luna',
      usage: { input: 100, output: 10, cacheRead: 50, cacheWrite: 0, totalTokens: 160 },
    };
    const second = {
      ...assistantMessage(sessionId, turnId, '检查完成。', 20),
      id: 'turn-1:assistant:provider:2',
      provider: 'openai-codex',
      model: 'gpt-5.6-luna',
      usage: { input: 200, output: 20, cacheRead: 100, cacheWrite: 10, totalTokens: 330 },
    };
    useAgentLiveStore.getState().applyEvents(sessionId, [
      agentEventFixture(1, 'message_completed', { message: first }),
      agentEventFixture(2, 'tool_finished', {
        toolCallId: 'usage-tool',
        toolName: 'overview',
        result: { details: { ok: true, operation: 'status', result: { summary: '状态已读取' } } },
      }),
      agentEventFixture(3, 'message_completed', { message: second }),
    ]);

    const view = render(
      <AgentTurn sessionId={sessionId} turnId={turnId} onApprovalDecision={() => {}} />,
    );
    expect(screen.queryByLabelText('本轮模型与 Token 用量')).not.toBeInTheDocument();

    act(() => useAgentLiveStore.getState().applyEvents(sessionId, [
      agentEventFixture(4, 'turn_completed', { status: 'completed' }),
    ]));
    view.rerender(
      <AgentTurn sessionId={sessionId} turnId={turnId} onApprovalDecision={() => {}} />,
    );

    const usage = screen.getByLabelText('本轮模型与 Token 用量');
    expect(screen.getAllByLabelText('本轮模型与 Token 用量')).toHaveLength(1);
    expect(usage).toHaveTextContent('gpt-5.6-luna');
    expect(usage).toHaveTextContent('openai-codex');
    expect(usage).toHaveTextContent('输入 460');
    expect(usage).toHaveTextContent('输出 30');
    expect(usage).toHaveTextContent('缓存 33%');
  });

  it('shows provider reasoning summaries and the live Agent state in the timeline', () => {
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
      agentEventFixture(1, 'reasoning_summary', {
        requestId: 'reasoning:turn-1:0',
        summary: '正在分析问题与下一步',
        items: [],
        source: 'runtime_status',
        state: 'running',
      }),
    ]);

    const view = render(
      <AgentTurn sessionId={sessionId} turnId={turnId} onApprovalDecision={() => {}} />,
    );

    expect(screen.queryByRole('button', { name: /查看 Agent 思考摘要/ })).not.toBeInTheDocument();
    expect(screen.queryByText('正在分析问题与下一步')).not.toBeInTheDocument();
    expect(document.querySelector('details.agent-activity--inline')).not.toBeInTheDocument();

    act(() => useAgentLiveStore.getState().applyEvents(sessionId, [
      agentEventFixture(2, 'reasoning_summary', {
        requestId: 'reasoning:turn-1:0',
        summary: 'Implementing durable history reconstruction',
        items: [
          'Analyzing session message discrepancies',
          'Implementing durable history reconstruction',
        ],
        source: 'provider_reasoning_summary',
        state: 'completed',
      }),
      agentEventFixture(3, 'turn_completed', { status: 'completed' }),
    ]));
    view.rerender(
      <AgentTurn sessionId={sessionId} turnId={turnId} onApprovalDecision={() => {}} />,
    );

    const summary = screen.getByRole('button', { name: /查看 Agent 思考摘要/ });
    expect(summary).toHaveTextContent('思考摘要');
    expect(summary).toHaveTextContent('Implementing durable history reconstruction');
    expect(summary).not.toHaveTextContent('Analyzing session message discrepancies');
    fireEvent.click(summary);
    const reasoningDialog = screen.getByRole('dialog', { name: '思考摘要' });
    expect(reasoningDialog).toHaveTextContent('Analyzing session message discrepancies');
    expect(reasoningDialog).toHaveTextContent('Implementing durable history reconstruction');
    expect(reasoningDialog).not.toHaveTextContent('provider_reasoning_summary');
  });

  it('keeps reasoning outside Tool counts and expanded Tool rows', () => {
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
      agentEventFixture(1, 'reasoning_summary', {
        requestId: 'reasoning:separate',
        summary: '先分析代码路径',
        items: ['先分析代码路径'],
        source: 'provider_reasoning_summary',
        state: 'completed',
      }),
      agentEventFixture(2, 'tool_started', {
        toolCallId: 'one-real-tool',
        toolName: 'grep',
        args: { pattern: 'AgentTurn', path: 'control-center-web' },
      }),
      agentEventFixture(3, 'tool_finished', {
        toolCallId: 'one-real-tool',
        toolName: 'grep',
        publicResult: {
          pattern: 'AgentTurn',
          path: 'control-center-web',
          outputPreview: 'AgentTimeline.tsx:342:export function AgentTurn',
        },
      }),
      agentEventFixture(4, 'turn_completed', { status: 'completed' }),
    ]);

    const { container } = render(
      <AgentTurn sessionId={sessionId} turnId={turnId} onApprovalDecision={() => {}} />,
    );

    expect(screen.getByRole('button', { name: /查看 Agent 思考摘要/ })).toHaveTextContent('先分析代码路径');
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    expect(group.querySelector('summary')).toHaveTextContent('1 项操作');
    fireEvent.click(group.querySelector('summary')!);
    expect(group).toHaveAttribute('open');
    expect(screen.queryByRole('dialog', { name: '操作记录' })).not.toBeInTheDocument();
    const details = within(group).getByLabelText('操作记录详情');
    expect(details.querySelectorAll('.agent-activity-row')).toHaveLength(1);
    expect(details).not.toHaveTextContent('处理说明');
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

  it('renders inline unified diffs and lets the user switch to a split view', () => {
    const diff = [
      'diff --git a/src/runtime.ts b/src/runtime.ts',
      'index 1111111..2222222 100644',
      '--- a/src/runtime.ts',
      '+++ b/src/runtime.ts',
      '@@ -1,2 +1,2 @@',
      '-const state = "queued";',
      '+const state = "running";',
      ' export { state };',
    ].join('\n');
    const { container } = render(
      <TooltipProvider>
        <AgentBlock block={{
          id: 'diff-1',
          type: 'diff',
          status: 'completed',
          presentationKind: 'diff.v1',
          data: { fileName: 'src/runtime.ts', diff },
        }} />
      </TooltipProvider>,
    );

    expect(container.querySelector('.agent-inline-diff')).toHaveAttribute('open');
    expect(screen.getAllByText('src/runtime.ts')).toHaveLength(2);
    expect(container.querySelector('tr[data-kind="remove"]')).toHaveTextContent('const state = "queued";');
    expect(container.querySelector('tr[data-kind="add"]')).toHaveTextContent('const state = "running";');

    fireEvent.click(screen.getByRole('radio', { name: /并排/ }));
    expect(container.querySelectorAll('.agent-diff-split')).toHaveLength(4);
  });

  it('renders hunk-only diffs with the trusted block file name', () => {
    const { container } = render(
      <TooltipProvider>
        <AgentBlock block={{
          id: 'diff-hunk-only',
          type: 'diff',
          status: 'completed',
          presentationKind: 'diff.v1',
          data: {
            fileName: 'src/state/live-store.ts',
            diff: [
              '@@ -12,2 +12,2 @@ export function commit(events) {',
              '-  set(next);',
              '+  set((state) => reduceBatch(state, events));',
            ].join('\n'),
          },
        }} />
      </TooltipProvider>,
    );

    expect(container.querySelector('.agent-diff-file')).toBeInTheDocument();
    expect(screen.getAllByText('src/state/live-store.ts')).toHaveLength(2);
    expect(container.querySelector('tr[data-kind="remove"]')).toHaveTextContent('set(next)');
    expect(container.querySelector('tr[data-kind="add"]')).toHaveTextContent('reduceBatch');
  });

  it('folds a completed long Markdown reply without hiding its readable prefix', () => {
    const markdown = Array.from(
      { length: 52 },
      (_, index) => `第 ${index + 1} 段仍可按需查看。`,
    ).join('\n\n');
    const { container } = render(<MarkdownBody text={markdown} />);

    expect(container.querySelector('.agent-markdown')).toHaveAttribute('data-collapsed', 'true');
    expect(screen.getByText('第 1 段仍可按需查看。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /展开全文/ }));
    expect(container.querySelector('.agent-markdown')).not.toHaveAttribute('data-collapsed');
    expect(screen.getByRole('button', { name: '收起长回复' })).toBeInTheDocument();
  });

  it('renders the typed rich block allowlist without executing untrusted markup or links', () => {
    const blocks: UiAgentBlock[] = [
      { id: 'card', type: 'card', status: 'completed', presentationKind: 'card.v1', data: { title: '发布检查', tone: 'success', bodyMarkdown: '[安全链接](https://example.com) <img src=x onerror=alert(1)> [危险](javascript:alert(1))', fields: [{ label: '测试', value: '通过' }] } },
      { id: 'checklist', type: 'checklist', status: 'completed', presentationKind: 'checklist.v1', data: { title: '验收项', items: [{ id: 'one', text: '类型检查', checked: true }, { id: 'two', text: '移动端检查' }] } },
      { id: 'table', type: 'table', status: 'completed', presentationKind: 'table.v1', data: { title: '结果表', columns: ['项目', '状态'], rows: [['Room Post', '通过']] } },
      { id: 'table-inferred', type: 'table', status: 'completed', presentationKind: 'table.v1', data: { title: '协作分工', rows: [{ partner: '澄·远', work: '实现命令入口' }, { partner: '澄·初', work: '独立复核' }] } },
      { id: 'artifact', type: 'artifact', status: 'completed', presentationKind: 'artifact.v1', data: { title: '审计报告', summary: '已持久化', url: 'javascript:alert(1)' } },
      { id: 'reference', type: 'reference', status: 'completed', presentationKind: 'reference.v1', data: { title: '需求原文', url: 'javascript:alert(1)', excerpt: '原始需求保持不变' } },
      { id: 'reference-aliases', type: 'reference', status: 'completed', presentationKind: 'reference.v1', data: { name: '项目说明', uri: 'https://example.com/docs', snippet: '包含命令使用方式' } },
      { id: 'artifact-protocol-relative', type: 'artifact', status: 'completed', presentationKind: 'artifact.v1', data: { title: '协议相对地址', url: '//evil.example/file' } },
      { id: 'reference-backslash', type: 'reference', status: 'completed', presentationKind: 'reference.v1', data: { title: '反斜杠地址', url: '/\\evil.example', excerpt: '不可点击' } },
      { id: 'status', type: 'status', status: 'completed', presentationKind: 'status.v1', data: { title: 'Runtime', state: 'completed', summary: '全部收束' } },
    ];

    const { container } = render(<TooltipProvider><AgentBlocks blocks={blocks} /></TooltipProvider>);

    expect(screen.getByRole('region', { name: '发布检查' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /安全链接/ })).toHaveAttribute('href', 'https://example.com/');
    expect(screen.getByText('危险').closest('a')).toBeNull();
    expect(container.querySelector('img[src="x"]')).toBeNull();
    expect(container.querySelector('script')).toBeNull();
    expect(screen.getByText('类型检查')).toBeInTheDocument();
    expect(screen.getAllByRole('table')[0]).toHaveTextContent('Room Post通过');
    expect(screen.getByText('协作分工').closest('details')).toHaveTextContent('澄·远实现命令入口');
    expect(screen.getByText('项目说明').closest('a')).toHaveAttribute('href', 'https://example.com/docs');
    expect(screen.getByText('包含命令使用方式')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '打开产物回执' })).not.toBeInTheDocument();
    expect(screen.getByText('原始需求保持不变').closest('a')).toBeNull();
    expect(screen.getByText('协议相对地址').closest('a')).toBeNull();
    expect(screen.getByText('不可点击').closest('a')).toBeNull();
    expect(screen.getByRole('region', { name: 'Runtime' })).toHaveTextContent('全部收束');
  });

  it('keeps a structured Tool disclosure anchored and focused when opened', () => {
    const block: UiAgentBlock = {
      id: 'tool-result-anchor',
      type: 'tool_result',
      status: 'completed',
      presentationKind: 'tool_result.v1',
      data: {
        toolName: 'overview',
        status: 'completed',
        summary: '运行状态已读取',
      },
    };
    const { container } = render(
      <div data-testid="structured-tool-scrollport" style={{ maxHeight: 240, overflowY: 'auto' }}>
        <AgentBlock block={block} />
      </div>,
    );
    const scrollport = screen.getByTestId('structured-tool-scrollport');
    Object.defineProperty(scrollport, 'scrollHeight', { configurable: true, value: 800 });
    Object.defineProperty(scrollport, 'clientHeight', { configurable: true, value: 240 });
    scrollport.scrollTop = 220;
    const details = container.querySelector<HTMLDetailsElement>('details.agent-tool-activity')!;
    const summary = details.querySelector<HTMLElement>('summary')!;
    vi.spyOn(summary, 'getBoundingClientRect').mockImplementation(() => {
      const top = details.hasAttribute('open')
        ? 96 + (220 - scrollport.scrollTop)
        : 132;
      return {
        bottom: top + 38,
        height: 38,
        left: 0,
        right: 600,
        top,
        width: 600,
        x: 0,
        y: top,
        toJSON: () => ({}),
      };
    });

    summary.focus();
    fireEvent.click(summary);

    expect(details).toHaveAttribute('open');
    expect(summary).toHaveAttribute('aria-expanded', 'true');
    expect(scrollport.scrollTop).toBe(184);
    expect(document.activeElement).toBe(summary);
  });

  it('keeps partial JSON as streaming text, collapses large code, and degrades unknown blocks readably', () => {
    const partial = '{"type":"card","data":{"title":"还没结束"';
    const blocks: UiAgentBlock[] = [
      { id: 'stream', type: 'text', status: 'running', presentationKind: 'markdown', data: { text: partial } },
      { id: 'large-code', type: 'code', status: 'completed', presentationKind: 'code', data: { fileName: 'worker.log', language: 'text', code: Array.from({ length: 40 }, (_, index) => `line ${index + 1}`).join('\n') } },
      { id: 'future', type: 'unknown', rawType: 'timeline_chart', status: 'completed', presentationKind: 'timeline.v2', summary: '未来时间线', data: { title: '不应从任意 data 展示' } },
    ];

    const { container } = render(<TooltipProvider><AgentBlocks blocks={blocks} streaming /></TooltipProvider>);

    expect(container.querySelectorAll('.agent-rich-card')).toHaveLength(0);
    expect(screen.getByText(partial)).toBeInTheDocument();
    const codeDetails = container.querySelector('details.agent-code-collapse');
    expect(codeDetails).not.toHaveAttribute('open');
    expect(codeDetails).toHaveTextContent('worker.log40 行');
    expect(screen.getByText(/暂不支持的内容 · timeline_chart/)).toBeInTheDocument();
    expect(screen.getByText('未来时间线')).toBeInTheDocument();
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
    expect(agentRendererPolicy('diff')?.Renderer).toBeTypeOf('function');
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

    rerender(<AgentBlock block={imageBlock({ receiptUrl: '/companions/personas/companion-present-v9.webp', alt: '静态资产' })} />);
    expect(screen.queryByRole('img', { name: '静态资产' })).not.toBeInTheDocument();
  });

  it('resolves managed conversation images through the native media origin', () => {
    const managedReceipt = '/api/agent/media/media_native_fixture_01/content?sessionId=session:native-1';
    render(
      <ControlTransportProvider transport={new StubControlTransport('native', {})}>
        <AgentBlock block={imageBlock({ receiptUrl: managedReceipt, alt: '原始对话图片' })} />
      </ControlTransportProvider>,
    );

    const image = screen.getByRole('img', { name: '原始对话图片' });
    expect(image).toHaveAttribute(
      'src',
      'http://127.0.0.1:8766/api/agent/media/media_native_fixture_01/content?sessionId=session%3Anative-1',
    );
    fireEvent.error(image);
    expect(screen.queryByRole('img', { name: '原始对话图片' })).not.toBeInTheDocument();
    expect(screen.getByText('图片无法读取')).toBeInTheDocument();
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
