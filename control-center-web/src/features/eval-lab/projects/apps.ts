import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import { labConnectionKey, requestLabControl } from '../control-request';
import { object, type JsonValue } from './types';
import type { ControlTransport } from '@/platform/transport';
import { projectCommandRejected, projectError } from './api';

export type LabAppAction = { id: string; title: string; prompt: string; inputSchema: Record<string, JsonValue> };
export type LabAppSpec = { title: string; description: string; html: string; skill: string; context: string[];
  model: { provider: string; model: string; thinkingLevel: string }; actions: LabAppAction[] };
export type LabApp = { appId: string; projectId: string; title: string; description: string; revision: number;
  latestVersion: number; activeVersion: number | null; createdAtMs: number; updatedAtMs: number; installation?: unknown };
export type LabAppVersion = { appId: string; version: number; spec: LabAppSpec; contentHash: string; html: string;
  fileCount: number; byteSize: number; createdAtMs: number; sourceFiles: { path: string; byteSize: number; sha256: string }[] };
export type LabAppCall = { callId: string; appId: string; version: number; actionId: string; input: Record<string, JsonValue>;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'; sessionId: string;
  result: { text?: string; usage?: Record<string, JsonValue>; receipt?: Record<string, JsonValue> }; error: string;
  cancelRequested: boolean; createdAtMs: number; updatedAtMs: number };
export type LabAppRead = { ok: true; items: LabApp[]; app: LabApp | null; version?: LabAppVersion; versions?: LabAppVersion[]; calls?: LabAppCall[]; call?: LabAppCall };
export type LabAppCommand = { appId: string; expectedRevision: number; clientRequestId: string;
  action: 'activate' | 'deactivate' | 'invoke' | 'cancel' | 'resume'; input: Record<string, JsonValue> };
export type LabAppReceipt = { ok: true; app: LabApp; call?: LabAppCall; replayed: boolean; clientRequestId: string };
const natural = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
export function isLabApp(raw: unknown): raw is LabApp {
  const value = object(raw);
  return typeof value.appId === 'string' && /^extension:lab-[a-f0-9]{32}$/u.test(value.appId)
    && typeof value.projectId === 'string' && typeof value.title === 'string' && typeof value.description === 'string'
    && natural(value.revision) && natural(value.latestVersion) && (value.activeVersion === null || natural(value.activeVersion));
}
export function parseLabAppRead(raw: unknown, appId = ''): LabAppRead {
  const value = object(raw);
  if (value.ok !== true || !Array.isArray(value.items) || !value.items.every(isLabApp)
      || !(value.app === null || isLabApp(value.app)) || (appId && (!isLabApp(value.app) || value.app.appId !== appId))) throw new Error('应用数据未完整返回。');
  if (appId) {
    const version = object(value.version); const spec = object(version.spec);
    if (version.appId !== appId || !natural(version.version) || typeof version.html !== 'string' || typeof version.contentHash !== 'string'
        || typeof spec.title !== 'string' || !Array.isArray(spec.actions)
        || !spec.actions.every((raw) => { const action = object(raw); return typeof action.id === 'string' && typeof action.title === 'string' && typeof action.prompt === 'string'; })) throw new Error('应用版本未完整返回。');
  }
  return value as LabAppRead;
}
export function useLabApps(projectId = '', appId = '', version?: number) {
  const transport = useControlTransport();
  return useQuery({ queryKey: ['lab-apps', labConnectionKey(transport), projectId, appId, version ?? 0], retry: false,
    refetchInterval: 3000, refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => parseLabAppRead(await requestLabControl(transport, { pathId: 'agent.eval-lab.apps.get', signal,
      query: { ...(projectId ? { projectId } : {}), ...(appId ? { appId } : {}), ...(version ? { version } : {}) } }), appId),
  });
}
export async function commandLabApp(transport: ControlTransport, command: LabAppCommand): Promise<LabAppReceipt> {
  persistAppCommand(transport, command);
  try {
    const value = object(await requestLabControl(transport, { pathId: 'agent.eval-lab.apps.command', body: command }));
    if (value.ok === false) throw Object.assign(new Error(projectError({ payload: value })), { payload: value });
    if (value.ok !== true || !isLabApp(value.app) || value.app.appId !== command.appId || value.clientRequestId !== command.clientRequestId) throw new Error('应用操作回执未完整返回，请核对原操作。');
    persistAppCommand(transport, command, true);
    return value as LabAppReceipt;
  } catch (error) {
    if (projectCommandRejected(error)) persistAppCommand(transport, command, true);
    throw error;
  }
}
const appPendingKey = (transport: ControlTransport) => `paw.lab.app-commands.v1:${labConnectionKey(transport)}`;
export function pendingLabAppCommands(transport: ControlTransport, appId: string): LabAppCommand[] {
  try {
    const values: unknown = JSON.parse(sessionStorage.getItem(appPendingKey(transport)) ?? '[]');
    if (!Array.isArray(values)) return [];
    return values.filter((value): value is LabAppCommand => {
      const row = object(value);
      return row.appId === appId && natural(row.expectedRevision) && typeof row.clientRequestId === 'string'
        && ['activate', 'deactivate', 'invoke', 'cancel', 'resume'].includes(String(row.action))
        && row.input !== null && typeof row.input === 'object' && !Array.isArray(row.input);
    });
  } catch { return []; }
}
function persistAppCommand(transport: ControlTransport, command: LabAppCommand, remove = false) {
  try {
    const raw: unknown = JSON.parse(sessionStorage.getItem(appPendingKey(transport)) ?? '[]');
    const values = (Array.isArray(raw) ? raw : []).filter((value) => object(value).clientRequestId !== command.clientRequestId);
    if (!remove) values.push(command);
    sessionStorage.setItem(appPendingKey(transport), JSON.stringify(values));
  } catch { /* The mounted surface retains its original operation too. */ }
}
export async function downloadLabApp(transport: ControlTransport, appId: string, version: number, target: 'paw' | 'standalone'): Promise<void> {
  const value = object(await requestLabControl(transport, { pathId: 'agent.eval-lab.apps.download', query: { appId, version, target } }));
  if (value.ok !== true || value.appId !== appId || value.version !== version || value.target !== target
      || typeof value.filename !== 'string' || typeof value.base64 !== 'string' || value.base64.length > 4_000_000) throw new Error('应用包未完整返回。');
  const bytes = Uint8Array.from(atob(value.base64), (character) => character.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/zip' }));
  const link = document.createElement('a'); link.href = url; link.download = value.filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
