import { act, cleanup, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  PAW_OS_THEME_STORAGE_KEY,
  PawOsAppearanceProvider,
  pawOsThemes,
  usePawOsAppearance,
} from './paw-os-themes';

const wrapper = ({ children }: { children: ReactNode }) => (
  <PawOsAppearanceProvider>{children}</PawOsAppearanceProvider>
);

describe('PAWOS appearance themes', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(cleanup);

  it('exposes exactly the three accepted signature themes', () => {
    expect(pawOsThemes.map((theme) => theme.id)).toEqual([
      'glacier',
      'ink-paper',
      'blueprint',
    ]);
  });

  it('uses Glacier by default and ignores an unsupported stored value', () => {
    window.localStorage.setItem(PAW_OS_THEME_STORAGE_KEY, 'slate');
    const { result } = renderHook(() => usePawOsAppearance(), { wrapper });

    expect(result.current.theme).toBe('glacier');
  });

  it('persists PAWOS appearance without overwriting the legacy theme key', () => {
    window.localStorage.setItem('rag-ime-control-theme', 'dark');
    const { result } = renderHook(() => usePawOsAppearance(), { wrapper });

    act(() => result.current.setTheme('blueprint'));

    expect(window.localStorage.getItem(PAW_OS_THEME_STORAGE_KEY)).toBe('blueprint');
    expect(window.localStorage.getItem('rag-ime-control-theme')).toBe('dark');
  });
});
