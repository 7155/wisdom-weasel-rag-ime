import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execute = promisify(execFile);

// macOS owns the rectangle picker (including Escape). No clipboard mutation,
// persistent screenshots directory or second desktop-control implementation.
export async function captureScreenRegion({
  run = execute, platform = process.platform, temporaryRoot = os.tmpdir(),
  sourceAppBundleId = '', signal,
} = {}) {
  if (platform !== 'darwin') throw new Error('当前框选入口需要 macOS。');
  const directory = await fs.mkdtemp(path.join(temporaryRoot, 'paw-screen-'));
  const file = path.join(directory, 'region.png');
  try {
    await fs.chmod(directory, 0o700);
    let captureError;
    try {
      await run('/usr/sbin/screencapture', ['-i', '-s', '-x', '-t', 'png', file], {
        timeout: 120_000, maxBuffer: 8192, signal,
      });
    } catch (error) { captureError = error; }
    if (signal?.aborted) return null;
    const stat = await fs.stat(file).catch(() => null);
    if (!stat?.size) {
      if (captureError && captureError.code !== 1) throw new Error('框选未完成，请重试。');
      return null;
    }
    if (stat.size > 20 * 1024 * 1024) throw new Error('选区图片超过 20 MB，请缩小选区。');
    const bytes = await fs.readFile(file);
    if (bytes.length < 24 || bytes.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') throw new Error('没有取得有效的选区图片。');
    return {
      dataUrl: `data:image/png;base64,${bytes.toString('base64')}`,
      mimeType: 'image/png', pixelWidth: bytes.readUInt32BE(16), pixelHeight: bytes.readUInt32BE(20),
      sourceAppBundleId, capturedAtMs: Date.now(),
    };
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
}
