import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { captureScreenRegion } from './screen-capture.mjs';

test('imports only the explicit rectangle and removes the temporary file', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'paw-capture-test-'));
  try {
    const receipt = await captureScreenRegion({ platform: 'darwin', temporaryRoot: root, sourceAppBundleId: 'com.example.Editor', run: async (command, args) => {
      assert.equal(command, '/usr/sbin/screencapture');
      assert.deepEqual(args.slice(0, -1), ['-i', '-s', '-x', '-t', 'png']);
      const png = Buffer.alloc(24);
      Buffer.from('89504e470d0a1a0a', 'hex').copy(png);
      png.writeUInt32BE(320, 16); png.writeUInt32BE(200, 20);
      await fs.writeFile(args.at(-1), png);
    } });
    assert.equal(receipt.pixelWidth, 320);
    assert.equal(receipt.pixelHeight, 200);
    assert.equal(receipt.sourceAppBundleId, 'com.example.Editor');
    assert.deepEqual(await fs.readdir(root), []);
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});

test('Escape creates no attachment and capture errors clean up', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'paw-capture-cancel-'));
  try {
    assert.equal(await captureScreenRegion({ platform: 'darwin', temporaryRoot: root, run: async () => { throw Object.assign(new Error('cancel'), { code: 1 }); } }), null);
    await assert.rejects(captureScreenRegion({ platform: 'darwin', temporaryRoot: root, run: async () => { throw Object.assign(new Error('not available'), { code: 'ENOENT' }); } }), /框选未完成/);
    assert.deepEqual(await fs.readdir(root), []);
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});
