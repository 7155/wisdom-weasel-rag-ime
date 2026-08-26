import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const graphRuntime = vi.hoisted(() => ({
  destroyed: 0,
  renderAttempts: 0,
}));

vi.mock('../knowledge/g6-runtime', () => ({
  Graph: class {
    destroy() { graphRuntime.destroyed += 1; }
    async fitCenter() {}
    async fitView() {}
    getZoom() { return 1; }
    on() {}
    resize() {}
    async render() {
      graphRuntime.renderAttempts += 1;
      if (graphRuntime.renderAttempts === 1) {
        throw new Error('/Users/private/memory.sqlite SELECT prompt reasoning rawJson');
      }
    }
    async setElementState() {}
    async zoomBy() {}
    async zoomTo() {}
  },
}));

import { MemoryRelationCanvas } from './MemoryRelationCanvas';

describe('MemoryRelationCanvas', () => {
  beforeEach(() => {
    graphRuntime.destroyed = 0;
    graphRuntime.renderAttempts = 0;
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800);
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(560);
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })));
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('shows public recovery copy after a graph failure and retries without hiding the accessible fallback', async () => {
    const user = userEvent.setup();
    render(
      <>
        <MemoryRelationCanvas
          edges={[]}
          enabled
          nodes={[{
            id: 'tag:memory',
            label: '记忆',
            kind: 'tag',
            count: 3,
            connections: 0,
          }]}
          onSelect={() => undefined}
          selectedId=""
        />
        <button type="button">记忆，3 条记忆</button>
      </>,
    );

    expect(await screen.findByRole('alert')).toHaveTextContent('关系图暂时无法布局');
    expect(screen.getByRole('button', { name: '记忆，3 条记忆' })).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('/Users/private/memory.sqlite');
    expect(document.body).not.toHaveTextContent('reasoning');

    await user.click(screen.getByRole('button', { name: '重新布局关系图' }));

    await waitFor(() => {
      expect(document.querySelector('.memory-relation-canvas')).toHaveAttribute('data-ready', 'true');
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(graphRuntime.renderAttempts).toBe(2);
    expect(graphRuntime.destroyed).toBeGreaterThanOrEqual(1);
  });
});
