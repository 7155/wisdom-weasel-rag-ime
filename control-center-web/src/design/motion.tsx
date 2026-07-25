import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { MotionConfig } from 'motion/react';

export const motionTokens = {
  duration: {
    instant: 0.08,
    press: 0.09,
    fast: 0.14,
    enter: 0.18,
    normal: 0.22,
    panel: 0.22,
    slow: 0.32,
    statusPulse: 0.72,
  },
  distance: { xs: 2, enter: 4, sm: 6, md: 12 },
  easing: {
    standard: [0.22, 1, 0.36, 1] as const,
    press: [0.2, 0.8, 0.3, 1] as const,
    exit: [0.4, 0, 1, 1] as const,
  },
  statusPulse: { iterations: 3 },
} as const;

export type MotionPreference = 'system' | 'reduce' | 'full';

type MotionContextValue = {
  preference: MotionPreference;
  reduceMotion: boolean;
  setPreference: (preference: MotionPreference) => void;
};

const STORAGE_KEY = 'rag-ime-control-motion';
const MotionContext = createContext<MotionContextValue | null>(null);

function getStoredPreference(): MotionPreference {
  if (typeof window === 'undefined') return 'system';
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === 'reduce' || stored === 'full' || stored === 'system' ? stored : 'system';
}

function getSystemPreference(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function MotionProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<MotionPreference>(getStoredPreference);
  const [systemReduceMotion, setSystemReduceMotion] = useState(getSystemPreference);
  const reduceMotion = preference === 'system' ? systemReduceMotion : preference === 'reduce';

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setSystemReduceMotion(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.reduceMotion = String(reduceMotion);
  }, [reduceMotion]);

  const setPreference = useCallback((next: MotionPreference) => {
    setPreferenceState(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  }, []);

  const value = useMemo(
    () => ({ preference, reduceMotion, setPreference }),
    [preference, reduceMotion, setPreference],
  );

  return (
    <MotionContext.Provider value={value}>
      <MotionConfig reducedMotion={reduceMotion ? 'always' : 'never'}>{children}</MotionConfig>
    </MotionContext.Provider>
  );
}

export function useMotionPreference(): MotionContextValue {
  const context = useContext(MotionContext);
  if (!context) throw new Error('useMotionPreference must be used inside MotionProvider');
  return context;
}
