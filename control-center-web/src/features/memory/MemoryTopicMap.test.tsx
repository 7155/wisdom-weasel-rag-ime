import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TopicEntry, TopicPage } from '@/contracts/generated/memory-entity.v1';
import { MemoryTopicMap } from './MemoryTopicMap';

afterEach(cleanup);

function atom(id: string, text: string, extra: Partial<TopicEntry> = {}): TopicEntry {
  return { id, text, kind: 'project_decision', status: 'active', claimState: 'current', atomIds: [id],
    references: [], sourceStatus: 'unavailable', lineageId: '', validFromMs: 100, validToMs: null,
    supersedesId: '', supersededByIds: [], reason: null, ...extra };
}
function topic(): TopicPage {
  const source = { kind: 'evidence' as const, id: 'source-b', referenceKind: 'evidence' as const, referenceId: 'source-b', label: '明确改用 B 的原文' };
  return { schemaVersion: 'rag-ime.memory-topic-page.v1', bookId: 'book-one', revision: 'r1', authority: 'atom_projection', freshness: 'current', summary: '',
    sections: {
      current: [atom('b', '目前采用模型 B。', { lineageId: 'choice', supersedesId: 'a', sourceStatus: 'available', references: [
        { kind: 'atom', id: 'b', referenceKind: 'atom', referenceId: 'b' }, source, source,
      ] })], constraints: [],
      openQuestions: [atom('question', '是否采用模型 C？', { kind: 'question' })],
      history: [atom('a', '以前采用模型 A。', { claimState: 'superseded', lineageId: 'choice', supersededByIds: ['b'] })],
    }, sources: [source], coverage: { memberCount: 2, visibleAtomCount: 3, omittedAtomCount: 0, truncated: false } };
}

describe('Memory topic provenance map', () => {
  it('counts distinct originals and opens their exact Evidence identity', async () => {
    const open = vi.fn(); const user = userEvent.setup();
    render(<MemoryTopicMap page={topic()} onOpenReference={open} />);
    const diagram = screen.getByRole('group', { name: '选中记忆的来源关系' });
    expect(within(diagram).getByText('1 条原始依据')).toBeInTheDocument();
    expect(within(diagram).getAllByRole('button')).toHaveLength(2);
    await user.click(within(diagram).getByRole('button', { name: '明确改用 B 的原文' }));
    expect(open).toHaveBeenCalledWith({ kind: 'evidence', referenceId: 'source-b', label: '明确改用 B 的原文' });
  });

  it('keeps unresolved questions separate and does not invent sources or history', async () => {
    const user = userEvent.setup();
    render(<MemoryTopicMap page={topic()} onOpenReference={vi.fn()} />);
    await user.click(screen.getByRole('combobox', { name: '选择要追溯的记忆' }));
    await user.click(screen.getByRole('option', { name: '待确认 · 是否采用模型 C？' }));
    const diagram = screen.getByRole('group', { name: '选中记忆的来源关系' });
    expect(within(diagram).getByText('待确认')).toBeInTheDocument();
    expect(within(diagram).getByText('0 条原始依据')).toBeInTheDocument();
    expect(within(diagram).getByText('原始依据暂不可读，未绘制来源连线。')).toBeInTheDocument();
    expect(screen.queryByText('这条认识的过去版本')).not.toBeInTheDocument();
  });

  it('lets the reader open a real previous version independently of the current claim', async () => {
    const open = vi.fn(); const user = userEvent.setup();
    render(<MemoryTopicMap page={topic()} onOpenReference={open} />);
    expect(screen.getByRole('heading', { name: '这条认识的过去版本' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /以前采用模型 A/ }));
    expect(open).toHaveBeenCalledWith({ kind: 'atom', referenceId: 'a', label: '记忆原文' });
  });

  it('does not promote history into a current node when the current selection is empty', () => {
    const page = topic(); page.sections.current = []; page.sections.openQuestions = [];
    render(<MemoryTopicMap page={page} onOpenReference={vi.fn()} />);
    expect(screen.getByText('当前没有可追溯的认识。已有历史仍可从上方展开。')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: '选中记忆的来源关系' })).not.toBeInTheDocument();
  });
});
