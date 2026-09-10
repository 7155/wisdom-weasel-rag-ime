// Usage: node tests/fixtures/pi_session_resource_policy_probe.mjs <prepared Runtime Host overlay>
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const host = resolve(process.argv[2]);
const { sessionResourceDisclosurePolicy, sessionResourceSettings, sessionLegacyExtensionPaths } = await import(pathToFileURL(join(host, 'src/session-resource-policy.ts')));
const { SettingsManager, DefaultResourceLoader } = await import(pathToFileURL(join(host, 'node_modules/@earendil-works/pi-coding-agent/dist/index.js')));
const root = await mkdtemp(join(tmpdir(), 'paw-plugin-policy-'));
try {
  const paths = [];
  for (const name of ['allowed', 'disabled']) {
    const path = join(root, name);
    await mkdir(path);
    await writeFile(join(path, 'package.json'), JSON.stringify({ name: `@test/${name}`, version: '1.0.0', type: 'module', pi: { extensions: ['index.mjs'] } }));
    await writeFile(join(path, 'index.mjs'), `globalThis.__pawPolicy_${name} = true; export default function () {}`);
    paths.push(path);
  }
  const original = SettingsManager.inMemory({ packages: paths });
  const scoped = sessionResourceSettings(original, [paths[1]]);
  const loader = new DefaultResourceLoader({ cwd: root, agentDir: join(root, 'agent'), settingsManager: scoped, noSkills: true, noContextFiles: true, noPromptTemplates: true, noThemes: true });
  await loader.reload();
  assert.equal(globalThis.__pawPolicy_allowed, true);
  assert.equal(globalThis.__pawPolicy_disabled, undefined, 'disabled plugin must not even be imported');
  assert.equal(loader.getExtensions().extensions.length, 1);
  assert.deepEqual(original.getPackages(), paths, 'global installation settings must be unchanged');
  assert.deepEqual(sessionLegacyExtensionPaths(['/plugins/review.ts', '/plugins/keep.ts'], ['review']), ['/plugins/keep.ts']);
  assert.throws(() => sessionResourceDisclosurePolicy({ disabledPluginIds: ['../../unexpected'] }));
  console.log(JSON.stringify({ ok: true, disabledPluginImported: false, allowedPluginLoaded: true, sharedSettingsUnchanged: true }));
} finally { await rm(root, { recursive: true, force: true }); }
