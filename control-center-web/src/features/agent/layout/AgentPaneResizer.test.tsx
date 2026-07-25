import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { AgentPaneResizer } from './AgentPaneResizer';

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe('AgentPaneResizer', () => {
  it('restores, adjusts, persists, and resets the rail width', () => {
    window.localStorage.setItem('wisdom-weasel.agent.rail-width', '304');
    const { container } = render(
      <main className="agent-feature">
        <AgentPaneResizer side="rail" />
      </main>,
    );
    const workspace = container.querySelector<HTMLElement>('.agent-feature')!;
    const separator = screen.getByRole('separator', { name: '调整任务列表宽度' });

    expect(workspace.style.getPropertyValue('--agent-rail-width')).toBe('304px');
    expect(separator).toHaveAttribute('aria-valuenow', '304');

    fireEvent.keyDown(separator, { key: 'ArrowRight' });
    expect(workspace.style.getPropertyValue('--agent-rail-width')).toBe('312px');
    expect(window.localStorage.getItem('wisdom-weasel.agent.rail-width')).toBe('312');

    fireEvent.doubleClick(separator);
    expect(workspace.style.getPropertyValue('--agent-rail-width')).toBe('224px');
    expect(window.localStorage.getItem('wisdom-weasel.agent.rail-width')).toBe('224');

    fireEvent.keyDown(separator, { key: 'Home' });
    expect(workspace.style.getPropertyValue('--agent-rail-width')).toBe('196px');
    expect(separator).toHaveAttribute('aria-valuetext', '196 像素');

    fireEvent.keyDown(separator, { key: 'End' });
    expect(workspace.style.getPropertyValue('--agent-rail-width')).toBe('320px');
  });

  it('uses screen direction for the right-side panel and clamps its size', () => {
    const { container } = render(
      <main className="agent-feature">
        <AgentPaneResizer side="status" />
      </main>,
    );
    const workspace = container.querySelector<HTMLElement>('.agent-feature')!;
    const separator = screen.getByRole('separator', { name: '调整状态面板宽度' });

    fireEvent.keyDown(separator, { key: 'ArrowLeft', shiftKey: true });
    expect(workspace.style.getPropertyValue('--agent-status-width')).toBe('344px');

    for (let index = 0; index < 10; index += 1) {
      fireEvent.keyDown(separator, { key: 'ArrowLeft', shiftKey: true });
    }
    expect(workspace.style.getPropertyValue('--agent-status-width')).toBe('420px');
    expect(separator).toHaveAttribute('data-clamped', 'max');
  });
});
