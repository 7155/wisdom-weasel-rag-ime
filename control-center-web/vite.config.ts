import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import type { Plugin } from 'vite';
import { defineConfig } from 'vitest/config';

const rootDirectory = path.dirname(fileURLToPath(import.meta.url));
const controlTransport = process.env.VITE_CONTROL_TRANSPORT ?? 'auto';
const buildChannel = process.env.VITE_BUILD_CHANNEL ?? 'preview';
const controlProxyTarget = normalizeControlProxyTarget(process.env.VITE_CONTROL_PROXY_TARGET);
const nativeOnlyBuild = controlTransport === 'native';
const sourceCommit = execFileSync('git', ['rev-parse', 'HEAD'], {
  cwd: path.resolve(rootDirectory, '..'),
  encoding: 'utf8',
}).trim();

if (!new Set(['auto', 'mock', 'http', 'native']).has(controlTransport)) {
  throw new Error(`Unsupported VITE_CONTROL_TRANSPORT: ${controlTransport}`);
}
if (!new Set(['preview', 'production']).has(buildChannel)) {
  throw new Error(`Unsupported VITE_BUILD_CHANNEL: ${buildChannel}`);
}
if (buildChannel === 'production' && !nativeOnlyBuild) {
  throw new Error('Production control-center builds require VITE_CONTROL_TRANSPORT=native');
}

const nativeTransportEntry = path.resolve(
  rootDirectory,
  'src/app/control-transport.native.tsx',
);
const productionDataEntry = path.resolve(
  rootDirectory,
  'src/features/agent/production-data.ts',
);
const forbiddenNativeBundleModules = [
  '/src/app/control-transport.tsx',
  '/src/platform/http-transport.ts',
  '/src/test/mock-transport.ts',
  '/src/features/agent/preview-data.ts',
];

function controlTransportBoundary(): Plugin {
  return {
    name: 'rag-ime-control-transport-boundary',
    transformIndexHtml(html) {
      if (!nativeOnlyBuild) return html;
      return html.replace(
        "connect-src 'self' http://127.0.0.1:8766 http://127.0.0.1:8768 ws://127.0.0.1:*;",
        "connect-src 'self';",
      );
    },
    generateBundle(_options, bundle) {
      const bundledModules = Object.values(bundle)
        .filter((output) => output.type === 'chunk')
        .flatMap((output) => Object.keys(output.modules))
        .map((moduleId) => moduleId.replaceAll('\\', '/'));
      const forbiddenModules = nativeOnlyBuild
        ? bundledModules.filter((moduleId) =>
            forbiddenNativeBundleModules.some((suffix) => moduleId.includes(suffix)))
        : [];
      if (forbiddenModules.length > 0) {
        this.error(
          `Native control-center bundle includes forbidden transport modules: ${forbiddenModules.join(', ')}`,
        );
      }
      this.emitFile({
        type: 'asset',
        fileName: 'rag-ime-control-web-build.json',
        source: `${JSON.stringify({
          schemaVersion: 'rag-ime.control-web-build.v1',
          buildChannel,
          transport: controlTransport,
          nativeOnly: nativeOnlyBuild,
          forbiddenTransportModulesExcluded: nativeOnlyBuild && forbiddenModules.length === 0,
          previewFixturesExcluded: nativeOnlyBuild && buildChannel === 'production' && forbiddenModules.length === 0,
          sourceCommit,
        }, null, 2)}\n`,
      });
    },
  };
}

function browserDependencyBoundary(): Plugin {
  return {
    name: 'rag-ime-browser-dependency-boundary',
    enforce: 'pre',
    transform(code, id) {
      if (!id.replaceAll('\\', '/').endsWith('/lodash/_nodeUtil.js')) return null;
      const browserCode = code.replace(
        /freeModule\.require\((['"])util\1\)\.types/g,
        'undefined',
      );
      return browserCode === code ? null : { code: browserCode, map: null };
    },
  };
}

function normalizeControlProxyTarget(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const url = new URL(value);
  if (
    url.protocol !== 'http:' ||
    !new Set(['127.0.0.1', 'localhost', '[::1]']).has(url.hostname) ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  ) {
    throw new Error('VITE_CONTROL_PROXY_TARGET must be a loopback HTTP origin');
  }
  return url.origin;
}

export default defineConfig({
  base: './',
  define: {
    __CONTROL_PREVIEW__: JSON.stringify(buildChannel !== 'production'),
  },
  plugins: [react(), browserDependencyBoundary(), controlTransportBoundary()],
  resolve: {
    alias: [
      ...(nativeOnlyBuild
        ? [{ find: /^@\/app\/control-transport$/, replacement: nativeTransportEntry }]
        : []),
      ...(nativeOnlyBuild
        ? [{ find: /^@\/features\/agent\/preview-data$/, replacement: productionDataEntry }]
        : []),
      { find: '@', replacement: path.resolve(rootDirectory, 'src') },
    ],
  },
  build: {
    sourcemap: false,
    target: 'es2022',
  },
  server: controlProxyTarget
    ? {
        proxy: {
          '/api': {
            target: controlProxyTarget,
          },
        },
      }
    : undefined,
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
