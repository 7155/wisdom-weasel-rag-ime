import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PawAgentCapsuleApp } from './PawAgentCapsuleApp';

afterEach(() => {
  cleanup();
  delete window.pawScreenAssistant;
  vi.restoreAllMocks();
});

describe('Agent Capsule App', () => {
  it('explains the managed capture boundary when no native host is present', async () => {
    render(<PawAgentCapsuleApp />);

    expect(screen.getByRole('heading', { name: 'Agent Capsule' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '框选屏幕' })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('浏览器预览不会读取系统屏幕'));
  });

  it('starts one host capture from the App button and the global shortcut', async () => {
    const capture = vi.fn().mockResolvedValue(true);
    window.pawScreenAssistant = { capture } as never;
    render(<PawAgentCapsuleApp />);

    const button = await screen.findByRole('button', { name: '框选屏幕' });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => expect(capture).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.keyDown(window, { code: 'Space', key: ' ', metaKey: true, shiftKey: true });
    await waitFor(() => expect(capture).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('status')).toHaveTextContent('已打开框选窗口');
  });

  it('keeps retry available when the host cancels or rejects capture', async () => {
    const capture = vi.fn()
      .mockResolvedValueOnce(false)
      .mockRejectedValueOnce(new Error('系统屏幕权限未开启'));
    window.pawScreenAssistant = { capture } as never;
    render(<PawAgentCapsuleApp />);

    const button = await screen.findByRole('button', { name: '框选屏幕' });
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('框选已取消'));
    expect(button).toBeEnabled();

    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('系统屏幕权限未开启'));
    expect(button).toBeEnabled();
  });
});
