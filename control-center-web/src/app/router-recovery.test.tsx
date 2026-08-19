import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LegacyPluginsRedirect, RouteErrorBoundary, RouteLoading } from './router';

function BrokenPage(): never {
  throw new Error('private implementation detail');
}

describe('route recovery', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('keeps route failures inside a product recovery surface', async () => {
    const errorLog = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const user = userEvent.setup();
    const testRouter = createMemoryRouter([
      {
        errorElement: <RouteErrorBoundary />,
        children: [
          { path: '/', element: <BrokenPage /> },
          { path: '/overview', element: <main>概览已打开</main> },
        ],
      },
    ]);

    render(<RouterProvider router={testRouter} />);

    expect(await screen.findByRole('heading', { name: '页面没有打开' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新打开' })).toHaveFocus();
    expect(screen.queryByText('private implementation detail')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '返回概览' }));
    expect(await screen.findByText('概览已打开')).toBeInTheDocument();
    errorLog.mockRestore();
  });

  it('turns an unusually slow initial route into an actionable state', async () => {
    vi.useFakeTimers();
    render(<RouteLoading />);

    expect(screen.getByText('正在打开')).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTime(8_000));

    expect(screen.getByText('打开得有点久')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新载入' })).toBeInTheDocument();
  });

  it('redirects the retired plugin route without dropping session context', async () => {
    const testRouter = createMemoryRouter([
      { path: '/plugins', element: <LegacyPluginsRedirect /> },
      { path: '/roles', element: <LocationProbe /> },
    ], { initialEntries: ['/plugins?sessionId=session-project'] });

    render(<RouterProvider router={testRouter} />);

    expect(await screen.findByTestId('redirect-location')).toHaveTextContent('/roles?sessionId=session-project');
  });
});

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="redirect-location">{`${location.pathname}${location.search}`}</span>;
}
