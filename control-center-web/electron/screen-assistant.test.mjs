import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { test } from 'node:test';
import { installScreenAssistant } from './screen-assistant.mjs';

function harness(overrides = {}) {
  const handlers = new Map(); const created = []; const errors = []; const opened = [];
  class Window extends EventEmitter {
    constructor(options) {
      super(); this.options = options; this.visible = false; this.destroyed = false;
      this.webContents = Object.assign(new EventEmitter(), { id: created.length + 1, getURL: () => this.url, setWindowOpenHandler: () => {} });
      created.push(this);
    }
    isVisible() { return this.visible; }
    isDestroyed() { return this.destroyed; }
    hide() { this.visible = false; }
    show() { this.visible = true; }
    showInactive() { this.visible = true; }
    async loadURL(url) { this.url = url; this.emit('ready-to-show'); }
    close() { this.destroyed = true; this.emit('closed'); }
  }
  const app = new EventEmitter();
  const capture = { dataUrl: 'data:image/png;base64,fixture', sourceAppBundleId: 'com.example.Editor' };
  const manager = installScreenAssistant({ app, BrowserWindow: Window,
    ipcMain: { handle: (name, handler) => handlers.set(name, handler) },
    dialog: { showMessageBox: async (error) => errors.push(error), showSaveDialog: async () => ({ canceled: true }), ...overrides.dialog },
    systemPreferences: { getMediaAccessStatus: () => 'granted' }, origin: 'http://127.0.0.1:7777', preload: '/test/preload.cjs', getMainWindow: () => null,
    openSession: (sessionId) => opened.push(sessionId), capture: async () => capture, ...overrides,
  });
  return { app, manager, handlers, created, capture, errors, opened };
}

test('popup owns its capture, opens the exact Session, and drops pixels on close', async () => {
  const h = harness();
  assert.equal(await h.manager.startCapture('com.example.Editor'), true);
  const window = h.created[0]; const event = { sender: window.webContents };
  assert.equal(window.url, 'http://127.0.0.1:7777/screen-assistant?frontend=paw-os&pawHost=electron');
  assert.equal(h.handlers.get('paw-screen:context')(event), h.capture);
  assert.throws(() => h.handlers.get('paw-screen:context')({ sender: { id: 999 } }), /rejected/);
  h.handlers.get('paw-screen:open-session')(event, 'session-screen');
  assert.deepEqual(h.opened, ['session-screen']);
  window.close();
  assert.throws(() => h.handlers.get('paw-screen:context')(event), /rejected/);
});

test('saved is returned only after the chosen Markdown file exists with the exact body', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'paw-note-test-'));
  try {
    const destination = path.join(root, '选区笔记.md');
    const h = harness({ dialog: { showSaveDialog: async () => ({ canceled: false, filePath: destination }) } });
    await h.manager.startCapture();
    const body = '# 笔记\n\n来自选区的事实。\n';
    const result = await h.handlers.get('paw-screen:save-note')({ sender: h.created[0].webContents }, { body });
    assert.deepEqual(result, { saved: true, name: '选区笔记.md' });
    assert.equal(await fs.readFile(destination, 'utf8'), body);
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});

test('cancelling capture never creates a window or saves a note', async () => {
  const h = harness({ capture: async () => null });
  assert.equal(await h.manager.startCapture(), false);
  assert.equal(h.created.length, 0);
  assert.equal(h.errors.length, 0);
});

test('conversation recovery stays bound to its popup and is discarded when that popup closes', async () => {
  const h = harness();
  await h.manager.startCapture();
  const first = { sender: h.created[0].webContents };
  const session = { id: 'session-screen', title: '选区对话' };
  h.handlers.get('paw-screen:remember-conversation')(first, { session });
  await h.manager.startCapture();
  const second = { sender: h.created[1].webContents };
  assert.deepEqual(h.handlers.get('paw-screen:conversation')(first), { session });
  assert.deepEqual(h.handlers.get('paw-screen:conversation')(second), {});
  assert.throws(() => h.handlers.get('paw-screen:remember-conversation')(first, { session: { id: 'another-session' } }), /Session/);
  h.created[0].close();
  assert.throws(() => h.handlers.get('paw-screen:conversation')(first), /rejected/);
});

test('concurrent capture clicks share one picker and application quit cancels it', async () => {
  let release; let signal;
  const h = harness({ capture: (options) => { signal = options.signal; return new Promise((resolve) => { release = resolve; }); } });
  const first = h.manager.startCapture();
  assert.equal(await h.manager.startCapture(), false);
  h.app.emit('before-quit');
  assert.equal(signal.aborted, true);
  release(h.capture);
  assert.equal(await first, false);
  assert.equal(h.created.length, 0);
});
