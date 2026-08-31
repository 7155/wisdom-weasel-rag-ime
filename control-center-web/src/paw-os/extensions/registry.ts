import type {
  PawExtensionAppId,
  PawExtensionAppManifest,
  PawExtensionAppModule,
} from './types';
export type { PawExtensionAppId } from './types';

const manifestModules = import.meta.glob('../../../extension-apps/*/pawos-app.json', {
  eager: true,
  import: 'default',
}) as Record<string, unknown>;

const entryModules = import.meta.glob('../../../extension-apps/*/App.tsx') as Record<
  string,
  () => Promise<PawExtensionAppModule>
>;

type RegisteredExtensionApp = {
  manifest: PawExtensionAppManifest;
  load: () => Promise<PawExtensionAppModule>;
  ownerDirectory: string;
};

const registeredApps = Object.entries(manifestModules).map(([manifestPath, value]) => {
  const ownerDirectory = ownerDirectoryFromPath(manifestPath, 'pawos-app.json');
  const manifest = requireManifest(value, ownerDirectory);
  const entry = Object.entries(entryModules).find(([entryPath]) => (
    ownerDirectoryFromPath(entryPath, 'App.tsx') === ownerDirectory
  ))?.[1];
  if (!entry) throw new Error(`Extension App ${manifest.id} has no App.tsx entry`);
  return { manifest, load: entry, ownerDirectory } satisfies RegisteredExtensionApp;
});

assertUnique(registeredApps, (app) => app.manifest.id, 'id');
assertUnique(registeredApps, (app) => app.manifest.route, 'route');
assertUnique(registeredApps, (app) => app.manifest.packageId, 'packageId');

const byId = new Map(registeredApps.map((app) => [app.manifest.id, app]));
const byPackage = new Map(registeredApps.map((app) => [app.manifest.packageId, app]));

export const pawExtensionApps: readonly PawExtensionAppManifest[] = registeredApps
  .map((app) => app.manifest)
  .sort((left, right) => left.id.localeCompare(right.id));

export function isPawExtensionAppId(value: string): value is PawExtensionAppId {
  return value.startsWith('extension:') && byId.has(value as PawExtensionAppId);
}

export function pawExtensionApp(id: PawExtensionAppId): PawExtensionAppManifest {
  const app = byId.get(id);
  if (!app) throw new Error(`Unknown PAWOS Extension App: ${id}`);
  return app.manifest;
}

export function extensionAppForPackage(packageId: string): PawExtensionAppManifest | null {
  return byPackage.get(packageId)?.manifest ?? null;
}

export async function loadPawExtensionApp(id: PawExtensionAppId): Promise<PawExtensionAppModule> {
  const app = byId.get(id);
  if (!app) throw new Error(`Unknown PAWOS Extension App: ${id}`);
  const module = await app.load();
  if (typeof module.default !== 'function') {
    throw new Error(`Extension App ${id} does not export a React component`);
  }
  return module;
}

function requireManifest(value: unknown, ownerDirectory: string): PawExtensionAppManifest {
  if (!isRecord(value)) throw new Error(`Extension App ${ownerDirectory} manifest must be an object`);
  const expectedId = `extension:${ownerDirectory}`;
  const expectedRoute = `/extensions/${ownerDirectory}`;
  if (value.schemaVersion !== 'pawos.extension-app.v1') {
    throw new Error(`Extension App ${ownerDirectory} has an unsupported schemaVersion`);
  }
  if (value.id !== expectedId || value.route !== expectedRoute) {
    throw new Error(`Extension App ${ownerDirectory} id and route must match its owner directory`);
  }
  if (typeof value.version !== 'string' || !/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(value.version)) {
    throw new Error(`Extension App ${ownerDirectory} version must be semantic`);
  }
  if (typeof value.bindingSha256 !== 'string' || !/^[0-9a-f]{64}$/.test(value.bindingSha256)) {
    throw new Error(`Extension App ${ownerDirectory} bindingSha256 must be a lowercase SHA-256`);
  }
  if (typeof value.skillSha256 !== 'string' || !/^[0-9a-f]{64}$/.test(value.skillSha256)) {
    throw new Error(`Extension App ${ownerDirectory} skillSha256 must be a lowercase SHA-256`);
  }
  for (const field of ['packageId', 'label', 'shortLabel', 'tagline', 'skillRef', 'verticalSuiteId', 'verticalSuiteRevision'] as const) {
    if (typeof value[field] !== 'string' || !value[field].trim()) {
      throw new Error(`Extension App ${ownerDirectory} requires ${field}`);
    }
  }
  if (!new Set(['workspace', 'conversation', 'library', 'studio', 'utility']).has(String(value.presentation))) {
    throw new Error(`Extension App ${ownerDirectory} presentation is invalid`);
  }
  if (!new Set(['cyan', 'blue', 'violet', 'amber', 'green', 'rose', 'slate']).has(String(value.accent))) {
    throw new Error(`Extension App ${ownerDirectory} accent is invalid`);
  }
  if (!isRecord(value.icon)
    || !new Set(['analytics', 'assistant', 'document', 'commerce']).has(String(value.icon.symbol))
    || typeof value.icon.background !== 'string'
    || !/^#[0-9A-Fa-f]{6}$/.test(value.icon.background)) {
    throw new Error(`Extension App ${ownerDirectory} icon is invalid`);
  }
  if (value.sandbox !== undefined && (
    !isRecord(value.sandbox)
    || !new Set(['required', 'optional', 'disabled']).has(String(value.sandbox.default))
    || value.sandbox.connectorPackageId !== 'vertical-agent-sandbox'
    || value.sandbox.policyId !== 'vertical-readonly-v1'
    || Object.keys(value.sandbox).some((key) => !new Set(['default', 'connectorPackageId', 'policyId']).has(key))
  )) {
    throw new Error(`Extension App ${ownerDirectory} sandbox contract is invalid`);
  }
  return value as PawExtensionAppManifest;
}

function ownerDirectoryFromPath(path: string, fileName: string): string {
  const normalized = path.replaceAll('\\', '/');
  const escapedFileName = fileName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = normalized.match(new RegExp(`/extension-apps/([^/]+)/${escapedFileName}$`));
  const ownerDirectory = match?.[1] ?? '';
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(ownerDirectory)) {
    throw new Error(`Invalid Extension App source path: ${path}`);
  }
  return ownerDirectory;
}

function assertUnique(
  apps: readonly RegisteredExtensionApp[],
  key: (app: RegisteredExtensionApp) => string,
  label: string,
): void {
  const values = new Set<string>();
  for (const app of apps) {
    const value = key(app);
    if (values.has(value)) throw new Error(`Duplicate Extension App ${label}: ${value}`);
    values.add(value);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
