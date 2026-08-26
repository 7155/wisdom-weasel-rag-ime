import { defineConfig } from '@playwright/test';

const port = 4_177;

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.capture.ts',
  outputDir: './test-results/showcase-playwright',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  reporter: [['line']],
  use: {
    actionTimeout: 10_000,
    baseURL: `http://127.0.0.1:${port}`,
    channel: process.env.PAW_E2E_SYSTEM_CHROME === '1' ? 'chrome' : undefined,
    colorScheme: 'light',
    locale: 'zh-CN',
    screenshot: 'off',
    trace: 'on',
    video: {
      mode: 'on',
      size: { width: 1_440, height: 900 },
    },
    viewport: { width: 1_440, height: 900 },
  },
  webServer: {
    command: `VITE_CONTROL_TRANSPORT=mock exec node ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}/?frontend=paw-os&controlTransport=mock#/agent`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
