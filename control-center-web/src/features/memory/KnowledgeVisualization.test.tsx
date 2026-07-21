import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { KnowledgeEvidenceExplorer } from './KnowledgeVisualization';

afterEach(cleanup);

describe('Knowledge evidence empty state', () => {
  it('uses a compact functional empty state without decorative artwork', () => {
    const { rerender } = render(<KnowledgeEvidenceExplorer items={[]} />);
    const emptyState = screen.getByText('暂无证据').closest('.ui-empty-state');
    expect(emptyState).not.toBeNull();
    expect(emptyState?.querySelector('img')).toBeNull();

    rerender(<KnowledgeEvidenceExplorer items={[{
      id: 'evidence:1',
      title: 'Room 路由审计',
      excerpt: '完整循环路径与取消传播证据',
      sourceType: 'local',
      source: 'memory',
      score: 0.91,
      url: '',
    }]} />);
    expect(screen.queryByText('暂无证据')).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Room 路由审计/ })).toBeInTheDocument();
  });
});
