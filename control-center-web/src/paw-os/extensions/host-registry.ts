/** Product-selected view loaders, not Package activation or execution state. */
export type ExtensionHostLoader<TModule> = () => Promise<TModule>;

export function createExtensionHostRegistry<TModule extends { default: unknown }>() {
  const loaders = new Map<string, ExtensionHostLoader<TModule>>();

  return {
    /** Bootstrap may repeat the same binding, but cannot silently replace it. */
    register(kind: string, loader: ExtensionHostLoader<TModule>): void {
      if (!/^[a-z][a-z0-9-]{0,63}$/u.test(kind)) {
        throw new Error(`Invalid extension host kind: ${kind}`);
      }
      if (typeof loader !== 'function') {
        throw new TypeError(`Extension host ${kind} requires a loader`);
      }
      const current = loaders.get(kind);
      if (current && current !== loader) {
        throw new Error(`Extension host ${kind} is already registered`);
      }
      loaders.set(kind, loader);
    },

    async load(kind: string): Promise<TModule> {
      const loader = loaders.get(kind);
      if (!loader) {
        throw new Error(`Extension host ${kind} is not registered`);
      }
      // Do not cache a rejected promise: the existing recovery UI may retry.
      // Native dynamic import remains responsible for module caching.
      const module = await loader();
      if (typeof module !== 'object' || module === null || typeof module.default !== 'function') {
        throw new Error(`Extension host ${kind} does not export a React component`);
      }
      return module;
    },
  };
}
