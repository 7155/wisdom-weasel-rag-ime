import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { AgentActivityProjection } from '@/contracts/agent-reducer';
import { ActivitySummary } from './ActivitySummary';

afterEach(cleanup);

describe('Agent tool activity details', () => {
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
    expect(container).not.toHaveTextContent('不应在时间线详情里展开');
    expect(container).not.toHaveTextContent('/Users/private');
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
