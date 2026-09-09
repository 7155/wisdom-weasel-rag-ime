import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type Ref } from 'react';
import './app-sidebar.css';

const sidebarEvent = 'pawos:app-sidebar-preference';
const sidebarKey = (appId: string) => `pawos.app-sidebar.v1:${appId}`;

function readCollapsed(key: string, fallback: boolean): boolean {
  try {
    const value = window.localStorage.getItem(key);
    return value === 'collapsed' ? true : value === 'expanded' ? false : fallback;
  } catch {
    return fallback;
  }
}

/** App presentation only: each App keeps its own preference across windows. */
export function useAppSidebar(appId: string, defaultCollapsed = false) {
  const key = sidebarKey(appId);
  const [preference, setPreference] = useState(() => ({ key, collapsed: readCollapsed(key, defaultCollapsed) }));
  const collapsed = preference.key === key ? preference.collapsed : readCollapsed(key, defaultCollapsed);
  const controlsId = `paw-app-sidebar-${useId()}`;
  const toggleRef = useRef<HTMLButtonElement>(null);
  const contentRef = useRef<HTMLElement | null>(null);
  const bindContent = useCallback((node: HTMLElement | null) => { contentRef.current = node; }, []);

  useEffect(() => {
    setPreference({ key, collapsed: readCollapsed(key, defaultCollapsed) });
    const onStorage = (event: StorageEvent) => {
      if (event.key === key || event.key === null) setPreference({ key, collapsed: readCollapsed(key, defaultCollapsed) });
    };
    const onPreference = (event: Event) => {
      const detail = (event as CustomEvent<{ key: string; collapsed: boolean }>).detail;
      if (detail?.key === key && typeof detail.collapsed === 'boolean') setPreference({ key, collapsed: detail.collapsed });
    };
    window.addEventListener('storage', onStorage);
    window.addEventListener(sidebarEvent, onPreference);
    return () => {
      window.removeEventListener('storage', onStorage);
      window.removeEventListener(sidebarEvent, onPreference);
    };
  }, [defaultCollapsed, key]);

  useLayoutEffect(() => {
    if (collapsed && contentRef.current?.contains(document.activeElement)) toggleRef.current?.focus();
  }, [collapsed]);

  const setCollapsed = useCallback((next: boolean) => {
    setPreference({ key, collapsed: next });
    try { window.localStorage.setItem(key, next ? 'collapsed' : 'expanded'); } catch { /* Keep the current window usable without storage. */ }
    window.dispatchEvent(new CustomEvent(sidebarEvent, { detail: { key, collapsed: next } }));
  }, [key]);

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Escape' || event.defaultPrevented || collapsed) return;
    event.preventDefault();
    event.stopPropagation();
    setCollapsed(true);
    toggleRef.current?.focus();
  };

  return {
    collapsed,
    controlsId,
    setCollapsed,
    toggleRef,
    contentProps: {
      id: controlsId,
      ref: bindContent,
      hidden: collapsed,
      inert: collapsed,
      // Author display rules for nav/flex must never override hidden content.
      style: collapsed ? { display: 'none' } : undefined,
      onKeyDown,
    },
  };
}

export function AppSidebarToggle({ collapsed, controlsId, label = '侧边栏', onToggle, toggleRef, className = '' }: {
  collapsed: boolean;
  controlsId: string;
  label?: string;
  onToggle: () => void;
  toggleRef?: Ref<HTMLButtonElement>;
  className?: string;
}) {
  const name = `${collapsed ? '展开' : '收起'}${label}`;
  const Icon = collapsed ? PanelLeftOpen : PanelLeftClose;
  return <button
    aria-controls={controlsId}
    aria-expanded={!collapsed}
    aria-label={name}
    className={`paw-app-sidebar-toggle ${className}`.trim()}
    onClick={onToggle}
    ref={toggleRef}
    title={name}
    type="button"
  ><Icon aria-hidden="true" size={17} /></button>;
}
