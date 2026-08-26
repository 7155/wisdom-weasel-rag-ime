import { useEffect, useState } from 'react';
import { useOptionalControlTransport } from '@/app/control-transport';
import {
  primaryDockAppIds,
  type PawOsAppId,
} from '@/features/paw-os/model/app-registry';

export type LandingFormPersonaRef = {
  roleId: string;
  version?: string;
};

export type LandingFormSummary = {
  id: string;
  displayName: string;
  version: string;
  description: string;
  tagline: string;
  dockAppIds: PawOsAppId[];
  launchpadAppIds: PawOsAppId[];
  defaultLandingAppId: PawOsAppId | null;
  defaultPersona: LandingFormPersonaRef | null;
  policyPreset: string;
  skillRefs: string[];
  bootstrapPrompt: string;
  digest: string;
  active: boolean;
};

type ActiveFormState = {
  form: LandingFormSummary | null;
  loading: boolean;
  unavailable: boolean;
};

const emptyState: ActiveFormState = { form: null, loading: false, unavailable: false };

const knownAppIds = new Set<string>([
  'project-workbench',
  'agent',
  'memory',
  'knowledge',
  'input-studio',
  'app-center',
  'system-monitor',
  'system-settings',
  'files',
  'browser',
  'terminal',
]);

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asAppIdList(value: unknown): PawOsAppId[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => String(item || ''))
    .filter((item): item is PawOsAppId => knownAppIds.has(item));
}

export function landingFormFromPayload(payload: unknown): LandingFormSummary | null {
  const record = asRecord(payload);
  const id = String(record.id || '');
  if (!id) return null;
  const persona = asRecord(record.defaultPersona);
  const landing = String(record.defaultLandingAppId || '');
  return {
    id,
    displayName: String(record.displayName || id),
    version: String(record.version || ''),
    description: String(record.description || ''),
    tagline: String(record.tagline || ''),
    dockAppIds: asAppIdList(record.dockAppIds),
    launchpadAppIds: asAppIdList(record.launchpadAppIds),
    defaultLandingAppId: knownAppIds.has(landing) ? (landing as PawOsAppId) : null,
    defaultPersona: persona.roleId
      ? { roleId: String(persona.roleId), version: String(persona.version || '') || undefined }
      : null,
    policyPreset: String(record.policyPreset || 'default'),
    skillRefs: Array.isArray(record.skillRefs)
      ? record.skillRefs.map((item) => String(item || '')).filter(Boolean)
      : [],
    bootstrapPrompt: String(record.bootstrapPrompt || ''),
    digest: String(record.digest || ''),
    active: record.active === true,
  };
}

/** Filter Dock ids: Form list ∩ primary dock when Form is active; else full primary dock. */
export function dockAppIdsForForm(form: LandingFormSummary | null): readonly PawOsAppId[] {
  if (!form || form.dockAppIds.length === 0) return primaryDockAppIds;
  const allowed = new Set(form.dockAppIds);
  // Always keep App Center reachable so the user can switch/rollback Forms.
  allowed.add('app-center');
  const filtered = primaryDockAppIds.filter((id) => allowed.has(id));
  // Form may place apps that are not in the default primary dock (e.g. app-center).
  for (const id of form.dockAppIds) {
    if (!filtered.includes(id) && knownAppIds.has(id)) filtered.push(id);
  }
  if (!filtered.includes('app-center')) filtered.push('app-center');
  return filtered;
}

/** Filter Launchpad: Form launchpad list when active; else all apps (caller supplies). */
export function launchpadAppIdsForForm(
  form: LandingFormSummary | null,
  allAppIds: readonly PawOsAppId[],
): readonly PawOsAppId[] {
  if (!form || form.launchpadAppIds.length === 0) return allAppIds;
  const allowed = new Set(form.launchpadAppIds);
  allowed.add('app-center');
  return allAppIds.filter((id) => allowed.has(id));
}

/**
 * Active Landing Form projection for shell Dock/Launchpad filtering.
 * Missing transport or empty active Form → default primary dock / full Launchpad.
 */
export function useActiveLandingForm(): ActiveFormState {
  const transport = useOptionalControlTransport();
  const [state, setState] = useState<ActiveFormState>(emptyState);

  useEffect(() => {
    if (!transport) return undefined;
    const controller = new AbortController();
    setState((current) => ({ ...current, loading: true, unavailable: false }));
    void transport
      .request({ pathId: 'agent.forms.active', signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted) return;
        const record = asRecord(payload);
        setState({
          form: landingFormFromPayload(record.form),
          loading: false,
          unavailable: record.ok === false,
        });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setState({ form: null, loading: false, unavailable: true });
      });
    return () => controller.abort();
  }, [transport]);

  return state;
}
