import { defineConfig } from '@playwright/test';

const port = 4_175;

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  outputDir: './test-results/playwright',
  snapshotPathTemplate: '{testDir}/__screenshots__/{testFilePath}/{arg}-{projectName}{ext}',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  preserveOutput: 'always',
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],
  expect: {
    timeout: 5_000,
    toHaveScreenshot: {
      animations: 'disabled',
      maxDiffPixelRatio: 0.01,
    },
  },
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    colorScheme: 'light',
    locale: 'zh-CN',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop-1440x900', use: { viewport: { width: 1_440, height: 900 } } },
    { name: 'desktop-1280x820', use: { viewport: { width: 1_280, height: 820 } } },
    { name: 'tablet-1024x768', use: { viewport: { width: 1_024, height: 768 } } },
    { name: 'mobile-390x844', use: { viewport: { width: 390, height: 844 } } },
    { name: 'mobile-430x932', use: { viewport: { width: 430, height: 932 } } },
  ],
  webServer: {
    // Replace Playwright's shell process with Vite so teardown cannot orphan
    // a package-manager child that keeps the strict test port occupied.
    command: `exec node ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}/#/overview`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
