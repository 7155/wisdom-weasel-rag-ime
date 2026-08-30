import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { GlobalFeedbackProvider, publishGlobalNotice } from '@/components/feedback';
import { PawNotificationCenter } from './PawNotificationCenter';

afterEach(() => cleanup());

describe('PawNotificationCenter', () => {
  it('opens as a right-side non-modal panel and clears real global notices', () => {
    render(<GlobalFeedbackProvider><PawNotificationCenter /></GlobalFeedbackProvider>);
    act(() => {
      publishGlobalNotice({ id: 'first', title: '记忆整理完成', message: '已写入 4 条候选', tone: 'info' });
      publishGlobalNotice({ id: 'second', title: '对话需要处理', message: '等待确认', tone: 'warning' });
    });

    fireEvent.click(screen.getByRole('button', { name: '通知中心，2 条通知' }));
    const panel = screen.getByRole('region', { name: '通知中心' });
    expect(panel).toHaveAttribute('data-open');
    expect(panel.parentElement).toBe(document.body);
    expect(within(panel).getByText('记忆整理完成')).toBeInTheDocument();
    expect(within(panel).getByText('对话需要处理')).toBeInTheDocument();
    expect(within(panel).getByText('今天')).toBeInTheDocument();

    fireEvent.click(within(panel).getByRole('button', { name: '清除全部通知' }));
    expect(within(panel).getByText('还没有通知')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '通知中心，无新通知' })).toBeInTheDocument();
  });

  it('closes with Escape and returns focus to the menu-bar trigger', () => {
    render(<GlobalFeedbackProvider><PawNotificationCenter /></GlobalFeedbackProvider>);
    const trigger = screen.getByRole('button', { name: '通知中心，无新通知' });
    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(document.querySelector('.paw-notification-center')).not.toHaveAttribute('data-open');
    expect(trigger).toHaveFocus();
  });

  it('moves keyboard focus into the portalled panel and exposes the trigger relationship', async () => {
    render(<GlobalFeedbackProvider><PawNotificationCenter /></GlobalFeedbackProvider>);
    const trigger = screen.getByRole('button', { name: '通知中心，无新通知' });
    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute('aria-controls', 'paw-notification-center-panel');
    const panel = screen.getByRole('region', { name: '通知中心' });
    expect(panel).toHaveAttribute('id', 'paw-notification-center-panel');
    await waitFor(() => expect(within(panel).getByRole('button', { name: '关闭通知中心' })).toHaveFocus());
  });

  it('hands focus to the adjacent notice and then to a stable panel control after dismissal', async () => {
    render(<GlobalFeedbackProvider><PawNotificationCenter /></GlobalFeedbackProvider>);
    act(() => {
      publishGlobalNotice({ id: 'first-focus', title: '第一条', tone: 'info' });
      publishGlobalNotice({ id: 'second-focus', title: '第二条', tone: 'warning' });
    });
    fireEvent.click(screen.getByRole('button', { name: '通知中心，2 条通知' }));
    const panel = screen.getByRole('region', { name: '通知中心' });
    const newest = within(panel).getByRole('button', { name: '清除通知：第二条' });
    newest.focus();

    fireEvent.click(newest);
    await waitFor(() => expect(within(panel).getByRole('button', { name: '清除通知：第一条' })).toHaveFocus());

    fireEvent.click(within(panel).getByRole('button', { name: '清除通知：第一条' }));
    await waitFor(() => expect(within(panel).getByRole('button', { name: '关闭通知中心' })).toHaveFocus());
  });
});
