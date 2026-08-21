import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { routeRegistry } from '@/app/route-registry';
import { usePawOsAppSurface } from '@/features/paw-os/surface-context';

const mockedRoute = vi.hoisted(() => ({ id: 'agent' }));

vi.mock('@/app/router', () => ({
  prefetchRoute: vi.fn(),
  router: {
    state: { navigation: { state: 'idle' } },
    subscribe: () => () => undefined,
  },
}));

vi.mock('@/components/feedback', () => ({
  ConnectionIndicator: () => <span>已连接</span>,
  GlobalNoticeRegion: () => <div data-testid="notices" />,
}));

vi.mock('@/components/layout/useHashRoute', () => ({
  useHashRoute: () => routeRegistry.find((route) => route.id === mockedRoute.id)!,
}));

vi.mock('@/design/paw-os-themes', () => ({
  usePawOsAppearance: () => ({ theme: 'glacier', setTheme: vi.fn() }),
}));

vi.mock('@/features/identity/product-identity', () => ({
  useProductIdentity: () => ({ productName: '澄' }),
}));

import { PawOsShell } from './PawOsShell';

function SurfaceProbe() {
  const surface = usePawOsAppSurface();
  return <div data-testid="surface-probe">{surface?.appId}:{surface?.width}</div>;
}

afterEach(() => {
  mockedRoute.id = 'agent';
  cleanup();
});

describe('PawOsShell', () => {
  it('renders routed Runtime content as an App window on a real desktop surface', () => {
    render(<PawOsShell><div data-testid="runtime-content">Agent Runtime<SurfaceProbe /></div></PawOsShell>);

    expect(screen.getByTestId('paw-os-desktop')).toHaveAttribute('data-window-count', '1');
    expect(screen.getByRole('region', { name: 'Agent App' })).toContainElement(
      screen.getByTestId('runtime-content'),
    );
    expect(screen.getByRole('navigation', { name: 'PAWOS 应用坞' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '最小化Agent' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '放大Agent' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '关闭Agent' })).toBeInTheDocument();
    expect(screen.getByTestId('surface-probe')).toHaveTextContent('agent:');
  });

  it('opens full desktop overlays for Launchpad and Mission Control', async () => {
    const user = userEvent.setup();
    render(<PawOsShell><div>Agent Runtime</div></PawOsShell>);

    await user.click(screen.getByRole('button', { name: '打开全部 App' }));
    expect(screen.getByRole('dialog', { name: '全部 App' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Knowledge · 资料、索引与检索空间' })).toBeInTheDocument();

    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', { name: '窗口总览' }));
    expect(screen.getByRole('dialog', { name: '窗口总览' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Agent窗口' })).toBeInTheDocument();
  });

  it('keeps Project Field as the windowless Wayfinder desktop home', () => {
    mockedRoute.id = 'project-field';
    render(<PawOsShell><div data-testid="wayfinder-runtime">Project Runtime</div></PawOsShell>);

    expect(screen.getByTestId('paw-os-desktop')).toHaveAttribute('data-window-count', '0');
    expect(screen.queryByRole('region', { name: /App$/ })).not.toBeInTheDocument();
    expect(screen.getByTestId('wayfinder-runtime')).toBeInTheDocument();
    expect(screen.getByText('沿着项目继续工作')).toBeInTheDocument();
  });
});
