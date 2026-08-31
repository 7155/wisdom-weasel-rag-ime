import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useOptionalControlTransport } from '@/app/control-transport';
import type { PawAppId } from '../runtime/app-registry';
import { extensionAppForPackage, isPawExtensionAppId } from './registry';
import type {
  PawExtensionAppId,
  PawExtensionAppInstallationEvidence,
  PawExtensionAppManifest,
} from './types';

export const PAW_EXTENSION_INSTALLATION_CHANGED_EVENT = 'pawos:extension-installation-changed';

export type PawExtensionInstallationStatus = 'loading' | 'ready' | 'unavailable';

export type PawExtensionInstallationProjection = {
  installedExtensionIds: ReadonlySet<PawExtensionAppId>;
  enabledExtensionIds: ReadonlySet<PawExtensionAppId>;
  availableExtensionIds: ReadonlySet<PawExtensionAppId>;
};

export type PawExtensionInstallation = PawExtensionInstallationProjection & {
  status: PawExtensionInstallationStatus;
  loading: boolean;
  unavailable: boolean;
  ready: boolean;
  isInstalled: (appId: PawAppId) => boolean;
  isEnabled: (appId: PawAppId) => boolean;
  isAvailable: (appId: PawAppId) => boolean;
  refresh: () => void;
};

const EMPTY_IDS: ReadonlySet<PawExtensionAppId> = new Set<PawExtensionAppId>();
const EXTENSION_BINDING_TOKEN = /^pawos\.extension\.binding\.[0-9a-f]{40}$/;
const INSTALLATION_CONTEXT = createContext<PawExtensionInstallation | null>(null);

/**
 * Reduce the Runtime inventory to the registered Extension App identities.
 * Package inventory ids are intentionally resolved through each manifest's
 * packageId; Runtime display names and resource lists cannot grant a desktop
 * surface. A Runtime that explicitly reports unavailable contributes no
 * identities, even if a stale items array accompanies the response.
 */
export function projectPawExtensionInstallation(payload: unknown): PawExtensionInstallationProjection {
  const source = asRecord(payload);
  if (source.runtimeAvailable === false) return emptyProjection();
  const installedExtensionIds = new Set<PawExtensionAppId>();
  const enabledExtensionIds = new Set<PawExtensionAppId>();
  const availableExtensionIds = new Set<PawExtensionAppId>();
  const items = Array.isArray(source.items) ? source.items : [];
  for (const candidate of items) {
    const item = asRecord(candidate);
    const itemId = text(item.id);
    const explicitPackageId = text(item.packageId);
    if (itemId && explicitPackageId && itemId !== explicitPackageId) continue;
    const packageId = explicitPackageId || itemId;
    const app = packageId ? extensionAppForPackage(packageId) : null;
    if (!app || item.installed !== true) continue;
    installedExtensionIds.add(app.id);
    if (item.enabled === true && extensionAppInstallationMatches(app, item)) {
      enabledExtensionIds.add(app.id);
      availableExtensionIds.add(app.id);
    }
  }
  return { installedExtensionIds, enabledExtensionIds, availableExtensionIds };
}

export function PawExtensionInstallationProvider({
  children,
  pollIntervalMs = 5_000,
}: {
  children: ReactNode;
  pollIntervalMs?: number;
}) {
  const transport = useOptionalControlTransport();
  const [projection, setProjection] = useState<PawExtensionInstallationProjection>(() => emptyProjection());
  const [status, setStatus] = useState<PawExtensionInstallationStatus>('loading');
  const activeRequest = useRef<AbortController | null>(null);

  const refresh = useCallback(() => {
    activeRequest.current?.abort();
    if (!transport) {
      activeRequest.current = null;
      setProjection(emptyProjection());
      setStatus('unavailable');
      return;
    }
    const controller = new AbortController();
    activeRequest.current = controller;
    setStatus('loading');
    void transport.request({ pathId: 'agent.extensions.list', signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted || activeRequest.current !== controller) return;
        const next = projectPawExtensionInstallation(payload);
        const runtimeUnavailable = asRecord(payload).runtimeAvailable === false;
        setProjection((current) => sameProjection(current, next) ? current : next);
        setStatus(runtimeUnavailable ? 'unavailable' : 'ready');
      })
      .catch(() => {
        if (controller.signal.aborted || activeRequest.current !== controller) return;
        setProjection(emptyProjection());
        setStatus('unavailable');
      });
  }, [transport]);

  useEffect(() => {
    refresh();
    window.addEventListener(PAW_EXTENSION_INSTALLATION_CHANGED_EVENT, refresh);
    if (pollIntervalMs <= 0) {
      return () => {
        window.removeEventListener(PAW_EXTENSION_INSTALLATION_CHANGED_EVENT, refresh);
        activeRequest.current?.abort();
      };
    }
    const timer = window.setInterval(refresh, pollIntervalMs);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener(PAW_EXTENSION_INSTALLATION_CHANGED_EVENT, refresh);
      activeRequest.current?.abort();
    };
  }, [pollIntervalMs, refresh]);

  const value = useMemo<PawExtensionInstallation>(() => ({
    installedExtensionIds: projection.installedExtensionIds,
    enabledExtensionIds: projection.enabledExtensionIds,
    availableExtensionIds: projection.availableExtensionIds,
    status,
    loading: status === 'loading',
    unavailable: status === 'unavailable',
    ready: status === 'ready',
    isInstalled: (appId) => !isPawExtensionAppId(appId) || projection.installedExtensionIds.has(appId),
    isEnabled: (appId) => !isPawExtensionAppId(appId) || projection.enabledExtensionIds.has(appId),
    isAvailable: (appId) => !isPawExtensionAppId(appId) || projection.availableExtensionIds.has(appId),
    refresh,
  }), [projection, refresh, status]);

  return createElement(INSTALLATION_CONTEXT.Provider, { value }, children);
}

