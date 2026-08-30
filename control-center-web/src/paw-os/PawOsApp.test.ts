import { afterEach, describe, expect, it } from 'vitest';
import { pawExtensionApps } from './extensions/registry';
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

  it('fails closed for an Extension App initial hash until its Package is enabled', () => {
    const extension = pawExtensionApps[0]!;
    window.location.hash = extension.route;
    const store = createPawDesktopStore(extension.id, extension.route);

    expect(store.getState().windows[extension.id]).toBeUndefined();

    store.getState().setExtensionAppGate('ready', new Set([extension.id]));
    syncPawOsRoute(store);

    expect(store.getState().windows[extension.id]).toMatchObject({
      appId: extension.id,
      initialRoute: extension.route,
    });
  });

  it('does not reopen an Extension App through the RouteBridge while Runtime is unavailable', () => {
    const extension = pawExtensionApps[0]!;
    window.location.hash = extension.route;
    const store = createPawDesktopStore();

    store.getState().setExtensionAppGate('unavailable', new Set([extension.id]));
    syncPawOsRoute(store);

    expect(store.getState().windows[extension.id]).toBeUndefined();
  });
});
