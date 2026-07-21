import { expect, test } from '@playwright/test';
import { expectNoHorizontalPageOverflow } from './helpers';

test('functional empty states stay compact and contain no decorative artwork', async ({ page }, testInfo) => {
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: width === 1440 ? 900 : 844 });
    await page.goto('/e2e/fixtures/functional-empty-states.html');

    const emptyStates = page.locator('.ui-empty-state');
    await expect(emptyStates).toHaveCount(2);
    await expect(page.locator('.functional-empty-fixture img')).toHaveCount(0);
    await expect(page.getByRole('region', { name: '记忆正常数据槽位' }).getByRole('option', { name: /Room 路由审计/ })).toBeVisible();

    for (const emptyState of await emptyStates.all()) {
      const metrics = await emptyState.evaluate((node) => {
        const rect = node.getBoundingClientRect();
        return { height: rect.height, left: rect.left, right: rect.right };
      });
      expect(metrics.height).toBeLessThanOrEqual(220);
      expect(metrics.left).toBeGreaterThanOrEqual(-1);
      expect(metrics.right).toBeLessThanOrEqual(width + 1);
    }
    await expectNoHorizontalPageOverflow(page);
    await testInfo.attach(`functional-empty-states-${width}`, {
      body: await page.screenshot({ animations: 'disabled', fullPage: true }),
      contentType: 'image/png',
    });
  }
});
