import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AgentActivityProjection } from '@/contracts/agent-reducer';
import { ActivitySummary, PublicActivityFeed } from './ActivitySummary';
import { inspectableRawResultText } from './public-tool-result';

afterEach(() => {
  cleanup();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
});

describe('Agent tool activity details', () => {
  it('bounds an inspectable receipt before it can be copied or rendered', () => {
    const text = inspectableRawResultText({
      rows: Array.from({ length: 500 }, (_, index) => ({
        index,
        value: `large-result-${index}-${'X'.repeat(200)}`,
      })),
    }, 'json');

    expect(text.length).toBeLessThanOrEqual(24_000);
    expect(text).toContain('large-result-0');
    expect(text).toContain('[结果已截断');
    expect(text).not.toContain('large-result-499');
  });

  it('renders an interleaved tool group as an inline disclosure with the real result', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-inline-result',
      toolName: 'overview',
      result: { details: { ok: true, operation: 'status', result: { summary: '运行状态已读取' } } },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline');
    expect(group).not.toBeNull();
    expect(group).not.toHaveAttribute('open');
    const summary = group!.querySelector('summary')!;
    expect(within(summary).getByText('1 项操作')).toBeInTheDocument();
    expect(within(summary).getByText('运行状态已读取')).toBeInTheDocument();
    expect(within(summary).getByText('完成')).toBeInTheDocument();
    expect(summary.querySelector('.agent-activity__inline-icon')).toBeInTheDocument();
    expect(summary.querySelector('.agent-activity__status')).not.toBeInTheDocument();
    expect(group!.querySelector('.agent-activity-row')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '操作记录' })).not.toBeInTheDocument();

    fireEvent.click(summary);
    expect(group).toHaveAttribute('open');
    const details = within(group!).getByRole('region', { name: '操作与思考过程' });
    expect(details).toHaveAttribute('data-bounded-scroll', 'true');
    expect(details).toHaveAttribute('tabindex', '0');
    const row = details.querySelector<HTMLDetailsElement>('.agent-activity-row');
    expect(row).not.toHaveAttribute('open');
    fireEvent.click(row!.querySelector('summary')!);
    expect(row).toHaveAttribute('open');
    expect(details).toHaveTextContent('运行状态已读取');
  });

  it('toggles a controlled disclosure by Enter and Space without native page activation', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-keyboard-disclosure',
      toolName: 'overview',
      result: { details: { result: { summary: '运行状态已读取' } } },
    });
    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    const summary = group.querySelector<HTMLElement>('summary')!;

    fireEvent.keyDown(summary, { key: 'Enter' });
    expect(group).toHaveAttribute('open');
    fireEvent.keyDown(summary, { key: ' ' });
    expect(group).not.toHaveAttribute('open');
  });

  it('preserves the scroll anchor and summary focus when an inline group changes height', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-anchored-disclosure',
      toolName: 'overview',
      result: { details: { result: { summary: '运行状态已读取' } } },
    });
    const { container } = render(
      <div data-testid="timeline-scrollport" style={{ maxHeight: 300, overflowY: 'auto' }}>
        <ActivitySummary activities={[activity]} inline />
      </div>,
    );
    const scrollport = screen.getByTestId('timeline-scrollport');
    Object.defineProperty(scrollport, 'scrollHeight', { configurable: true, value: 1_000 });
    Object.defineProperty(scrollport, 'clientHeight', { configurable: true, value: 300 });
    scrollport.scrollTop = 320;
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    const summary = group.querySelector<HTMLElement>('summary')!;
    expect(group).not.toHaveAttribute('open');
    vi.spyOn(summary, 'getBoundingClientRect').mockImplementation(() => {
      const top = group.hasAttribute('open')
        ? 130 + (320 - scrollport.scrollTop)
        : 180;
      return {
        bottom: top + 42,
        height: 42,
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

    expect(group).toHaveAttribute('open');
    expect(summary).toHaveAttribute('aria-expanded', 'true');
    expect(scrollport.scrollTop).toBe(270);
    expect(document.activeElement).toBe(summary);
  });

  it('expands a large tool group downward below its summary without a screen dialog', () => {
    const activities = Array.from({ length: 34 }, (_, index) => toolActivity(
      'tool_finished',
      index === 17 ? 'failed' : 'completed',
      {
        toolCallId: `call-large-${index}`,
        toolName: index === 17 ? 'workspace_edit' : 'workspace_read',
        result: { details: index === 17
          ? { error: '当前 Todo 尚未进入执行中，写入未执行' }
          : { result: { summary: `已读取文件 ${index + 1}` } } },
      },
    ));
    const { container } = render(<ActivitySummary activities={activities} inline />);
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;

    expect(group).toHaveAttribute('open');
    expect(screen.queryByRole('dialog', { name: '操作记录' })).not.toBeInTheDocument();
    expect(group).toHaveAttribute('data-state', 'mixed');
    expect(group).toHaveTextContent('33 已完成 · 1 未完成');
    const scrollRegion = within(group).getByRole('region', { name: '操作与思考过程' });
    expect(scrollRegion).toHaveAttribute('data-bounded-scroll', 'true');
    expect(scrollRegion.querySelectorAll('.agent-activity-row')).toHaveLength(34);
  });

  it('keeps a live inline group open in its bounded scroll region while status updates', () => {
    const activity = toolActivity('tool_progress', 'running', {
      toolCallId: 'call-running-disclosure',
      toolName: 'workspace_search',
      partialResult: { details: { summary: '正在检索项目内容' } },
    });
    const { container, rerender } = render(<ActivitySummary activities={[activity]} inline />);
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;

    expect(group).toHaveAttribute('open');
    expect(group.querySelector('.agent-activity-row')).toBeInTheDocument();

    rerender(
      <ActivitySummary
        activities={[{ ...activity, updatedAtMs: activity.updatedAtMs + 1_000 }]}
        inline
      />,
    );
    expect(group).toHaveAttribute('open');
    expect(within(group).getByRole('region', { name: '操作与思考过程' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '正在处理' })).not.toBeInTheDocument();

    rerender(
      <ActivitySummary
        activities={[{ ...activity, status: 'completed', updatedAtMs: activity.updatedAtMs + 2_000 }]}
        inline
      />,
    );
    expect(group).toHaveAttribute('open');
    expect(within(group).getByRole('region', { name: '操作与思考过程' })).toBeInTheDocument();
  });

  it('opens a failed inline group so its public error is immediately viewable', () => {
    const activity = toolActivity('tool_finished', 'failed', {
      toolCallId: 'call-failed-disclosure',
      toolName: 'workspace_search',
      isError: true,
      result: { details: { error: '搜索参数超出允许范围' } },
    });
    const { container, rerender } = render(<ActivitySummary activities={[activity]} inline />);
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    const summary = group.querySelector('summary')!;

    expect(group).toHaveAttribute('open');
    expect(group.querySelector('.agent-activity-row')).toBeInTheDocument();
    expect(summary).toHaveTextContent('搜索参数超出允许范围');
    expect(group).toHaveAttribute('data-state', 'mixed');
    expect(screen.getByLabelText('工具未完成')).toHaveTextContent('搜索参数超出允许范围');
    expect(screen.queryByRole('dialog', { name: '操作记录' })).not.toBeInTheDocument();

    rerender(<ActivitySummary activities={[{ ...activity, updatedAtMs: 3 }]} inline />);
    expect(group).toHaveAttribute('open');
  });

  it('renders an Act Gate refusal as an expected no-op rather than a Tool failure', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-goal-paused',
      toolName: 'edit',
      isError: false,
      governanceBlocked: true,
      summary: '工作区变更未执行：当前 Todo、Goal 或权限状态不允许执行。',
      result: {
        details: {
          ok: false,
          error: 'Act Gate blocked workspace mutation (goal_paused): 当前 Goal 已暂停，恢复后才能继续写入。',
        },
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    expect(group).toHaveTextContent('1 项操作');
    expect(group).toHaveTextContent('工作区变更未执行');
    expect(group).not.toHaveTextContent('失败');
    const dialog = openInlineActivity(container);
    expect(dialog).not.toHaveTextContent('失败原因');
    expect(dialog).not.toHaveTextContent('未成功');
  });

  it('shows the exact safe coding-tool request and meaningful returned lines', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-grep-evidence',
      toolName: 'grep',
      args: {
        path: '[REDACTED_PATH]',
        pattern: 'rime_lexicon_review',
      },
      publicResult: {
        path: '…/project/rag_ime',
        pattern: 'rime_lexicon_review',
        glob: '*.py',
        limit: 100,
        context: 2,
        outputPreview: [
          'rag_ime/agent_tools.py:41:def rime_lexicon_review(...):',
          'tests/test_rime_lexicon_review.py:12:class ReviewTests:',
        ].join('\n'),
        outputTruncated: true,
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const dialog = openInlineActivity(container);
    const row = dialog.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    expect(row.querySelector('summary')).toHaveTextContent('在 …/project/rag_ime 搜索 “rime_lexicon_review”');
    expect(within(row.querySelector('summary')!).getByText('搜索文本', { selector: 'strong' })).toBeInTheDocument();
    fireEvent.click(row.querySelector('summary')!);

    const request = within(row).getByLabelText('工具调用参数');
    expect(request).toHaveTextContent('目标');
    expect(request).toHaveTextContent('…/project/rag_ime');
    expect(request).toHaveTextContent('rime_lexicon_review');
    expect(request).toHaveTextContent('*.py');
    expect(request).toHaveTextContent('100');
    expect(request).toHaveTextContent('2');
    const output = within(row).getByRole('region', { name: '搜索匹配结果' });
    expect(within(request).getByRole('button', { name: '复制参数' })).toBeInTheDocument();
    expect(output).toHaveTextContent('rag_ime/agent_tools.py:41');
    expect(output).toHaveTextContent('tests/test_rime_lexicon_review.py:12');
    expect(output).toHaveTextContent('完整结果仍由本机工具回执保留');
    expect(within(output).getByRole('button', { name: '复制结果' })).toBeInTheDocument();
  });

  it('renders Shell output as a terminal result instead of a generic result fragment', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-shell-renderer',
      toolName: 'workspace_shell',
      publicResult: {
        command: 'pnpm test',
        outputPreview: 'Tests: 12 passed\nDuration: 1.42s',
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const details = openInlineActivity(container);
    const row = details.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    const result = within(row).getByRole('region', { name: '命令输出' });
    expect(result).toHaveAttribute('data-result-kind', 'terminal');
    expect(result).toHaveTextContent('Tests: 12 passed');
  });

  it('renders a read result as code with its safe file name and language', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-read-renderer',
      toolName: 'workspace_read',
      publicResult: {
        path: 'src/example.ts',
        outputPreview: 'export const ready: boolean = true;',
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const details = openInlineActivity(container);
    const row = details.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    const result = within(row).getByRole('region', { name: '文件内容：src/example.ts' });
    expect(result).toHaveAttribute('data-result-kind', 'code');
    expect(within(result).getByLabelText('src/example.ts 代码内容')).toHaveTextContent('export const ready');
  });

  it('renders search output as individually readable matches', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-search-renderer',
      toolName: 'workspace_search',
      publicResult: {
        pattern: 'AgentTurn',
        outputPreview: [
          'src/AgentTimeline.tsx:520:export function AgentTurn()',
          'src/AgentTimeline.test.tsx:41:describe(\'AgentTurn\')',
        ].join('\n'),
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const details = openInlineActivity(container);
    const row = details.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    const result = within(row).getByRole('region', { name: '搜索匹配结果' });
    expect(result).toHaveAttribute('data-result-kind', 'matches');
    expect(within(result).getAllByRole('listitem')).toHaveLength(2);
    expect(result).toHaveTextContent('AgentTimeline.tsx:520');
  });

  it('keeps the file summary compact while exposing the complete nested receipt', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-list-renderer',
      toolName: 'workspace_list',
      result: {
        details: {
          ok: true,
          operation: 'list',
          result: {
            summary: '已读取 2 个工作区条目',
            entries: [
              { name: 'src', kind: 'directory', sourcePath: '/Users/private/project/src' },
              {
                name: 'README.md',
                kind: 'file',
                content: 'private file body',
                metadata: { cursor: 'page:2', accessToken: 'do-not-render-this-token' },
              },
            ],
          },
        },
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const details = openInlineActivity(container);
    const row = details.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    const result = within(row).getByRole('region', { name: '项目文件结果' });
    expect(result).toHaveAttribute('data-result-kind', 'files');
    expect(result).toHaveTextContent('src');
    expect(result).toHaveTextContent('README.md');
    expect(result).not.toHaveTextContent('/Users/private');
    expect(result).not.toHaveTextContent('private file body');

    const raw = within(row).getByLabelText('完整工具返回');
    fireEvent.click(within(raw).getByText('完整返回'));
    expect(raw).toHaveTextContent('/Users/private/project/src');
    expect(raw).toHaveTextContent('private file body');
    expect(raw).toHaveTextContent('page:2');
    expect(raw).toHaveTextContent('[REDACTED_SECRET]');
    expect(raw).not.toHaveTextContent('do-not-render-this-token');
  });

  it('virtualizes a long complete receipt while copying every result line', async () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-long-complete-result',
      toolName: 'custom_report',
      result: {
        rows: Array.from({ length: 320 }, (_, index) => ({
          index,
          value: `complete-result-line-${index}`,
        })),
      },
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const details = openInlineActivity(container);
    const row = details.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    const raw = within(row).getByLabelText('完整工具返回');
    expect(within(raw).queryByLabelText('完整工具返回内容')).not.toBeInTheDocument();
    fireEvent.click(within(raw).getByText('完整返回'));

    const viewport = within(raw).getByRole('region', { name: '完整工具返回内容' });
    expect(viewport).toHaveTextContent('complete-result-line-0');
    expect(viewport).not.toHaveTextContent('complete-result-line-319');
    fireEvent.click(within(raw).getByRole('button', { name: '复制完整返回' }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('complete-result-line-319'),
    ));
  });

  it('renders a file mutation as a change receipt', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-change-renderer',
      toolName: 'workspace_edit',
      publicResult: {
        path: 'src/example.ts',
        additions: 4,
        deletions: 2,
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const details = openInlineActivity(container);
    const row = details.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    const result = within(row).getByRole('region', { name: '文件变更结果' });
    expect(result).toHaveAttribute('data-result-kind', 'change');
    expect(result).toHaveTextContent('src/example.ts');
    expect(result).toHaveTextContent('+4');
    expect(result).toHaveTextContent('−2');
  });

  it('renders browser tabs as safe page cards without URL credentials or page markdown', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-browser-renderer',
      toolName: 'browser',
      result: {
        details: {
          ok: true,
          operation: 'tabs',
          result: {
            summary: '已读取 2 个浏览器标签页',
            items: [
              { title: 'React 文档', url: 'https://react.dev/reference?token=private' },
              { title: 'PAW 本地页', url: 'http://127.0.0.1:5173/agent', markdown: 'private page body' },
            ],
          },
        },
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const details = openInlineActivity(container);
    const row = details.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    const result = within(row).getByRole('region', { name: '浏览器结果' });
    expect(result).toHaveAttribute('data-result-kind', 'browser');
    expect(result).toHaveTextContent('React 文档');
    expect(result).toHaveTextContent('react.dev');
    expect(result).toHaveTextContent('PAW 本地页');
    expect(result).not.toHaveTextContent('token=private');
    expect(result).not.toHaveTextContent('private page body');
  });

  it('bounds long public output and copies exactly the visible safe fragment', async () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-bounded-output',
      toolName: 'grep',
      publicResult: {
        outputPreview: '/Users/private/project/output apiKey=secret-value --token raw-token safe-output-line\n'.repeat(700),
        outputTruncated: false,
      },
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const { container } = render(
      <div data-testid="output-scrollport" style={{ maxHeight: 300, overflowY: 'auto' }}>
        <ActivitySummary activities={[activity]} inline />
      </div>,
    );
    const group = openInlineActivity(container);
    const row = group.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);
    const output = within(row).getByLabelText('工具返回片段');
    const visibleOutput = within(output).getByLabelText('工具返回内容');
    const scrollport = screen.getByTestId('output-scrollport');
    scrollport.scrollTop = 180;

    expect(visibleOutput.textContent?.length).toBeLessThanOrEqual(6_000);
    expect(visibleOutput.textContent?.split('\n')).toHaveLength(40);
    expect(visibleOutput).not.toHaveTextContent('/Users/private');
    expect(visibleOutput).not.toHaveTextContent('secret-value');
    expect(visibleOutput).not.toHaveTextContent('raw-token');
    expect(output).toHaveTextContent('完整结果仍由本机工具回执保留');
    expect(visibleOutput).toHaveTextContent('apiKey=[REDACTED_SECRET]');
    expect(visibleOutput).toHaveAttribute('tabindex', '0');
    fireEvent.click(within(output).getByRole('button', { name: '复制结果' }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(visibleOutput.textContent));
    expect(scrollport.scrollTop).toBe(180);
    expect(within(output).getByRole('button', { name: '已复制结果' })).toBeInTheDocument();
  });

  it('unwraps legacy managed evidence JSON without exposing its internal envelope', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-managed-evidence',
      toolName: 'grep',
      publicResult: {
        outputPreview: JSON.stringify({
          evidenceHandle: 'private-evidence-handle',
          evidenceRequest: {
            path: '/Volumes/private/project/rag_ime',
            pattern: 'todo',
            limit: 40,
          },
          evidenceSummary: 'rag_ime/agent_tools.py:81:def _todo(...):',
          evidenceBytes: 2_048,
          evidenceSha256: 'a'.repeat(64),
        }),
        outputTruncated: true,
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    expect(group).toHaveTextContent('在 rag_ime 搜索 “todo”');
    const dialog = openInlineActivity(container);
    const row = dialog.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    expect(within(row).getByLabelText('工具调用参数')).toHaveTextContent('rag_ime');
    expect(within(row).getByLabelText('工具调用参数')).toHaveTextContent('todo');
    expect(within(row).getByRole('region', { name: '搜索匹配结果' })).toHaveTextContent('agent_tools.py:81');
    expect(container).not.toHaveTextContent('evidenceHandle');
    expect(container).not.toHaveTextContent('private-evidence-handle');
    expect(container).not.toHaveTextContent('evidenceSha256');
  });

  it('keeps the timeline compact and opens full activity details in a dialog', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-compact-dialog',
      toolName: 'overview',
      result: { details: { ok: true, operation: 'status', result: { summary: '运行状态已读取' } } },
    });

    const { container } = render(<ActivitySummary activities={[activity]} />);

    expect(container.querySelector('details.agent-activity')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /查看活动详情：操作记录/ }));
    expect(screen.getByRole('dialog', { name: '操作记录' })).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toHaveTextContent('当前状态');
  });

  it('labels provider turn failures as model service failures instead of tool operations', () => {
    const activity: AgentActivityProjection = {
      id: 'turn-provider-failed',
      turnId: 'turn-provider-failed',
      kind: 'turn_failed',
      status: 'failed',
      summary: '400 Error from provider (Console Go): Upstream request failed',
      payload: { error: '400 Error from provider (Console Go): Upstream request failed' },
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    const { container } = render(<ActivitySummary activities={[activity]} />);

    expect(container).toHaveTextContent('模型服务请求失败');
    expect(container).not.toHaveTextContent('工具操作');
    openActivity(container);
    expect(screen.getByRole('dialog')).toHaveTextContent('模型服务请求失败，请重试或切换模型。');
    expect(screen.queryByText(/Console Go|Upstream request failed/)).not.toBeInTheDocument();
  });

  it('renders the public overview capability result without raw tool material', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-overview-capabilities',
      toolName: 'overview',
      args: {
        op: 'capabilities',
        path: '/Users/private/project',
        apiKey: 'do-not-render',
        reasoning: 'private chain of thought',
      },
      isError: false,
      result: {
        content: [{
          type: 'text',
          text: '{"raw":"this serialized result must not render"}',
        }],
        details: {
          schemaVersion: 'rag-ime.agent-tool-result.v1',
          ok: true,
          tool: 'overview',
          operation: 'capabilities',
          result: {
            summary: '已连接 9 个控制中心领域',
            toolCount: 13,
            tools: [
              { id: 'overview', displayName: '控制中心概览', operations: ['status'] },
              { id: 'input', displayName: '输入法', operations: ['get_settings'] },
              { id: 'voice', displayName: '语音输入', operations: ['status'] },
            ],
            approvalGatedOperations: ['input.apply_settings', 'voice.provider_apply'],
            writePolicy: '写入操作必须经过本机确认并保存回执',
          },
        },
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} />);
    openActivity(container);

    expect(screen.getByText('当前状态')).toBeInTheDocument();
    expect(screen.getAllByText('已连接 9 个控制中心领域')).toHaveLength(2);
    expect(screen.getByText('查看可用能力')).toBeInTheDocument();
    expect(screen.getByText('13 项')).toBeInTheDocument();
    expect(screen.getByText('当前状态、输入法与词库、语音输入')).toBeInTheDocument();
    expect(screen.getByText('2 项操作')).toBeInTheDocument();
    expect(screen.getByText('写入操作必须经过本机确认并保存回执')).toBeInTheDocument();
    expect(container).not.toHaveTextContent('overview');
    expect(container).not.toHaveTextContent('do-not-render');
    expect(container).not.toHaveTextContent('/Users/private/project');
    expect(container).not.toHaveTextContent('private chain of thought');
    expect(container).not.toHaveTextContent('serialized result');
  });

  it('shows bounded status and progress fields while hiding nested metadata', () => {
    const completed = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-overview-status',
      toolName: 'overview',
      result: {
        details: {
          ok: true,
          operation: 'status',
          result: {
            summary: '发现 1 个未就绪组件',
            components: {
              inputMethod: { truncated: true },
              sidecar: { truncated: true },
              predictor: { truncated: true },
            },
            unhealthyComponents: ['predictor'],
            memory: {
              memoryBookCount: 4,
              memoryAtomCount: 21,
              pendingCompileEvents: 2,
            },
          },
        },
      },
    });
    const progress = toolActivity('tool_progress', 'running', {
      toolCallId: 'call-overview-progress',
      toolName: 'overview',
      args: { op: 'status', token: 'hidden-token' },
      partialResult: {
        content: [{ type: 'text', text: 'raw progress content' }],
        details: { summary: '正在读取控制中心状态', metadata: { path: '/Volumes/private/model' } },
      },
    });

    const { container } = render(<ActivitySummary activities={[completed, progress]} />);
    openActivity(container);

    const dialog = screen.getByRole('dialog');
    expect([...dialog.querySelectorAll('.agent-activity-row > summary strong')].map((node) => node.textContent)).toEqual([
      '当前状态',
      '当前状态',
    ]);
    expect(dialog).toHaveTextContent('2 / 3 可用');
    expect(dialog).toHaveTextContent('预测服务');
    expect(dialog).toHaveTextContent('4 条');
    expect(dialog).toHaveTextContent('21 条');
    expect(dialog).toHaveTextContent('2 条');
    expect(dialog).toHaveTextContent('正在读取控制中心状态');
    expect(dialog).toHaveTextContent('进行中');
    expect(container).not.toHaveTextContent('/Volumes/private/model');
    expect(container).not.toHaveTextContent('hidden-token');
    expect(container).not.toHaveTextContent('raw progress content');
  });

  it('renders retained tool checkpoints and the completed duration', () => {
    const activity: AgentActivityProjection = {
      ...toolActivity('tool_finished', 'completed', {
        toolCallId: 'call-progress-history',
        toolName: 'knowledge',
        result: { details: { result: { summary: '知识检索完成' } } },
        progressHistory: [
          { eventId: 'event-1', kind: 'tool_started', status: 'running', summary: '开始检索知识库', createdAtMs: 1_000 },
          { eventId: 'event-2', kind: 'tool_progress', status: 'running', summary: '已找到候选来源', createdAtMs: 2_000 },
          { eventId: 'event-3', kind: 'tool_finished', status: 'completed', summary: '知识检索完成', createdAtMs: 4_500 },
        ],
      }),
      createdAtMs: 1_000,
      updatedAtMs: 4_500,
    };

    const { container } = render(<ActivitySummary activities={[activity]} />);
    openActivity(container);

    const dialog = screen.getByRole('dialog');
    /* Durations are reported in the largest honest unit: raw milliseconds stop
       being readable above a second, and sub-second work still gets ms. */
    expect(dialog).toHaveTextContent('完成 · 3.5 秒');
    expect(dialog).toHaveTextContent('过程记录');
    expect(dialog).toHaveTextContent('+0 ms · 开始检索知识库 · 进行中');
    expect(dialog).toHaveTextContent('+1.0 秒 · 已找到候选来源 · 进行中');
    expect(dialog).toHaveTextContent('+3.5 秒 · 知识检索完成 · 完成');
  });

  it('summarizes document knowledge citations without expanding raw chunks or paths', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-document-knowledge',
      toolName: 'knowledge',
      result: {
        details: {
          ok: true,
          operation: 'search',
          result: {
            summary: '文档知识库返回 2 条引用证据',
            items: [
              {
                fileName: 'acceptance.md',
                content: '不应在时间线详情里展开的文档原文',
                sourcePath: '/Users/private/acceptance.md',
                citation: { startLine: 41, endLine: 57 },
              },
              {
                fileName: 'design.pdf',
                content: '另一段不应展示的原文',
                citation: { page: 3 },
              },
            ],
          },
        },
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} />);
    openActivity(container);

    expect(screen.getByText('检索文档')).toBeInTheDocument();
    expect(screen.getByText('信息来源')).toBeInTheDocument();
    expect(screen.getByText('acceptance.md · 41-57 行')).toBeInTheDocument();
    expect(screen.getByText('design.pdf · 第 3 页')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '打开知识库' })).toHaveAttribute('href', '#/knowledge');
    expect(container).not.toHaveTextContent('不应在时间线详情里展开');
    expect(container).not.toHaveTextContent('/Users/private');
  });

  it('renders safe generic interface entries without dumping their private fields', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-public-structure',
      toolName: 'workspace_list',
      result: {
        details: {
          ok: true,
          operation: 'list',
          result: {
            summary: '已读取 2 个工作区条目',
            entries: [
              { name: 'src', kind: 'directory', itemCount: 12, sourcePath: '/Users/private/project/src', content: 'private file body' },
              { name: 'README.md', kind: 'file' },
            ],
            nextCursor: 'cursor-public-2',
            metadata: { healthy: true, authorization: 'Bearer hidden' },
            content: { state: 'ready', resultCount: 2 },
            apiKey: 'sk-do-not-render',
            reasoning: 'private chain of thought',
          },
        },
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} />);
    openActivity(container);
    const dialog = screen.getByRole('dialog');

    expect(screen.queryByLabelText('工具公开结果')).not.toBeInTheDocument();
    expect(dialog).toHaveTextContent('已读取 2 个工作区条目');
    expect(dialog).not.toHaveTextContent('entries');
    expect(screen.getByRole('region', { name: '项目文件结果' })).toHaveTextContent('README.md');
    expect(screen.getByRole('region', { name: '项目文件结果' })).toHaveTextContent('src');
    expect(dialog).not.toHaveTextContent('cursor-public-2');
    expect(dialog).not.toHaveTextContent('/Users/private');
    expect(dialog).not.toHaveTextContent('private file body');
    expect(dialog).not.toHaveTextContent('sk-do-not-render');
    expect(dialog).not.toHaveTextContent('private chain of thought');
    expect(dialog).not.toHaveTextContent('authorization');
  });

  it('renders a memory book as a semantic expandable preview', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-memory-book',
      toolName: 'memory',
      operation: 'read',
      result: {
        book: {
          title: '输入法与 Agent 上下文',
          summary: '输入缓冲与长期记忆之间的边界。',
          tags: ['输入法', '上下文'],
          memories: [
            {
              type: 'principle',
              text: '单个词不得进入长期上下文。',
              ref: { type: 'memory_atom', id: 'atom:input-boundary' },
            },
            { type: 'decision', text: '闪电联想只读取临时缓冲。' },
          ],
        },
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const dialog = openInlineActivity(container);
    const row = dialog.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    expect(within(row).getByLabelText('《输入法与 Agent 上下文》内容')).toHaveTextContent('输入缓冲与长期记忆之间的边界。');
    expect(row).toHaveTextContent('原则');
    expect(row).toHaveTextContent('单个词不得进入长期上下文。');
    expect(within(row).getByRole('link', { name: /单个词不得进入长期上下文/ })).toHaveAttribute(
      'href',
      '#/memory?layer=atoms&id=atom%3Ainput-boundary',
    );
    expect(row).not.toHaveTextContent('结果摘要');
    expect(row).not.toHaveTextContent('读取内容');
    expect(row).not.toHaveTextContent('"memories"');
  });

  it('uses the stable ref kind before an Atom semantic kind when building memory links', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-memory-atom-ref',
      toolName: 'memory',
      operation: 'search',
      result: {
        summary: '命中 1 条当前事实',
        items: [{
          memoryId: 'atom:completion-latency',
          kind: 'preference',
          text: '输入法首候选延迟需要保持在 50ms 内。',
          ref: {
            referenceKind: 'atom',
            referenceId: 'atom:completion-latency',
          },
        }],
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const dialog = openInlineActivity(container);
    const row = dialog.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    expect(within(row).getByRole('link', { name: /输入法首候选延迟/ })).toHaveAttribute(
      'href',
      '#/memory?layer=atoms&id=atom%3Acompletion-latency',
    );
  });

  it('deep-links memory catalog entries through their stable Book reference', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-memory-catalog-ref',
      toolName: 'memory',
      operation: 'catalog',
      result: {
        summary: '查询到 1 本主题书',
        items: [{
          kind: 'book',
          bookId: 'book:input-method',
          title: '输入法产品与上下文边界',
          ref: {
            kind: 'book',
            id: 'book:input-method',
            referenceKind: 'book',
            referenceId: 'book:input-method',
          },
        }],
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const dialog = openInlineActivity(container);
    const row = dialog.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    expect(within(row).getByRole('link', { name: /输入法产品与上下文边界/ })).toHaveAttribute(
      'href',
      '#/memory?layer=books&id=book%3Ainput-method',
    );
  });

  it('renders governed timeline recall as a deep-linked semantic result', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-memory-timeline',
      toolName: 'memory',
      operation: 'search',
      result: {
        summary: '命中 1 条时间线记忆',
        items: [{
          id: 'activity-timeline:2026-07-18',
          kind: 'daily_timeline',
          text: 'CAS 切换 Codex 账号，然后继续验证记忆界面。',
          ref: { type: 'timeline', id: 'activity-timeline:2026-07-18' },
        }],
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const dialog = openInlineActivity(container);
    const row = dialog.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    expect(within(row).getByLabelText('记忆召回结果内容')).toHaveTextContent('CAS 切换 Codex 账号');
    expect(within(row).getByRole('link', { name: /CAS 切换 Codex 账号/ })).toHaveAttribute(
      'href',
      '#/memory?layer=timelines&id=activity-timeline%3A2026-07-18',
    );
  });

  it('deep-links a governed memory preview to its target Atom and Evidence', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-memory-correct-preview',
      toolName: 'memory',
      operation: 'correct_preview',
      result: {
        summary: '已生成事实更正预览',
        proposalId: 'memory-proposal:1',
        targetId: 'atom:model-size',
        proposedText: '当前使用 100M 自训练输入法模型。',
        evidenceIds: ['message:evidence-1'],
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const dialog = openInlineActivity(container);
    const row = dialog.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    expect(within(row).getByRole('link', { name: /当前使用 100M/ })).toHaveAttribute(
      'href',
      '#/memory?layer=atoms&id=atom%3Amodel-size',
    );
    expect(within(row).getByRole('link', { name: '来源证据 1' })).toHaveAttribute(
      'href',
      '#/memory?layer=evidence&id=message%3Aevidence-1',
    );
    expect(row).toHaveTextContent('尚未应用');
  });

  it('labels and deep-links the pinned Agent Role Book revision', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-role-book-get',
      toolName: 'agent_role_book',
      operation: 'get',
      result: {
        summary: '已读取角色书 revision 3',
        result: {
          revision: {
            revisionId: 'role-book-revision:3',
            revisionNumber: 3,
            status: 'active',
            changeSummary: '补充最近完成的记忆迁移工作。',
          },
          pinned: true,
        },
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const dialog = openInlineActivity(container);
    const row = dialog.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    expect(row).toHaveTextContent('伙伴记忆');
    expect(within(row).getByRole('link', { name: /补充最近完成的记忆迁移工作/ })).toHaveAttribute(
      'href',
      '#/memory?layer=role-books&id=role-book-revision%3A3',
    );
  });

  it('summarizes a Pi write_file result as a safe file name and added line count', () => {
    const writtenContent = Array.from({ length: 335 }, (_, index) => `line ${index + 1}`).join('\n');
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-pi-write-file',
      toolName: 'write_file',
      args: {
        path: '/Users/private/project/src/report.ts',
        content: writtenContent,
      },
      result: {
        content: [{
          type: 'text',
          text: 'Successfully wrote 2908 bytes to /Users/private/project/src/report.ts',
        }],
      },
    });

    const { container } = render(<ActivitySummary activities={[activity]} />);
    openActivity(container);

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent('写入文件');
    expect(dialog).toHaveTextContent('report.ts +335');
    expect(dialog).toHaveTextContent('335 行');
    expect(dialog).toHaveTextContent('+335 / -0');
    expect(dialog).not.toHaveTextContent('/Users/private/project');
    expect(dialog).not.toHaveTextContent('line 1');
    expect(dialog).not.toHaveTextContent('Successfully wrote');
  });

  it('shows the sanitized permission failure and opens the real permission picker entry point', () => {
    const onRequestPermission = vi.fn();
    const activity = toolActivity('tool_finished', 'failed', {
      toolCallId: 'call-permission-failed',
      toolName: 'workspace_shell',
      result: {
        details: {
          ok: false,
          operation: 'run',
          result: {
            error: '工作区不在授权目录内，当前权限不足。',
            sourcePath: '/Users/private/project',
            apiKey: 'sk-do-not-render',
          },
        },
      },
    });

    const { container } = render(
      <ActivitySummary activities={[activity]} onRequestPermission={onRequestPermission} />,
    );
    openActivity(container);

    expect(screen.getByLabelText('工具未完成')).toHaveTextContent('工作区不在授权目录内，当前权限不足。');
    expect(within(screen.getByLabelText('工具未完成')).getByRole('button', { name: '复制错误' })).toBeInTheDocument();
    expect(container).not.toHaveTextContent('/Users/private/project');
    expect(container).not.toHaveTextContent('sk-do-not-render');
    fireEvent.click(screen.getByRole('button', { name: '请求权限' }));
    expect(onRequestPermission).toHaveBeenCalledOnce();
  });

  it('routes an approval-gated failure to the existing bound approval review', () => {
    const onOpenApproval = vi.fn();
    const activity = toolActivity('tool_finished', 'failed', {
      toolCallId: 'call-approval-failed',
      toolName: 'input',
      approvalId: 'approval-bound-1',
      payloadSha256: 'a'.repeat(64),
      preview: { title: '应用输入法设置', summary: '需要本机审批后才能应用。' },
      result: {
        details: {
          ok: false,
          operation: 'apply_settings',
          result: { error: '该操作需要本机审批后继续。' },
        },
      },
    });

    const { container } = render(
      <ActivitySummary activities={[activity]} onOpenApproval={onOpenApproval} />,
    );
    openActivity(container);

    expect(screen.getByLabelText('工具未完成')).toHaveTextContent('该操作需要本机审批后继续。');
    fireEvent.click(screen.getByRole('button', { name: '去审批' }));
    expect(onOpenApproval).toHaveBeenCalledOnce();
    expect(onOpenApproval).toHaveBeenCalledWith(activity);
  });
  it('shows a fail-closed approval inside its owning tool row', () => {
    const activity = toolActivity('tool_finished', 'failed', {
      toolCallId: 'call-owned-approval',
      toolName: 'workspace_shell',
      approvalId: 'approval-owned-1',
      automatic: true,
      result: {
        details: {
          result: {
            summary: '审批未通过，命令没有执行。',
            decisionMode: 'model',
            decisionStatus: 'failed_closed',
            approvalModelDecision: {
              decision: 'deny',
              status: 'failed_closed',
              model: 'openai-codex/gpt-5.6-luna',
              reasonCodes: ['model_timeout'],
              rationaleSummary: '审批模型未能形成可验证裁决。',
            },
          },
        },
      },
    });

    const { container } = render(
      <ActivitySummary activities={[activity]} inline />,
    );
    const details = openInlineActivity(container);
    expect(details.querySelectorAll('.agent-activity-row')).toHaveLength(1);
    const row = details.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);
    expect(row).toHaveTextContent('审批未通过，命令没有执行');
    expect(row).toHaveTextContent('Luna Max 独立判定');
    expect(row).toHaveTextContent('无法形成可验证裁决，已按拒绝处理');
    expect(row).toHaveTextContent('审批模型未能形成可验证裁决');
    expect(row).toHaveTextContent('审批模型超时');
  });

  it('shows the independent Luna approval agent without exposing human controls', () => {
    const onApprovalDecision = vi.fn();
    const activity: AgentActivityProjection = {
      id: 'approval-model-1',
      turnId: 'turn-model-approval',
      kind: 'approval_required',
      status: 'waiting',
      summary: '',
      payload: {
        approvalId: 'approval-model-1',
        payloadSha256: 'b'.repeat(64),
        decisionMode: 'model',
        automatic: true,
        approvalModelDecision: {
          status: 'pending',
          model: 'openai-codex/gpt-5.6-luna',
          receiptId: 'approval-model-decision:1',
        },
      },
      createdAtMs: 1,
      updatedAtMs: 2,
    };

    const { container } = render(
      <ActivitySummary activities={[activity]} inline onApprovalDecision={onApprovalDecision} />,
    );

    expect(container).toHaveTextContent('独立审批 Agent（Luna Max）正在评估这次操作');
    expect(screen.queryByRole('button', { name: '批准' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '拒绝' })).not.toBeInTheDocument();
    const details = openInlineActivity(container);
    const row = details.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);
    expect(row).toHaveTextContent('不读取当前 Agent 的输出或推理');
    expect(row).toHaveTextContent('无需人工操作');
    expect(row).toHaveTextContent('approval-model-decision:1');
    expect(onApprovalDecision).not.toHaveBeenCalled();
  });
  it('shows a fail-closed Luna verdict with rationale, reason, and history', () => {
    const activity: AgentActivityProjection = {
      id: 'approval-model-denied',
      turnId: 'turn-model-denied',
      kind: 'approval_resolved',
      status: 'failed',
      summary: '',
      payload: {
        approvalId: 'approval-model-denied',
        decisionMode: 'model',
        automatic: true,
        approvalModelDecision: {
          decision: 'deny',
          status: 'failed_closed',
          modelProfile: 'openai-codex/gpt-5.6-luna',
          receiptId: 'approval-model-decision:denied',
          reasonCodes: ['model_timeout', 'insufficient_evidence'],
          rationaleSummary: '审批模型未能形成可验证裁决。',
          contextKind: 'session',
          contextId: 'session-1',
          historyEntryCount: 4,
        },
      },
      createdAtMs: 1,
      updatedAtMs: 2,
    };

    const { container } = render(
      <ActivitySummary activities={[activity]} inline />,
    );

    expect(container).toHaveTextContent('独立审批 Agent（Luna Max）无法形成可验证裁决，已拒绝这次操作');
    const details = openInlineActivity(container);
    const row = details.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);
    expect(row).toHaveTextContent('已按拒绝处理');
    expect(row).toHaveTextContent('审批模型未能形成可验证裁决');
    expect(row).toHaveTextContent('审批模型超时');
    expect(row).toHaveTextContent('已参考 4 条同一 Session 审批历史');
    expect(screen.queryByRole('button', { name: '批准' })).not.toBeInTheDocument();
  });

  it('keeps the live preview to one latest thought and one latest Tool update', () => {
    const reasoning: AgentActivityProjection = {
      id: 'reasoning-public-feed',
      turnId: 'turn-public-feed',
      kind: 'reasoning_summary',
      status: 'running',
      summary: '正在核对事件顺序',
      payload: {
        source: 'provider_reasoning_summary',
        items: ['先检查旧路径', '正在核对事件顺序'],
      },
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    const activity = (toolCallId: string, summary: string) => toolActivity('tool_progress', 'running', {
      toolCallId,
      toolName: 'workspace_search',
      summary,
    });
    const { container } = render(<PublicActivityFeed activities={[
      activity('call-public-feed-old', '旧的检索结果'),
      reasoning,
      activity('call-public-feed-latest', '正在核对第二批结果'),
    ]} />);

    expect(screen.getByRole('status', { name: '本轮最新进展' })).toBeInTheDocument();
    expect(container.querySelectorAll('.agent-public-activity__feed > article')).toHaveLength(2);
    expect(screen.getByText('正在核对事件顺序')).toBeInTheDocument();
    expect(screen.getByText('正在核对第二批结果')).toBeInTheDocument();
    expect(screen.queryByText('先检查旧路径')).not.toBeInTheDocument();
    expect(screen.queryByText('旧的检索结果')).not.toBeInTheDocument();
    expect(screen.queryByRole('log', { name: '最新公开思考与工具活动' })).not.toBeInTheDocument();
  });


});

