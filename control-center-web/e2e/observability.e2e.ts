import { expect, test } from '@playwright/test';
import { expectNoHorizontalPageOverflow } from './helpers';

test('runtime observation stays bounded and filters its causal trace', async ({
  page,
}, testInfo) => {
  test.skip(
    !['desktop-1440x900', 'mobile-390x844'].includes(testInfo.project.name),
    'the observation workspace is accepted at the product desktop and narrow-screen viewports',
  );

  await page.goto('/#/observability');
  const feature = page.locator('main[data-route-id="observability"]');
  await expect(feature).toBeVisible();
  await expectNoHorizontalPageOverflow(page);
  await expect(feature).toContainText('运行记录只保存状态、耗时、数量和脱敏后的标识');
  await expect(feature).toContainText('原始提示词和消息正文不会写进运行记录');
  await expect(page.getByRole('list', { name: '运行记录事件' }).getByRole('listitem')).toHaveCount(8);

  const bounds = await feature.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(bounds.scrollWidth).toBeLessThanOrEqual(bounds.clientWidth + 1);

  await page.getByRole('tab', { name: '记忆' }).click();
  await expect(page).toHaveURL(/category=memory/);
  await expect(page.getByRole('list', { name: '运行记录事件' }).getByRole('listitem')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: '这次是怎样完成的' })).toBeVisible();
  await expect(feature).toContainText('一次完整流程');
  await expect(feature).not.toContainText('PRIVATE_');

  await testInfo.attach(`observability-${testInfo.project.name}.png`, {
    body: await page.screenshot({ animations: 'disabled', fullPage: true }),
    contentType: 'image/png',
  });
});
