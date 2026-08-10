import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { App } from '@/app/App';
import { router } from '@/app/router';
import { GlobalFeedbackProvider, publishConnectionState, publishGlobalNotice } from '@/components/feedback';
import { TooltipProvider } from '@/components/primitives';
import { MotionProvider } from '@/design/motion';
import { ThemeProvider } from '@/design/themes';
import { AppShell } from './AppShell';

describe('control center shell', () => {
  afterEach(cleanup);

  beforeEach(async () => {
    window.localStorage.clear();
    await router.navigate('/agent');
    document.documentElement.dataset.controlTransport = 'mock';
  });

  it('switches routes immediately and exposes one global status surface', async () => {
    const user = userEvent.setup();
    await router.navigate('/agent');
    render(<App />);

    await waitFor(
      () => expect(document.querySelector('main[data-route-id="agent"]')).toBeInTheDocument(),
      { timeout: 10_000 },
    );
    expect(screen.getAllByRole('heading', { name: '对话' })).not.toHaveLength(0);

    await user.click(screen.getAllByRole('link', { name: '任务' })[0]);
    await waitFor(() => expect(document.querySelector('main[data-route-id="planning"]')).toBeInTheDocument());
    expect(screen.getAllByRole('heading', { name: '任务' })).not.toHaveLength(0);
    expect(document.activeElement).toHaveAttribute('id', 'workspace-main');

    act(() => publishConnectionState({ state: 'connected', label: 'Sidecar 已连接' }));
    expect(screen.getByText('Sidecar 已连接').closest('[role="status"]')).toHaveClass('global-connection');

    act(() => publishGlobalNotice({ id: 'update', title: '可用更新', message: '重启后生效。', tone: 'info' }));
    expect(screen.getByRole('region', { name: '全局通知' })).toHaveTextContent('可用更新');
  });

  it('keeps the shell title in sync with programmatic route navigation', async () => {
    await router.navigate('/planning');
    render(<App />);

    await waitFor(() => expect(document.querySelector('main[data-route-id="planning"]')).toBeInTheDocument());
    await router.navigate('/agent');

    await waitFor(
      () => expect(document.querySelector('main[data-route-id="agent"]')).toBeInTheDocument(),
      { timeout: 10_000 },
    );
    expect(document.querySelector('.shell-topbar__title h1')).toHaveTextContent('对话');
    expect(document.querySelector('.shell-sidebar [data-route="agent"]')).toHaveAttribute('aria-current', 'page');
  });

  it('persists theme, motion, and sidebar preferences', async () => {
    const user = userEvent.setup();
    await router.navigate('/agent');
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

  it('moves keyboard focus to the active workspace without changing routes', async () => {
    const user = userEvent.setup();
    await router.navigate('/agent');
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

    const skipLink = screen.getByRole('link', { name: '跳到主工作区' });
    expect(skipLink).toHaveAttribute('href', '#workspace-main');
    expect(document.querySelector('#workspace-main')).toHaveAttribute('tabindex', '-1');

    await user.click(skipLink);

    expect(window.location.hash).toBe('#/agent');
    expect(document.activeElement).toHaveAttribute('id', 'workspace-main');
  });

  it('gives the Project Field an immersive shell without duplicate navigation chrome', async () => {
    await router.navigate('/project-field');
    render(<App />);

    await waitFor(() => expect(document.querySelector('main.project-field')).toBeInTheDocument());
    expect(document.querySelector('.control-shell')).toHaveAttribute('data-immersive', 'true');
    expect(document.querySelector('.shell-sidebar')).not.toBeInTheDocument();
    expect(document.querySelector('.shell-topbar')).not.toBeInTheDocument();
    expect(document.querySelector('.shell-mobile-nav')).not.toBeInTheDocument();
  });
});
