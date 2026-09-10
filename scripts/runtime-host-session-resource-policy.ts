import { basename } from 'node:path';
import { SettingsManager } from '@earendil-works/pi-coding-agent';

export interface SessionResourceDisclosurePolicy {
  disabledSkillNames: string[];
  disabledPluginIds: string[];
}

export function sessionResourceDisclosurePolicy(value: unknown): SessionResourceDisclosurePolicy {
  if (value === undefined) return { disabledSkillNames: [], disabledPluginIds: [] };
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid Session resource policy');
  const policy = value as Record<string, unknown>;
  const names = (key: string, pattern: RegExp) => {
    const items = policy[key] ?? [];
    if (!Array.isArray(items) || items.length > 512 || items.some((item) => typeof item !== 'string' || !pattern.test(item))) {
      throw new Error(`Invalid Session resource policy: ${key}`);
    }
    return [...new Set(items as string[])];
  };
  return {
    disabledSkillNames: names('disabledSkillNames', /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/),
    disabledPluginIds: names('disabledPluginIds', /^(?:@[A-Za-z0-9._-]+\/)?[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/),
  };
}

/** Give Pi's existing loader a private settings view before any package is imported.
 * Session choices must never write shared package installation settings. */
export function sessionResourceSettings(settings: SettingsManager, disabledSources: string[]): SettingsManager {
  if (!disabledSources.length) return settings;
  const excluded = new Set(disabledSources);
  const filter = (source: ReturnType<SettingsManager['getGlobalSettings']>) => ({
    ...source,
    packages: (source.packages ?? []).filter((item) => !excluded.has(typeof item === 'string' ? item : item.source)),
  });
  const snapshots = {
    global: JSON.stringify(filter(settings.getGlobalSettings())),
    project: JSON.stringify(filter(settings.getProjectSettings())),
  };
  return SettingsManager.fromStorage({
    withLock(scope, update) {
      const next = update(snapshots[scope]);
      if (next !== undefined) snapshots[scope] = next;
    },
  }, { projectTrusted: true });
}

export function sessionLegacyExtensionPaths(paths: string[], disabledIds: string[]): string[] {
  const excluded = new Set(disabledIds);
  return paths.filter((path) => !excluded.has(basename(path, '.ts')));
}
