import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MotionProvider } from '@/design/motion';
import { PAW_OS_THEME_STORAGE_KEY, PawOsAppearanceProvider } from '@/design/paw-os-themes';
import { pawOsAppRegistry } from '@/features/paw-os/model/app-registry';
import { PawOsAppearanceSettings } from './PawOsAppearanceSettings';

function renderAppearance() {
  return render(
    <PawOsAppearanceProvider>
      <MotionProvider>
        <PawOsAppearanceSettings />
      </MotionProvider>
    </PawOsAppearanceProvider>,
  );
}

describe('PAWOS appearance settings', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it('presents the single bright theme without inventing deferred variants', () => {
    window.localStorage.setItem(PAW_OS_THEME_STORAGE_KEY, 'ink-paper');
    renderAppearance();

    const themes = screen.getByRole('radiogroup', { name: 'PAWOS 主题' });
    expect(within(themes).getAllByRole('radio')).toHaveLength(1);
    expect(within(themes).getByRole('radio', { name: /默认明亮/ })).toBeChecked();
    expect(screen.queryByRole('radio', { name: /墨纸工作台|蓝图系统|冰川玻璃/ })).not.toBeInTheDocument();
  });

  it('saves the motion preference locally and reports the effective result', async () => {
    const user = userEvent.setup();
    renderAppearance();

    const motion = screen.getByRole('radiogroup', { name: '界面动效' });
    expect(within(motion).getAllByRole('radio')).toHaveLength(3);
    expect(within(motion).getByRole('radio', { name: /跟随系统/ })).toBeChecked();
    expect(screen.getByRole('status')).toHaveTextContent('当前生效：完整动效（跟随系统设置）');

    await user.click(within(motion).getByRole('radio', { name: /减少动效/ }));

    expect(within(motion).getByRole('radio', { name: /减少动效/ })).toBeChecked();
    expect(window.localStorage.getItem('rag-ime-control-motion')).toBe('reduce');
    expect(screen.getByRole('status')).toHaveTextContent('当前生效：减少动效');
  });

  it('keeps the system reduce-motion request effective when full motion is selected', async () => {
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: query === '(prefers-reduced-motion: reduce)',
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    const user = userEvent.setup();
    renderAppearance();

    const motion = screen.getByRole('radiogroup', { name: '界面动效' });
    await user.click(within(motion).getByRole('radio', { name: /完整动效/ }));

    expect(within(motion).getByRole('radio', { name: /完整动效/ })).toBeChecked();
    expect(screen.getByRole('status')).toHaveTextContent('当前生效：减少动效（系统设置优先）');
    expect(document.documentElement).toHaveAttribute('data-reduce-motion', 'true');
  });

  it('lists every registered App next to its identity swatch', () => {
    renderAppearance();

    const apps = screen.getByRole('list', { name: 'App 身份色' });
    const items = within(apps).getAllByRole('listitem');
    expect(items).toHaveLength(pawOsAppRegistry.length);
    expect(within(apps).getByText('Agent')).toBeInTheDocument();
    expect(within(apps).getByText('System Settings')).toBeInTheDocument();
    for (const item of items) expect(item.querySelector('i')).not.toBeNull();
  });
});
