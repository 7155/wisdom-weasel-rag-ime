import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import test from 'node:test';
import {
  addBookmark,
  cancelDownload,
  getBookmarks,
  getDownloads,
  openDownload,
  removeBookmark,
  revealDownload,
  restoreInterruptedDownloads,
  trackDownload,
} from './browser-library.mjs';

function temporaryBrowserLibraryRoot() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'paw-browser-library-'));
}

class FakeDownload extends EventEmitter {
  constructor(savePath = '/tmp/paw-downloads/report.pdf') {
    super();
    this.savePath = savePath;
    this.receivedBytes = 0;
    this.totalBytes = 120;
    this.cancelCalls = 0;
  }

  getURL() { return 'https://example.com/files/report.pdf?token=redacted'; }
  getFilename() { return 'report.pdf'; }
  getSavePath() { return this.savePath; }
  getReceivedBytes() { return this.receivedBytes; }
  getTotalBytes() { return this.totalBytes; }
  cancel() {
    this.cancelCalls += 1;
    this.emit('done', {}, 'cancelled');
  }
}

test('bookmarks persist, deduplicate by URL, validate URLs, and remove by stored ID', () => {
  const root = temporaryBrowserLibraryRoot();
  const file = path.join(root, 'PAWBrowserHost.bookmarks.json');
  try {
    const first = addBookmark(file, { title: 'PAW docs', url: 'https://example.com/docs' });
    assert.equal(first.length, 1);
    assert.match(first[0].id, /^bookmark-/);
    assert.deepEqual(getBookmarks(file), first);

    const updated = addBookmark(file, { title: 'Updated docs', url: 'https://example.com/docs' });
    assert.equal(updated.length, 1);
    assert.equal(updated[0].id, first[0].id);
    assert.equal(updated[0].title, 'Updated docs');

    assert.throws(
      () => addBookmark(file, { title: 'Credentials', url: 'https://user:pass@example.com/' }),
      /bookmark URL cannot contain credentials/,
    );
    assert.throws(
      () => addBookmark(file, { title: 'Local file', url: 'file:///tmp/private.txt' }),
      /bookmark URL must be http\(s\)/,
    );

    const second = addBookmark(file, { title: 'Reference', url: 'https://reference.example/' });
    assert.equal(removeBookmark(file, second[1].id).length, 1);
    assert.throws(() => removeBookmark(file, 'bookmark-missing'), /unknown bookmark ID/);
    assert.equal(fs.existsSync(`${file}.${process.pid}.tmp`), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('downloads persist actual lifecycle events and expose only stable metadata', () => {
  const root = temporaryBrowserLibraryRoot();
  const file = path.join(root, 'PAWBrowserHost.downloads.json');
  const downloadsPath = '/tmp/paw-downloads';
  const activeDownloads = new Map();
  const item = new FakeDownload();
  try {
    const downloadId = trackDownload(file, item, {
      activeDownloads,
      coalesceMs: 0,
      downloadsPath,
      now: () => 100,
    });
    assert.match(downloadId, /^download-/);
    assert.equal(activeDownloads.get(downloadId), item);
    assert.deepEqual(getDownloads(file)[0], {
      id: downloadId,
      filename: 'report.pdf',
      url: 'https://example.com/files/report.pdf',
      path: '/tmp/paw-downloads/report.pdf',
      state: 'progressing',
      receivedBytes: 0,
      totalBytes: 120,
      startedAt: 100,
      updatedAt: 100,
      pathAuthority: 'electron-download-item',
    });

    item.receivedBytes = 60;
    item.emit('updated', {}, 'progressing');
    assert.equal(getDownloads(file)[0].receivedBytes, 60);

    item.emit('done', {}, 'completed');
    const completed = getDownloads(file)[0];
    assert.equal(completed.state, 'completed');
    assert.equal(completed.completedAt, 100);
    assert.equal(activeDownloads.has(downloadId), false);
    assert.equal(getDownloads(file)[0].url.includes('token'), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('unfinished persisted downloads recover as interrupted and Save As paths use host authority', async () => {
  const root = temporaryBrowserLibraryRoot();
  const file = path.join(root, 'PAWBrowserHost.downloads.json');
  const downloadsPath = path.join(root, 'Downloads');
  const savedElsewhere = path.join(root, 'Saved Elsewhere', 'complete.zip');
  fs.mkdirSync(downloadsPath);
  fs.mkdirSync(path.dirname(savedElsewhere), { recursive: true });
  fs.writeFileSync(savedElsewhere, 'download');
  fs.writeFileSync(file, JSON.stringify([
    {
      id: 'download-old',
      filename: 'partial.zip',
      url: 'https://example.com/partial.zip',
      path: path.join(downloadsPath, 'partial.zip'),
      state: 'progressing',
      receivedBytes: 4,
      totalBytes: 20,
      startedAt: 10,
      updatedAt: 20,
    },
  ]));
  try {
    assert.equal(restoreInterruptedDownloads(file)[0].state, 'interrupted');
    assert.equal(JSON.parse(fs.readFileSync(file, 'utf8'))[0].state, 'interrupted');

    const restored = restoreInterruptedDownloads(file);
    restored.push({
      id: 'download-complete',
      filename: 'complete.zip',
      url: 'https://example.com/complete.zip',
      path: savedElsewhere,
      pathAuthority: 'electron-download-item',
      state: 'completed',
      receivedBytes: 8,
      totalBytes: 8,
      startedAt: 30,
      updatedAt: 40,
      completedAt: 40,
    });
    fs.writeFileSync(file, JSON.stringify(restored));

    const opened = [];
    const revealed = [];
    assert.equal(
      await openDownload(file, 'download-complete', {
        downloadsPath,
        openPath: async (value) => { opened.push(value); return ''; },
      }).then((record) => record.id),
      'download-complete',
    );
    assert.deepEqual(opened, [savedElsewhere]);
    assert.equal(
      revealDownload(file, 'download-complete', {
        downloadsPath,
        showItemInFolder: (value) => { revealed.push(value); },
      }).id,
      'download-complete',
    );
    assert.deepEqual(revealed, [savedElsewhere]);

    await assert.rejects(
      () => openDownload(file, 'download-old', { downloadsPath, openPath: async () => '' }),
      /not complete/,
    );

    const activeDownloads = new Map([['download-old', { cancel: () => { throw new Error('must not cancel restored download'); } }]]);
    assert.equal(cancelDownload(file, 'download-old', { activeDownloads }).state, 'interrupted');
    await assert.rejects(
      () => openDownload(file, 'download-missing', { downloadsPath, openPath: async () => '' }),
      /unknown download ID/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('active download cancellation calls only the main-owned item', () => {
  const root = temporaryBrowserLibraryRoot();
  const file = path.join(root, 'PAWBrowserHost.downloads.json');
  const activeDownloads = new Map();
  const item = new FakeDownload();
  try {
    const downloadId = trackDownload(file, item, { activeDownloads, downloadsPath: '/tmp/paw-downloads' });
    cancelDownload(file, downloadId, { activeDownloads });
    assert.equal(item.cancelCalls, 1);
    assert.equal(getDownloads(file)[0].state, 'cancelled');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('download progress bursts are coalesced and done always flushes the terminal state', () => {
  const root = temporaryBrowserLibraryRoot();
  const file = path.join(root, 'PAWBrowserHost.downloads.json');
  const activeDownloads = new Map();
  const item = new FakeDownload();
  const changes = [];
  let clock = 100;
  let queued = null;
  try {
    const downloadId = trackDownload(file, item, {
      activeDownloads,
      clock: () => clock,
      coalesceMs: 1_000,
      downloadsPath: '/tmp/paw-downloads',
      now: () => clock,
      onChange: (downloads) => changes.push(downloads),
      schedule: (callback, delay) => {
        assert.equal(queued, null);
        queued = { callback, delay };
        return queued;
      },
      clearTimer: (timer) => {
        if (queued === timer) queued = null;
      },
    });

    assert.equal(changes.length, 1);
    item.receivedBytes = 10;
    item.emit('updated', {}, 'progressing');
    item.receivedBytes = 20;
    item.emit('updated', {}, 'progressing');
    assert.equal(changes.length, 1);
    assert.equal(queued.delay, 1_000);

    item.receivedBytes = 30;
    clock = 200;
    item.emit('done', {}, 'completed');
    assert.equal(changes.length, 2);
    assert.equal(changes.at(-1)[0].id, downloadId);
    assert.equal(changes.at(-1)[0].receivedBytes, 30);
    assert.equal(changes.at(-1)[0].state, 'completed');
    assert.equal(activeDownloads.has(downloadId), false);
    assert.equal(queued, null);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('download metadata write and renderer callback failures do not escape lifecycle events', () => {
  const root = temporaryBrowserLibraryRoot();
  const file = path.join(root, 'PAWBrowserHost.downloads.json');
  const activeDownloads = new Map();
  const item = new FakeDownload();
  const stages = [];
  const changes = [];
  try {
    const downloadId = trackDownload(file, item, {
      activeDownloads,
      clock: () => 100,
      coalesceMs: 0,
      downloadsPath: '/tmp/paw-downloads',
      now: () => 100,
      onChange: (downloads) => {
        changes.push(downloads);
        throw new Error('renderer callback failed');
      },
      onError: (stage) => stages.push(stage),
      writeRecords: () => { throw new Error('disk full'); },
    });

    assert.doesNotThrow(() => {
      item.receivedBytes = 50;
      item.emit('updated', {}, 'progressing');
      item.emit('done', {}, 'completed');
    });
    assert.equal(changes.at(-1)[0].id, downloadId);
    assert.equal(changes.at(-1)[0].state, 'completed');
    assert.equal(activeDownloads.has(downloadId), false);
    assert.ok(stages.includes('download-metadata-write'));
    assert.ok(stages.includes('download-change-callback'));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('download failures remain terminal and file opener errors are surfaced', async () => {
  const root = temporaryBrowserLibraryRoot();
  const file = path.join(root, 'PAWBrowserHost.downloads.json');
  const activeDownloads = new Map();
  const item = new FakeDownload();
  try {
    const downloadId = trackDownload(file, item, {
      activeDownloads,
      downloadsPath: '/tmp/paw-downloads',
      now: () => 300,
    });
    item.emit('done', {}, 'interrupted');
    assert.equal(getDownloads(file)[0].state, 'interrupted');
    assert.equal('completedAt' in getDownloads(file)[0], false);
    await assert.rejects(
      () => openDownload(file, downloadId, {
        downloadsPath: '/tmp/paw-downloads',
        openPath: async () => 'open failed',
      }),
      /not complete/,
    );

    const savedPath = path.join(root, 'Saved Elsewhere', 'done.txt');
    fs.mkdirSync(path.dirname(savedPath), { recursive: true });
    fs.writeFileSync(savedPath, 'done');
    fs.writeFileSync(file, JSON.stringify([{
      id: 'download-complete',
      filename: 'done.txt',
      url: 'https://example.com/done.txt',
      path: savedPath,
      pathAuthority: 'electron-download-item',
      state: 'completed',
      receivedBytes: 4,
      totalBytes: 4,
      startedAt: 301,
      updatedAt: 302,
      completedAt: 302,
    }]));
    await assert.rejects(
      () => openDownload(file, 'download-complete', {
        downloadsPath: '/tmp/paw-downloads',
        openPath: async () => 'open failed',
      }),
      /open failed/,
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test('a transient save-path read failure preserves the last Electron-authorized Save As path', () => {
  const root = temporaryBrowserLibraryRoot();
  const file = path.join(root, 'downloads.json');
  const actualPath = path.join(root, 'Saved Elsewhere', 'report.pdf');
  const item = new FakeDownload(actualPath);
  try {
    trackDownload(file, item, { downloadsPath: path.join(root, 'Downloads') });
    item.getSavePath = () => { throw new Error('item no longer readable'); };
    item.emit('done', {}, 'completed');
    assert.equal(getDownloads(file)[0].path, actualPath);
    assert.equal(getDownloads(file)[0].pathAuthority, 'electron-download-item');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});


test('metadata persistence failure does not prevent cancelling the live host-owned download', () => {
  const root = temporaryBrowserLibraryRoot();
  const file = path.join(root, 'downloads.json');
  const activeDownloads = new Map();
  const item = new FakeDownload();
  let state = 'progressing';
  item.getState = () => state;
  item.cancel = () => {
    item.cancelCalls += 1;
    state = 'cancelled';
    item.emit('done', {}, state);
  };
  try {
    const id = trackDownload(file, item, {
      activeDownloads,
      writeRecords: () => { throw new Error('disk full'); },
    });
    const receipt = cancelDownload(file, id, { activeDownloads });
    assert.equal(item.cancelCalls, 1);
    assert.equal(receipt.state, 'cancelled');
    assert.equal(activeDownloads.has(id), false);
    assert.throws(() => cancelDownload(file, 'download-unknown', { activeDownloads }), /unknown download ID/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
