import { createContext, useContext, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

const PawWindowChromeContext = createContext<HTMLElement | null>(null);

export function PawWindowChromeProvider({ children, target }: { children: ReactNode; target: HTMLElement | null }) {
  return <PawWindowChromeContext.Provider value={target}>{children}</PawWindowChromeContext.Provider>;
}

export function PawWindowChromePortal({ children }: { children: ReactNode }) {
  const target = useContext(PawWindowChromeContext);
  return target ? createPortal(children, target) : null;
}

export function usePawWindowChromeTarget(): HTMLElement | null {
  return useContext(PawWindowChromeContext);
}
