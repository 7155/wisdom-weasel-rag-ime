import { describe, expect, it } from 'vitest';
import {
  PAW_DESKTOP_GRID,
  pawDesktopGridPosition,
  pawDesktopShortcutLayout,
  pawDesktopWorkOriginY,
} from './desktop-grid';

const SHORTCUT_HEIGHT = 86;

describe('PAWOS desktop grid', () => {
  it('keeps all eleven desktop Apps above the first work-file row', () => {
    const layout = pawDesktopShortcutLayout(900);

    expect(layout).toMatchObject({ columns: 7, originY: PAW_DESKTOP_GRID.originY });
    expect(pawDesktopGridPosition(10, layout.columns, layout.originY).y).toBe(
      PAW_DESKTOP_GRID.originY + PAW_DESKTOP_GRID.pitchY,
    );
    expect(pawDesktopWorkOriginY(layout.columns, layout.originY)).toBeGreaterThan(
      pawDesktopGridPosition(10, layout.columns, layout.originY).y + SHORTCUT_HEIGHT,
    );
  });

  it('wraps all eleven desktop Apps into a stable compact grid on narrow screens', () => {
    const layout = pawDesktopShortcutLayout(420);

    expect(layout).toMatchObject({ columns: 3, originY: PAW_DESKTOP_GRID.originY });
    expect(pawDesktopGridPosition(10, layout.columns, layout.originY).y).toBe(
      PAW_DESKTOP_GRID.originY + PAW_DESKTOP_GRID.pitchY * 3,
    );
    expect(pawDesktopWorkOriginY(layout.columns, layout.originY)).toBeGreaterThan(
      pawDesktopGridPosition(10, layout.columns, layout.originY).y + SHORTCUT_HEIGHT,
    );
  });

  it('keeps the wide desktop shortcut row in its established top-left position', () => {
    const layout = pawDesktopShortcutLayout(1440);

    expect(layout.originY).toBe(PAW_DESKTOP_GRID.originY);
    expect(pawDesktopGridPosition(0, layout.columns, layout.originY)).toEqual({ x: 24, y: 24 });
  });
});
