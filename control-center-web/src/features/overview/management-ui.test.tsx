import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { PawOsAppSurfaceProvider } from '@/features/paw-os/surface-context';
import { ManagementPage } from './management-ui';

afterEach(cleanup);

describe('ManagementPage PAWOS surface', () => {
  it('adapts a legacy management route to its owning App window', () => {
    render(
      <PawOsAppSurfaceProvider appId="memory" height={620} width={720}>
        <ManagementPage actions={<button type="button">刷新</button>} description="可追溯的个人记忆" eyebrow="关于我" routeId="memory" title="我的记忆">
          <p>记忆内容</p>
        </ManagementPage>
      </PawOsAppSurfaceProvider>,
    );

    const page = screen.getByRole('main');
    expect(page).toHaveAttribute('data-paw-os-app', 'memory');
    expect(page).toHaveAttribute('data-paw-os-compact', 'true');
    expect(page).toHaveAttribute('data-route-id', 'memory');
    expect(screen.getByRole('heading', { name: '我的记忆' })).toHaveClass('mgmt-sr-only');
    expect(screen.getByRole('toolbar', { name: '我的记忆页面操作' })).toHaveTextContent('刷新');
    expect(screen.queryByText('关于我')).not.toBeInTheDocument();
    expect(screen.queryByText('可追溯的个人记忆')).not.toBeInTheDocument();
  });

  it('keeps the legacy page contract when there is no PAWOS window', () => {
    render(
      <ManagementPage description="系统设置" routeId="configuration" title="设置">
        <p>设置内容</p>
      </ManagementPage>,
    );

    expect(screen.getByRole('main')).not.toHaveAttribute('data-paw-os-app');
  });
});
