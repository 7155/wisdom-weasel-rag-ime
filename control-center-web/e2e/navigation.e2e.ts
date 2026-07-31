import { expect, test, type Page } from '@playwright/test';
import {
  expectNoHorizontalPageOverflow,
  isMobileViewport,
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
    navigationLatencies.push(await openRouteFromCurrentShell(page, route.id));
    await expect(page.locator('.shell-topbar__title h1')).toHaveText(route.label);
    await expect(page.locator(`.shell-sidebar [data-route="${route.id}"]`)).toHaveAttribute(
      'aria-current',
      'page',
    );
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

  const dialog = page.getByRole('dialog', { name: '去哪里？' });
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

async function openRouteFromCurrentShell(page: Page, routeId: string): Promise<number> {
  if (!isMobileViewport(page)) return openRoute(page, routeId);

  const trigger = page.getByRole('navigation', { name: '快捷导航' })
    .getByRole('button', { name: '打开全部导航' });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: '去哪里？' });
  await expect(dialog).toBeVisible();
  const link = dialog.locator(`[data-route="${routeId}"]`);

  await page.evaluate((expectedRouteId) => {
    Reflect.set(window, '__RAG_IME_NAV_LATENCY__', null);
    const onClick = (event: MouseEvent) => {
      const target = event.target instanceof Element
        ? event.target.closest(`[data-route="${expectedRouteId}"]`)
        : null;
      if (!target) return;
      document.removeEventListener('click', onClick, true);
      const started = performance.now();
      const poll = () => {
        const selected = document.querySelector(
          `.shell-nav__link[data-route="${expectedRouteId}"][aria-current="page"]`,
        );
        if (!selected) {
          requestAnimationFrame(poll);
          return;
        }
        requestAnimationFrame(() => {
          Reflect.set(window, '__RAG_IME_NAV_LATENCY__', performance.now() - started);
        });
      };
      requestAnimationFrame(poll);
    };
    document.addEventListener('click', onClick, true);
  }, routeId);
  await link.click();
  await expect(page.locator(`main[data-route-id="${routeId}"]`)).toBeVisible();
  await page.waitForFunction(
    () => typeof Reflect.get(window, '__RAG_IME_NAV_LATENCY__') === 'number',
  );
  return page.evaluate(() => Number(Reflect.get(window, '__RAG_IME_NAV_LATENCY__')));
}
