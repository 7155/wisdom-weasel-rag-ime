import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { App } from '@/app/App';
import { GlobalFeedbackProvider, publishConnectionState, publishGlobalNotice } from '@/components/feedback';
import { TooltipProvider } from '@/components/primitives';
import { MotionProvider } from '@/design/motion';
import { ThemeProvider } from '@/design/themes';
import { AppShell } from './AppShell';

describe('control center shell', () => {
  afterEach(cleanup);

  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = '#/';
    document.documentElement.dataset.controlTransport = 'mock';
  });

  it('switches routes immediately and exposes one global status surface', async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getAllByRole('heading', { name: '任务与验收' })).not.toHaveLength(0);
    expect(document.querySelector('main[data-route-id="planning"]')).toBeInTheDocument();

    await user.click(screen.getAllByRole('link', { name: 'Session 工作台' })[0]);
    await waitFor(() => expect(document.querySelector('main[data-route-id="agent"]')).toBeInTheDocument());
    expect(screen.getByRole('heading', { name: 'Session 工作台' })).toBeInTheDocument();

    act(() => publishConnectionState({ state: 'connected', label: 'Sidecar 已连接' }));
    expect(screen.getByRole('status')).toHaveTextContent('Sidecar 已连接');

    act(() => publishGlobalNotice({ id: 'update', title: '可用更新', message: '重启后生效。', tone: 'info' }));
    expect(screen.getByRole('region', { name: '全局通知' })).toHaveTextContent('可用更新');
  });

  it('keeps the shell title in sync with programmatic route navigation', async () => {
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(document.querySelector('main[data-route-id="planning"]')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '交给智鼬整理' }));

    await waitFor(() => expect(document.querySelector('main[data-route-id="agent"]')).toBeInTheDocument());
    expect(document.querySelector('.shell-topbar__title h1')).toHaveTextContent('Session 工作台');
    expect(document.querySelector('.shell-sidebar [data-route="agent"]')).toHaveAttribute('aria-current', 'page');
  });

  it('persists theme, motion, and sidebar preferences', async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <MotionProvider>
          <TooltipProvider>
            <GlobalFeedbackProvider>
              <AppShell><main aria-label="测试页面" /></AppShell>
            </GlobalFeedbackProvider>
          </TooltipProvider>
        </MotionProvider>
      </ThemeProvider>,
    );

    await user.click(screen.getByRole('button', { name: '外观与动效' }));
    await user.click(screen.getByRole('menuitemradio', { name: '深色' }));
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(window.localStorage.getItem('rag-ime-control-theme')).toBe('dark');

    await user.click(screen.getByRole('button', { name: '外观与动效' }));
    await user.click(screen.getByRole('menuitemradio', { name: '减少动效' }));
    expect(document.documentElement).toHaveAttribute('data-reduce-motion', 'true');

    await user.click(screen.getByRole('button', { name: '收起侧边栏' }));
    expect(document.querySelector('.control-shell')).toHaveAttribute('data-sidebar-collapsed', 'true');
    expect(window.localStorage.getItem('rag-ime-control-sidebar-collapsed')).toBe('true');
  });
});
