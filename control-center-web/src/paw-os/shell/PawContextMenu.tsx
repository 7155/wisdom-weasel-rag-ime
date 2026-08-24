import { useEffect, useMemo, useRef, type KeyboardEvent, type ReactNode } from 'react';

export type PawContextMenuItem = {
  id: string;
  label: string;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  separatorBefore?: boolean;
  action: () => void;
};

export function PawContextMenu({
  anchor,
  ariaLabel,
  items,
  onClose,
  x,
  y,
}: {
  anchor?: { readonly current: HTMLElement | null };
  ariaLabel: string;
  items: readonly PawContextMenuItem[];
  onClose: () => void;
  x: number;
  y: number;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const position = useMemo(() => ({
    left: Math.max(8, Math.min(x, window.innerWidth - 248)),
    top: Math.max(48, Math.min(y, window.innerHeight - Math.max(72, items.length * 38 + 20))),
  }), [items.length, x, y]);

  useEffect(() => {
    const menu = menuRef.current;
    menu?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
    const dismiss = (event: PointerEvent) => {
      const target = event.target as Node;
      if (menu?.contains(target) || anchor?.current?.contains(target)) return;
      onClose();
    };
    const blur = () => onClose();
    window.addEventListener('pointerdown', dismiss);
    window.addEventListener('blur', blur);
    return () => {
      window.removeEventListener('pointerdown', dismiss);
      window.removeEventListener('blur', blur);
    };
  }, [anchor, onClose]);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    const enabled = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'),
    );
    const current = enabled.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === 'Escape' || event.key === 'Tab') {
      event.preventDefault();
      onClose();
      return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || enabled.length === 0) return;
    event.preventDefault();
    if (event.key === 'Home') enabled[0]?.focus();
    else if (event.key === 'End') enabled.at(-1)?.focus();
    else {
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      enabled[(current + delta + enabled.length) % enabled.length]?.focus();
    }
  }

  return (
    <div
      aria-label={ariaLabel}
      className="paw-context-menu"
      onContextMenu={(event) => event.preventDefault()}
      onKeyDown={handleKeyDown}
      ref={menuRef}
      role="menu"
      style={position}
    >
      {items.map((item) => (
        <div className="paw-context-menu__row" data-separator={item.separatorBefore || undefined} key={item.id}>
          <button
            data-danger={item.danger || undefined}
            disabled={item.disabled}
            onClick={() => {
              item.action();
              onClose();
            }}
            role="menuitem"
            type="button"
          >
            <span aria-hidden="true">{item.icon}</span>
            <strong>{item.label}</strong>
          </button>
        </div>
      ))}
    </div>
  );
}
