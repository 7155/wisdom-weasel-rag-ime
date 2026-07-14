import path from 'node:path';
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import type { Plugin } from 'vite';
import { defineConfig } from 'vitest/config';

const rootDirectory = path.dirname(fileURLToPath(import.meta.url));
const controlTransport = process.env.VITE_CONTROL_TRANSPORT ?? 'auto';
const buildChannel = process.env.VITE_BUILD_CHANNEL ?? 'preview';
const nativeOnlyBuild = controlTransport === 'native';

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
const forbiddenNativeBundleModules = [
  '/src/app/control-transport.tsx',
  '/src/platform/http-transport.ts',
  '/src/test/mock-transport.ts',
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
        }, null, 2)}\n`,
      });
    },
  };
}

export default defineConfig({
  base: './',
  plugins: [react(), controlTransportBoundary()],
  resolve: {
    alias: [
      ...(nativeOnlyBuild
        ? [{ find: /^@\/app\/control-transport$/, replacement: nativeTransportEntry }]
        : []),
      { find: '@', replacement: path.resolve(rootDirectory, 'src') },
    ],
  },
  build: {
    sourcemap: false,
    target: 'es2022',
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
