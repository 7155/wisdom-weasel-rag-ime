import { afterEach, describe, expect, it } from 'vitest';
import { createPawDesktopStore } from './runtime/desktop-store';
import { syncPawOsRoute } from './PawOsApp';

afterEach(() => {
  window.location.hash = '';
});

describe('PAWOS route bridge', () => {
  it('reconciles an existing App window to the current hash on mount', () => {
    const store = createPawDesktopStore('input-studio', '/input');
    window.location.hash = '#/input?view=lexicon';

    syncPawOsRoute(store);

    expect(store.getState().windows['input-studio']).toMatchObject({
      initialRoute: '/input?view=lexicon',
    });
  });
});
