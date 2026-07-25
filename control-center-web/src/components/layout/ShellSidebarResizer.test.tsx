import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ShellSidebarResizer } from './ShellSidebarResizer';

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe('ShellSidebarResizer', () => {
  it('restores and persists an accessible navigation width', () => {
    window.localStorage.setItem('rag-ime-control-sidebar-width', '236');
    const { container } = render(
      <div className="control-shell">
        <ShellSidebarResizer />
      </div>,
    );
    const shell = container.querySelector<HTMLElement>('.control-shell')!;
    const separator = screen.getByRole('separator', { name: '调整主导航宽度' });

    expect(shell.style.getPropertyValue('--sidebar-wide')).toBe('236px');
    fireEvent.keyDown(separator, { key: 'ArrowLeft' });
    expect(shell.style.getPropertyValue('--sidebar-wide')).toBe('228px');
    expect(window.localStorage.getItem('rag-ime-control-sidebar-width')).toBe('228');

    fireEvent.doubleClick(separator);
    expect(shell.style.getPropertyValue('--sidebar-wide')).toBe('220px');

    fireEvent.keyDown(separator, { key: 'End' });
    expect(shell.style.getPropertyValue('--sidebar-wide')).toBe('280px');
    expect(separator).toHaveAttribute('aria-valuetext', '280 像素');

    fireEvent.keyDown(separator, { key: 'Home' });
    expect(shell.style.getPropertyValue('--sidebar-wide')).toBe('196px');
  });
});
