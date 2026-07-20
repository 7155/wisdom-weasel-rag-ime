import { expect, type Page } from '@playwright/test';

export const routes = [
  { id: 'overview', label: '总览' },
  { id: 'input', label: '输入法' },
  { id: 'agent', label: 'Agent' },
  { id: 'rooms', label: 'Rooms' },
  { id: 'roles', label: '角色' },
  { id: 'plugins', label: '插件' },
  { id: 'voice', label: '语音' },
  { id: 'planning', label: '规划' },
  { id: 'memory', label: '记忆' },
  { id: 'knowledge', label: '知识库' },
  { id: 'governance', label: '治理中心' },
  { id: 'history', label: '历史' },
  { id: 'observability', label: '运行观察' },
  { id: 'diagnostics', label: '诊断' },
  { id: 'configuration', label: '配置' },
] as const;

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
        if (!document.querySelector(`main[data-route-id="${expectedRouteId}"]`)) {
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
}
