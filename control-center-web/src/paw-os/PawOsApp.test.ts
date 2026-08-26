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

  it('lets an Agent deep link replace a previously bound Session target', () => {
    const store = createPawDesktopStore('agent', '/agent?session=session-old');
    store.getState().bindAgentMain('agent', {
      kind: 'session',
      id: 'session-old',
      title: '旧 Session',
    });
    window.location.hash = '#/rooms?room=room-preview';

    syncPawOsRoute(store);

    expect(store.getState().windows.agent).toMatchObject({
      initialRoute: '/rooms?room=room-preview',
      title: 'Agent',
    });
    expect(store.getState().windows.agent?.target).toBeUndefined();
  });
});
