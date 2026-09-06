import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const bookmarkLimit = 500;
const downloadLimit = 500;
// Only the main process can set this marker from DownloadItem.getSavePath().
// Renderer input never creates an authoritative saved-file path.
const electronDownloadPathAuthority = 'electron-download-item';
const activeDownloadStates = new Set(['pending', 'progressing']);
const terminalDownloadStates = new Set(['completed', 'cancelled', 'interrupted', 'failed']);

export function getBookmarks(bookmarksFile) {
  return readJsonArray(bookmarksFile)
    .flatMap((entry) => {
      let normalized;
      try {
        normalized = normalizeBookmark(entry);
      } catch {
        normalized = null;
      }
      return normalized ? [normalized] : [];
    })
    .slice(0, bookmarkLimit);
}

export function addBookmark(bookmarksFile, value) {
  const normalized = normalizeBookmark(value, { createId: true });
  if (!normalized) throw new Error('bookmark must include a valid URL');
  const current = getBookmarks(bookmarksFile);
  const existing = current.find((entry) => entry.url === normalized.url);
  const next = [{
    ...normalized,
    id: existing?.id || normalized.id,
    createdAt: existing?.createdAt || normalized.createdAt,
    updatedAt: normalized.updatedAt,
  }, ...current.filter((entry) => entry.url !== normalized.url)].slice(0, bookmarkLimit);
  writeJsonAtomic(bookmarksFile, next);
  return next;
}

export function removeBookmark(bookmarksFile, bookmarkId) {
  const id = validatedStoredId(bookmarkId, 'bookmark');
  const current = getBookmarks(bookmarksFile);
  if (!current.some((entry) => entry.id === id)) throw new Error('unknown bookmark ID');
  const next = current.filter((entry) => entry.id !== id);
  writeJsonAtomic(bookmarksFile, next);
  return next;
}

export function getDownloads(downloadsFile) {
  return readDownloadRecords(downloadsFile, { recoverInterrupted: false });
}

export function restoreInterruptedDownloads(downloadsFile) {
  return readDownloadRecords(downloadsFile, { recoverInterrupted: true });
}

/**
 * Attach the host-owned record to Electron's real DownloadItem lifecycle.
 * The returned ID is the only identifier exposed to the renderer.
 */
export function trackDownload(downloadsFile, item, {
  activeDownloads = new Map(),
  clearTimer = clearTimeout,
  clock = () => Date.now(),
  coalesceMs = 1_000,
  downloadsPath = '',
  now = () => Date.now(),
  onChange = () => undefined,
  onError = () => undefined,
  schedule = setTimeout,
  writeRecords = writeJsonAtomic,
} = {}) {
  if (!item || typeof item.on !== 'function' || typeof item.once !== 'function') {
    throw new Error('Browser download item is unavailable');
  }
  const id = `download-${crypto.randomUUID()}`;
  activeDownloads.set(id, item);

  const interval = Math.max(0, Number(coalesceMs) || 0);
  let pendingState = 'progressing';
  let timer = null;
  let settled = false;
  let lastFlushAt = 0;

  const reportError = (stage) => {
    // Metadata is an observability aid. A broken profile file or renderer
    // callback must never escape an Electron DownloadItem event listener.
    try {
      onError(stage);
    } catch {
      // Error reporting cannot become a second download failure.
    }
  };

  const flush = (state) => {
    let current = [];
    let record;
    try {
      current = readDownloadRecords(downloadsFile, { recoverInterrupted: false });
      const previous = current.find((entry) => entry.id === id);
      record = downloadRecordFromItem(item, id, state, {
        downloadsPath,
        now: now(),
        previous,
      });
    } catch {
      reportError('download-record-read');
      lastFlushAt = clock();
      return null;
    }
    const next = [record, ...current.filter((entry) => entry.id !== id)].slice(0, downloadLimit);
    try {
      writeRecords(downloadsFile, next);
    } catch {
      reportError('download-metadata-write');
    }
    try {
      onChange(next);
    } catch {
      reportError('download-change-callback');
    }
    lastFlushAt = clock();
    return record;
  };

  const flushPending = () => {
    timer = null;
    flush(pendingState);
  };

  const enqueue = (state) => {
    if (settled) return;
    pendingState = state;
    if (timer) return;
    const elapsed = clock() - lastFlushAt;
    const delay = Math.max(0, interval - elapsed);
    if (delay === 0) {
      flushPending();
      return;
    }
    timer = schedule(flushPending, delay);
  };

  const finish = (state) => {
    if (settled) return;
    settled = true;
    if (timer) {
      clearTimer(timer);
      timer = null;
    }
    // `done` is the authoritative terminal event; always attempt this flush
    // even when a progress timer was pending or an earlier write failed.
    flush(state);
    activeDownloads.delete(id);
  };

  flush('progressing');
  item.on('updated', (_event, state) => {
    if (!terminalDownloadStates.has(String(state || ''))) enqueue(state);
  });
  item.once('done', (_event, state) => {
    finish(state);
  });
  return id;
}

