import { cleanup, fireEvent, render, screen } from '@testing-library/react';
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

    fireEvent.click(group!.querySelector('summary')!);
    expect(group).toHaveAttribute('open');
    const row = group!.querySelector<HTMLDetailsElement>('.agent-activity-row');
    fireEvent.click(row!.querySelector('summary')!);
    expect(row).toHaveAttribute('open');
    expect(group).toHaveTextContent('运行状态已读取');
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
    expect(screen.getByRole('dialog')).toHaveTextContent('控制中心概览');
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

    expect(screen.getByText('控制中心概览')).toBeInTheDocument();
    expect(screen.getAllByText('已连接 9 个控制中心领域')).toHaveLength(2);
    expect(screen.getByText('查看可用能力')).toBeInTheDocument();
    expect(screen.getByText('13 项')).toBeInTheDocument();
    expect(screen.getByText('控制中心概览、输入法、语音输入')).toBeInTheDocument();
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
      '控制中心概览',
      '控制中心概览',
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
    expect(dialog).toHaveTextContent('完成 · 3秒');
    expect(dialog).toHaveTextContent('过程记录');
    expect(dialog).toHaveTextContent('+0秒 · 开始检索知识库 · 进行中');
    expect(dialog).toHaveTextContent('+1秒 · 已找到候选来源 · 进行中');
    expect(dialog).toHaveTextContent('+3秒 · 知识检索完成 · 完成');
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

    expect(screen.getByText('文档知识库')).toBeInTheDocument();
    expect(screen.getByText('信息来源')).toBeInTheDocument();
    expect(screen.getByText('acceptance.md · 41-57 行')).toBeInTheDocument();
    expect(screen.getByText('design.pdf · 第 3 页')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '打开知识库' })).toHaveAttribute('href', '#/knowledge');
    expect(container).not.toHaveTextContent('不应在时间线详情里展开');
    expect(container).not.toHaveTextContent('/Users/private');
  });

  it('shows a bounded public structured result while removing secrets, paths and private reasoning', () => {
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

    const result = screen.getByLabelText('工具公开结果');
    expect(result).toHaveTextContent('公开的结构化结果');
    expect(result).toHaveTextContent('entries');
    expect(result).toHaveTextContent('README.md');
    expect(result).toHaveTextContent('cursor-public-2');
    expect(result).toHaveTextContent('healthy');
    expect(result).toHaveTextContent('content');
    expect(result).toHaveTextContent('resultCount');
    expect(result).not.toHaveTextContent('/Users/private');
    expect(result).not.toHaveTextContent('private file body');
    expect(result).not.toHaveTextContent('sk-do-not-render');
    expect(result).not.toHaveTextContent('private chain of thought');
    expect(result).not.toHaveTextContent('authorization');
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
