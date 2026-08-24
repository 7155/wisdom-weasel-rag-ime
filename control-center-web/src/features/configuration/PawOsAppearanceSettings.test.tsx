import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { PAW_OS_THEME_STORAGE_KEY, PawOsAppearanceProvider } from '@/design/paw-os-themes';
import { PawOsAppearanceSettings } from './PawOsAppearanceSettings';

describe('PAWOS appearance settings', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(cleanup);

  it('presents one bright default theme while multi-theme work is deferred', () => {
    window.localStorage.setItem(PAW_OS_THEME_STORAGE_KEY, 'ink-paper');
    render(
      <PawOsAppearanceProvider>
        <PawOsAppearanceSettings />
      </PawOsAppearanceProvider>,
    );

    const choices = screen.getAllByRole('radio');
    expect(choices).toHaveLength(1);
    expect(screen.getByRole('radio', { name: /默认明亮/ })).toBeChecked();
    expect(screen.queryByRole('radio', { name: /墨纸工作台|蓝图系统|冰川玻璃/ })).not.toBeInTheDocument();
  });
});
