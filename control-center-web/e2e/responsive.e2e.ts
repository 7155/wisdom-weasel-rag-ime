import { expect, test } from '@playwright/test';
import { expectNoHorizontalPageOverflow, isMobileViewport } from './helpers';

test('control center shell matches the viewport visual baseline', async ({ page }) => {
  await page.goto('/#/overview');
  await expect(page.locator('main[data-route-id="overview"]')).toBeVisible();
  await expectNoHorizontalPageOverflow(page);

  const mobile = isMobileViewport(page);
  if (mobile) {
    await expect(page.locator('.shell-sidebar')).toBeHidden();
    await expect(page.locator('.shell-mobile-nav')).toBeVisible();
  } else {
    await expect(page.locator('.shell-sidebar')).toBeVisible();
    await expect(page.locator('.shell-mobile-nav')).toBeHidden();
  }
  await expect(page).toHaveScreenshot('control-center-shell.png', { fullPage: false });
});

test('production-shaped fixture stays bounded and records a viewport screenshot', async ({
  page,
}, testInfo) => {
  await page.goto('/e2e/fixtures/load.html');
  await page.waitForFunction(() => Boolean(Reflect.get(window, '__RAG_IME_QA__')));
  await expectNoHorizontalPageOverflow(page);

  const screenshot = await page.screenshot({ animations: 'disabled', fullPage: false });
  await testInfo.attach(`load-fixture-${testInfo.project.name}`, {
    body: screenshot,
    contentType: 'image/png',
  });
});
