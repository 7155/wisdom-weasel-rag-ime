#!/usr/bin/env node
/** Capture read-only Lab documentation images. Start Vite before running this script. */
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const web = path.join(root, 'control-center-web');
const base = new URL(process.argv[2] || 'http://127.0.0.1:5173');
assert.ok(['127.0.0.1', 'localhost'].includes(base.hostname), 'Use a local source preview.');
const require = createRequire(path.join(web, 'package.json'));
const { chromium } = require('@playwright/test');
const out = path.join(root, 'assets/showcase/readme');
const raw = path.join(web, 'output/readme');
await mkdir(out, { recursive: true }); await mkdir(raw, { recursive: true });
const browser = await chromium.launch({ headless: true });
const viewport = { width: 1180, height: 1050 };
const page = await browser.newPage({ viewport, deviceScaleFactor: 1, reducedMotion: 'reduce' });
const errors = []; const blockedRequests = [];
page.on('pageerror', (error) => errors.push(error.message));
await page.route('**/*', async (route) => {
  const url = new URL(route.request().url());
  if (url.origin !== base.origin || url.pathname.startsWith('/api/')) {
    blockedRequests.push(url.origin + url.pathname); await route.abort(); return;
  }
  await route.continue();
});
const assets = [];
async function capture(file, caption) {
  const png = path.join(raw, file.replace('.webp', '.png'));
  await page.mouse.move(0, 0);
  await page.screenshot({ path: png, animations: 'disabled' });
  execFileSync('cwebp', ['-quiet', '-q', '88', png, '-o', path.join(out, file)]);
  const bytes = await readFile(path.join(out, file));
  assets.push({ file, caption, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), viewport });
}
try {
  await page.goto(new URL('/e2e/fixtures/readme-lab/index.html', base).href);
  await page.getByRole('heading', { name: '方案、过程与结果', exact: true }).waitFor();
  await capture('lab-workspace.webp', '新版 Lab 项目与三阶段实验过程');
  await page.getByRole('button', { name: '指标对照', exact: true }).click();
  await page.getByRole('heading', { name: '质量与成本对照', exact: true }).waitFor();
  await capture('lab-metrics.webp', '同一组任务的基线与候选指标');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.deepEqual(errors, []); assert.deepEqual(blockedRequests, []);
  const fixtureFiles = ['index.html', 'main.tsx', 'preview.css', 'scene.json'];
  const fingerprints = {};
  for (const name of fixtureFiles) fingerprints[name] = createHash('sha256').update(await readFile(path.join(web, 'e2e/fixtures/readme-lab', name))).digest('hex');
  const scene = JSON.parse(await readFile(path.join(web, 'e2e/fixtures/readme-lab/scene.json'), 'utf8'));
  const git = (args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
  const manifest = { schemaVersion: 'paw.readme-showcase.v1', capturedAt: new Date().toISOString(), sourceCommit: git(['rev-parse', 'HEAD']), workingTree: git(['status', '--porcelain']).length ? 'modified' : 'clean', fixture: 'control-center-web/e2e/fixtures/readme-lab', fixtureSha256: fingerprints, sourceDocument: scene.sourceDocument, sourceSha256: scene.sourceSha256, transport: 'mock', modelCalls: 0, personalDataAccessed: false, evidenceBoundary: 'Current source components with allowlisted public historical metadata. No current experiment, installed application, model call or native acceptance is asserted.', command: 'node scripts/capture_readme_lab.mjs <Vite origin>', assets };
  await writeFile(path.join(out, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  console.log(JSON.stringify({ assets: assets.map((a) => a.file), errors, blockedRequests }));
} finally { await browser.close(); }
