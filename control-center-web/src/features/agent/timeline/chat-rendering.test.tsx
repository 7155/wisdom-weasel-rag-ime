import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import type { UiAgentBlock, UiAgentMessage } from '@/contracts/ui-events';
import { useAgentLiveStore } from '../state/live-store';
import { AgentTurn } from './AgentTimeline';
import { AgentBlock, MarkdownBody } from './BlockRenderer';

afterEach(() => {
  cleanup();
  useAgentLiveStore.getState().clear('session-failed-snapshot');
});

describe('Agent chat rendering', () => {
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
    expect(container.querySelectorAll('.agent-code-block')).toHaveLength(2);
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
