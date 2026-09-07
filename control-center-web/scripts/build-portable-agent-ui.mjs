import { build } from 'vite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
await build({ configFile: false, root, resolve: { alias: { '@': path.join(root, 'src') } },
  define: { 'process.env.NODE_ENV': '"production"' }, esbuild: { jsx: 'automatic' },
  build: { outDir: '.generated/portable-agent-ui', emptyOutDir: true, target: 'es2022',
    lib: { entry: path.join(root, 'src/features/eval-lab/projects/portable-agent-ui.tsx'),
      name: 'PawAgentUIBundle', formats: ['iife'], fileName: () => 'agent-ui.js', cssFileName: 'agent-ui' } } });
