import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppErrorBoundary } from '@/app/AppErrorBoundary';
import { PawOsAppSurfaceProvider, PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import { PawAppProcess } from './PawApps';

vi.mock('./PawAppsRuntime', () => ({
  PawAppBody: ({ appId, initialRoute }: { appId: string; initialRoute?: string }) => {
    if (appId === 'knowledge' && initialRoute === '/broken') {
      throw new TypeError('Failed to fetch dynamically imported module: private-internal-url');
    }
    return appId === 'agent'
      ? <input aria-label="未发送的消息" defaultValue="" />
      : <p>知识库已打开</p>;
  },
}));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function workspace(route: string, closeWindow = vi.fn(), active = true) {
  return <AppErrorBoundary>
    <PawOsDesktopProvider openWindow={vi.fn()} closeWindow={closeWindow}>
      <nav aria-label="桌面工具架">桌面导航</nav>
      <PawOsAppSurfaceProvider appId="agent" windowId="session:one" width={900} height={700}>
        <PawAppProcess appId="agent" />
      </PawOsAppSurfaceProvider>
      <PawOsAppSurfaceProvider appId="knowledge" windowId="knowledge:two" active={active} width={900} height={700}>
        <PawAppProcess appId="knowledge" initialRoute={route} />
      </PawOsAppSurfaceProvider>
    </PawOsDesktopProvider>
  </AppErrorBoundary>;
}

describe('App window error isolation', () => {
  it('preserves another App and its unsent draft when a page fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const view = render(workspace('/knowledge'));
    const draft = await screen.findByRole('textbox', { name: '未发送的消息' });
    fireEvent.change(draft, { target: { value: '保留这个草稿' } });

    view.rerender(workspace('/broken'));

    expect(await screen.findByRole('heading', { name: 'Knowledge 未能显示' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: '桌面工具架' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '未发送的消息' })).toHaveValue('保留这个草稿');
    expect(screen.queryByText('工作台需要重新载入')).not.toBeInTheDocument();
    expect(screen.queryByText(/private-internal-url/)).not.toBeInTheDocument();
  });

  it('closes only the failed window and can render a different route', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const closeWindow = vi.fn();
    const view = render(workspace('/broken', closeWindow));
    fireEvent.click(await screen.findByRole('button', { name: '关闭此窗口' }));
    expect(closeWindow).toHaveBeenCalledExactlyOnceWith('knowledge:two');
    expect(screen.getByRole('button', { name: '重新载入工作台' })).toBeInTheDocument();

    view.rerender(workspace('/knowledge', closeWindow));
    expect(await screen.findByText('知识库已打开')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Knowledge 未能显示' })).not.toBeInTheDocument();
  });

  it('does not steal focus when an inactive window fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const closeWindow = vi.fn();
    const view = render(workspace('/knowledge', closeWindow, false));
    const draft = await screen.findByRole('textbox', { name: '未发送的消息' });
    draft.focus();
    view.rerender(workspace('/broken', closeWindow, false));
    const close = await screen.findByRole('button', { name: '关闭此窗口' });
    expect(draft).toHaveFocus();

    view.rerender(workspace('/broken', closeWindow, true));
    expect(close).toHaveFocus();
  });
});
