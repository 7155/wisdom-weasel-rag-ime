import { createContext, useContext, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

const PawWindowLeadingChromeContext = createContext<HTMLElement | null>(null);
const PawWindowTrailingChromeContext = createContext<HTMLElement | null>(null);

export function PawWindowChromeProvider({
  children,
  leading = null,
  target = null,
  trailing = null,
}: {
  children: ReactNode;
  leading?: HTMLElement | null;
  /** @deprecated use `trailing` */
  target?: HTMLElement | null;
  trailing?: HTMLElement | null;
}) {
  const trailingTarget = trailing ?? target ?? null;
  return (
    <PawWindowLeadingChromeContext.Provider value={leading ?? null}>
      <PawWindowTrailingChromeContext.Provider value={trailingTarget}>
        {children}
      </PawWindowTrailingChromeContext.Provider>
    </PawWindowLeadingChromeContext.Provider>
  );
}

export function PawWindowChromePortal({ children }: { children: ReactNode }) {
  const target = useContext(PawWindowTrailingChromeContext);
  return target ? createPortal(children, target) : null;
}

/** Left titlebar slot — controls that open left-side surfaces (e.g. work-record rail). */
export function PawWindowLeadingPortal({ children }: { children: ReactNode }) {
  const target = useContext(PawWindowLeadingChromeContext);
  return target ? createPortal(children, target) : null;
}

export function usePawWindowChromeTarget(): HTMLElement | null {
  return useContext(PawWindowTrailingChromeContext);
}

export function usePawWindowLeadingChromeTarget(): HTMLElement | null {
  return useContext(PawWindowLeadingChromeContext);
}
