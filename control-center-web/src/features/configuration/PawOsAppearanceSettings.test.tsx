import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { PAW_OS_THEME_STORAGE_KEY, PawOsAppearanceProvider } from '@/design/paw-os-themes';
import { PawOsAppearanceSettings } from './PawOsAppearanceSettings';

describe('PAWOS appearance settings', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(cleanup);

  it('offers the three signature themes in Settings and persists the choice', async () => {
    const user = userEvent.setup();
    render(
      <PawOsAppearanceProvider>
        <PawOsAppearanceSettings />
      </PawOsAppearanceProvider>,
    );

    const choices = screen.getAllByRole('radio');
    expect(choices).toHaveLength(3);
    expect(screen.getByRole('radio', { name: /冰川玻璃/ })).toBeChecked();

    await user.click(screen.getByRole('radio', { name: /蓝图系统/ }));

    expect(screen.getByRole('radio', { name: /蓝图系统/ })).toBeChecked();
    expect(window.localStorage.getItem(PAW_OS_THEME_STORAGE_KEY)).toBe('blueprint');
  });
});
