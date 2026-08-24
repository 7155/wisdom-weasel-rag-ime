import { cleanup, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ThemeProvider, useTheme } from './themes';

describe('ThemeProvider', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => {
    cleanup();
    delete document.documentElement.dataset.theme;
    document.documentElement.style.removeProperty('color-scheme');
  });

  it('can force the PAWOS surface light without overwriting the saved legacy preference', () => {
    window.localStorage.setItem('rag-ime-control-theme', 'dark');
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ThemeProvider forcedTheme="light">{children}</ThemeProvider>
    );

    const { result } = renderHook(() => useTheme(), { wrapper });

    expect(result.current.resolvedTheme).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(window.localStorage.getItem('rag-ime-control-theme')).toBe('dark');
  });
});
