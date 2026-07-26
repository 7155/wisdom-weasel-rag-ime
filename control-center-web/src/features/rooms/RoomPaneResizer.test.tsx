import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { RoomPaneResizer } from './RoomPaneResizer';

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe('RoomPaneResizer', () => {
  it('shares the workspace sizing contract with Session panes', () => {
    window.localStorage.setItem('wisdom-weasel.rooms.rail-width', '272');
    const { container } = render(
      <main className="rooms-feature">
        <RoomPaneResizer side="rail" />
      </main>,
    );
    const workspace = container.querySelector<HTMLElement>('.rooms-feature')!;
    const separator = screen.getByRole('separator', { name: '调整协作空间列表宽度' });

    expect(workspace.style.getPropertyValue('--room-rail-width')).toBe('272px');
    expect(separator).toHaveAttribute('aria-valuetext', '272 像素');

    fireEvent.keyDown(separator, { key: 'ArrowRight', shiftKey: true });
    expect(workspace.style.getPropertyValue('--room-rail-width')).toBe('304px');

    fireEvent.keyDown(separator, { key: 'Home' });
    expect(workspace.style.getPropertyValue('--room-rail-width')).toBe('196px');

    fireEvent.doubleClick(separator);
    expect(workspace.style.getPropertyValue('--room-rail-width')).toBe('224px');
    expect(window.localStorage.getItem('wisdom-weasel.rooms.rail-width')).toBe('224');
  });
});
