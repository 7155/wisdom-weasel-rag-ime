import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AgentActivityProjection } from '@/contracts/agent-reducer';
import { ActivitySummary } from './ActivitySummary';

afterEach(cleanup);

describe('Agent tool activity details', () => {
  it('renders an interleaved tool group as an inline disclosure with the real result', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-inline-result',
      toolName: 'ime_overview',
      result: { details: { ok: true, operation: 'status', result: { summary: '运行状态已读取' } } },
    });

    const { container } = render(<ActivitySummary activities={[activity]} inline />);
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline');
    expect(group).not.toBeNull();
    expect(group).not.toHaveAttribute('open');
    const summary = group!.querySelector('summary')!;
    expect(within(summary).getByText('已完成 1 项操作')).toBeInTheDocument();
    expect(within(summary).getByText('运行状态已读取')).toBeInTheDocument();
    expect(within(summary).getByText('完成')).toBeInTheDocument();
    expect(summary.querySelector('.agent-activity__inline-icon')).toBeInTheDocument();
    expect(summary.querySelector('.agent-activity__status')).not.toBeInTheDocument();
    expect(group!.querySelector('.agent-activity-row')).not.toBeInTheDocument();

    fireEvent.click(summary);
    expect(group).toHaveAttribute('open');
    const row = group!.querySelector<HTMLDetailsElement>('.agent-activity-row');
    fireEvent.click(row!.querySelector('summary')!);
    expect(row).toHaveAttribute('open');
    expect(group).toHaveTextContent('运行状态已读取');
  });

  it('lets a running inline group stay closed while its status keeps updating', () => {
    const activity = toolActivity('tool_progress', 'running', {
      toolCallId: 'call-running-disclosure',
      toolName: 'workspace_search',
      partialResult: { details: { summary: '正在检索项目内容' } },
    });
    const { container, rerender } = render(<ActivitySummary activities={[activity]} inline />);
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;

    expect(group).toHaveAttribute('open');
    fireEvent.click(group.querySelector('summary')!);
    expect(group).not.toHaveAttribute('open');
    expect(group.querySelector('.agent-activity-row')).not.toBeInTheDocument();

    rerender(
      <ActivitySummary
        activities={[{ ...activity, updatedAtMs: activity.updatedAtMs + 1_000 }]}
        inline
      />,
    );
    expect(group).not.toHaveAttribute('open');
    expect(group.querySelector('.agent-activity-row')).not.toBeInTheDocument();
  });

  it('keeps a failed inline group collapsed until the user asks for evidence', () => {
    const activity = toolActivity('tool_finished', 'failed', {
      toolCallId: 'call-failed-disclosure',
      toolName: 'workspace_search',
      isError: true,
      result: { details: { error: '搜索参数超出允许范围' } },
    });
    const { container, rerender } = render(<ActivitySummary activities={[activity]} inline />);
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    const summary = group.querySelector('summary')!;

    expect(group).not.toHaveAttribute('open');
    expect(group.querySelector('.agent-activity-row')).not.toBeInTheDocument();
    expect(summary).toHaveTextContent('搜索参数超出允许范围');
    fireEvent.click(summary);
    expect(group).toHaveAttribute('open');
    expect(group.querySelector('.agent-activity-row')).toBeInTheDocument();
    fireEvent.click(summary);
    expect(group).not.toHaveAttribute('open');

    rerender(<ActivitySummary activities={[{ ...activity, updatedAtMs: 3 }]} inline />);
    expect(group).not.toHaveAttribute('open');
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
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    fireEvent.click(group.querySelector('summary')!);
    const row = group.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    const request = within(row).getByLabelText('工具调用参数');
    expect(request).toHaveTextContent('目标');
    expect(request).toHaveTextContent('…/project/rag_ime');
    expect(request).toHaveTextContent('rime_lexicon_review');
    expect(request).toHaveTextContent('*.py');
    expect(request).toHaveTextContent('100');
    expect(request).toHaveTextContent('2');
    const output = within(row).getByLabelText('工具返回片段');
    expect(output).toHaveTextContent('rag_ime/agent_tools.py:41');
    expect(output).toHaveTextContent('tests/test_rime_lexicon_review.py:12');
    expect(output).toHaveTextContent('完整结果仍由本机工具回执保留');
  });

  it('keeps the timeline compact and opens full activity details in a dialog', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-compact-dialog',
      toolName: 'ime_overview',
      result: { details: { ok: true, operation: 'status', result: { summary: '运行状态已读取' } } },
    });

    const { container } = render(<ActivitySummary activities={[activity]} />);

    expect(container.querySelector('details.agent-activity')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /查看活动详情：活动已完成/ }));
    expect(screen.getByRole('dialog', { name: '活动已完成' })).toBeInTheDocument();
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

  it('renders the public ime_overview capability result without raw tool material', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-overview-capabilities',
      toolName: 'ime_overview',
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
          tool: 'ime_overview',
          operation: 'capabilities',
          result: {
            summary: '已连接 9 个控制中心领域',
            toolCount: 13,
            tools: [
              { id: 'ime_overview', displayName: '控制中心概览', operations: ['status'] },
              { id: 'ime_input', displayName: '输入法', operations: ['get_settings'] },
              { id: 'ime_voice', displayName: '语音输入', operations: ['status'] },
            ],
            approvalGatedOperations: ['ime_input.apply_settings', 'ime_voice.provider_apply'],
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
    expect(container).not.toHaveTextContent('ime_overview');
    expect(container).not.toHaveTextContent('do-not-render');
    expect(container).not.toHaveTextContent('/Users/private/project');
    expect(container).not.toHaveTextContent('private chain of thought');
    expect(container).not.toHaveTextContent('serialized result');
  });

  it('shows bounded status and progress fields while hiding nested metadata', () => {
    const completed = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-overview-status',
      toolName: 'ime_overview',
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
      toolName: 'ime_overview',
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
        toolName: 'ime_knowledge',
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
      toolName: 'ime_knowledge',
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

  it('does not dump a generic interface result into the conversation body', () => {
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
    expect(dialog).not.toHaveTextContent('README.md');
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
      toolName: 'ime_memory',
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
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    fireEvent.click(group.querySelector('summary')!);
    const row = group.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
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
      toolName: 'ime_memory',
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
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    fireEvent.click(group.querySelector('summary')!);
    const row = group.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    expect(within(row).getByRole('link', { name: /输入法首候选延迟/ })).toHaveAttribute(
      'href',
      '#/memory?layer=atoms&id=atom%3Acompletion-latency',
    );
  });

  it('deep-links memory catalog entries through their stable Book reference', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-memory-catalog-ref',
      toolName: 'ime_memory',
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
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    fireEvent.click(group.querySelector('summary')!);
    const row = group.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
    fireEvent.click(row.querySelector('summary')!);

    expect(within(row).getByRole('link', { name: /输入法产品与上下文边界/ })).toHaveAttribute(
      'href',
      '#/memory?layer=books&id=book%3Ainput-method',
    );
  });

  it('renders governed timeline recall as a deep-linked semantic result', () => {
    const activity = toolActivity('tool_finished', 'completed', {
      toolCallId: 'call-memory-timeline',
      toolName: 'ime_memory',
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
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    fireEvent.click(group.querySelector('summary')!);
    const row = group.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
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
      toolName: 'ime_memory',
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
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    fireEvent.click(group.querySelector('summary')!);
    const row = group.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
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
    const group = container.querySelector<HTMLDetailsElement>('details.agent-activity--inline')!;
    fireEvent.click(group.querySelector('summary')!);
    const row = group.querySelector<HTMLDetailsElement>('.agent-activity-row')!;
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

    expect(screen.getByLabelText('工具错误')).toHaveTextContent('工作区不在授权目录内，当前权限不足。');
    expect(container).not.toHaveTextContent('/Users/private/project');
    expect(container).not.toHaveTextContent('sk-do-not-render');
    fireEvent.click(screen.getByRole('button', { name: '请求权限' }));
    expect(onRequestPermission).toHaveBeenCalledOnce();
  });

  it('routes an approval-gated failure to the existing bound approval review', () => {
    const onOpenApproval = vi.fn();
    const activity = toolActivity('tool_finished', 'failed', {
      toolCallId: 'call-approval-failed',
      toolName: 'ime_input',
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

    expect(screen.getByLabelText('工具错误')).toHaveTextContent('该操作需要本机审批后继续。');
    fireEvent.click(screen.getByRole('button', { name: '去审批' }));
    expect(onOpenApproval).toHaveBeenCalledOnce();
    expect(onOpenApproval).toHaveBeenCalledWith(activity);
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