export async function openDownload(downloadsFile, downloadId, {
  downloadsPath,
  openPath,
} = {}) {
  if (typeof openPath !== 'function') throw new Error('Browser download opener is unavailable');
  const record = findDownload(downloadsFile, downloadId);
  const filePath = validatedDownloadPath(record, downloadsPath);
  const error = await openPath(filePath);
  if (error) throw new Error(String(error));
  return record;
}

export function revealDownload(downloadsFile, downloadId, {
  downloadsPath,
  showItemInFolder,
} = {}) {
  if (typeof showItemInFolder !== 'function') throw new Error('Browser download revealer is unavailable');
  const record = findDownload(downloadsFile, downloadId);
  const filePath = validatedDownloadPath(record, downloadsPath);
  showItemInFolder(filePath);
  return record;
}

export function cancelDownload(downloadsFile, downloadId, { activeDownloads = new Map() } = {}) {
  const id = validatedStoredId(downloadId, 'download');
  const record = getDownloads(downloadsFile).find((entry) => entry.id === id);
  const item = activeDownloads.get(id);
  if (!record && !item) throw new Error('unknown download ID');
  // The live main-owned item remains cancellable when optional metadata could
  // not be persisted. Persisted records alone never authorize another item.
  if (item && (!record || activeDownloadStates.has(record.state)) && typeof item.cancel === 'function') {
    item.cancel();
  }
  const latest = getDownloads(downloadsFile).find((entry) => entry.id === id) || record;
  return item ? downloadRecordFromItem(item, id, readItem(item, 'getState', latest?.state || 'progressing'), {
    now: Date.now(),
    previous: latest,
  }) : latest;
}

function normalizeBookmark(value, { createId = false } = {}) {
  if (!value || typeof value !== 'object') return null;
  let url;
  try {
    url = new URL(String(value.url || ''));
  } catch {
    return null;
  }
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error('bookmark URL must be http(s)');
  }
  if (url.username || url.password) throw new Error('bookmark URL cannot contain credentials');
  const id = String(value.id || '').trim();
  if (!id && !createId) return null;
  if (id && !/^bookmark-[A-Za-z0-9_-]{1,128}$/.test(id)) return null;
  const createdAt = finitePositive(value.createdAt) || finitePositive(value.updatedAt) || Date.now();
  const updatedAt = finitePositive(value.updatedAt) || createdAt;
  return {
    id: id || `bookmark-${crypto.randomUUID()}`,
    title: safeText(value.title, url.toString()).slice(0, 500) || url.toString(),
    url: url.toString().slice(0, 8_000),
    createdAt,
    updatedAt,
  };
}

function normalizeDownload(value, { recoverInterrupted = false } = {}) {
  if (!value || typeof value !== 'object') return null;
  const id = String(value.id || '').trim();
  if (!/^download-[A-Za-z0-9_-]{1,128}$/.test(id)) return null;
  const state = String(value.state || '').trim();
  if (![...activeDownloadStates, ...terminalDownloadStates].includes(state)) return null;
  const startedAt = finitePositive(value.startedAt) || Date.now();
  const updatedAt = finitePositive(value.updatedAt) || startedAt;
  const normalizedState = recoverInterrupted && activeDownloadStates.has(state)
    ? 'interrupted'
    : state;
  const output = {
    id,
    filename: safeFilename(value.filename),
    url: safeDownloadUrl(value.url),
    path: safeAbsolutePath(value.path),
    state: normalizedState,
    receivedBytes: nonNegativeInteger(value.receivedBytes),
    totalBytes: nonNegativeInteger(value.totalBytes),
    startedAt,
    updatedAt,
  };
  if (value.pathAuthority === electronDownloadPathAuthority) {
    output.pathAuthority = electronDownloadPathAuthority;
  }
  const completedAt = finitePositive(value.completedAt);
  if (normalizedState === 'completed' && completedAt) output.completedAt = completedAt;
  return output;
}

function downloadRecordFromItem(item, id, state, { downloadsPath, now, previous }) {
  const normalizedState = normalizeDownloadState(state);
  const filename = safeFilename(readItem(item, 'getFilename', previous?.filename));
  // A path is authoritative only when the main-owned DownloadItem supplied it.
  // A renderer-provided or filename-derived fallback never receives this marker.
  const itemPath = safeAbsolutePath(readItem(item, 'getSavePath', ''));
  const previousItemPath = previous?.pathAuthority === electronDownloadPathAuthority
    ? safeAbsolutePath(previous.path)
    : '';
  const fallbackPath = itemPath || previousItemPath || (
    downloadsPath && filename ? path.join(path.resolve(downloadsPath), filename) : ''
  );
  const pathAuthority = itemPath || previousItemPath
    ? electronDownloadPathAuthority
    : '';
  const startedAt = previous?.startedAt || now;
  const output = {
    id,
    filename,
    url: safeDownloadUrl(readItem(item, 'getURL', previous?.url)),
    path: fallbackPath,
    state: normalizedState,
    receivedBytes: nonNegativeInteger(readItem(item, 'getReceivedBytes', previous?.receivedBytes)),
    totalBytes: nonNegativeInteger(readItem(item, 'getTotalBytes', previous?.totalBytes)),
    startedAt,
    updatedAt: now,
  };
  if (pathAuthority === electronDownloadPathAuthority) output.pathAuthority = pathAuthority;
  if (normalizedState === 'completed') output.completedAt = previous?.completedAt || now;
  return output;
}

