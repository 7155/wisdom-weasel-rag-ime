import { expect, test } from '@playwright/test';
import { expectNoHorizontalPageOverflow } from './helpers';

test('governed project scenes fit empty slots without replacing normal data', async ({ page }, testInfo) => {
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: width === 1440 ? 900 : 844 });
    await page.goto('/e2e/fixtures/project-scenes.html');

    const roomScene = page.getByAltText(/带有任务、证据和验收条件的交接单/);
    const memoryScene = page.getByAltText(/长期输入形成的时间线/);
    await expect(roomScene).toHaveAttribute('loading', 'lazy');
    await expect(memoryScene).toHaveAttribute('loading', 'lazy');
    await expect(roomScene).toHaveAttribute('width', '960');
    await expect(memoryScene).toHaveAttribute('height', '640');
    await expect(page.getByRole('region', { name: '记忆正常数据槽位' }).getByRole('option', { name: /Room 路由审计/ })).toBeVisible();
    await expect(page.getByRole('region', { name: '记忆正常数据槽位' }).locator('.project-scene-empty')).toHaveCount(0);

    for (const scene of [roomScene, memoryScene]) {
      const metrics = await scene.evaluate((node) => {
        const image = node as HTMLImageElement;
        return {
          naturalWidth: image.naturalWidth,
          naturalHeight: image.naturalHeight,
          left: image.getBoundingClientRect().left,
          right: image.getBoundingClientRect().right,
        };
      });
      expect(metrics.naturalWidth).toBeGreaterThan(0);
      expect(metrics.naturalHeight).toBeGreaterThan(0);
      expect(metrics.left).toBeGreaterThanOrEqual(-1);
      expect(metrics.right).toBeLessThanOrEqual(width + 1);
    }
    await expectNoHorizontalPageOverflow(page);
    await testInfo.attach(`project-scenes-${width}`, {
      body: await page.screenshot({ animations: 'disabled', fullPage: true }),
      contentType: 'image/png',
    });
  }
});
