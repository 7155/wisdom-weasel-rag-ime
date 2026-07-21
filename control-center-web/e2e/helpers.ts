import { expect, type Page } from '@playwright/test';
import { routeRegistry } from '../src/app/route-registry';

// E2E route assertions consume the same registry as the shell so product copy
// changes cannot leave a second, stale navigation contract behind.
export const routes = routeRegistry.map(({ id, label }) => ({ id, label }));

export function isMobileViewport(page: Page): boolean {
  return (page.viewportSize()?.width ?? 0) <= 760;
}

export async function openRoute(page: Page, routeId: string): Promise<number> {
  let link = page.locator(`.shell-sidebar [data-route="${routeId}"]`);
  if (isMobileViewport(page)) {
    await page.locator('.shell-topbar .shell-mobile-menu__trigger').click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    link = dialog.locator(`[data-route="${routeId}"]`);
  }

  await armNavigationMeasurement(page, routeId);
  await link.click();
  await expect(page.locator(`main[data-route-id="${routeId}"]`)).toBeVisible();
  await page.waitForFunction(
    () => typeof Reflect.get(window, '__RAG_IME_NAV_LATENCY__') === 'number',
  );
  return page.evaluate(() => Number(Reflect.get(window, '__RAG_IME_NAV_LATENCY__')));
}

export async function expectNoHorizontalPageOverflow(page: Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
}

export async function settleAgentTimeline(page: Page): Promise<void> {
  const scroller = page.locator('main[data-route-id="agent"] [data-testid="virtuoso-scroller"]');
  await expect(scroller).toBeVisible();
  await scroller.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect.poll(() => scroller.evaluate(
    (element) => element.scrollHeight - element.clientHeight - element.scrollTop,
  )).toBeLessThanOrEqual(1);
  await page.waitForTimeout(50);
}

export function percentile(values: readonly number[], ratio: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * ratio) - 1)] ?? 0;
}

async function armNavigationMeasurement(page: Page, routeId: string): Promise<void> {
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
        // Route feedback is owned by the always-mounted shell. Heavy feature
        // code may still be resolving behind the visible loading state.
        requestAnimationFrame(() => {
          Reflect.set(window, '__RAG_IME_NAV_LATENCY__', performance.now() - started);
        });
      };
      requestAnimationFrame(poll);
    };
    document.addEventListener('click', onClick, true);
  }, routeId);
}
