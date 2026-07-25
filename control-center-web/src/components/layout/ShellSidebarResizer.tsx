import { GripVertical } from 'lucide-react';
import { useEffect, useRef } from 'react';

const DEFAULT_SIZE = 220;
const MIN_SIZE = 196;
const MAX_SIZE = 280;
const STORAGE_KEY = 'rag-ime-control-sidebar-width';

function clamp(value: number): number {
  return Math.min(MAX_SIZE, Math.max(MIN_SIZE, Math.round(value)));
}

export function ShellSidebarResizer() {
  const handleRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handle = handleRef.current;
    const shell = handle?.closest<HTMLElement>('.control-shell');
    if (!handle || !shell) return;
    const stored = readStoredSize();
    applySize(shell, handle, stored ?? DEFAULT_SIZE);
  }, []);

  function currentSize(): number {
    return Number(handleRef.current?.getAttribute('aria-valuenow')) || DEFAULT_SIZE;
  }

  function setSize(value: number, persist = false): void {
    const handle = handleRef.current;
    const shell = handle?.closest<HTMLElement>('.control-shell');
    if (!handle || !shell) return;
    const size = clamp(value);
    applySize(shell, handle, size);
    if (persist) storeSize(size);
  }

  return (
    <div
      ref={handleRef}
      aria-label="调整主导航宽度"
      aria-orientation="vertical"
      aria-valuemax={MAX_SIZE}
      aria-valuemin={MIN_SIZE}
      aria-valuenow={DEFAULT_SIZE}
      aria-valuetext={`${DEFAULT_SIZE} 像素`}
      className="shell-sidebar-resizer"
      role="separator"
      tabIndex={0}
      onDoubleClick={() => setSize(DEFAULT_SIZE, true)}
      onKeyDown={(event) => {
        if (event.key === 'Home' || event.key === 'End') {
          event.preventDefault();
          setSize(event.key === 'Home' ? MIN_SIZE : MAX_SIZE, true);
          return;
        }
        const direction = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0;
        if (!direction) return;
        event.preventDefault();
        setSize(currentSize() + direction * (event.shiftKey ? 24 : 8), true);
      }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        const handle = event.currentTarget;
        const shell = handle.closest<HTMLElement>('.control-shell');
        if (!shell) return;
        event.preventDefault();
        handle.focus();
        handle.setPointerCapture(event.pointerId);
        shell.dataset.resizingSidebar = 'true';
        const startCoordinate = event.clientX;
        const startSize = currentSize();
        const onPointerMove = (pointerEvent: PointerEvent) => {
          setSize(startSize + pointerEvent.clientX - startCoordinate);
        };
        const onPointerEnd = () => {
          handle.removeEventListener('pointermove', onPointerMove);
          handle.removeEventListener('pointerup', onPointerEnd);
          handle.removeEventListener('pointercancel', onPointerEnd);
          delete shell.dataset.resizingSidebar;
          storeSize(currentSize());
        };
        handle.addEventListener('pointermove', onPointerMove);
        handle.addEventListener('pointerup', onPointerEnd);
        handle.addEventListener('pointercancel', onPointerEnd);
      }}
    >
      <GripVertical aria-hidden="true" size={12} />
    </div>
  );
}

function applySize(shell: HTMLElement, handle: HTMLElement, value: number): void {
  const size = clamp(value);
  shell.style.setProperty('--sidebar-wide', `${size}px`);
  handle.setAttribute('aria-valuenow', String(size));
  handle.setAttribute('aria-valuetext', `${size} 像素`);
  if (size <= MIN_SIZE) handle.dataset.clamped = 'min';
  else if (size >= MAX_SIZE) handle.dataset.clamped = 'max';
  else delete handle.dataset.clamped;
}

function readStoredSize(): number | null {
  try {
    const value = Number(window.localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(value) && value > 0 ? clamp(value) : null;
  } catch {
    return null;
  }
}

function storeSize(size: number): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(size));
  } catch {
    // Resizing remains available when storage is disabled.
  }
}
