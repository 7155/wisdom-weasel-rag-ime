import { describe, expect, it } from 'vitest';
import { pawAppForPath, pawApps } from './app-registry';

describe('PAWOS App registry', () => {
  it('maps legacy feature URLs onto native PAWOS Apps', () => {
    expect(pawAppForPath('/planning')?.id).toBe('project-workbench');
    expect(pawAppForPath('/rooms')?.id).toBe('agent');
    expect(pawAppForPath('/voice')?.id).toBe('input-studio');
    expect(pawAppForPath('/context-debug')?.id).toBe('system-monitor');
    expect(pawAppForPath('/appearance')?.id).toBe('system-settings');
  });

  it('keeps Project Field as the OS home instead of registering it as an App', () => {
    expect(pawAppForPath('/project-field')).toBeNull();
    expect(pawApps.some((app) => app.id === ('project-field' as never))).toBe(false);
  });

  it('does not silently turn an unknown hash into a project window', () => {
    expect(pawAppForPath('/not-a-paw-app')).toBeNull();
  });
});
