import { useEffect, useState } from 'react';
import { useOptionalControlTransport } from '@/app/control-transport';

export type PawOsPackageApp = {
  packageId: string;
  label: string;
  tagline: string;
  version: string;
  resourceCount: number;
};

type PackageAppsState = {
  apps: PawOsPackageApp[];
  loading: boolean;
  unavailable: boolean;
};

const emptyState: PackageAppsState = { apps: [], loading: false, unavailable: false };

/**
 * Installed Packages are discovered only while Launchpad is visible. The
 * Package contributes identity and Runtime resources, never executable UI.
 */
export function usePawOsPackageApps(): PackageAppsState {
  const transport = useOptionalControlTransport();
  const [state, setState] = useState<PackageAppsState>(emptyState);

  useEffect(() => {
    if (!transport) return undefined;
    const controller = new AbortController();
    setState((current) => ({ ...current, loading: true, unavailable: false }));
    void transport.request({ pathId: 'agent.extensions.list', signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted) return;
        const record = asRecord(payload);
        setState({
          apps: packageAppsFromInventory(payload),
          loading: false,
          unavailable: record.runtimeAvailable === false,
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setState({ apps: [], loading: false, unavailable: true });
        }
      });
    return () => controller.abort();
  }, [transport]);

  return state;
}

export function packageAppsFromInventory(payload: unknown): PawOsPackageApp[] {
  const inventory = asRecord(payload);
  const items = Array.isArray(inventory.items) ? inventory.items : [];
  return items
    .map(asRecord)
    .filter((item) => item.installed === true && item.enabled === true)
    .map((item) => {
      const packageId = boundedText(item.id, 200);
      const label = boundedText(item.displayName, 120) || packageId;
      const resources = asRecord(item.resources);
      const resourceCount = ['extensions', 'skills', 'prompts', 'themes']
        .reduce((total, kind) => total + (Array.isArray(resources[kind]) ? resources[kind].length : 0), 0);
      return {
        packageId,
        label,
        tagline: boundedText(item.description, 240) || '由 Pi Runtime 提供的受管能力',
        version: boundedText(item.version, 64),
        resourceCount,
      };
    })
    .filter((item) => Boolean(item.packageId))
    .sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'));
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function boundedText(value: unknown, limit: number): string {
  return typeof value === 'string' ? value.trim().slice(0, limit) : '';
}
