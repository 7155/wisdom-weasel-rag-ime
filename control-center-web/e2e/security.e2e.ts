import { expect, test } from '@playwright/test';

test('strict CSP stays eval-free and still permits the React app to boot', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-1440x900', 'one CSP execution gate is sufficient');
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto('/#/overview');
  await expect(page.locator('main[data-route-id="overview"]')).toBeVisible();

  const contentSecurityPolicy = await page
    .locator('meta[http-equiv="Content-Security-Policy"]')
    .getAttribute('content');
  expect(contentSecurityPolicy).toContain("script-src 'self'");
  expect(contentSecurityPolicy).toContain("frame-src 'self' blob:");
  expect(contentSecurityPolicy).not.toMatch(/frame-src[^;]*(?:https?:|\*)/);
  expect(contentSecurityPolicy).not.toContain("'unsafe-eval'");
  expect(pageErrors).toEqual([]);
});

test('browser preview does not expose the native message handler', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-1440x900', 'one browser capability gate is sufficient');
  await page.goto('/#/overview');
  await expect(page.locator('main[data-route-id="overview"]')).toBeVisible();

  const state = await page.evaluate(() => ({
    nativeHandler: Boolean(
      (window as Window & {
        webkit?: { messageHandlers?: { ragImeNativeBridge?: unknown } };
      }).webkit?.messageHandlers?.ragImeNativeBridge,
    ),
    transport: document.documentElement.dataset.controlTransport,
  }));
  expect(state.nativeHandler).toBe(false);
  expect(state.transport).toBe('mock');
});
