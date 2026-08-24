import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { App } from '@/app/App';
import { router } from '@/app/router';
import { GlobalFeedbackProvider, publishConnectionState, publishGlobalNotice } from '@/components/feedback';
import { TooltipProvider } from '@/components/primitives';
import { MotionProvider } from '@/design/motion';
import { ThemeProvider } from '@/design/themes';
import { AppShell } from './AppShell';
import { MobileBottomNavigation } from './Navigation';

describe('control center shell', () => {
  afterEach(cleanup);

  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = '#/';
    document.documentElement.dataset.controlTransport = 'mock';
  });

  it('switches routes immediately and exposes one global status surface', async () => {
    const user = userEvent.setup();
    await router.navigate('/agent');
    render(<App frontendProduct="legacy" />);

    await waitFor(
      () => expect(document.querySelector('main[data-route-id="agent"]')).toBeInTheDocument(),
      { timeout: 10_000 },
    );
    expect(screen.getAllByRole('heading', { name: '对话' })).not.toHaveLength(0);

    await user.click(screen.getAllByRole('link', { name: '任务' })[0]);
    await waitFor(() => expect(document.querySelector('main[data-route-id="planning"]')).toBeInTheDocument());
    expect(screen.getAllByRole('heading', { name: '任务' })).toHaveLength(1);
    expect(document.activeElement).toHaveAttribute('id', 'workspace-main');

    act(() => publishConnectionState({ state: 'connected', label: 'Sidecar 已连接' }));
    expect(screen.getByText('Sidecar 已连接').closest('[role="status"]')).toHaveClass('global-connection');

    act(() => publishGlobalNotice({ id: 'update', title: '可用更新', message: '重启后生效。', tone: 'info' }));
    expect(screen.getByRole('region', { name: '全局通知' })).toHaveTextContent('可用更新');
  });

  it('keeps the shell title in sync with programmatic route navigation', async () => {
    await router.navigate('/planning');
    render(<App frontendProduct="legacy" />);

    await waitFor(() => expect(document.querySelector('main[data-route-id="planning"]')).toBeInTheDocument());
    await router.navigate('/agent');

    await waitFor(
      () => expect(document.querySelector('main[data-route-id="agent"]')).toBeInTheDocument(),
      { timeout: 10_000 },
    );
    expect(document.querySelector('.shell-topbar__title h1')).toHaveTextContent('对话');
    expect(document.title).toBe('对话 · PAW');
    expect(document.querySelector('#workspace-main')).toHaveAccessibleName('对话主内容');
    expect(document.querySelector('.shell-sidebar [data-route="agent"]')).toHaveAttribute('aria-current', 'page');
  });

  it('uses the conversation shell while the root or an unknown hash redirects', async () => {
    window.location.hash = '#/not-a-route';

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

    expect(document.querySelector('.control-shell')).not.toHaveAttribute('data-immersive');
    expect(document.querySelector('.shell-topbar__title h1')).toHaveTextContent('对话');
    expect(document.querySelector('#workspace-main')).toHaveAccessibleName('对话主内容');
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
    expect(document.querySelector('#workspace-main')).toHaveAttribute('role', 'region');

    await user.click(skipLink);

    expect(window.location.hash).toBe('#/agent');
    expect(document.activeElement).toHaveAttribute('id', 'workspace-main');
  });

  it('groups mobile navigation and closes it after a route choice', async () => {
    const user = userEvent.setup();
    render(<MobileBottomNavigation activeRouteId="overview" />);
    fireEvent.click(screen.getByLabelText('打开全部导航，当前页面：概览'));

    const dialog = screen.getByRole('dialog', { name: '全部功能' });
    expect(dialog).toHaveTextContent('工作');
    expect(dialog).toHaveTextContent('能力');
    expect(dialog).toHaveTextContent('系统');
    expect(screen.getByRole('link', { name: '概览', current: 'page' })).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: '任务' }));
    expect(screen.queryByRole('dialog', { name: '全部功能' })).not.toBeInTheDocument();
  });
});
