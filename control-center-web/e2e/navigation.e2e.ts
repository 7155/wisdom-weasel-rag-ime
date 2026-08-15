import { expect, test } from '@playwright/test';
import {
  expectNoHorizontalPageOverflow,
  openRoute,
  percentile,
  routes,
} from './helpers';

test('conversation is the default companion workspace', async ({ page }) => {
  await page.goto('/#/');
  await expect(page.locator('main[data-route-id="agent"]')).toBeVisible();
  await expect(page.locator('.shell-topbar__title h1')).toHaveText('对话');
});

test('all registered routes commit before data work and preserve the selected state', async ({ page }, testInfo) => {
  await page.goto('/#/overview');
  await expect(page.locator('main[data-route-id="overview"]')).toBeVisible();
  const navigationLatencies: number[] = [];
  const routeSequence = [...routes.slice(1), routes[0]];

  for (const route of routeSequence) {
    navigationLatencies.push(await openRoute(page, route.id));
    await expect(page.locator('.shell-route-stage')).toHaveAttribute('data-active-route', route.id);
    await expect(page.locator('.shell-route-stage')).toHaveAttribute('aria-label', `${route.label}主内容`);
    if (route.id === 'project-field') {
      await expect(page.locator('.shell-topbar')).toHaveCount(0);
      await expect(page.locator('.shell-sidebar')).toHaveCount(0);
    } else {
      await expect(page.locator('.shell-topbar__title > :is(h1, strong)')).toHaveText(route.label);
      await expect(page.locator(`.shell-sidebar [data-route="${route.id}"]`)).toHaveAttribute(
        'aria-current',
        'page',
      );
    }
    await expectNoHorizontalPageOverflow(page);
  }

  const p95Ms = percentile(navigationLatencies, 0.95);
  const maxMs = Math.max(...navigationLatencies);
  await testInfo.attach('navigation-performance.json', {
    body: JSON.stringify({ samplesMs: navigationLatencies, p95Ms, maxMs }, null, 2),
    contentType: 'application/json',
  });
  expect(p95Ms).toBeLessThan(100);
  expect(maxMs).toBeLessThan(250);
});

test('mobile route dialog is keyboard operable and restores focus', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith('mobile-'), 'mobile navigation contract');
  await page.goto('/#/overview');
  await expect(page.locator('main[data-route-id="overview"]')).toBeVisible();

  const trigger = page.getByRole('navigation', { name: '快捷导航' })
    .getByRole('button', { name: '打开全部导航' });
  await trigger.focus();
  await page.keyboard.press('Enter');

  const dialog = page.getByRole('dialog', { name: '全部功能' });
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);

  await page.keyboard.press('Tab');
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Escape');

  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

test('desktop navigation exposes a visible focus indicator', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.startsWith('mobile-'), 'desktop navigation contract');
  await page.goto('/#/overview');
  await expect(page.locator('main[data-route-id="overview"]')).toBeVisible();

  const firstLink = page.locator('.shell-sidebar [data-route="overview"]');
  await firstLink.focus();
  await expect(firstLink).toBeFocused();
  const outline = await firstLink.evaluate((element) => getComputedStyle(element).outlineStyle);
  expect(outline).not.toBe('none');
});
