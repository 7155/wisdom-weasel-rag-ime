import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';

export type PawContextMenuItem = {
  id: string;
  label: string;
  icon?: ReactNode;
  /* Real keyboard bindings only, rendered as a dimmed right-aligned hint the
   * way native menus print ⌘H — never a decorative chord for a verb that has
   * no binding. */
  shortcut?: string;
  danger?: boolean;
  disabled?: boolean;
  separatorBefore?: boolean;
  action: () => void;
};

export type PawContextMenuCloseReason = 'action' | 'keyboard' | 'pointer' | 'blur';

/* Menus measure themselves after mount instead of trusting a size estimate:
 * the real box decides the clamp, and near the bottom edge the menu flips to
 * open upward from the anchor like a native menu. The entrance rises from the
 * corner the menu grew out of (--paw-menu-origin / --paw-menu-rise), so a
 * flipped menu reads as unfolding from the pointer, not sliding past it. */
export function PawContextMenu({
  anchor,
  ariaLabel,
  items,
  onClose,
  onHorizontalNavigate,
  x,
  y,
}: {
  anchor?: { readonly current: HTMLElement | null };
  ariaLabel: string;
  items: readonly PawContextMenuItem[];
  onClose: (reason: PawContextMenuCloseReason) => void;
  /* macOS menu-bar behaviour: ArrowLeft/ArrowRight walk to the neighbouring
   * menu while one is open. Only menu-bar menus pass this; context menus
   * keep the arrows for future submenu use. */
  onHorizontalNavigate?: (direction: -1 | 1) => void;
  x: number;
  y: number;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState<{ left: number; top: number; origin: string; rise: number } | null>(null);

  useLayoutEffect(() => {
    const menu = menuRef.current;
    if (!menu) return;
    const rect = menu.getBoundingClientRect();
    // jsdom reports a zero box; fall back to the estimate so tests and the
    // first paint still land inside the viewport.
    const width = rect.width || 220;
    const height = rect.height || items.length * 38 + 20;
    const left = Math.max(8, Math.min(x, window.innerWidth - width - 8));
    const fitsBelow = y + height + 8 <= window.innerHeight;
    // The 48px floor keeps every menu below the menu bar, flipped or not.
    const top = fitsBelow ? Math.max(48, y) : Math.max(48, y - height);
    setPlacement({
      left,
      top,
      origin: `${x - left > width / 2 ? '100%' : '0'} ${fitsBelow ? '0' : '100%'}`,
      rise: fitsBelow ? 4 : -4,
    });
  }, [items.length, x, y]);

  useEffect(() => {
    const menu = menuRef.current;
    menu?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
    const dismiss = (event: PointerEvent) => {
      const target = event.target as Node;
      if (menu?.contains(target) || anchor?.current?.contains(target)) return;
      onClose('pointer');
    };
    const blur = () => onClose('blur');
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
      event.stopPropagation();
      onClose('keyboard');
      return;
    }
    if ((event.key === 'ArrowLeft' || event.key === 'ArrowRight') && onHorizontalNavigate) {
      event.preventDefault();
      onHorizontalNavigate(event.key === 'ArrowRight' ? 1 : -1);
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

  // Hidden until the measured clamp lands in the same pre-paint commit, so an
  // edge menu never flashes at the pointer and then jumps.
  const style: CSSProperties = placement
    ? {
      left: placement.left,
      top: placement.top,
      '--paw-menu-origin': placement.origin,
      '--paw-menu-rise': `${placement.rise}px`,
    } as CSSProperties
    : { left: x, top: y, visibility: 'hidden' };

  return (
    <div
      aria-label={ariaLabel}
      className="paw-context-menu"
      onContextMenu={(event) => event.preventDefault()}
      onKeyDown={handleKeyDown}
      ref={menuRef}
      role="menu"
      style={style}
    >
      {items.map((item) => (
        <div className="paw-context-menu__row" data-separator={item.separatorBefore || undefined} key={item.id}>
          <button
            data-danger={item.danger || undefined}
            disabled={item.disabled}
            onClick={() => {
              item.action();
              onClose('action');
            }}
            role="menuitem"
            type="button"
          >
            <span aria-hidden="true">{item.icon}</span>
            <strong>{item.label}</strong>
            {item.shortcut ? <kbd aria-hidden="true">{item.shortcut}</kbd> : null}
          </button>
        </div>
      ))}
    </div>
  );
}