export function usePawExtensionInstallation(): PawExtensionInstallation {
  const value = useContext(INSTALLATION_CONTEXT);
  if (!value) throw new Error('usePawExtensionInstallation must be used inside PawExtensionInstallationProvider');
  return value;
}

function emptyProjection(): PawExtensionInstallationProjection {
  return {
    installedExtensionIds: EMPTY_IDS,
    enabledExtensionIds: EMPTY_IDS,
    availableExtensionIds: EMPTY_IDS,
  };
}

function sameProjection(left: PawExtensionInstallationProjection, right: PawExtensionInstallationProjection): boolean {
  return sameSet(left.installedExtensionIds, right.installedExtensionIds)
    && sameSet(left.enabledExtensionIds, right.enabledExtensionIds)
    && sameSet(left.availableExtensionIds, right.availableExtensionIds);
}

function sameSet(left: ReadonlySet<PawExtensionAppId>, right: ReadonlySet<PawExtensionAppId>): boolean {
  if (left.size !== right.size) return false;
  for (const value of right) if (!left.has(value)) return false;
  return true;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

export function extensionAppInstallationMatches(
  app: PawExtensionAppManifest,
  item: Record<string, unknown>,
): boolean {
  const itemId = text(item.id);
  const explicitPackageId = text(item.packageId);
  if ((itemId && explicitPackageId && itemId !== explicitPackageId)
    || (explicitPackageId || itemId) !== app.packageId) return false;
  const evidence = extensionAppInstallationEvidence(item);
  if (!evidence) return false;
  const installedVersion = text(item.version);
  return installedVersion === app.version
    && evidence.id === app.id
    && evidence.packageId === app.packageId
    && evidence.version === app.version
    && evidence.bindingSha256 === app.bindingSha256
    && evidence.bindingCapability === extensionBindingCapability(app.bindingSha256)
    && evidence.skillRef === app.skillRef
    && evidence.skillSha256 === app.skillSha256
    && evidence.verticalSuiteId === app.verticalSuiteId
    && evidence.verticalSuiteRevision === app.verticalSuiteRevision
    && sameSandboxContract(evidence.sandbox, app.sandbox);
}

function extensionAppInstallationEvidence(
  item: Record<string, unknown>,
): PawExtensionAppInstallationEvidence | null {
  const raw = asRecord(item.extensionApp);
  const rawCapability = text(raw.bindingCapability);
  const listedCapability = extensionBindingCapabilityFromList(item.capabilities);
  if (!rawCapability || !listedCapability || rawCapability !== listedCapability) return null;
  const capability = listedCapability;
  const id = text(raw.id);
  const packageId = text(raw.packageId);
  const version = text(raw.version);
  const bindingSha256 = text(raw.bindingSha256);
  const skillRef = text(raw.skillRef);
  const skillSha256 = text(raw.skillSha256);
  const verticalSuiteId = text(raw.verticalSuiteId);
  const verticalSuiteRevision = text(raw.verticalSuiteRevision);
  const sandbox = extensionSandboxContract(raw.sandbox);
  if (!isPawExtensionAppId(id)
    || !packageId
    || !version
    || !/^[0-9a-f]{64}$/.test(bindingSha256)
    || !capability
    || !EXTENSION_BINDING_TOKEN.test(capability)
    || !skillRef
    || !/^[0-9a-f]{64}$/.test(skillSha256)
    || !verticalSuiteId
    || !verticalSuiteRevision) return null;
  return {
    id,
    packageId,
    version,
    bindingSha256,
    bindingCapability: capability,
    skillRef,
    skillSha256,
    verticalSuiteId,
    verticalSuiteRevision,
    ...(sandbox ? { sandbox } : {}),
  };
}

function extensionSandboxContract(value: unknown): PawExtensionAppInstallationEvidence['sandbox'] | undefined {
  const raw = asRecord(value);
  return raw.default === 'required' || raw.default === 'optional' || raw.default === 'disabled'
    ? raw.connectorPackageId === 'vertical-agent-sandbox' && raw.policyId === 'vertical-readonly-v1'
      ? {
          default: raw.default,
          connectorPackageId: 'vertical-agent-sandbox',
          policyId: 'vertical-readonly-v1',
        }
      : undefined
    : undefined;
}

function sameSandboxContract(
  left: PawExtensionAppInstallationEvidence['sandbox'],
  right: PawExtensionAppManifest['sandbox'],
): boolean {
  if (!left || !right) return left === right;
  return left.default === right.default
    && left.connectorPackageId === right.connectorPackageId
    && left.policyId === right.policyId;
}

function extensionBindingCapabilityFromList(value: unknown): string {
  if (!Array.isArray(value)) return '';
  const matches = value.filter((candidate): candidate is string => (
    typeof candidate === 'string' && EXTENSION_BINDING_TOKEN.test(candidate)
  ));
  return matches.length === 1 ? matches[0]! : '';
}

function extensionBindingCapability(bindingSha256: string): string {
  return `pawos.extension.binding.${bindingSha256.slice(0, 40)}`;
}
