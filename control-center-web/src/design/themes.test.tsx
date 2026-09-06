import { act, cleanup, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ThemeProvider, useTheme } from './themes';

const STORAGE_KEY = 'rag-ime-control-theme';

describe('ThemeProvider', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => {
    cleanup();
    delete document.documentElement.dataset.theme;
    document.documentElement.style.removeProperty('color-scheme');
  });

  it('can force the PAWOS surface light without overwriting the saved legacy preference', () => {
    window.localStorage.setItem(STORAGE_KEY, 'dark');
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ThemeProvider forcedTheme="light">{children}</ThemeProvider>
    );

    const { result } = renderHook(() => useTheme(), { wrapper });

    expect(result.current.resolvedTheme).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('dark');
  });

  it('syncs a same-key localStorage event without echoing it back to storage', () => {
    const wrapper = ({ children }: { children: ReactNode }) => <ThemeProvider>{children}</ThemeProvider>;
    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => {
      window.dispatchEvent(new StorageEvent('storage', {
        key: STORAGE_KEY,
        newValue: 'dark',
        storageArea: window.localStorage,
      }));
    });

    expect(result.current.preference).toBe('dark');
    expect(result.current.resolvedTheme).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('treats a removed preference as system and ignores unrelated keys or storage areas', () => {
    window.localStorage.setItem(STORAGE_KEY, 'dark');
    const wrapper = ({ children }: { children: ReactNode }) => <ThemeProvider>{children}</ThemeProvider>;
    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => {
      window.dispatchEvent(new StorageEvent('storage', {
        key: 'unrelated-setting',
        newValue: 'light',
        storageArea: window.localStorage,
      }));
      window.dispatchEvent(new StorageEvent('storage', {
        key: STORAGE_KEY,
        newValue: 'light',
        storageArea: window.sessionStorage,
      }));
    });
    expect(result.current.preference).toBe('dark');

    act(() => {
      window.dispatchEvent(new StorageEvent('storage', {
        key: STORAGE_KEY,
        newValue: null,
        storageArea: window.localStorage,
      }));
    });

    expect(result.current.preference).toBe('system');
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('dark');
  });

  it('returns to system when another window clears localStorage without writing back', () => {
    window.localStorage.setItem(STORAGE_KEY, 'dark');
    const wrapper = ({ children }: { children: ReactNode }) => <ThemeProvider>{children}</ThemeProvider>;
    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => {
      window.localStorage.clear();
      window.dispatchEvent(new StorageEvent('storage', {
        key: null,
        newValue: null,
        storageArea: window.localStorage,
      }));
    });

    expect(result.current.preference).toBe('system');
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});