function toolActivity(
  kind: 'tool_started' | 'tool_progress' | 'tool_finished',
  status: AgentActivityProjection['status'],
  payload: Record<string, unknown>,
): AgentActivityProjection {
  return {
    id: String(payload.toolCallId),
    turnId: 'turn-tool-details',
    kind,
    status,
    summary: String(payload.toolName ?? kind),
    payload,
    createdAtMs: 1,
    updatedAtMs: 2,
  };
}

function openInlineActivity(container: HTMLElement): HTMLElement {
  const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline');
  expect(group).not.toBeNull();
  if (!group!.hasAttribute('open')) fireEvent.click(group!.querySelector('summary')!);
  expect(group).toHaveAttribute('open');
  expect(screen.queryByRole('dialog', { name: '操作记录' })).not.toBeInTheDocument();
  const details = group!.querySelector<HTMLElement>('.agent-activity__inline-timeline');
  expect(details).not.toBeNull();
  for (const row of details!.querySelectorAll<HTMLDetailsElement>('.agent-activity-row[open]')) {
    fireEvent.click(row.querySelector('summary')!);
  }
  return details!;
}

function openActivity(container: HTMLElement): void {
  const outer = container.querySelector<HTMLButtonElement>('.agent-activity');
  expect(outer).not.toBeNull();
  fireEvent.click(outer!);
  const dialog = document.querySelector<HTMLElement>('.agent-activity-dialog');
  expect(dialog).not.toBeNull();
  for (const row of dialog!.querySelectorAll<HTMLDetailsElement>('.agent-activity-row')) {
    fireEvent.click(row.querySelector('summary')!);
  }
}
