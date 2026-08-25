import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { browserPartition } from './host-config.mjs';

const browserHistoryLimit = 500;

export function listBrowserExtensions(electronSession) {
  return [...electronSession.extensions.getAllExtensions().values()].map((extension) => ({
    id: extension.id,
    name: extension.name,
    path: extension.path,
    version: extension.version,
  }));
}

export async function readBrowserSessionSettings({ downloadsPath, electronSession, extensionsPath, startPage }) {
  const [cacheBytes, cookies] = await Promise.all([
    electronSession.getCacheSize(),
    electronSession.cookies.get({}),
  ]);
  const extensions = listBrowserExtensions(electronSession);
  return {
    cacheBytes,
    cookieCount: cookies.length,
    downloadPath: downloadsPath,
    extensionCount: extensions.length,
    extensionsPath,
    partition: browserPartition,
    permissionMode: 'site-request',
    startPage,
  };
}

export async function clearBrowserSessionData(electronSession, action) {
  if (action === 'cache') {
    const before = await electronSession.getCacheSize();
    await electronSession.clearCache();
    return { action, before, after: await electronSession.getCacheSize() };
  }
  if (action === 'site-data') {
    const before = (await electronSession.cookies.get({})).length;
    await electronSession.clearStorageData();
    electronSession.flushStorageData();
    return { action, before, after: (await electronSession.cookies.get({})).length };
  }
  throw new Error('Unsupported Browser maintenance action');
}

export function readBrowserHistory(historyFile) {
  try {
    const value = JSON.parse(fs.readFileSync(historyFile, 'utf8'));
    if (!Array.isArray(value)) return [];
    return value.flatMap((entry) => {
      const normalized = normalizedHistoryEntry(entry);
      return normalized ? [normalized] : [];
    }).slice(0, browserHistoryLimit);
  } catch {
    return [];
  }
}

export function appendBrowserHistory(historyFile, entry) {
  const normalized = normalizedHistoryEntry(entry, true);
  const current = readBrowserHistory(historyFile);
  if (!normalized) return current;
  const existing = current.find((item) => item.url === normalized.url);
  const next = [{
    ...normalized,
    id: existing?.id || normalized.id,
  }, ...current.filter((item) => item.url !== normalized.url)].slice(0, browserHistoryLimit);
  writeBrowserHistory(historyFile, next);
  return next;
}

export function removeBrowserHistoryEntry(historyFile, entryId) {
  const next = readBrowserHistory(historyFile).filter((entry) => entry.id !== String(entryId || ''));
  writeBrowserHistory(historyFile, next);
  return next;
}

export function clearBrowserHistory(historyFile) {
  writeBrowserHistory(historyFile, []);
  return [];
}

function normalizedHistoryEntry(value, createId = false) {
  if (!value || typeof value !== 'object') return null;
  let url;
  try {
    url = new URL(String(value.url || ''));
  } catch {
    return null;
  }
  if (!['http:', 'https:'].includes(url.protocol)) return null;
  const visitedAt = Number(value.visitedAt || 0);
  if (!Number.isFinite(visitedAt) || visitedAt <= 0) return null;
  const id = String(value.id || '').trim();
  if (!id && !createId) return null;
  return {
    id: id || `history-${crypto.randomUUID()}`,
    title: String(value.title || url.toString()).trim().slice(0, 500) || url.toString(),
    url: url.toString().slice(0, 8_000),
    visitedAt,
  };
}

function writeBrowserHistory(historyFile, entries) {
  fs.mkdirSync(path.dirname(historyFile), { recursive: true });
  const temporaryFile = `${historyFile}.${process.pid}.tmp`;
  fs.writeFileSync(temporaryFile, `${JSON.stringify(entries)}\n`, { encoding: 'utf8', mode: 0o600 });
  fs.renameSync(temporaryFile, historyFile);
}
