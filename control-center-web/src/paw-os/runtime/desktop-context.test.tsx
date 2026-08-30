import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PawDesktopProvider, usePawDesktopApi, usePawDesktopStore } from './desktop-context';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe('PawDesktopProvider persistence safety', () => {
  it('falls back to a clean desktop when the saved JSON is corrupt', () => {
    window.localStorage.setItem('pawos.desktop.v1', '{not-json');

    expect(() => render(<PawDesktopProvider><DesktopProbe /></PawDesktopProvider>)).not.toThrow();
    expect(screen.getByTestId('window-count')).toHaveTextContent('0');
  });

  it('keeps interaction alive when the browser refuses a snapshot write', () => {
    vi.useFakeTimers();
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('quota', 'QuotaExceededError'); });
    render(<PawDesktopProvider><DesktopProbe /></PawDesktopProvider>);

    fireEvent.click(screen.getByRole('button', { name: '打开 Agent' }));
    expect(screen.getByTestId('window-count')).toHaveTextContent('1');
    expect(() => act(() => vi.advanceTimersByTime(250))).not.toThrow();
    expect(screen.getByTestId('window-count')).toHaveTextContent('1');
  });

  it('restores only known unique Dock App identities from the saved snapshot', () => {
    window.localStorage.setItem('pawos.desktop.v1', JSON.stringify({
      windows: {},
      stack: [],
      activeWindowId: null,
      dockAppIds: ['system-settings', 'unknown-app', 'system-settings', 'agent'],
    }));

    render(<PawDesktopProvider><DesktopProbe /></PawDesktopProvider>);

    expect(screen.getByTestId('dock-apps')).toHaveTextContent('system-settings,agent');
  });
});

function DesktopProbe() {
  const api = usePawDesktopApi();
  const count = usePawDesktopStore((state) => Object.keys(state.windows).length);
  const dockApps = usePawDesktopStore((state) => state.dockAppIds.join(','));
  return <><button onClick={() => api.getState().openApp('agent')} type="button">打开 Agent</button><output data-testid="window-count">{count}</output><output data-testid="dock-apps">{dockApps}</output></>;
}
