import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport } from '@/test/mock-transport';
import { pawExtensionApps } from './registry';
import {
  PawExtensionInstallationProvider,
  PAW_EXTENSION_INSTALLATION_CHANGED_EVENT,
  projectPawExtensionInstallation,
  usePawExtensionInstallation,
} from './installation';

afterEach(() => cleanup());

describe('PAWOS Extension App installation projection', () => {
  const extension = pawExtensionApps[0]!;
  const bindingCapability = `pawos.extension.binding.${extension.bindingSha256.slice(0, 40)}`;
  const evidence = {
    id: extension.id,
    packageId: extension.packageId,
    version: extension.version,
    bindingSha256: extension.bindingSha256,
    bindingCapability,
    skillRef: extension.skillRef,
    skillSha256: extension.skillSha256,
    verticalSuiteId: extension.verticalSuiteId,
    verticalSuiteRevision: extension.verticalSuiteRevision,
  };

  it('maps a Runtime Package ID to its manifest without treating disabled as enabled', () => {
    const projection = projectPawExtensionInstallation({
      ok: true,
      runtimeAvailable: true,
      items: [
        { id: extension.packageId, version: extension.version, installed: true, enabled: false, capabilities: [bindingCapability], extensionApp: evidence },
        { id: 'unrelated-package', installed: true, enabled: true },
      ],
    });

    expect([...projection.installedExtensionIds]).toEqual([extension.id]);
    expect([...projection.enabledExtensionIds]).toEqual([]);
  });

  it('projects installed and enabled Extension Apps through the transport hook', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.extensions.list': {
        ok: true,
        runtimeAvailable: true,
        items: [{ id: extension.packageId, version: extension.version, installed: true, enabled: true, capabilities: [bindingCapability], extensionApp: evidence }],
      },
    } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ControlTransportProvider transport={transport}>
        <PawExtensionInstallationProvider pollIntervalMs={0}>{children}</PawExtensionInstallationProvider>
      </ControlTransportProvider>
    );
    const { result } = renderHook(() => usePawExtensionInstallation(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.isInstalled(extension.id)).toBe(true);
    expect(result.current.isEnabled(extension.id)).toBe(true);
    expect(result.current.isAvailable('agent')).toBe(true);
  });

  it('does not claim a stale installed projection when Runtime is unavailable', () => {
    const projection = projectPawExtensionInstallation({
      ok: true,
      runtimeAvailable: false,
      items: [{ id: extension.packageId, installed: true, enabled: true }],
    });

    expect([...projection.installedExtensionIds]).toEqual([]);
    expect([...projection.enabledExtensionIds]).toEqual([]);
  });

  it('projects an uninstall by removing the Extension App identity from both sets', () => {
    const installed = projectPawExtensionInstallation({
      ok: true,
      items: [{ id: extension.packageId, version: extension.version, installed: true, enabled: true, capabilities: [bindingCapability], extensionApp: evidence }],
    });
    const uninstalled = projectPawExtensionInstallation({ ok: true, items: [] });

    expect(installed.enabledExtensionIds.has(extension.id)).toBe(true);
    expect(uninstalled.installedExtensionIds.has(extension.id)).toBe(false);
    expect(uninstalled.enabledExtensionIds.has(extension.id)).toBe(false);
  });

  it('refreshes immediately when App Center applies an install or uninstall receipt', async () => {
    let enabled = false;
    const transport = new MockControlTransport({ routes: {
      'agent.extensions.list': () => ({
        ok: true,
        runtimeAvailable: true,
        items: enabled
          ? [{ id: extension.packageId, version: extension.version, installed: true, enabled: true, capabilities: [bindingCapability], extensionApp: evidence }]
          : [],
      }),
    } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ControlTransportProvider transport={transport}>
        <PawExtensionInstallationProvider pollIntervalMs={0}>{children}</PawExtensionInstallationProvider>
      </ControlTransportProvider>
    );
    const { result } = renderHook(() => usePawExtensionInstallation(), { wrapper });
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.isEnabled(extension.id)).toBe(false);

    enabled = true;
    act(() => window.dispatchEvent(new Event(PAW_EXTENSION_INSTALLATION_CHANGED_EVENT)));

    await waitFor(() => expect(result.current.isEnabled(extension.id)).toBe(true));
    expect(transport.requests.filter(({ request }) => request.pathId === 'agent.extensions.list')).toHaveLength(2);
  });

  it.each([
    ['version', { version: '9.9.9' }],
    ['binding digest', { bindingSha256: 'f'.repeat(64), bindingCapability: `pawos.extension.binding.${'f'.repeat(40)}` }],
    ['skill', { skillRef: 'wrong-skill' }],
    ['suite', { verticalSuiteId: 'wrong-suite' }],
  ])('fails closed when Extension App %s evidence is stale or mismatched', (_label, override) => {
    const projection = projectPawExtensionInstallation({
      ok: true,
      runtimeAvailable: true,
      items: [{
        id: extension.packageId,
        version: extension.version,
        installed: true,
        enabled: true,
        capabilities: [bindingCapability],
        extensionApp: { ...evidence, ...override },
      }],
    });

    expect(projection.installedExtensionIds.has(extension.id)).toBe(true);
    expect(projection.enabledExtensionIds.has(extension.id)).toBe(false);
    expect(projection.availableExtensionIds.has(extension.id)).toBe(false);
  });

  it('requires a binding capability even when the Runtime reports the current version', () => {
    const projection = projectPawExtensionInstallation({
      ok: true,
      runtimeAvailable: true,
      items: [{
        id: extension.packageId,
        version: extension.version,
        installed: true,
        enabled: true,
        capabilities: [],
        extensionApp: { ...evidence, bindingCapability: '' },
      }],
    });

    expect(projection.enabledExtensionIds.has(extension.id)).toBe(false);
    expect(projection.availableExtensionIds.has(extension.id)).toBe(false);
  });

  it.each([
    'id',
    'packageId',
    'version',
    'bindingSha256',
    'bindingCapability',
    'skillRef',
    'skillSha256',
    'verticalSuiteId',
    'verticalSuiteRevision',
  ])('rejects Runtime evidence when required %s is missing', (field) => {
    const incomplete = { ...evidence } as Record<string, unknown>;
    delete incomplete[field];
    const projection = projectPawExtensionInstallation({
      ok: true,
      runtimeAvailable: true,
      items: [{
        id: extension.packageId,
        version: extension.version,
        installed: true,
        enabled: true,
        capabilities: [bindingCapability],
        extensionApp: incomplete,
      }],
    });

    expect(projection.enabledExtensionIds.has(extension.id)).toBe(false);
    expect(projection.availableExtensionIds.has(extension.id)).toBe(false);
  });

  it('rejects conflicting Runtime item and package identities', () => {
    const projection = projectPawExtensionInstallation({
      ok: true,
      runtimeAvailable: true,
      items: [{
        id: 'another-package',
        packageId: extension.packageId,
        version: extension.version,
        installed: true,
        enabled: true,
        capabilities: [bindingCapability],
        extensionApp: evidence,
      }],
    });

    expect(projection.installedExtensionIds.has(extension.id)).toBe(false);
    expect(projection.availableExtensionIds.has(extension.id)).toBe(false);
  });
});
