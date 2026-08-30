import { act, cleanup, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import pawOsStyles from '@/paw-os/styles/paw-os.css?raw';
import pawOsMotionStyles from '@/paw-os/styles/paw-os-motion.css?raw';
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

  it('uses the square-corner Blueprint theme by default and ignores an unsupported stored value', () => {
    window.localStorage.setItem(PAW_OS_THEME_STORAGE_KEY, 'slate');
    const { result } = renderHook(() => usePawOsAppearance(), { wrapper });

    expect(result.current.theme).toBe('blueprint');
  });

  it('keeps the current OS on the single bright baseline while theme variants are deferred', () => {
    window.localStorage.setItem(PAW_OS_THEME_STORAGE_KEY, 'ink-paper');
    const { result } = renderHook(() => usePawOsAppearance(), { wrapper });

    expect(result.current.theme).toBe('blueprint');
  });

  it('persists PAWOS appearance without overwriting the legacy theme key', () => {
    window.localStorage.setItem('rag-ime-control-theme', 'dark');
    const { result } = renderHook(() => usePawOsAppearance(), { wrapper });

    act(() => result.current.setTheme('blueprint'));

    expect(window.localStorage.getItem(PAW_OS_THEME_STORAGE_KEY)).toBe('blueprint');
    expect(window.localStorage.getItem('rag-ime-control-theme')).toBe('dark');
  });

  it('keeps the compatibility theme id from restoring retired square shell visuals', () => {
    const baseTheme = pawOsStyles.match(/\.paw-desktop-root\s*\{(?<body>[\s\S]*?)\n\}/)?.groups?.body;

    expect(baseTheme).toContain('--paw-panel: #ffffff');
    expect(baseTheme).toContain('--paw-accent: #2563eb');
    // Easing tokens have exactly one definition site: the motion authority.
    // The structure owner consumes them but never re-declares them.
    expect(baseTheme).not.toContain('--paw-ease-out:');
    expect(baseTheme).not.toContain('--paw-ease-in-out:');
    expect(pawOsMotionStyles.match(/--paw-ease-out:/g)).toHaveLength(1);
    expect(pawOsMotionStyles.match(/--paw-ease-in-out:/g)).toHaveLength(1);
    expect(pawOsMotionStyles).toContain('--paw-ease-out: cubic-bezier(.23, 1, .32, 1)');
    expect(pawOsStyles).not.toContain(".paw-desktop-root[data-paw-theme='glacier']");
    expect(pawOsStyles).not.toContain(".paw-desktop-root[data-paw-theme='ink-paper']");
    expect(pawOsStyles).not.toContain(".paw-desktop-root[data-paw-theme='blueprint']");
    expect(pawOsStyles).not.toContain('--paw-radius: 0px');
    expect(pawOsStyles).not.toContain('.app-shell');
  });

});
