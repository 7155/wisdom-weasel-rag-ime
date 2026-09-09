import { describe, expect, it, vi } from 'vitest';
import { createExtensionHostRegistry } from './host-registry';

describe('product extension host bindings', () => {
  const component = () => null;

  it('is lazy and returns the selected module unchanged', async () => {
    const registry = createExtensionHostRegistry<{ default: typeof component }>();
    const module = { default: component };
    const loader = vi.fn(async () => module);
    registry.register('lab-html', loader);
    expect(loader).not.toHaveBeenCalled();
    expect(await registry.load('lab-html')).toBe(module);
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it('fails explicitly when the product did not bind a host', async () => {
    const registry = createExtensionHostRegistry();
    await expect(registry.load('lab-html')).rejects.toThrow('is not registered');
  });

  it('allows repeated bootstrap with the same loader', async () => {
    const registry = createExtensionHostRegistry();
    const loader = async () => ({ default: component });
    registry.register('lab-html', loader);
    expect(() => registry.register('lab-html', loader)).not.toThrow();
    expect((await registry.load('lab-html')).default).toBe(component);
  });

  it('rejects silent replacement and preserves the original binding', async () => {
    const registry = createExtensionHostRegistry();
    const first = async () => ({ default: component });
    registry.register('lab-html', first);
    expect(() => registry.register('lab-html', async () => ({ default: () => null })))
      .toThrow('already registered');
    expect((await registry.load('lab-html')).default).toBe(component);
  });

  it.each(['', 'Lab HTML', '../lab', '__proto__', 'x'.repeat(65)])('rejects invalid host kind %j', (kind) => {
    const registry = createExtensionHostRegistry();
    expect(() => registry.register(kind, async () => ({ default: component }))).toThrow('Invalid');
  });

  it.each([null, {}, { default: 'not a component' }])('rejects invalid module %j', async (value) => {
    const registry = createExtensionHostRegistry();
    registry.register('lab-html', async () => value as { default: unknown });
    await expect(registry.load('lab-html')).rejects.toThrow('does not export');
  });

  it('allows a later retry after a rejected load', async () => {
    const registry = createExtensionHostRegistry();
    const loader = vi.fn()
      .mockRejectedValueOnce(new Error('chunk unavailable'))
      .mockResolvedValueOnce({ default: component });
    registry.register('lab-html', loader);
    await expect(registry.load('lab-html')).rejects.toThrow('chunk unavailable');
    expect((await registry.load('lab-html')).default).toBe(component);
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('keeps separate registry instances independent', async () => {
    const first = createExtensionHostRegistry();
    const second = createExtensionHostRegistry();
    first.register('lab-html', async () => ({ default: component }));
    await expect(second.load('lab-html')).rejects.toThrow('is not registered');
  });
});
