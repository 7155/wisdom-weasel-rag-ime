import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import memoryStylesheet from './memory.css?raw';
import { MemoryPipeline } from './MemoryPipeline';

afterEach(() => cleanup());

describe('MemoryPipeline', () => {
  it('renders the Evidence, Atom, and Book stages as one ordered flow with real counts', () => {
    renderPipeline({
      summary: {
        memoryEvidenceCount: 24,
        inputMethodEvidenceCount: 18,
        voiceEvidenceCount: 2,
        agentCapturedEvidenceCount: 4,
        currentAtomCount: 10,
        memoryAtomTotalCount: 14,
        historicalAtomCount: 4,
        memoryBookCount: 5,
        memoryTagCount: 7,
      },
    });

    const flow = screen.getByRole('list', { name: '记忆内容分类' });
    const stages = [...flow.querySelectorAll('.memory-pipeline__stage')];
    expect(stages.map((stage) => stage.getAttribute('data-stage'))).toEqual(['evidence', 'atoms', 'books']);
    expect(within(flow).getByRole('button', { name: '来源 · 来源记录 · 24 项' })).toHaveTextContent('24');
    expect(within(flow).getByRole('button', { name: '记忆 · 记忆 · 10 项' })).toHaveTextContent('全部 14 · 历史 4');
    expect(within(flow).getByRole('button', { name: '主题 · 长期主题 · 5 项' })).toHaveTextContent('7 个关系标签');
    expect(within(flow).getByText('输入法 18 · 语音 2 · 伙伴主动记录 4')).toBeInTheDocument();
  });

  it('marks only the active layer as pressed and opens the clicked stage', async () => {
    const user = userEvent.setup();
    const onOpenLayer = vi.fn();
    renderPipeline({ activeLayer: 'atoms', onOpenLayer });

    const flow = screen.getByRole('list', { name: '记忆内容分类' });
    const buttons = within(flow).getAllByRole('button');
    expect(buttons.map((button) => button.getAttribute('aria-pressed'))).toEqual(['false', 'true', 'false']);

    await user.click(within(flow).getByRole('button', { name: /主题/ }));
    expect(onOpenLayer).toHaveBeenCalledWith('books');
    await user.click(within(flow).getByRole('button', { name: /来源/ }));
    expect(onOpenLayer).toHaveBeenCalledWith('evidence');
  });

  it('reports governance honestly: pending drafts lead as a warning, a clean state stays quiet', () => {
    renderPipeline({
      summary: {
        needsReviewSourceCount: 2,
        governanceProposalCounts: { preview: 1 },
        activityTimelineCounts: { draft: 3 },
        projection: { fresh: true, retrievalDocuments: 12 },
        latestActivityTimeline: { date: '2026-08-20', status: 'draft' },
      },
    });

    const meters = screen.getByLabelText('记忆整理状态');
    expect(within(meters).getByText('6 项等待处理').closest('.memory-pipeline__meter')).toHaveAttribute('data-tone', 'warning');
    expect(within(meters).getByText('12 份检索文档').closest('.memory-pipeline__meter')).toHaveAttribute('data-tone', 'success');
    expect(within(meters).getByText('08-20 待审核')).toBeInTheDocument();
    cleanup();

    renderPipeline({ summary: { projection: { fresh: true, retrievalDocuments: 3 } } });
    expect(screen.getByText('没有待处理草案').closest('.memory-pipeline__meter')).toHaveAttribute('data-tone', 'success');
    expect(screen.getByText('尚未生成')).toBeInTheDocument();
  });

  it('keeps every companion view reachable from the pipeline frame', async () => {
    const user = userEvent.setup();
    const onOpenOrganize = vi.fn();
    const onOpenPreferences = vi.fn();
    const onOpenRelations = vi.fn();
    const onOpenTimeline = vi.fn();
    renderPipeline({ onOpenOrganize, onOpenPreferences, onOpenRelations, onOpenTimeline });

    await user.click(screen.getByRole('button', { name: '关系图' }));
    await user.click(screen.getByRole('button', { name: '让Agent整理' }));
    await user.click(screen.getByRole('button', { name: '查看时间线' }));
    await user.click(screen.getByRole('button', { name: '记忆偏好' }));

    expect(onOpenRelations).toHaveBeenCalledTimes(1);
    expect(onOpenOrganize).toHaveBeenCalledTimes(1);
    expect(onOpenTimeline).toHaveBeenCalledTimes(1);
    expect(onOpenPreferences).toHaveBeenCalledTimes(1);
    expect(screen.getByText('主题不会替代原始记录')).toBeInTheDocument();
  });

  it('owns a token-driven stylesheet with the stage hues and no retired overview classes', () => {
    for (const token of [
      '--memory-flow-source:',
      '--memory-flow-atom:',
      '--memory-flow-book:',
      '--mem-ink:',
      '--mem-hairline:',
      '--mem-panel:',
    ]) {
      expect(memoryStylesheet).toContain(token);
    }
    expect(memoryStylesheet).toContain('.memory-pipeline__flow');
    expect(memoryStylesheet).not.toContain('.memory-system-overview');
    expect(memoryStylesheet).not.toContain('.memory-architecture');
  });
});

function renderPipeline(overrides: {
  activeLayer?: 'evidence' | 'atoms' | 'books';
  onOpenLayer?: (layer: 'evidence' | 'atoms' | 'books') => void;
  onOpenOrganize?: () => void;
  onOpenPreferences?: () => void;
  onOpenRelations?: () => void;
  onOpenTimeline?: () => void;
  summary?: Record<string, unknown>;
} = {}) {
  render(
    <MemoryPipeline
      activeLayer={overrides.activeLayer ?? 'atoms'}
      onOpenLayer={overrides.onOpenLayer ?? (() => {})}
      onOpenOrganize={overrides.onOpenOrganize ?? (() => {})}
      onOpenPreferences={overrides.onOpenPreferences ?? (() => {})}
      onOpenRelations={overrides.onOpenRelations ?? (() => {})}
      onOpenTimeline={overrides.onOpenTimeline ?? (() => {})}
      summary={overrides.summary ?? {}}
    />,
  );
}
