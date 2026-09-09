import { act, cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppSidebarToggle, useAppSidebar } from './app-sidebar';

afterEach(() => { cleanup(); window.localStorage.clear(); vi.restoreAllMocks(); });

function Sidebar({ appId, name = appId, defaultCollapsed = false }: { appId: string; name?: string; defaultCollapsed?: boolean }) {
  const sidebar = useAppSidebar(appId, defaultCollapsed);
  return <section aria-label={name}>
    <AppSidebarToggle collapsed={sidebar.collapsed} controlsId={sidebar.controlsId} onToggle={() => sidebar.setCollapsed(!sidebar.collapsed)} toggleRef={sidebar.toggleRef} />
    <nav aria-label={`${name}页面`} {...sidebar.contentProps}><button type="button">任务</button></nav>
    <button type="button">正文操作</button>
  </section>;
}

describe('PAWOS App sidebar preference', () => {
  it('collapses by keyboard, removes hidden destinations from tab order, and keeps a reachable opener', async () => {
    const user = userEvent.setup();
    render(<Sidebar appId="project-workbench" />);
    const toggle = screen.getByRole('button', { name: '收起侧边栏' });
    expect(document.getElementById(toggle.getAttribute('aria-controls')!)).toBe(screen.getByRole('navigation'));
    screen.getByRole('button', { name: '任务' }).focus();
    await user.keyboard('{Escape}');
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    await user.tab();
    expect(screen.getByRole('button', { name: '正文操作' })).toHaveFocus();
    await user.tab({ shift: true });
    await user.keyboard('{Enter}');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('navigation')).toBeVisible();
  });

  it('remembers each App independently and reloads the preference when the App identity changes', async () => {
    const user = userEvent.setup();
    const view = render(<Sidebar appId="memory" />);
    await user.click(screen.getByRole('button', { name: '收起侧边栏' }));
    expect(window.localStorage.getItem('pawos.app-sidebar.v1:memory')).toBe('collapsed');
    view.rerender(<Sidebar appId="system-settings" />);
    expect(screen.getByRole('button', { name: '收起侧边栏' })).toHaveAttribute('aria-expanded', 'true');
    view.rerender(<Sidebar appId="memory" />);
    expect(screen.getByRole('button', { name: '展开侧边栏' })).toHaveAttribute('aria-expanded', 'false');
    view.unmount();
    render(<Sidebar appId="memory" />);
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  it('synchronizes App windows while their controls retain unique relationships', async () => {
    const user = userEvent.setup();
    render(<><Sidebar appId="trace-agent" name="first" /><Sidebar appId="trace-agent" name="second" /></>);
    const first = within(screen.getByRole('region', { name: 'first' }));
    const second = within(screen.getByRole('region', { name: 'second' }));
    const firstToggle = first.getByRole('button', { name: '收起侧边栏' });
    const secondToggle = second.getByRole('button', { name: '收起侧边栏' });
    expect(firstToggle.getAttribute('aria-controls')).not.toBe(secondToggle.getAttribute('aria-controls'));
    await user.click(firstToggle);
    expect(secondToggle).toHaveAttribute('aria-expanded', 'false');
    act(() => {
      window.localStorage.setItem('pawos.app-sidebar.v1:trace-agent', 'expanded');
      window.dispatchEvent(new StorageEvent('storage', { key: 'pawos.app-sidebar.v1:trace-agent', newValue: 'expanded' }));
    });
    expect(secondToggle).toHaveAttribute('aria-expanded', 'true');
    second.getByRole('button', { name: '任务' }).focus();
    act(() => {
      window.localStorage.setItem('pawos.app-sidebar.v1:trace-agent', 'collapsed');
      window.dispatchEvent(new StorageEvent('storage', { key: 'pawos.app-sidebar.v1:trace-agent', newValue: 'collapsed' }));
    });
    expect(secondToggle).toHaveFocus();
  });

  it('keeps collapse usable when local storage is unavailable', async () => {
    const user = userEvent.setup();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage unavailable'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage unavailable'); });
    render(<Sidebar appId="eval-lab" defaultCollapsed />);
    await user.click(screen.getByRole('button', { name: '展开侧边栏' }));
    expect(screen.getByRole('navigation')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '收起侧边栏' }));
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });
});
