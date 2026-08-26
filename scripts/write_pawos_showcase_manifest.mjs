import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const repoDir = path.resolve(process.argv[2] ?? '.');
const assetDir = path.join(repoDir, 'assets', 'showcase');
const outputVideo = path.join(repoDir, 'control-center-web', 'output', 'showcase', 'pawos-showcase.webm');
const assets = [
  {
    file: 'pawos-agent-trace.webp',
    caption: '同一 Session 的上下文装配与事件证据视图。',
  },
  {
    file: 'pawos-room-focus-satellite.webp',
    caption: 'Room 公开对话与可弹出的 Sol 协作态势卫星窗。',
  },
  {
    file: 'pawos-room-starfield.webp',
    caption: 'Room 把伙伴、任务与状态投影到同一星系视图。',
  },
].map((asset) => {
  const assetPath = path.join(assetDir, asset.file);
  const body = readFileSync(assetPath);
  return {
    ...asset,
    bytes: body.length,
    sha256: createHash('sha256').update(body).digest('hex'),
    viewport: { width: 1_440, height: 900 },
  };
});

const baseCommit = git(['rev-parse', 'HEAD']).toString('utf8').trim();
const trackedDiff = git([
  'diff', '--binary', 'HEAD', '--', '.', ':(exclude)assets/showcase',
]);
const untracked = git(['ls-files', '--others', '--exclude-standard', '-z'])
  .toString('utf8')
  .split('\0')
  .filter((file) => file
    && !file.startsWith('assets/showcase/')
    && !file.startsWith('control-center-web/output/')
    && !file.includes('/node_modules/'))
  .sort();
const fingerprint = createHash('sha256').update(trackedDiff);
for (const file of untracked) {
  fingerprint.update(`\0${file}\0`);
  fingerprint.update(readFileSync(path.join(repoDir, file)));
}

const manifest = {
  schemaVersion: 'pawos.showcase-assets.v1',
  generatedAt: new Date().toISOString(),
  source: {
    baseCommit,
    workingTree: trackedDiff.length || untracked.length ? 'modified' : 'clean',
    diffFingerprint: `sha256:${fingerprint.digest('hex')}`,
    untrackedSourceFiles: untracked.length,
  },
  capture: {
    frontend: 'paw-os',
    transport: 'mock',
    fixture: 'deterministic public preview data',
    command: 'scripts/capture_pawos_showcase.sh',
    fixedTime: '2026-08-27T04:00:00+08:00',
    viewport: { width: 1_440, height: 900 },
    starfieldReducedMotion: true,
  },
  reproducibility: 'The command reproduces the same named scenes and checkpoints. Asset hashes identify this run; they are not cross-machine golden-image assertions because Chromium and GPU rasterization can vary by a few pixels.',
  privacy: 'Synthetic public preview data only; no private Session, credential, local database, or personal input is captured.',
  evidenceBoundary: 'These images and the video prove the deterministic preview flow, not installation, live Runtime health, foreground macOS behavior, signing, notarization, or release readiness.',
  assets,
  video: statIfPresent(outputVideo),
};

writeFileSync(
  path.join(assetDir, 'showcase-manifest.json'),
  `${JSON.stringify(manifest, null, 2)}\n`,
);

function git(args) {
  return execFileSync('git', args, { cwd: repoDir, maxBuffer: 64 * 1024 * 1024 });
}

function statIfPresent(file) {
  try {
    const body = readFileSync(file);
    return {
      tracked: false,
      path: 'control-center-web/output/showcase/pawos-showcase.webm',
      bytes: statSync(file).size,
      sha256: createHash('sha256').update(body).digest('hex'),
    };
  } catch {
    return { tracked: false, path: 'control-center-web/output/showcase/pawos-showcase.webm', missing: true };
  }
}