function normalizeDownloadState(value) {
  const state = String(value || '').trim();
  if ([...activeDownloadStates, ...terminalDownloadStates].includes(state)) return state;
  return 'failed';
}

function readDownloadRecords(downloadsFile, { recoverInterrupted = false } = {}) {
  const raw = readJsonArray(downloadsFile);
  const records = raw.flatMap((entry) => {
    const normalized = normalizeDownload(entry, { recoverInterrupted });
    return normalized ? [normalized] : [];
  }).slice(0, downloadLimit);
  if (recoverInterrupted && raw.length && JSON.stringify(records) !== JSON.stringify(raw.slice(0, downloadLimit))) {
    writeJsonAtomic(downloadsFile, records);
  }
  return records;
}

function findDownload(downloadsFile, downloadId) {
  const id = validatedStoredId(downloadId, 'download');
  const record = getDownloads(downloadsFile).find((entry) => entry.id === id);
  if (!record) throw new Error('unknown download ID');
  return record;
}

function validatedStoredId(value, prefix) {
  const id = String(value || '').trim();
  const pattern = prefix === 'bookmark'
    ? /^bookmark-[A-Za-z0-9_-]{1,128}$/
    : /^download-[A-Za-z0-9_-]{1,128}$/;
  if (!pattern.test(id)) throw new Error(`invalid ${prefix} ID`);
  return id;
}

function validatedDownloadPath(record, downloadsPath) {
  if (record.state !== 'completed') throw new Error('Browser download is not complete');
  const candidate = safeAbsolutePath(record.path);
  if (!candidate) throw new Error('Browser download has no saved file');
  // Electron's DownloadItem path is the host authority for Save As locations.
  // Legacy records without that marker remain constrained to the default folder.
  if (record.pathAuthority !== electronDownloadPathAuthority) {
    const rootText = String(downloadsPath || '').trim();
    if (!rootText || !path.isAbsolute(rootText)) throw new Error('Browser Downloads folder is unavailable');
    const root = path.resolve(rootText);
    const relative = path.relative(root, candidate);
    if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
      throw new Error('Browser download path is outside the Downloads folder');
    }
  }
  let stat;
  try {
    stat = fs.statSync(candidate);
  } catch {
    throw new Error('Browser download file is unavailable');
  }
  if (!stat.isFile()) throw new Error('Browser download file is unavailable');
  return candidate;
}

function readItem(item, method, fallback) {
  try {
    const value = typeof item[method] === 'function' ? item[method]() : fallback;
    return value === undefined || value === null ? fallback : value;
  } catch {
    return fallback;
  }
}

function readJsonArray(file) {
  try {
    const value = JSON.parse(fs.readFileSync(file, 'utf8'));
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function writeJsonAtomic(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporaryFile = `${file}.${process.pid}.tmp`;
  try {
    fs.writeFileSync(temporaryFile, `${JSON.stringify(value)}\n`, { encoding: 'utf8', mode: 0o600 });
    fs.renameSync(temporaryFile, file);
  } catch (error) {
    try {
      fs.unlinkSync(temporaryFile);
    } catch {
      // Preserve the original persistence error without masking it in cleanup.
    }
    throw error;
  }
}

function safeText(value, fallback = '') {
  const text = String(value || fallback).replace(/[\u0000-\u001f\u007f]/g, ' ').trim();
  return text || fallback;
}

function safeFilename(value) {
  const text = safeText(value, 'download').replace(/[\\/]/g, '_');
  return text.slice(0, 500) || 'download';
}

function safeDownloadUrl(value) {
  try {
    const url = new URL(String(value || ''));
    if (!['http:', 'https:'].includes(url.protocol)) return '';
    url.username = '';
    url.password = '';
    url.search = '';
    url.hash = '';
    return url.toString().slice(0, 8_000);
  } catch {
    return '';
  }
}

function safeAbsolutePath(value) {
  const text = String(value || '').trim();
  return text && path.isAbsolute(text) ? path.resolve(text) : '';
}

function finitePositive(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

function nonNegativeInteger(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) && number >= 0 ? Math.floor(number) : 0;
}
