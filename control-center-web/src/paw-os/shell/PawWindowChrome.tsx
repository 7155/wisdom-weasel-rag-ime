import { createContext, useContext, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

const PawWindowLeadingChromeContext = createContext<HTMLElement | null>(null);
const PawWindowTrailingChromeContext = createContext<HTMLElement | null>(null);

export function PawWindowChromeProvider({
  children,
  leading = null,
  trailing = null,
}: {
  children: ReactNode;
  leading?: HTMLElement | null;
  trailing?: HTMLElement | null;
}) {
  return (
    <PawWindowLeadingChromeContext.Provider value={leading}>
      <PawWindowTrailingChromeContext.Provider value={trailing}>
        {children}
      </PawWindowTrailingChromeContext.Provider>
    </PawWindowLeadingChromeContext.Provider>
  );
}

export function PawWindowChromePortal({ children }: { children: ReactNode }) {
  const target = useContext(PawWindowTrailingChromeContext);
  return target ? createPortal(children, target) : null;
}

/** Leading titlebar slot, immediately after the traffic lights — for controls
 * that open a leading-edge surface, so the control and the surface it reveals
 * sit on the same side. */
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
