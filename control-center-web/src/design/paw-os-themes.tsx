import {
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from 'react';

export type PawOsTheme = 'glacier' | 'ink-paper' | 'blueprint';

export type PawOsThemeDefinition = {
  id: PawOsTheme;
  label: string;
  description: string;
};

type PawOsAppearanceValue = {
  theme: PawOsTheme;
  setTheme: (theme: PawOsTheme) => void;
};

export const PAW_OS_THEME_STORAGE_KEY = 'paw-os.appearance.theme';

export const pawOsThemes: readonly PawOsThemeDefinition[] = [
  {
    id: 'glacier',
    label: '冰川玻璃',
    description: '明亮、通透，适合主窗口与多窗口协作。',
  },
  {
    id: 'ink-paper',
    label: '墨纸工作台',
    description: '低干扰的纸面层次，适合阅读和长时间工作。',
  },
  {
    id: 'blueprint',
    label: '蓝图系统',
    description: '清晰的网格与技术标记，适合任务和工作流。',
  },
] as const;

const appearanceListeners = new Set<() => void>();

export function PawOsAppearanceProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

export function usePawOsAppearance(): PawOsAppearanceValue {
  const theme = useSyncExternalStore(
    subscribeToAppearance,
    readStoredTheme,
    (): PawOsTheme => 'blueprint',
  );
  return useMemo(() => ({ theme, setTheme: setPawOsTheme }), [theme]);
}

function readStoredTheme(): PawOsTheme {
  return 'blueprint';
}

function setPawOsTheme(_next: PawOsTheme): void {
  window.localStorage.setItem(PAW_OS_THEME_STORAGE_KEY, 'blueprint');
  appearanceListeners.forEach((listener) => listener());
}

function subscribeToAppearance(listener: () => void): () => void {
  appearanceListeners.add(listener);
  const handleStorage = (event: StorageEvent) => {
    if (event.key === PAW_OS_THEME_STORAGE_KEY) listener();
  };
  window.addEventListener('storage', handleStorage);
  return () => {
    appearanceListeners.delete(listener);
    window.removeEventListener('storage', handleStorage);
  };
}
