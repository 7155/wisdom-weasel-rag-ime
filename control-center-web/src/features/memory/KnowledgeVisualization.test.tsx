import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { KnowledgeEvidenceExplorer } from './KnowledgeVisualization';

afterEach(cleanup);

describe('Knowledge evidence project scene', () => {
  it('uses the governed memory scene only for the real evidence empty state', () => {
    const { rerender } = render(<KnowledgeEvidenceExplorer items={[]} />);
    const scene = screen.getByAltText(/封存的历史证据/);
    expect(scene).toHaveAttribute('src', '/companions/scenes/memory-evidence-timeline-v1.webp');
    expect(scene).toHaveAttribute('width', '960');
    expect(scene).toHaveAttribute('height', '640');
    expect(scene).toHaveAttribute('loading', 'lazy');

    rerender(<KnowledgeEvidenceExplorer items={[{
      id: 'evidence:1',
      title: 'Room 路由审计',
      excerpt: '完整循环路径与取消传播证据',
      sourceType: 'local',
      source: 'memory',
      score: 0.91,
      url: '',
    }]} />);
    expect(screen.queryByAltText(/封存的历史证据/)).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Room 路由审计/ })).toBeInTheDocument();
  });
});
